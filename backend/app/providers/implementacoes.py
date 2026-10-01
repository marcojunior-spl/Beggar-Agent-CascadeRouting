"""
Implementação concreta de LLMProvider usando smolagents.LiteLLMModel.

Cobre tanto provedores em nuvem (Gemini, Groq, OpenRouter, etc, todos via
LiteLLM) quanto o modelo local via Ollama.

IMPORTANTE sobre retry:
- Passamos `num_retries=0` e `timeout=X` para o LiteLLMModel. Isso desliga o
  retry INTERNO do LiteLLM, que historicamente esperava "RetryInfo.retryDelay"
  (ex: 43s) e retentava por conta própria, queimando minutos do orçamento
  global antes do nosso orquestrador sequer ser notificado. Quem decide
  quando parar de tentar é o `_tentar_provedor_com_retry` em agente.py.
"""

import os
import logging
from typing import Optional

from smolagents import LiteLLMModel

from .base import LLMProvider
from .catalogo import ModeloCatalogado, DefinicaoProvedor

logger = logging.getLogger("AgenteResiliente.Providers")

# Timeout HTTP duro por chamada individual (segundos). Uma vez estourado,
# a exceção sobe pro nosso orquestrador, que decide se retenta ou pula
# pro próximo provedor. Sem isso, o LiteLLM pode ficar pendurado muito
# mais tempo do que o orçamento global permite.
TIMEOUT_HTTP_POR_CHAMADA = int(os.environ.get("PROVEDOR_TIMEOUT_HTTP_SEGUNDOS", "60"))


class ProvedorLiteLLM(LLMProvider):
    """
    Provedor genérico que delega a chamada real ao LiteLLM. Funciona para
    qualquer provedor em nuvem suportado.
    """

    def __init__(
        self,
        modelo: ModeloCatalogado,
        definicao: DefinicaoProvedor,
        api_key: str,
        env_extra_valores: Optional[dict] = None,
        max_tokens: int = 800,
    ):
        self.nome_exibicao = modelo.nome_exibicao
        self.provedor_id = modelo.provedor_id
        self._modelo = modelo
        self._definicao = definicao
        self._api_key = api_key
        self._env_extra_valores = env_extra_valores or {}
        self._max_tokens = max_tokens
        self._instancia_litellm: Optional[LiteLLMModel] = None

    def check_health(self) -> bool:
        return bool(self._api_key)

    def obter_model_litellm(self) -> LiteLLMModel:
        if self._instancia_litellm is None:
            # Alguns provedores esperam a chave via variável de ambiente, além
            # do parâmetro direto — mantemos os dois.
            os.environ[self._definicao.env_api_key] = self._api_key

            # Provedores com env_extra (ex: Cloudflare com CLOUDFLARE_ACCOUNT_ID)
            # também precisam dessas vars no ambiente para o LiteLLM montar o
            # endpoint correto.
            for nome_var, valor in self._env_extra_valores.items():
                if valor:
                    os.environ[nome_var] = valor

            model_id = self._modelo.model_id_template
            logger.info(f"Criando LiteLLMModel: {model_id} (provedor={self._definicao.id})")

            self._instancia_litellm = LiteLLMModel(
                model_id=model_id,
                api_key=self._api_key,
                max_tokens=self._max_tokens,
                # Desliga o retry interno do LiteLLM — quem orquestra é o
                # nosso agente.py (com backoff, cooldown, e orçamento global).
                num_retries=0,
                # Timeout HTTP duro para UMA chamada. Sem isso, quando o
                # provedor responde com "RetryInfo.retryDelay: 43s", o
                # LiteLLM pode esperar e retentar internamente por minutos.
                timeout=TIMEOUT_HTTP_POR_CHAMADA,
            )

        return self._instancia_litellm


class ProvedorOllama(LLMProvider):
    """
    Provedor para um modelo rodando localmente via Ollama.
    """

    provedor_id = "ollama"

    def __init__(self, nome_modelo: str, api_base: str, num_ctx: int = 4096, max_tokens: int = 800):
        self.nome_exibicao = f"{nome_modelo} (Ollama local)"
        self._nome_modelo = nome_modelo
        self._api_base = api_base
        self._num_ctx = num_ctx
        self._max_tokens = max_tokens
        self._instancia_litellm: Optional[LiteLLMModel] = None

    def check_health(self) -> bool:
        try:
            import httpx
            resposta = httpx.get(f"{self._api_base}/api/tags", timeout=1.5)
            return resposta.status_code == 200
        except Exception:
            return False

    def obter_model_litellm(self) -> LiteLLMModel:
        if self._instancia_litellm is None:
            self._instancia_litellm = LiteLLMModel(
                model_id=f"ollama_chat/{self._nome_modelo}",
                api_base=self._api_base,
                api_key="ollama-local",
                num_ctx=self._num_ctx,
                max_tokens=self._max_tokens,
                num_retries=0,
                timeout=TIMEOUT_HTTP_POR_CHAMADA,
            )
        return self._instancia_litellm