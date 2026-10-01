# Beggar Agent CascadeRouting

Agente de desenvolvimento com **roteamento por complexidade** e **fallback em cascata** entre vários provedores de LLM gratuitos. A ideia é simples: quem não tem dinheiro para pagar uma API usa o que o tier gratuito de cada provedor oferece, e quando um deles estoura a cota (HTTP 429), o agente passa sozinho para o próximo.

## Como funciona

1. **Classificação do pedido.** O `TaskComplexityRouter` (`backend/app/providers/complexidade.py`) analisa o prompt com heurísticas determinísticas — palavras-chave e tamanho do texto, sem chamar nenhum LLM — e classifica em um nível:

   | Nível | Quando | Exemplos |
   |---|---|---|
   | `RAPIDO` | Prompt curto ou saudação/trivialidade | "oi", "que horas são?" |
   | `EQUILIBRADO` | Tamanho médio, sem sinais fortes | perguntas gerais |
   | `RACIOCINIO` | Termos como *refatore*, *debug*, *arquitetura*, *algoritmo*, ou prompt longo (> 400 caracteres) | revisão de código, planejamento |

2. **Montagem da cadeia.** O `FallbackChain` (`backend/app/providers/registry.py`) ordena os modelos configurados começando pelo nível ideal e subindo/descendo pelos demais. Modelos em cooldown são pulados. O **Ollama (modelo local) entra sempre por último**, como recurso extremo.

3. **Execução com resiliência.** Cada tentativa roda em thread separada com timeout. Erros transitórios (429, 503, timeout) têm retry com backoff exponencial; erros permanentes (401, 404) pulam direto para o próximo provedor.

4. **Controle de cota.** O `RastreadorCota` guarda o cooldown **por modelo** (não por provedor), então um 429 em um modelo da Groq não derruba os outros modelos da mesma Groq. Rate limit por minuto → 60 s de cooldown; cota diária esgotada → 1 h.

5. **Orçamentos de tempo.** Dois limites valem ao mesmo tempo: `TIMEOUT_POR_PROVEDOR_SEGUNDOS` (padrão 45 s) e `TEMPO_MAXIMO_TOTAL_SEGUNDOS` (padrão 90 s para a requisição inteira). Cada provedor recebe uma fatia do orçamento restante, para que um único provedor lento não impeça o cascade de tentar os seguintes.

## Provedores suportados

Você **não precisa** configurar todos: a aplicação descobre sozinha quais têm chave no `.env` e usa apenas esses. Quanto mais provedores, mais resiliente fica a cascata.

