"""
ProviderRegistry & FallbackChain: o núcleo de orquestração de provedores.

Responsabilidades:
1. Descobrir quais provedores estão configurados via env vars.
2. Montar uma cadeia de tentativa (FallbackChain) ordenada por complexidade,
   cota disponível e prioridade.
3. Cooldown por provedor após 429 (RPM = 60s; cota diária = 1h).

Para um dev júnior:
- Se um provedor está tomando 429 com frequência, `RastreadorCota` o marca
  como indisponível por um tempo para não desperdiçar tentativas nele.
- Esse rastreamento é em memória (reinicia com o processo).
"""

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .base import LLMProvider
from .catalogo import (
    CATALOGO_PROVEDORES,
    MODELOS_CATALOGADOS,
    NivelCapacidade,
    ModeloCatalogado,
    obter_definicao,
)
from .implementacoes import ProvedorLiteLLM, ProvedorOllama
from .complexidade import TaskComplexityRouter, ResultadoClassificacao

# Cooldown padrão após um 429 transitório (rate limit por minuto, RPM).
COOLDOWN_APOS_429_SEGUNDOS = 60

# Cooldown depois de uma cota DIÁRIA esgotada. Não adianta tentar de novo —
# a quota só renova no dia seguinte. 1h é um compromisso pragmático.
COOLDOWN_QUOTA_DIARIA_SEGUNDOS = 3600

# Ordem de preferência entre níveis quando o nível ideal não tem nenhum
# provedor disponível — tenta o nível pedido, depois vai "subindo".
ORDEM_FALLBACK_DE_NIVEL = {
    NivelCapacidade.RAPIDO: [NivelCapacidade.RAPIDO, NivelCapacidade.EQUILIBRADO, NivelCapacidade.RACIOCINIO],
    NivelCapacidade.EQUILIBRADO: [NivelCapacidade.EQUILIBRADO, NivelCapacidade.RACIOCINIO, NivelCapacidade.RAPIDO],
    NivelCapacidade.RACIOCINIO: [NivelCapacidade.RACIOCINIO, NivelCapacidade.EQUILIBRADO, NivelCapacidade.RAPIDO],
}


@dataclass
class RastreadorCota:
    """
    Guarda, por MODELO (não por provedor/empresa), quando foi o último 429 e
    por quanto tempo o modelo deve ficar de molho.
    dict chave_modelo -> (timestamp, cooldown_segundos).

    IMPORTANTE: a chave é (provedor_id, nome_exibicao), não só provedor_id.
    Um provedor como Groq ou Google oferece VÁRIOS modelos no catálogo
    (catalogo.py). Rate limit é aplicado por modelo pela maioria das APIs,
    não pela conta inteira — usar só provedor_id como chave faz um 429 em
    um único modelo (ex: "GPT-OSS 20B (Groq)") derrubar TODOS os outros
    modelos do mesmo provedor (ex: as outras 3 opções da Groq), mesmo que
    eles tenham cota própria intacta. Isso já foi observado esvaziando a
    cadeia inteira de fallback para provedores com múltiplos modelos.
    """
    ultimo_429_por_modelo: Dict[tuple, tuple] = field(default_factory=dict)

    @staticmethod
    def _chave(provedor_id: str, nome_exibicao: str) -> tuple:
        return (provedor_id, nome_exibicao)

    def registrar_429(
        self, provedor_id: str, nome_exibicao: str,
        cooldown_segundos: int = COOLDOWN_APOS_429_SEGUNDOS,
    ):
        chave = self._chave(provedor_id, nome_exibicao)
        self.ultimo_429_por_modelo[chave] = (time.time(), cooldown_segundos)

    def esta_em_cooldown(self, provedor_id: str, nome_exibicao: str) -> bool:
        chave = self._chave(provedor_id, nome_exibicao)
        entry = self.ultimo_429_por_modelo.get(chave)
        if entry is None:
            return False
        quando, cooldown = entry
        return (time.time() - quando) < cooldown

    def limpar(self, provedor_id: str, nome_exibicao: str):
        self.ultimo_429_por_modelo.pop(self._chave(provedor_id, nome_exibicao), None)


