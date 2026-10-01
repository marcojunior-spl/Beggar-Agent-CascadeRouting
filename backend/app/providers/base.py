"""
Interface abstrata LLMProvider.

Padroniza a forma como o restante da aplicação (registry, agente) interage
com qualquer modelo de LLM, seja ele um provedor em nuvem (via LiteLLM) ou
um modelo local (Ollama). Isso permite trocar/adicionar provedores sem
mudar o código que os consome.

Para um dev júnior: se um dia adicionarmos um provedor que o LiteLLM não
suporta nativamente (ex: uma API proprietária interna), a forma correta de
integrar é criar uma nova classe que implemente esta interface, em vez de
espalhar `if/else` pelo código do agente.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ResultadoGeracao:
    sucesso: bool
    texto: Optional[str] = None
    erro: Optional[Exception] = None


class LLMProvider(ABC):
    """Contrato mínimo que todo provedor de LLM usado pela aplicação deve implementar."""

    #: Nome amigável para exibição em logs/UI (ex: "Gemini 3.6 Flash (Google)").
    nome_exibicao: str

    #: Identificador do provedor no catálogo (ex: "google", "groq", "ollama").
    provedor_id: str

    @abstractmethod
    def obter_model_litellm(self) -> Any:
        """
        Retorna a instância configurada de `smolagents.LiteLLMModel` (ou
        compatível) pronta para ser usada pelo CodeAgent.
        """
        raise NotImplementedError

    @abstractmethod
    def check_health(self) -> bool:
        """
        Verificação leve e rápida de que o provedor está utilizável (ex: uma
        chave de API está presente, ou o servidor Ollama responde). Isso NÃO
        deve fazer uma chamada cara ao modelo — apenas uma checagem de
        pré-condições, usada pelo registry para pular provedores obviamente
        indisponíveis antes de gastar uma tentativa real.
        """
        raise NotImplementedError