| Provedor | Variável de ambiente |
|---|---|
| Google AI Studio (Gemini) | `GEMINI_API_KEY` |
| Groq Cloud | `GROQ_API_KEY` |
| OpenRouter (modelos `:free`) | `OPENROUTER_API_KEY` |
| Cloudflare Workers AI | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` |
| Mistral AI | `MISTRAL_API_KEY` |
| Cohere | `COHERE_API_KEY` |
| GitHub Models | `GITHUB_API_KEY` |
| Cerebras Cloud | `CEREBRAS_API_KEY` |
| SambaNova Cloud | `SAMBANOVA_API_KEY` |
| Hugging Face | `HF_TOKEN` |
| Ollama (local) | `OLLAMA_ENABLED`, `OLLAMA_MODEL`, `OLLAMA_API_BASE` |

> **Atenção:** modelos gratuitos são descontinuados com frequência, e alguns provedores estão com modelos comentados no catálogo (GitHub Models, Cerebras, SambaNova e Hugging Face), por mudança de endpoint ou falta de acesso gratuito na conta usada nos testes. Consulte os comentários em `backend/app/providers/catalogo.py`.

## Estrutura do projeto

```
.
├── backend/              # API FastAPI + núcleo do agente
│   ├── app/
│   │   ├── agente.py         # Agente (smolagents), ferramentas e executar_com_fallback
│   │   ├── api.py            # Endpoints REST/SSE, rate limit e métricas
│   │   ├── cli.py            # Modo terminal
│   │   ├── persistencia.py   # Histórico de conversas em SQLite
│   │   └── providers/
│   │       ├── catalogo.py       # Provedores e modelos (apenas dados)
│   │       ├── complexidade.py   # Classificador de complexidade
│   │       ├── registry.py       # Descoberta, cooldown de cota e cadeia de fallback
│   │       └── implementacoes.py # Provedores LiteLLM e Ollama
│   ├── verificar_modelos.py  # Testa quais modelos do catálogo respondem agora
│   └── .env.example
├── frontend/             # Interface web (React 19 + Vite + Tailwind)
├── docs/systemd.md       # Rodar o backend como serviço systemd
└── start.sh              # Script de inicialização
```

## Requisitos

- Python 3.10+
- Node.js (para a interface web)
- Pelo menos **uma** chave de API gratuita **ou** o [Ollama](https://ollama.com) instalado localmente

## Instalação e uso

```bash
git clone https://github.com/marcojunior-spl/Beggar-Agent-CascadeRouting.git
cd Beggar-Agent-CascadeRouting
./start.sh --gui
```

Na primeira execução o script cria o ambiente virtual do backend, instala as dependências e copia `backend/.env.example` para `backend/.env`. **Edite o `.env` e preencha suas chaves** antes de usar.

| Comando | O que faz |
|---|---|
| `./start.sh --gui` | Backend (porta 8000) + frontend (porta 3000) |
| `./start.sh --cli` | Agente direto no terminal, sem interface gráfica |
| `./start.sh --backend` | Só a API, com `--reload` |

## Configuração

Todas as opções estão comentadas em `backend/.env.example`. As principais:

| Variável | Padrão | Função |
|---|---|---|
| `TIMEOUT_POR_PROVEDOR_SEGUNDOS` | `45` | Tempo máximo de uma chamada a um provedor |
| `TEMPO_MAXIMO_TOTAL_SEGUNDOS` | `90` | Tempo máximo de uma requisição inteira (todas as tentativas) |
| `OLLAMA_ENABLED` | `true` | Liga/desliga o fallback local |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Modelo local, como aparece em `ollama list` |
| `ALLOWED_ORIGINS` | `localhost:3000,5173` | Origens permitidas (CORS) |
| `RATE_MAX_MSGS_POR_MINUTO` | `10` | Limite de mensagens por IP |
| `AGENTE_DB_PATH` | `./conversas.db` | Banco SQLite do histórico |
| `AGENTE_CHROMA_PATH` | `./chroma_db` | Memória vetorial (ChromaDB) |
| `AGENTE_LOG_FILE` | `agente_falhas.log` | Log de falhas |

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Verificação de saúde |
| `GET` | `/api/provedores` | Status dos provedores configurados |
| `POST` | `/api/chat` | Envia uma mensagem e recebe a resposta completa |
| `POST` | `/api/chat/stream` | Mesma coisa, com eventos em tempo real (SSE) |
| `GET` / `DELETE` | `/api/historico/{sessao_id}` | Lê ou apaga o histórico de uma sessão |
| `GET` / `DELETE` | `/api/logs` | Lê ou limpa os logs de falhas |
| `GET` | `/api/metricas` | Métricas de uso |

A documentação interativa fica em `http://localhost:8000/docs`.

## Expondo para outras pessoas (Cloudflare Tunnel / ngrok)

Se for expor a aplicação por um túnel, preencha no `backend/.env` o `ALLOWED_ORIGINS` com a URL pública do **frontend**, e no `frontend/.env` as variáveis `VITE_API_BASE_URL` (URL pública do **backend**) e `VITE_ALLOWED_HOST` (domínio do frontend, sem `https://`). Reinicie o `./start.sh --gui` depois de alterar. Os detalhes estão em `frontend/.env.example`.

## Adicionando ou atualizando modelos

1. Confirme o formato do `model_id` na [documentação do LiteLLM](https://docs.litellm.ai/docs/providers).
2. Adicione um `ModeloCatalogado` em `backend/app/providers/catalogo.py` (e uma `DefinicaoProvedor`, se o provedor for novo).
3. Valide com o script de verificação:

```bash
cd backend
source venv/bin/activate
python verificar_modelos.py
```

Erros `404` ou `decommissioned` significam que o modelo foi descontinuado e o ID precisa ser atualizado.

## Rodando como serviço

Veja [`docs/systemd.md`](docs/systemd.md) para manter o backend rodando continuamente em um servidor Linux.
