"""
API web (FastAPI) que expõe o Agente Resiliente para o frontend React.

Endpoints:
- POST   /api/chat                    -> resposta final síncrona (JSON)
- POST   /api/chat/stream             -> resposta via SSE (streaming de eventos)
- GET    /api/provedores              -> inventário de provedores configurados
- GET    /api/logs                    -> últimos diagnósticos de falha
- DELETE /api/logs                    -> limpa o arquivo de falhas
- GET    /api/historico/{sessao_id}   -> mensagens persistidas de uma sessão
- DELETE /api/historico/{sessao_id}   -> limpa o histórico de uma sessão
- GET    /api/metricas                -> métricas simples em memória
- GET    /health                      -> checagem de saúde

Para um dev júnior:
- Este arquivo só cuida de "transporte" (HTTP). A lógica de verdade do agente
  está em agente.py. Se for adicionar um novo endpoint, siga o padrão dos
  existentes: valide a entrada com um modelo Pydantic, chame o `assistente`
  global, e devolva um dicionário serializável em JSON.
"""

import os
import json
import queue
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from .agente import AssistenteDesenvolvimento, LOG_FILE
from . import persistencia

persistencia.inicializar()

logger = logging.getLogger("AgenteAPI")

app = FastAPI(title="Agente Resiliente LLM - API", version="1.0.0")

# Libera acesso do frontend local. Para produção, restrinja ALLOWED_ORIGINS
# no .env em vez de usar "*".
origens_permitidas = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origens_permitidas,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instância única do agente, criada na primeira requisição (lazy init) para que
# o servidor consiga subir mesmo que as chaves de API ainda não existam --
# nesse caso, o erro só aparece quando alguém tenta conversar.
_assistente: Optional[AssistenteDesenvolvimento] = None


def obter_assistente() -> AssistenteDesenvolvimento:
    global _assistente
    if _assistente is None:
        _assistente = AssistenteDesenvolvimento()
    return _assistente


# =====================================================================
# RATE LIMITING SIMPLES (por IP, em memória)
# =====================================================================
# Protege as chaves de API contra uso abusivo quando o serviço está exposto
# (ex: via túnel Cloudflare). Se o processo reiniciar, os contadores zeram —
# o objetivo é mitigar abuso casual, não é uma solução robusta de produção.
RATE_MAX_MSGS_POR_MINUTO = int(os.environ.get("RATE_MAX_MSGS_POR_MINUTO", "10"))
_rate_limite: Dict[str, List[float]] = defaultdict(list)


def _checar_rate_limit(request: Request):
    ip = request.client.host if request.client else "desconhecido"
    agora = time.time()
    janela = [t for t in _rate_limite[ip] if agora - t < 60]
    if len(janela) >= RATE_MAX_MSGS_POR_MINUTO:
        raise HTTPException(
            status_code=429,
            detail=f"Limite de {RATE_MAX_MSGS_POR_MINUTO} mensagens por minuto atingido. Tente novamente em instantes.",
        )
    janela.append(agora)
    _rate_limite[ip] = janela


# =====================================================================
# MÉTRICAS EM MEMÓRIA
# =====================================================================
# Contadores simples que zeram quando o processo reinicia. Suficiente para
# decidir quais provedores manter no catálogo com base em dados reais.
_metricas: Dict[str, Any] = {
    "total_requisicoes": 0,
    "por_provedor_sucesso": defaultdict(int),
    "por_provedor_falha": defaultdict(int),
    "tempo_total_segundos": 0.0,
}


def _registrar_metricas(resultado: Dict[str, Any]):
    _metricas["total_requisicoes"] += 1
    _metricas["tempo_total_segundos"] += float(resultado.get("tempo_total_segundos") or 0)

    if resultado.get("sucesso") and resultado.get("modelo_final"):
        _metricas["por_provedor_sucesso"][resultado["modelo_final"]] += 1
    for m in resultado.get("modelos_falhados", []) or []:
        nome = m.get("nome")
        if nome:
            _metricas["por_provedor_falha"][nome] += 1


# =====================================================================
# MODELOS PYDANTIC
# =====================================================================
class MensagemEntrada(BaseModel):
    texto: str
    sessao_id: str = "default"


class ModeloFalhado(BaseModel):
    nome: str
    categoria: str
    codigo_http: Optional[int] = None


class RespostaChat(BaseModel):
    sucesso: bool
    resposta: str
    modelo_final: Optional[str] = None
    fallback_acionado: bool = False
    modelos_tentados: List[str] = []
    modelos_falhados: List[ModeloFalhado] = []
    nivel_complexidade: Optional[str] = None
    motivo_complexidade: Optional[str] = None 
    duracao_segundos: Optional[float] = None
    tempo_total_segundos: Optional[float] = None


# =====================================================================
# ENDPOINTS BÁSICOS
# =====================================================================
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/provedores")
def listar_provedores():
    try:
        assistente = obter_assistente()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return assistente.listar_provedores_status()


@app.get("/api/logs")
def listar_logs(limite: int = 50):
    """Lê as últimas `limite` linhas do arquivo de log de falhas (JSON Lines)."""
    if not os.path.exists(LOG_FILE):
        return []

    linhas = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                linhas.append(json.loads(linha))
            except json.JSONDecodeError:
                continue

    return list(reversed(linhas[-limite:]))


@app.delete("/api/logs")
def limpar_logs():
    if os.path.exists(LOG_FILE):
        open(LOG_FILE, "w").close()
    return {"status": "logs limpos"}


