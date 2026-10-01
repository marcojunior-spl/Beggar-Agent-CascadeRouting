"""
Núcleo do Agente Resiliente Híbrido (multi-provedor com roteamento por
complexidade e fallback em cascata).

Este arquivo é usado tanto pelo backend web (api.py) quanto pelo modo CLI (cli.py).
Não deve conter nenhuma chave de API — todas vêm de variáveis de ambiente (.env).

Para um dev júnior:
- Se quiser ADICIONAR uma nova ferramenta, veja "FERRAMENTAS DO AGENTE".
- Se quiser ADICIONAR um provedor/modelo, veja app/providers/catalogo.py.
- Se quiser ENTENDER como um erro é classificado, veja diagnosticar_erro_llm.
- Para STREAMING (SSE), veja _executar_no_provedor_streaming.

IMPORTANTE sobre timeouts:
- TODA execução de provedor (nuvem OU Ollama) roda em thread separada com
  timeout. Isso porque uma única chamada do smolagents pode disparar vários
  steps internamente, e o retry interno do litellm pode obedecer
  `RetryInfo.retryDelay` do provedor (ex: Google devolve "retry in 9s" e o
  cliente espera de verdade). Já observamos um único `agente.run()` durar
  843 segundos, muito além de qualquer orçamento global nosso — o orçamento
  só é checado ENTRE tentativas, não DURANTE uma tentativa.
"""

import os
import json
import time
import logging
import concurrent.futures
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

import chromadb
from smolagents import CodeAgent, LiteLLMModel, tool

# =====================================================================
# CONFIGURAÇÃO DE LOGS ESTRUTURADOS
# =====================================================================
LOG_FILE = os.environ.get("AGENTE_LOG_FILE", "agente_falhas.log")

logger = logging.getLogger("AgenteResiliente")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


# =====================================================================
# BANCO VETORIAL (MEMÓRIA DO AGENTE)
# =====================================================================
CHROMA_DB_PATH = os.environ.get("AGENTE_CHROMA_PATH", "./chroma_db")

try:
    db_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    memoria = db_client.get_or_create_collection(name="memoria_projeto")
except Exception as e:
    logger.warning(f"ChromaDB não pôde ser inicializado em persistência local ({e}). Usando memória volátil.")
    memoria = None


# =====================================================================
# FERRAMENTAS DO AGENTE (TOOLS)
# =====================================================================
@tool
def ler_arquivo(caminho: str) -> str:
    """
    Lê o conteúdo de um arquivo de texto no sistema.
    Args:
        caminho: O caminho completo ou relativo para o arquivo que deve ser lido.
    """
    try:
        if not os.path.exists(caminho):
            return f"Erro: O arquivo '{caminho}' não foi encontrado."
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
        if len(conteudo) > 5000:
            return conteudo[:5000] + "\n\n[... Truncado ...]"
        return conteudo
    except Exception as e:
        return f"Erro: {str(e)}"


@tool
def criar_diretorio(caminho: str) -> str:
    """
    Cria uma nova pasta ou estrutura de diretórios no sistema local.
    Args:
        caminho: O caminho completo ou relativo do diretório a ser criado.
    """
    try:
        os.makedirs(caminho, exist_ok=True)
        return f"Diretório '{caminho}' criado."
    except Exception as e:
        return f"Erro: {str(e)}"


@tool
def criar_arquivo(caminho: str, conteudo: str) -> str:
    """
    Cria um novo arquivo no sistema com um conteúdo inicial.
    Args:
        caminho: O caminho completo ou relativo do arquivo.
        conteudo: O texto ou código que será escrito dentro do arquivo.
    """
    try:
        pasta_pai = os.path.dirname(caminho)
        if pasta_pai:
            os.makedirs(pasta_pai, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo)
        return f"Arquivo '{caminho}' criado."
    except Exception as e:
        return f"Erro: {str(e)}"


