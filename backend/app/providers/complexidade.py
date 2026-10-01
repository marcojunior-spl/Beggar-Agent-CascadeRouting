"""
TaskComplexityRouter: classifica a complexidade de um pedido do usuário usando
heurísticas determinísticas (sem chamar nenhum LLM), para decidir qual "nível"
de modelo tentar primeiro (ver NivelCapacidade em catalogo.py).

Por que heurística e não um LLM classificador?
- É instantâneo (não gasta uma chamada de API nem tempo de rede).
- É determinístico e fácil de debugar/ajustar.
- Um classificador via LLM também poderia falhar/ter rate-limit, e aí
  precisaríamos de fallback PRO CLASSIFICADOR — complexidade desnecessária
  para o que é, na prática, uma decisão simples.

Para um dev júnior: os limites de tamanho de prompt (curto/médio/longo) e as
listas de palavras-chave abaixo são ajustáveis. Se perceber que tarefas estão
sendo roteadas para o nível errado, o primeiro lugar a olhar é
`PALAVRAS_CHAVE_ALTA_COMPLEXIDADE` e `PALAVRAS_CHAVE_BAIXA_COMPLEXIDADE`.
"""

import re
from dataclasses import dataclass

from .catalogo import NivelCapacidade


def _contem_termo(texto: str, termo: str) -> bool:
    """
    Verifica se `termo` aparece em `texto` como PALAVRA/EXPRESSÃO INTEIRA,
    não como substring solta.

    Antes, a checagem era `termo in texto`, o que causava falsos positivos
    graves: a palavra-chave curta "oi" (saudação) "aparecia dentro" de
    palavras comuns como "foi", "apoio", "depois", "coisa" — classificando
    incorretamente qualquer prompt com essas palavras como trivial/RAPIDO.
    O mesmo valia para "não" dentro de "organização", "nação" etc.

    Usamos fronteira de palavra (\\b) nas pontas do termo; como os termos já
    vêm em minúsculas e o texto é normalizado (espaços colapsados) antes de
    chegar aqui, isso cobre tanto palavras isoladas quanto expressões de
    várias palavras (ex: "corrija o bug").
    """
    padrao = r"\b" + re.escape(termo) + r"\b"
    return re.search(padrao, texto) is not None

# Palavras/expressões que indicam uma tarefa de raciocínio complexo: refatoração,
# depuração, lógica em várias etapas, arquitetura, matemática não trivial.
PALAVRAS_CHAVE_ALTA_COMPLEXIDADE = [
    "refator", "refatore", "refactor",
    "depura", "debugar", "debug", "corrija o bug", "corrigir bug", "traceback",
    "arquitet", "arquitetura",
    "algoritmo", "otimiz", "performance", "complexidade de tempo", "big o",
    "prove que", "demonstre que", "por que isso falha", "análise passo a passo",
    "planeje", "planejamento", "estratégia",
    "escreva testes", "cobertura de teste", "casos de borda",
    "compare as abordagens", "trade-off", "vantagens e desvantagens",
    "múltiplas etapas", "várias etapas", "raciocínio",
]

# Palavras/expressões típicas de interações triviais (saudação, confirmação,
# perguntas factuais diretas) — não precisam de um modelo grande.
PALAVRAS_CHAVE_BAIXA_COMPLEXIDADE = [
    "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "e aí", "eae",
    "obrigado", "obrigada", "valeu", "tchau", "até mais",
    "que horas", "que dia", "qual a data", "quanto é", "quanto e",
    "sim", "não", "nao", "ok", "certo", "beleza",
]

# Limites de tamanho de prompt (em caracteres) usados como sinal auxiliar.
LIMITE_PROMPT_CURTO = 40
LIMITE_PROMPT_LONGO = 400


@dataclass
class ResultadoClassificacao:
    nivel: NivelCapacidade
    motivo: str


class TaskComplexityRouter:
    """Decide, a partir do texto do prompt, qual nível de modelo tentar primeiro."""

    @staticmethod
    def classificar(prompt: str) -> ResultadoClassificacao:
        texto = prompt.strip().lower()
        texto_normalizado = re.sub(r"\s+", " ", texto)

        if not texto_normalizado:
            return ResultadoClassificacao(NivelCapacidade.RAPIDO, "Prompt vazio.")

        # 1) Sinal mais forte: palavras-chave de alta complexidade.
        for termo in PALAVRAS_CHAVE_ALTA_COMPLEXIDADE:
            if _contem_termo(texto_normalizado, termo):
                return ResultadoClassificacao(
                    NivelCapacidade.RACIOCINIO,
                    f"Contém termo associado a raciocínio complexo: '{termo}'.",
                )

        # 2) Prompt muito longo tende a ser uma tarefa elaborada (ex: colar um
        #    trecho de código inteiro pedindo revisão).
        if len(texto_normalizado) > LIMITE_PROMPT_LONGO:
            return ResultadoClassificacao(
                NivelCapacidade.RACIOCINIO,
                f"Prompt longo ({len(texto_normalizado)} caracteres) sugere tarefa elaborada.",
            )

        # 3) Prompt curto e bate com saudação/trivialidade conhecida.
        if len(texto_normalizado) <= LIMITE_PROMPT_CURTO:
            for termo in PALAVRAS_CHAVE_BAIXA_COMPLEXIDADE:
                if _contem_termo(texto_normalizado, termo):
                    return ResultadoClassificacao(
                        NivelCapacidade.RAPIDO,
                        f"Prompt curto e trivial (contém '{termo}').",
                    )
            # Curto mas sem palavra-chave reconhecida: ainda assim tratamos
            # como rápido, já que é provável ser uma pergunta direta.
            return ResultadoClassificacao(
                NivelCapacidade.RAPIDO,
                "Prompt curto sem indícios de complexidade.",
            )

        # 4) Caso padrão: nem trivial nem claramente complexo -> equilibrado.
        return ResultadoClassificacao(
            NivelCapacidade.EQUILIBRADO,
            "Prompt de tamanho médio sem sinais fortes de alta ou baixa complexidade.",
        )