# =====================================================================
# HISTÓRICO PERSISTIDO (SQLite)
# =====================================================================
@app.get("/api/historico/{sessao_id}")
def listar_historico(sessao_id: str, limite: int = 100):
    return persistencia.listar_mensagens(sessao_id, limite)


@app.delete("/api/historico/{sessao_id}")
def limpar_historico(sessao_id: str):
    persistencia.limpar_sessao(sessao_id)
    return {"status": "histórico limpo"}


# =====================================================================
# MÉTRICAS
# =====================================================================
@app.get("/api/metricas")
def metricas():
    total = _metricas["total_requisicoes"] or 1
    return {
        "total_requisicoes": _metricas["total_requisicoes"],
        "tempo_medio_segundos": round(_metricas["tempo_total_segundos"] / total, 2),
        "sucesso_por_provedor": dict(_metricas["por_provedor_sucesso"]),
        "falha_por_provedor": dict(_metricas["por_provedor_falha"]),
    }


# =====================================================================
# CHAT: SÍNCRONO E STREAMING (SSE)
# =====================================================================
@app.post("/api/chat", response_model=RespostaChat)
def enviar_mensagem(mensagem: MensagemEntrada, request: Request):
    _checar_rate_limit(request)

    if not mensagem.texto or not mensagem.texto.strip():
        raise HTTPException(status_code=400, detail="Campo 'texto' não pode ser vazio.")

    try:
        assistente = obter_assistente()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Persiste a pergunta do usuário antes de executar.
    persistencia.salvar_mensagem(
        sessao_id=mensagem.sessao_id,
        remetente="usuario",
        conteudo=mensagem.texto,
    )

    resultado = assistente.executar_com_fallback(mensagem.texto)
    _registrar_metricas(resultado)

    persistencia.salvar_mensagem(
        sessao_id=mensagem.sessao_id,
        remetente="agente",
        conteudo=resultado["resposta"],
        modelo_utilizado=resultado.get("modelo_final"),
        nivel_complexidade=resultado.get("nivel_complexidade"),
        motivo_complexidade=resultado.get("motivo_complexidade"),
        fallback_acionado=resultado.get("fallback_acionado", False),
        duracao_segundos=resultado.get("duracao_segundos"),
    )

    return RespostaChat(
        sucesso=resultado["sucesso"],
        resposta=resultado["resposta"],
        modelo_final=resultado.get("modelo_final"),
        fallback_acionado=resultado.get("fallback_acionado", False),
        modelos_tentados=resultado.get("modelos_tentados", []),
        modelos_falhados=[ModeloFalhado(**m) for m in resultado.get("modelos_falhados", [])],
        duracao_segundos=resultado.get("duracao_segundos"),
        nivel_complexidade=resultado.get("nivel_complexidade"),
        motivo_complexidade=resultado.get("motivo_complexidade"),
        tempo_total_segundos=resultado.get("tempo_total_segundos"),
    )


@app.post("/api/chat/stream")
def enviar_mensagem_streaming(mensagem: MensagemEntrada, request: Request):
    """
    Versão SSE do /api/chat. Emite eventos conforme a orquestração acontece:

      classificacao   -> nível de complexidade detectado
      tentativa       -> provedor sendo tentado agora
      step_planejamento / step_raciocinio / step_observacao / step_erro
                      -> steps internos do agente (streaming real do smolagents)
      falha / retry   -> problemas e retentativas no caminho
      timeout_global  -> orçamento total estourado, cascade abortado
      sucesso         -> provedor respondeu
      final           -> resposta consolidada + metadados (igual ao /api/chat)
      erro_fatal      -> falha total antes de obter resposta

    O formato é `data: {json}\n\n` (Server-Sent Events padrão). O frontend usa
    fetch + ReadableStream porque o endpoint é POST (EventSource só faz GET).
    """
    _checar_rate_limit(request)

    if not mensagem.texto or not mensagem.texto.strip():
        raise HTTPException(status_code=400, detail="Campo 'texto' não pode ser vazio.")

    try:
        assistente = obter_assistente()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Persiste a pergunta do usuário antes de executar.
    persistencia.salvar_mensagem(
        sessao_id=mensagem.sessao_id,
        remetente="usuario",
        conteudo=mensagem.texto,
    )

    # Fila thread-safe: o agente roda em uma thread (é bloqueante) e empurra
    # eventos para cá; o generator do SSE consome em outra. Sem isso, o event
    # loop do FastAPI ficaria bloqueado durante todo o cascade.
    fila: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()

    def produtor():
        try:
            def on_evento(evt: Dict[str, Any]):
                fila.put(evt)

            resultado = assistente.executar_com_fallback(
                mensagem.texto, on_evento=on_evento, stream=True
            )
            _registrar_metricas(resultado)

            persistencia.salvar_mensagem(
                sessao_id=mensagem.sessao_id,
                remetente="agente",
                conteudo=resultado["resposta"],
                modelo_utilizado=resultado.get("modelo_final"),
                nivel_complexidade=resultado.get("nivel_complexidade"),
                motivo_complexidade=resultado.get("motivo_complexidade"),
                fallback_acionado=resultado.get("fallback_acionado", False),
                duracao_segundos=resultado.get("duracao_segundos"),
            )
            fila.put({"tipo": "final", "resultado": resultado})
        except Exception as e:
            logger.exception("Falha no produtor do streaming")
            fila.put({"tipo": "erro_fatal", "mensagem": str(e)})
        finally:
            fila.put(None)  # sentinela: encerra o generator

    threading.Thread(target=produtor, daemon=True).start()

    def gerador_sse():
        while True:
            item = fila.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gerador_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # evita buffering em proxies (nginx etc)
        },
    )