@tool
def salvar_memoria(titulo: str, conteudo: str) -> str:
    """
    Salva um fragmento de código, regra ou contexto na memória vetorial do projeto.
    Args:
        titulo: Um título curto e descritivo (ex: 'Regra de Banco de Dados').
        conteudo: O texto detalhado ou código que será salvo.
    """
    if memoria is None:
        return "Memória vetorial desabilitada nesta sessão."
    try:
        doc_id = titulo.lower().replace(" ", "_")
        memoria.upsert(
            documents=[conteudo],
            metadatas=[{"titulo": titulo, "timestamp": datetime.now().isoformat()}],
            ids=[doc_id],
        )
        return f"Memória '{titulo}' salva com sucesso."
    except Exception as e:
        return f"Erro ao salvar memória: {str(e)}"


@tool
def pesquisar_memoria(consulta: str) -> str:
    """
    Pesquisa na memória vetorial por regras ou códigos salvos anteriormente.
    Args:
        consulta: A frase de busca para encontrar memórias similares.
    """
    if memoria is None:
        return "Memória vetorial desabilitada nesta sessão."
    try:
        resultados = memoria.query(query_texts=[consulta], n_results=2)

        if not resultados["documents"] or not resultados["documents"][0]:
            return "Nenhuma memória encontrada."

        textos = resultados["documents"][0]
        titulos = [meta["titulo"] for meta in resultados["metadatas"][0]]

        resposta = "Memórias encontradas:\n"
        for i in range(len(textos)):
            resposta += f"- {titulos[i]}: {textos[i]}\n"
        return resposta
    except Exception as e:
        return f"Erro ao pesquisar memória: {str(e)}"


FERRAMENTAS_PADRAO = [criar_diretorio, criar_arquivo, ler_arquivo, salvar_memoria, pesquisar_memoria]