class ProviderRegistry:
    """Descobre provedores configurados e constrói instâncias de LLMProvider."""

    def __init__(self, ambiente: Optional[Dict[str, str]] = None):
        self._ambiente = ambiente if ambiente is not None else os.environ
        self.rastreador_cota = RastreadorCota()
        self._provedores_por_nivel: Dict[NivelCapacidade, List[LLMProvider]] = {
            nivel: [] for nivel in NivelCapacidade
        }
        self._provedor_ollama: Optional[LLMProvider] = None
        self._descobrir_provedores()

    def _descobrir_provedores(self):
        for modelo in MODELOS_CATALOGADOS:
            definicao = obter_definicao(modelo.provedor_id)
            if definicao is None:
                continue
            if not definicao.esta_configurado(self._ambiente):
                continue

            api_key = self._ambiente[definicao.env_api_key]
            env_extra_valores = {
                var: self._ambiente.get(var, "")
                for var in definicao.env_extra
            }

            provedor = ProvedorLiteLLM(
                modelo=modelo,
                definicao=definicao,
                api_key=api_key,
                env_extra_valores=env_extra_valores,
            )
            self._provedores_por_nivel[modelo.nivel].append(provedor)

        if self._ambiente.get("OLLAMA_ENABLED", "true").lower() in ("1", "true", "yes"):
            nome_modelo = self._ambiente.get("OLLAMA_MODEL", "deepseek-r1:1.7b")
            api_base = self._ambiente.get("OLLAMA_API_BASE", "http://localhost:11434")
            self._provedor_ollama = ProvedorOllama(nome_modelo=nome_modelo, api_base=api_base)

    def tem_algum_provedor_em_nuvem(self) -> bool:
        return any(self._provedores_por_nivel[n] for n in NivelCapacidade)

    def tem_ollama(self) -> bool:
        return self._provedor_ollama is not None

    def listar_todos(self) -> List[LLMProvider]:
        """Lista achatada de todos os provedores em nuvem configurados (sem o Ollama)."""
        todos = []
        for nivel in NivelCapacidade:
            todos.extend(self._provedores_por_nivel[nivel])
        return todos

    def obter_ollama(self) -> Optional[LLMProvider]:
        return self._provedor_ollama


class FallbackChain:
    """
    Monta, para um prompt específico, a ordem de tentativa de provedores:
    nuvem (priorizada por complexidade e cota) e, por último, Ollama.
    """

    def __init__(self, registry: ProviderRegistry):
        self._registry = registry

    def montar_cadeia(self, prompt: str) -> List[LLMProvider]:
        classificacao: ResultadoClassificacao = TaskComplexityRouter.classificar(prompt)
        ordem_niveis = ORDEM_FALLBACK_DE_NIVEL[classificacao.nivel]

        cadeia: List[LLMProvider] = []
        ja_incluidos = set()

        for nivel in ordem_niveis:
            for provedor in self._registry._provedores_por_nivel[nivel]:
                chave_unica = (provedor.provedor_id, provedor.nome_exibicao)
                if self._registry.rastreador_cota.esta_em_cooldown(*chave_unica):
                    continue
                if chave_unica in ja_incluidos:
                    continue
                cadeia.append(provedor)
                ja_incluidos.add(chave_unica)

        # Modelo local SEMPRE por último — fallback extremo.
        ollama = self._registry.obter_ollama()
        if ollama is not None:
            cadeia.append(ollama)

        return cadeia

    def registrar_erro(
        self,
        provedor: LLMProvider,
        eh_rate_limit: bool,
        eh_quota_diaria: bool = False,
    ):
        if eh_rate_limit:
            cooldown = (
                COOLDOWN_QUOTA_DIARIA_SEGUNDOS if eh_quota_diaria
                else COOLDOWN_APOS_429_SEGUNDOS
            )
            self._registry.rastreador_cota.registrar_429(
                provedor.provedor_id, provedor.nome_exibicao, cooldown_segundos=cooldown
            )

    def registrar_sucesso(self, provedor: LLMProvider):
        self._registry.rastreador_cota.limpar(provedor.provedor_id, provedor.nome_exibicao)