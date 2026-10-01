"""
Catálogo de provedores de LLM suportados pela aplicação.

Este arquivo é só DADOS (nenhuma lógica de execução) — descreve, para cada
provedor, como montar o `model_id` que o LiteLLM espera, quais variáveis de
ambiente são necessárias, e uma classificação de "força" do modelo.

Para um dev júnior:
1. Confirme o formato exato do model_id na documentação oficial do LiteLLM
   (https://docs.litellm.ai/docs/providers) — cada provedor tem um prefixo
   diferente.
2. Adicione um novo `ModeloCatalogado` na lista `MODELOS_CATALOGADOS`.
3. Se for um provedor NOVO, adicione também uma `DefinicaoProvedor` na lista
   `CATALOGO_PROVEDORES`.
4. Rode `python verificar_modelos.py` (na pasta backend/, com venv ativo) para
   validar quais modelos estão respondendo AGORA.

LEMBRETE IMPORTANTE: modelos de IA são descontinuados com frequência. Se você
começar a ver erros 404 "model not found" ou "decommissioned", rode o script
de verificação e atualize os IDs aqui.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class NivelCapacidade(Enum):
    """
    Classifica a "força" de raciocínio de um modelo, usada pelo roteador de
    complexidade (complexidade.py) para decidir qual modelo tentar primeiro.

    RAPIDO: modelos pequenos/velozes, bons para saudações, perguntas diretas.
    EQUILIBRADO: modelos de porte médio, bons para a maioria das tarefas.
    RACIOCINIO: modelos grandes ou especializados em raciocínio.
    """
    RAPIDO = "rapido"
    EQUILIBRADO = "equilibrado"
    RACIOCINIO = "raciocinio"


@dataclass
class DefinicaoProvedor:
    """Descreve um provedor de LLM e como construir suas variantes de modelo."""

    id: str
    nome_exibicao: str
    env_api_key: str
    env_extra: List[str] = field(default_factory=list)
    gratuito: bool = True

    def esta_configurado(self, ambiente: dict) -> bool:
        """
        Verifica se todas as variáveis de ambiente necessárias estão presentes.

        Provedores sem `env_api_key` (ex: Ollama) são considerados NÃO
        configurados por este método — o Ollama é tratado à parte no registry.
        """
        if not self.env_api_key:
            return False
        if not ambiente.get(self.env_api_key):
            return False
        return all(ambiente.get(var) for var in self.env_extra)


@dataclass
class ModeloCatalogado:
    """Um modelo específico oferecido por um provedor, pronto para uso no LiteLLM."""

    provedor_id: str
    nome_exibicao: str
    model_id_template: str
    nivel: NivelCapacidade


# =====================================================================
# CATÁLOGO DE PROVEDORES
# =====================================================================
CATALOGO_PROVEDORES: List[DefinicaoProvedor] = [
    DefinicaoProvedor(id="google", nome_exibicao="Google AI Studio", env_api_key="GEMINI_API_KEY"),
    DefinicaoProvedor(id="groq", nome_exibicao="Groq Cloud", env_api_key="GROQ_API_KEY"),
    DefinicaoProvedor(id="openrouter", nome_exibicao="OpenRouter", env_api_key="OPENROUTER_API_KEY"),
    DefinicaoProvedor(id="github", nome_exibicao="GitHub Models", env_api_key="GITHUB_API_KEY"),
    DefinicaoProvedor(
        id="cloudflare", nome_exibicao="Cloudflare Workers AI",
        env_api_key="CLOUDFLARE_API_KEY", env_extra=["CLOUDFLARE_ACCOUNT_ID"],
    ),
    DefinicaoProvedor(id="mistral", nome_exibicao="Mistral AI", env_api_key="MISTRAL_API_KEY"),
    DefinicaoProvedor(id="cerebras", nome_exibicao="Cerebras Cloud", env_api_key="CEREBRAS_API_KEY"),
    DefinicaoProvedor(id="cohere", nome_exibicao="Cohere", env_api_key="COHERE_API_KEY"),
    DefinicaoProvedor(id="sambanova", nome_exibicao="SambaNova Cloud", env_api_key="SAMBANOVA_API_KEY"),
    DefinicaoProvedor(id="huggingface", nome_exibicao="Hugging Face", env_api_key="HF_TOKEN"),
    DefinicaoProvedor(id="ollama", nome_exibicao="Ollama (local)", env_api_key="", gratuito=True),
]


def obter_definicao(provedor_id: str) -> Optional[DefinicaoProvedor]:
    for p in CATALOGO_PROVEDORES:
        if p.id == provedor_id:
            return p
    return None


# =====================================================================
# MODELOS CATALOGADOS
# =====================================================================
# Verificado em 2026-09-13 (via verificar_modelos.py). Modelos com erro 404
# puro ou "payment required" foram removidos/comentados; erros transitórios
# (429) foram mantidos no catálogo.

MODELOS_CATALOGADOS: List[ModeloCatalogado] = [
    # --- Google AI Studio (2/2 ✅) ---
    ModeloCatalogado("google", "Gemini 3.5 Flash-Lite", "gemini/gemini-3.5-flash-lite", NivelCapacidade.RAPIDO),
    ModeloCatalogado("google", "Gemini 3.6 Flash", "gemini/gemini-3.6-flash", NivelCapacidade.EQUILIBRADO),

    # --- Groq Cloud (5/5 ✅) ---
    #ModeloCatalogado("groq", "Allam 2 7B (Groq)", "groq/allam-2-7b", NivelCapacidade.RAPIDO),
    ModeloCatalogado("groq", "GPT-OSS 20B (Groq)", "groq/openai/gpt-oss-20b", NivelCapacidade.RAPIDO),
    ModeloCatalogado("groq", "Qwen 3.6 27B (Groq)", "groq/qwen/qwen3.6-27b", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("groq", "Qwen 3.8 27B (Groq)", "groq/qwen/qwen3.8-27b", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("groq", "GPT-OSS 120B (Groq)", "groq/openai/gpt-oss-120b", NivelCapacidade.RACIOCINIO),

    # --- OpenRouter (selecionados do tier :free atual em 2026-09-13) ---
    # Lista completa de slugs :free via:
    #   curl -sS https://openrouter.ai/api/v1/models \
    #     -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    #     | python -c "import sys,json; d=json.load(sys.stdin); [print(m['id']) for m in d['data'] if m['id'].endswith(':free')]"
    ModeloCatalogado("openrouter", "LFM 2.5 2.6B Free (OpenRouter)", "openrouter/liquid/lfm-2.5-2.6b:free", NivelCapacidade.RAPIDO),
    ModeloCatalogado("openrouter", "Gemma 4 31B Free (OpenRouter)", "openrouter/google/gemma-4-31b-it:free", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("openrouter", "North Mini Code Free (OpenRouter)", "openrouter/cohere/north-mini-code:free", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("openrouter", "Nemotron 3 Super 120B Free (OpenRouter)", "openrouter/nvidia/nemotron-3-super-120b-a12b:free", NivelCapacidade.RACIOCINIO),

    # --- GitHub Models ---
    # ATENÇÃO: o endpoint do GitHub Models mudou e o LiteLLM 1.100.1 (o que
    # temos instalado) ainda aponta para o antigo, que responde HTTP 410 Gone.
    # Verificado com curl em 2026-09-13.
    # Descomentar quando sair versão do litellm que suporte o novo endpoint:
    # ModeloCatalogado("github", "GPT-4o-mini (GitHub Models)", "github/gpt-4o-mini", NivelCapacidade.RAPIDO),
    # ModeloCatalogado("github", "Phi-4 (GitHub Models)", "github/Phi-4", NivelCapacidade.EQUILIBRADO),
    # ModeloCatalogado("github", "DeepSeek R1 (GitHub Models)", "github/DeepSeek-R1", NivelCapacidade.RACIOCINIO),

    # --- Cloudflare Workers AI (3/3 ✅) ---
    ModeloCatalogado("cloudflare", "Qwen 2.5 Coder 32B (Cloudflare)", "cloudflare/@cf/qwen/qwen2.5-coder-32b-instruct", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("cloudflare", "DeepSeek R1 Distill 32B (Cloudflare)", "cloudflare/@cf/deepseek-ai/deepseek-r1-distill-qwen-32b", NivelCapacidade.RACIOCINIO),
    ModeloCatalogado("cloudflare", "Llama 3.3 70B Fast (Cloudflare)", "cloudflare/@cf/meta/llama-3.3-70b-instruct-fp8-fast", NivelCapacidade.EQUILIBRADO),

    # --- Mistral AI (1/2 ✅; Mistral Small dá 429 transitório, mantido) ---
    ModeloCatalogado("mistral", "Mistral Small (código/geral)", "mistral/mistral-small-latest", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("mistral", "Codestral (geração de código)", "mistral/codestral-latest", NivelCapacidade.RACIOCINIO),

    # --- Cerebras Cloud ---
    # Sua conta não tem tier gratuito (retorna "Payment required" para todos).
    # A listagem `/v1/models` mostra modelos que a conta NÃO pode usar (ex:
    # gemma-4-31b retorna NotFoundError) — peculiaridade do Cerebras.
    # Se um dia você assinar, os IDs da sua conta aparecem em:
    #   curl -sS https://api.cerebras.ai/v1/models -H "Authorization: Bearer $CEREBRAS_API_KEY"
    # e aí é só descomentar e ajustar:
    # ModeloCatalogado("cerebras", "...", "cerebras/...", NivelCapacidade.RACIOCINIO),

    # --- Cohere (2/2 ✅) ---
    ModeloCatalogado("cohere", "Command R (Cohere)", "cohere_chat/command-r-08-2024", NivelCapacidade.EQUILIBRADO),
    ModeloCatalogado("cohere", "Command R+ (Cohere)", "cohere_chat/command-r-plus-08-2024", NivelCapacidade.RACIOCINIO),

    # --- SambaNova Cloud ---
    # Retornou erro de acesso/pagamento em 2026-09-13. Comentado.
    # ModeloCatalogado("sambanova", "Llama 3.3 70B (SambaNova)", "sambanova/Meta-Llama-3.3-70B-Instruct", NivelCapacidade.EQUILIBRADO),
    # ModeloCatalogado("sambanova", "Llama 3.1 405B (SambaNova)", "sambanova/Meta-Llama-3.1-405B-Instruct", NivelCapacidade.RACIOCINIO),

    # --- Hugging Face ---
    # Deu "Model ... is not supported for provider together". Comentado.
    # ModeloCatalogado("huggingface", "DeepSeek R1 via HF", "huggingface/together/deepseek-ai/DeepSeek-R1", NivelCapacidade.RACIOCINIO),
]