# =====================================================================
# CLASSIFICADOR ROBUSTO DE ERROS DE LLM
# =====================================================================
def diagnosticar_erro_llm(excecao: Exception, modelo_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analisa a exceção gerada pela chamada ao modelo LLM e extrai um diagnóstico
    claro com categoria, código HTTP e recomendação prática.
    """
    msg = str(excecao)
    tipo_excecao = type(excecao).__name__

    categoria = "Erro Geral de Execução"
    codigo_http: Optional[int] = None
    motivo_amigavel = "Ocorreu uma falha não especificada ao comunicar com o provedor."
    sugestao = "Verifique a conectividade com a internet e as credenciais."
    eh_quota_diaria = False

    if "404" in msg or "NotFoundError" in tipo_excecao or "not found" in msg.lower():
        categoria = "Modelo Inexistente ou Descontinuado (HTTP 404)"
        codigo_http = 404
        motivo_amigavel = (
            f"O identificador de modelo '{modelo_info.get('model_id')}' não foi localizado "
            f"na versão da API do provedor (ex: uso de '-latest' ou modelo descontinuado)."
        )
        sugestao = (
            "Consulte a lista atual de modelos do provedor e atualize o model_id "
            "correspondente em backend/app/providers/catalogo.py."
        )

    elif any(term in msg.lower() for term in ["401", "403", "unauthorized", "api_key_invalid", "permissiondenied", "invalid api key"]):
        categoria = "Falha de Autenticação / Chave Inválida (HTTP 401/403)"
        codigo_http = 401 if "401" in msg else 403
        motivo_amigavel = "A chave de API informada é inválida, expirou ou não possui permissão de acesso ao modelo."
        sugestao = "Verifique a variável de ambiente correspondente ao provedor no arquivo .env."

    elif "429" in msg or "RateLimitError" in tipo_excecao or "resource_exhausted" in msg.lower() or "quota" in msg.lower():
        categoria = "Limite de Taxa ou Quota Excedida (HTTP 429)"
        codigo_http = 429
        # Distinguir cota DIÁRIA (quotaId com "PerDay") de limite por minuto.
        # Diária não renova em segundos — retry é inútil.
        msg_lower = msg.lower().replace(" ", "")
        eh_quota_diaria = (
            "perday" in msg_lower
            or "per_day" in msg.lower()
            or "requests_per_day" in msg_lower
            or "generaterequestsperday" in msg_lower
        )
        if eh_quota_diaria:
            motivo_amigavel = (
                "A cota diária gratuita deste modelo foi esgotada. Ela só renova "
                "no próximo ciclo (geralmente à meia-noite UTC do provedor)."
            )
            sugestao = (
                "Trocar para outro provedor da esteira. Para aumentar a cota, "
                "considere o tier pago do provedor correspondente."
            )
        else:
            motivo_amigavel = "O limite de requisições por minuto (RPM) ou cota gratuita do provedor foi esgotado temporariamente."
            sugestao = "Aguarde alguns segundos ou alterne para um provedor com limites disponíveis."

    elif any(code in msg for code in ["500", "502", "503", "504"]) or "internal" in msg.lower() or "unavailable" in msg.lower():
        categoria = "Instabilidade do Servidor do Provedor (HTTP 5xx)"
        codigo_http = 503
        motivo_amigavel = "O servidor remoto do provedor de IA está enfrentando lentidão ou sobrecarga temporária."
        sugestao = "O fallback automático selecionará outro modelo até o serviço estabilizar."

    elif "timeout" in msg.lower() or "timed out" in msg.lower():
        categoria = "Tempo Limite de Resposta Excedido (Timeout)"
        codigo_http = 408
        motivo_amigavel = "O modelo demorou mais que o tempo limite configurado para gerar a resposta."
        sugestao = "Reduza a complexidade do prompt ou tente um modelo menor/mais rápido."

    elif "context" in msg.lower() and ("length" in msg.lower() or "window" in msg.lower() or "token" in msg.lower()):
        categoria = "Janela de Contexto Excedida"
        motivo_amigavel = "O prompt ou o histórico ultrapassou o limite máximo de tokens suportado por este modelo."
        sugestao = "Truncar o histórico de mensagens ou selecionar um modelo com janela maior."

    return {
        "categoria": categoria,
        "codigo_http": codigo_http,
        "tipo_excecao": tipo_excecao,
        "motivo_amigavel": motivo_amigavel,
        "sugestao": sugestao,
        "eh_rate_limit": codigo_http == 429,
        "eh_transitorio": codigo_http in (429, 503, 408),
        "eh_quota_diaria": eh_quota_diaria,
        "detalhes_brutos": (msg[:350] + "...") if len(msg) > 350 else msg,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# =====================================================================
# ORQUESTRAÇÃO MULTI-PROVEDOR
# =====================================================================
from .providers.registry import ProviderRegistry, FallbackChain
from .providers.complexidade import TaskComplexityRouter
from .providers.base import LLMProvider

# Tempo máximo (segundos) que uma chamada ao modelo local (Ollama) pode rodar
# antes de ser abortada. Modelo local "esquentando" pode demorar mais.
TIMEOUT_OLLAMA_SEGUNDOS = int(os.environ.get("OLLAMA_TIMEOUT_SEGUNDOS", "45"))

# Tempo máximo (segundos) que UMA chamada a um provedor em nuvem pode rodar
# antes de ser abandonada e o próximo da cadeia ser tentado. ESSENCIAL: sem
# isso, uma única chamada do smolagents pode durar 10+ minutos (o retry
# interno do litellm obedece `RetryInfo.retryDelay` do provedor). O timeout
# aqui garante que uma tentativa ruim não consuma todo o orçamento global.
TIMEOUT_POR_PROVEDOR_SEGUNDOS = int(os.environ.get("TIMEOUT_POR_PROVEDOR_SEGUNDOS", "45"))

# Tempo máximo TOTAL (segundos) que UMA requisição inteira pode gastar tentando
# todos os provedores, incluindo retries e backoffs em cascata.
TEMPO_MAXIMO_TOTAL_SEGUNDOS = int(os.environ.get("TEMPO_MAXIMO_TOTAL_SEGUNDOS", "90"))

# Quantas vezes tentamos de novo o MESMO provedor antes de desistir dele —
# só para erros transitórios (429, 503, timeout). Erros permanentes (404, 401)
# não fazem retry.
MAX_RETRIES_TRANSITORIO = 2
BACKOFF_INICIAL_SEGUNDOS = 2


class AssistenteDesenvolvimento:
    """
    Orquestra chamadas a múltiplos provedores de LLM com:
    - Roteamento por complexidade da tarefa (TaskComplexityRouter);
    - Fallback em cascata (FallbackChain), com rastreamento de cota;
    - Retry com backoff para erros transitórios (429/503/timeout);
    - Orçamento de tempo global (TEMPO_MAXIMO_TOTAL_SEGUNDOS);
    - Timeout por provedor (TIMEOUT_POR_PROVEDOR_SEGUNDOS) aplicado em TODAS
      as execuções (nuvem e local), via thread separada;
    - Modelo local via Ollama como fallback extremo;
    - Streaming opcional via `stream=True` (SSE).
    """

    def __init__(self):
        self.registry = ProviderRegistry()
        self.cadeia = FallbackChain(self.registry)

        if not self.registry.tem_algum_provedor_em_nuvem() and not self.registry.tem_ollama():
            raise RuntimeError(
                "Nenhum provedor configurado. Defina ao menos uma chave de API de algum "
                "provedor gratuito (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, etc) "
                "e/ou deixe OLLAMA_ENABLED=true para usar um modelo local. Veja .env.example."
            )

        self.historico_falhas: List[Dict[str, Any]] = []
        self._agentes_cache: Dict[str, CodeAgent] = {}
        # Executor compartilhado para toda execução de modelo. max_workers > 1
        # para que threads "vazadas" (chamadas que estouraram timeout mas cujo
        # agente.run() ainda está rodando em background até terminar sozinho)
        # não bloqueiem chamadas novas.
        self._executor_modelos = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="modelo"
        )

    def _obter_agente_para(self, provedor: LLMProvider) -> CodeAgent:
        """Cria (ou reaproveita, em cache) um CodeAgent para um provedor."""
        chave = f"{provedor.provedor_id}:{provedor.nome_exibicao}"
        if chave not in self._agentes_cache:
            modelo_litellm = provedor.obter_model_litellm()
            self._agentes_cache[chave] = CodeAgent(
                tools=FERRAMENTAS_PADRAO,
                model=modelo_litellm,
                additional_authorized_imports=["os", "datetime", "posixpath", "stat"],
                add_base_tools=False,
                max_steps=6,
            )
        return self._agentes_cache[chave]

    def _registrar_em_arquivo(self, log_entry: Dict[str, Any]):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def listar_provedores_status(self) -> List[Dict[str, Any]]:
        """Retorna a esteira de provedores conhecida (usado pela API/UI)."""
        resultado = []
        for provedor in self.registry.listar_todos():
            em_cooldown = self.registry.rastreador_cota.esta_em_cooldown(
                provedor.provedor_id, provedor.nome_exibicao
            )
            modelo_catalogado = getattr(provedor, "_modelo", None)
            model_id = modelo_catalogado.model_id_template if modelo_catalogado is not None else ""
            resultado.append({
                "id": f"{provedor.provedor_id}-{provedor.nome_exibicao}",
                "nome": provedor.nome_exibicao,
                "model_id": model_id,
                "provedor": provedor.provedor_id,
                "ativo": not em_cooldown,
                "em_cooldown": em_cooldown,
            })
        ollama = self.registry.obter_ollama()
        if ollama is not None:
            resultado.append({
                "id": "ollama-local",
                "nome": ollama.nome_exibicao,
                "model_id": "",
                "provedor": "ollama",
                "ativo": True,
                "em_cooldown": False,
            })
        return resultado

    def _executar_no_provedor_streaming(
        self,
        provedor: LLMProvider,
        prompt: str,
        emitir: Callable[[str, Dict[str, Any]], None],
    ) -> str:
        """
        Executa o prompt usando `agent.run(prompt, stream=True)`, emitindo um
        evento por step (planejamento/raciocínio/observação/resposta final).

        IMPORTANTE: NÃO usamos `stream_outputs=True` no construtor do CodeAgent
        — essa flag tem bug conhecido (issue huggingface/smolagents #1872).
        """
        agente = self._obter_agente_para(provedor)
        ultima_resposta: Optional[str] = None

        for step in agente.run(prompt, stream=True):
            nome_classe = type(step).__name__

            if nome_classe == "PlanningStep":
                emitir("step_planejamento", {
                    "texto": str(getattr(step, "plan", "") or ""),
                })
            elif nome_classe == "ActionStep":
                texto = getattr(step, "model_output", None)
                if texto:
                    emitir("step_raciocinio", {"texto": str(texto)})
                observacao = getattr(step, "observations", None)
                if observacao:
                    emitir("step_observacao", {"texto": str(observacao)})
                erro = getattr(step, "error", None)
                if erro:
                    emitir("step_erro", {"texto": str(erro)})
            elif nome_classe == "FinalAnswerStep":
                saida = getattr(step, "output", None)
                if saida is not None:
                    ultima_resposta = str(saida)

        if ultima_resposta is None:
            raise RuntimeError(
                "Streaming terminou sem FinalAnswerStep — o provedor não devolveu resposta final."
            )
        return ultima_resposta

    def _executar_no_provedor(
        self,
        provedor: LLMProvider,
        prompt: str,
        stream: bool = False,
        emitir: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        timeout_maximo: Optional[float] = None,
    ) -> str:
        """
        Executa o prompt em um provedor específico, SEMPRE em thread separada
        com timeout.

        O timeout "de cheio" é TIMEOUT_OLLAMA_SEGUNDOS para Ollama (modelo
        local pode demorar mais para "esquentar") e TIMEOUT_POR_PROVEDOR_SEGUNDOS
        para provedores em nuvem. Se `timeout_maximo` for informado (porque o
        orçamento GLOBAL restante é menor que o timeout de cheio), o timeout
        efetivo é o menor dos dois — isso é o que garante que uma tentativa
        (ou retry) num provedor lento nunca consuma sozinha todo o orçamento
        do cascade, deixando zero tempo para tentar os próximos provedores.

        Quando o timeout estoura, a thread em background não é morta (Python
        não permite matar threads com segurança) — ela continua rodando até
        terminar sozinha, mas o orquestrador SEGUE EM FRENTE para o próximo
        da cadeia. O executor tem max_workers=4 justamente para que essas
        threads vazadas não bloqueiem as próximas chamadas.
        """
        timeout_cheio = (
            TIMEOUT_OLLAMA_SEGUNDOS
            if provedor.provedor_id == "ollama"
            else TIMEOUT_POR_PROVEDOR_SEGUNDOS
        )
        timeout = min(timeout_cheio, timeout_maximo) if timeout_maximo is not None else timeout_cheio

        if stream and emitir is not None:
            future = self._executor_modelos.submit(
                self._executar_no_provedor_streaming, provedor, prompt, emitir
            )
        else:
            agente = self._obter_agente_para(provedor)
            future = self._executor_modelos.submit(agente.run, prompt)

        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # Tenta cancelar — só funciona se ainda não começou a rodar.
            # Se já estiver rodando, o cancel é no-op e a thread segue.
            future.cancel()
            raise TimeoutError(
                f"{provedor.nome_exibicao} não respondeu em {timeout}s (timeout). "
                f"Seguindo para o próximo provedor da cadeia."
            )

    def executar_com_fallback(
        self,
        prompt: str,
        on_evento: Optional[Callable[[Dict[str, Any]], None]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Executa o prompt do usuário com resiliência total.
        Se `stream=True`, cada step do agente é emitido em tempo real via
        `on_evento` (útil para SSE no endpoint /api/chat/stream).
        """

        def emitir(tipo: str, dados: Dict[str, Any]):
            if on_evento:
                try:
                    on_evento({"tipo": tipo, **dados})
                except Exception:
                    pass

        classificacao = TaskComplexityRouter.classificar(prompt)
        cadeia = self.cadeia.montar_cadeia(prompt)

        emitir("classificacao", {
            "nivel": classificacao.nivel.value,
            "motivo": classificacao.motivo,
        })

        if not cadeia:
            msg_fatal = (
                "Nenhum provedor disponível: todas as APIs configuradas estão em cooldown "
                "por rate-limit e não há modelo local (Ollama) habilitado."
            )
            emitir("erro_fatal", {"mensagem": msg_fatal})
            return {
                "sucesso": False,
                "resposta": msg_fatal,
                "modelo_final": None,
                "fallback_acionado": True,
                "modelos_tentados": [],
                "modelos_falhados": [],
                "nivel_complexidade": classificacao.nivel.value,
                "motivo_complexidade": classificacao.motivo,
            }

        modelos_tentados: List[str] = []
        modelos_falhados: List[Dict[str, Any]] = []
        fallback_ocorreu = False
        inicio_total = time.time()
        timeout_global_acionado = False

        for indice, provedor in enumerate(cadeia):
            decorrido = time.time() - inicio_total
            tempo_restante_global = TEMPO_MAXIMO_TOTAL_SEGUNDOS - decorrido
            if tempo_restante_global <= 0:
                timeout_global_acionado = True
                emitir("timeout_global", {
                    "mensagem": (
                        f"Orçamento total de {TEMPO_MAXIMO_TOTAL_SEGUNDOS}s esgotado "
                        f"({round(decorrido, 1)}s decorridos). Abortando cascade."
                    ),
                    "segundos_decorridos": round(decorrido, 1),
                })
                break

            # Reserva uma fatia justa do tempo restante para ESTE provedor,
            # em vez de deixá-lo (com seus retries) consumir o orçamento
            # global inteiro sozinho. Isso é o que garante que, mesmo se o
            # primeiro provedor da cadeia travar/timeout repetidamente, ainda
            # sobre tempo real para tentar os próximos — sem essa reserva, um
            # único provedor lento podia esgotar TEMPO_MAXIMO_TOTAL_SEGUNDOS
            # inteiro antes do loop sequer chegar ao segundo item da cadeia.
            provedores_restantes = len(cadeia) - indice
            orcamento_provedor = tempo_restante_global / provedores_restantes

            modelos_tentados.append(provedor.nome_exibicao)
            emitir("tentativa", {
                "modelo": provedor.nome_exibicao,
                "indice": indice,
                "total": len(cadeia),
                "eh_fallback": indice > 0,
                "eh_local": provedor.provedor_id == "ollama",
            })

            resultado_provedor = self._tentar_provedor_com_retry(
                provedor, prompt, emitir,
                stream=stream, inicio_total=inicio_total,
                orcamento_provedor_segundos=orcamento_provedor,
            )

            if resultado_provedor["sucesso"]:
                self.cadeia.registrar_sucesso(provedor)
                return {
                    "sucesso": True,
                    "resposta": resultado_provedor["resposta"],
                    "modelo_final": provedor.nome_exibicao,
                    "fallback_acionado": fallback_ocorreu,
                    "modelos_tentados": modelos_tentados,
                    "modelos_falhados": modelos_falhados,
                    "duracao_segundos": resultado_provedor["duracao"],
                    "nivel_complexidade": classificacao.nivel.value,
                    "motivo_complexidade": classificacao.motivo,
                    "tempo_total_segundos": round(time.time() - inicio_total, 2),
                }

            fallback_ocorreu = True
            diag = resultado_provedor.get("diagnostico") or {}
            modelos_falhados.append({
                "nome": provedor.nome_exibicao,
                "categoria": diag.get("categoria", "Erro Desconhecido"),
                "codigo_http": diag.get("codigo_http"),
            })
            self.cadeia.registrar_erro(
                provedor,
                eh_rate_limit=diag.get("eh_rate_limit", False),
                eh_quota_diaria=diag.get("eh_quota_diaria", False),
            )

        if timeout_global_acionado:
            msg_fatal = (
                f"Orçamento total de {TEMPO_MAXIMO_TOTAL_SEGUNDOS}s esgotado antes de obter "
                f"resposta. Consulte '{LOG_FILE}' para o relatório completo."
            )
        else:
            msg_fatal = (
                "Erro fatal: todos os provedores configurados (incluindo o modelo local, se "
                f"habilitado) falharam. Consulte '{LOG_FILE}' para o relatório completo."
            )
        emitir("erro_fatal", {"mensagem": msg_fatal})
        return {
            "sucesso": False,
            "resposta": msg_fatal,
            "modelo_final": None,
            "fallback_acionado": True,
            "modelos_tentados": modelos_tentados,
            "modelos_falhados": modelos_falhados,
            "historico_erros": self.historico_falhas,
            "nivel_complexidade": classificacao.nivel.value,
            "motivo_complexidade": classificacao.motivo,
            "tempo_total_segundos": round(time.time() - inicio_total, 2),
            "timeout_global_acionado": timeout_global_acionado,
        }

    def _tentar_provedor_com_retry(
        self,
        provedor: LLMProvider,
        prompt: str,
        emitir: Callable[[str, Dict[str, Any]], None],
        stream: bool = False,
        inicio_total: Optional[float] = None,
        orcamento_provedor_segundos: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Tenta um único provedor, com retry+backoff exponencial para erros
        transitórios (429, 503, timeout). Erros permanentes (404, 401) não
        fazem retry.

        Dois orçamentos são respeitados simultaneamente:
        1. `TEMPO_MAXIMO_TOTAL_SEGUNDOS` (global, via `inicio_total`): a
           requisição inteira nunca deve passar disso, não importa quantos
           provedores existam na cadeia.
        2. `orcamento_provedor_segundos` (fatia justa deste provedor, calculada
           pelo chamador como tempo_restante / provedores_restantes): impede
           que ESTE provedor sozinho — mesmo com seus retries internos —
           consuma todo o orçamento global, o que impediria o cascade de
           sequer tentar os próximos provedores da cadeia.

        Bug corrigido: antes, cada tentativa (e cada retry) era limitada só
        pelo timeout "de cheio" do provedor (TIMEOUT_POR_PROVEDOR_SEGUNDOS).
        Como esse timeout de cheio podia, por si só, se aproximar do
        orçamento GLOBAL (ex: 45s de timeout vs 90s de orçamento total), duas
        tentativas transitórias no MESMO provedor já esgotavam o orçamento
        inteiro, e o `for` da cadeia nunca chegava ao segundo provedor —
        exatamente o comportamento relatado (duas tentativas na mesma LLM,
        depois "orçamento esgotado", sem fallback de verdade).
        """
        tentativa = 0
        diagnostico_final = None
        inicio_total = inicio_total or time.time()
        inicio_provedor = time.time()

        # Reserva mínima de tempo para que valha a pena sequer tentar: uma
        # tentativa com menos de 1s de orçamento não tem chance real de
        # completar, então é melhor desistir deste provedor imediatamente e
        # deixar o tempo restante (se houver) para o próximo da cadeia.
        ORCAMENTO_MINIMO_POR_TENTATIVA = 1.0

        while tentativa <= MAX_RETRIES_TRANSITORIO:
            tempo_restante_global = TEMPO_MAXIMO_TOTAL_SEGUNDOS - (time.time() - inicio_total)
            tempo_restante_provedor = (
                orcamento_provedor_segundos - (time.time() - inicio_provedor)
                if orcamento_provedor_segundos is not None
                else tempo_restante_global
            )
            # O orçamento efetivo desta tentativa é o menor dos dois limites.
            tempo_restante = min(tempo_restante_global, tempo_restante_provedor)

            if tempo_restante <= ORCAMENTO_MINIMO_POR_TENTATIVA:
                emitir("timeout_global", {
                    "mensagem": "Orçamento esgotado (global ou fatia deste provedor) — desistindo deste provedor.",
                })
                break

            t_inicio = time.time()
            try:
                resposta = self._executar_no_provedor(
                    provedor, prompt, stream=stream, emitir=emitir,
                    timeout_maximo=tempo_restante,
                )
                duracao = round(time.time() - t_inicio, 2)
                emitir("sucesso", {"modelo": provedor.nome_exibicao, "duracao": duracao})
                return {"sucesso": True, "resposta": resposta, "duracao": duracao}

            except Exception as e:
                duracao = round(time.time() - t_inicio, 2)
                modelo_catalogado = getattr(provedor, "_modelo", None)
                model_id = (
                    modelo_catalogado.model_id_template
                    if modelo_catalogado is not None
                    else provedor.nome_exibicao
                )
                info_modelo = {"model_id": model_id}
                diagnostico_final = diagnosticar_erro_llm(e, info_modelo)

                log_entry = {
                    "timestamp": diagnostico_final["timestamp"],
                    "modelo": provedor.nome_exibicao,
                    "model_id": info_modelo["model_id"],
                    "duracao_segundos": duracao,
                    "categoria": diagnostico_final["categoria"],
                    "codigo_http": diagnostico_final["codigo_http"],
                    "motivo": diagnostico_final["motivo_amigavel"],
                    "sugestao": diagnostico_final["sugestao"],
                    "erro_bruto": diagnostico_final["detalhes_brutos"],
                    "tentativa": tentativa + 1,
                }
                self.historico_falhas.append(log_entry)
                self._registrar_em_arquivo(log_entry)
                emitir("falha", {"log": log_entry})

                eh_transitorio = diagnostico_final.get("eh_transitorio", False)
                # Não faz retry em timeout do modelo LOCAL: se o Ollama já
                # travou/demorou demais uma vez, insistir nele imediatamente
                # só desperdiça tempo — ele é o fallback extremo.
                eh_timeout_local = (
                    provedor.provedor_id == "ollama"
                    and diagnostico_final.get("codigo_http") == 408
                )

                tempo_restante_global_apos = TEMPO_MAXIMO_TOTAL_SEGUNDOS - (time.time() - inicio_total)
                tempo_restante_provedor_apos = (
                    orcamento_provedor_segundos - (time.time() - inicio_provedor)
                    if orcamento_provedor_segundos is not None
                    else tempo_restante_global_apos
                )
                tempo_restante_apos_falha = min(tempo_restante_global_apos, tempo_restante_provedor_apos)
                espera = BACKOFF_INICIAL_SEGUNDOS * (2 ** tentativa)
                cabe_mais_uma_tentativa = (
                    tempo_restante_apos_falha - espera > ORCAMENTO_MINIMO_POR_TENTATIVA
                )

                if (
                    eh_transitorio
                    and not eh_timeout_local
                    and tentativa < MAX_RETRIES_TRANSITORIO
                    and cabe_mais_uma_tentativa
                ):
                    emitir("retry", {
                        "modelo": provedor.nome_exibicao,
                        "tentativa": tentativa + 1,
                        "espera_segundos": espera,
                    })
                    time.sleep(espera)
                    tentativa += 1
                    continue

                # Erro permanente, orçamento insuficiente para mais uma
                # tentativa (seja o global ou a fatia deste provedor), ou já
                # esgotou as retentativas transitórias: desiste deste
                # provedor e deixa a cadeia seguir para o próximo (é isso que
                # garante o fallback de verdade).
                break

        return {"sucesso": False, "diagnostico": diagnostico_final}