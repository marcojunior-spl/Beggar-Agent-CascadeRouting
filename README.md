# Agente Resiliente LLM

App Linux (backend Python + frontend web) para um agente de IA com fallback
automático entre múltiplos modelos de linguagem (Google Gemini + Groq),
diagnóstico detalhado de erros HTTP (404, 429, 401, 5xx, timeout) e memória
vetorial persistente (ChromaDB).

Este projeto nasceu de um protótipo visual feito no Google AI Studio e foi
reestruturado para ter um **backend Python real** por trás da interface —
antes, a interface apenas simulava as respostas do agente.

## Estrutura do projeto

```
.
├── backend/            # Servidor Python (FastAPI) com a lógica real do agente
│   ├── app/
│   │   ├── agente.py   # Núcleo do agente: ferramentas, fallback, diagnóstico de erros
│   │   ├── api.py      # Endpoints HTTP (REST) que expõem o agente ao frontend
│   │   └── cli.py       # Modo terminal (sem interface gráfica)
│   ├── requirements.txt
│   └── .env.example    # Modelo de variáveis de ambiente (SEM chaves reais)
├── frontend/           # Interface web (React + Vite + Tailwind)
│   └── src/
│       ├── api/client.ts        # Cliente HTTP que fala com o backend
│       ├── components/          # Componentes de UI (chat, logs, esteira de provedores)
│       └── App.tsx              # Componente raiz
├── start.sh            # Script único para subir o app (GUI ou CLI)
└── docs/               # Notas adicionais para desenvolvimento
```

## ⚠️ Segurança: chaves de API

O protótipo original tinha chaves de API **reais, hardcoded** no código-fonte
como valor padrão. Isso foi removido nesta versão. Se você usou o arquivo
`agente_01.py` original, **revogue essas chaves antes de continuar**:
- Google AI Studio: https://aistudio.google.com/apikey
- Groq Console: https://console.groq.com/keys

Neste projeto, as chaves ficam **somente** no arquivo `backend/.env` (que não
deve nunca ser commitado — já está no `.gitignore`).

## Pré-requisitos

- Linux (testado em Ubuntu/Debian; deve funcionar em qualquer distro moderna)
- Python 3.10+
- Node.js 18+ e npm
- Ao menos uma chave de API de algum provedor gratuito (veja a tabela abaixo)
  e/ou [Ollama](https://ollama.com) instalado para usar um modelo local

## Arquitetura de provedores (multi-LLM com fallback em cascata)

A partir desta versão, o backend não depende mais só de Gemini/Groq — ele
suporta **10 provedores diferentes com tier gratuito**, além de um modelo
local via Ollama como último recurso. Você não precisa configurar todos:
a aplicação descobre sozinha quais provedores têm chave configurada no `.env`
e monta a esteira de fallback só com esses.

| Provedor | Função preferencial | Variável de ambiente |
|---|---|---|
| Google AI Studio | Geral / alta contextualização | `GEMINI_API_KEY` |
| Groq Cloud | Respostas de extrema velocidade | `GROQ_API_KEY` |
| OpenRouter | Agregador / backup versátil | `OPENROUTER_API_KEY` |
| GitHub Models | Tarefas de complexidade média/alta | `GITHUB_API_KEY` |
| Cloudflare Workers AI | Módulos leves / tarefas rápidas | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` |
| Mistral AI | Geração e análise de código | `MISTRAL_API_KEY` |
| Cerebras Cloud | Inferência ultrarrápida | `CEREBRAS_API_KEY` |
| Cohere | RAG, busca e ordenação | `COHERE_API_KEY` |
| SambaNova Cloud | Tarefas de alta complexidade (70B/405B) | `SAMBANOVA_API_KEY` |
| Hugging Face | Modelos especializados de nicho | `HF_TOKEN` |
| **Modelo local (Ollama)** | **Último fallback**, apenas após exaustão das APIs | `OLLAMA_ENABLED` |

### Como a aplicação decide qual modelo usar

1. **Classificação de complexidade** (`backend/app/providers/complexidade.py`):
   toda mensagem passa por um classificador determinístico (sem custo, sem
   chamar nenhum LLM) que a categoriza em `RAPIDO`, `EQUILIBRADO` ou
   `RACIOCINIO`, com base em palavras-chave e tamanho do texto. Uma saudação
   cai em `RAPIDO`; um pedido de refatoração ou depuração cai em `RACIOCINIO`.
2. **Montagem da cadeia de fallback** (`backend/app/providers/registry.py`):
   a partir da classificação, a aplicação ordena os provedores CONFIGURADOS
   priorizando o nível pedido, e coloca o modelo local (Ollama) sempre por
   último — ele só é chamado se **todos** os provedores em nuvem
   configurados falharem ou estiverem com cota esgotada.
3. **Execução com retry e gestão de cota**: se um provedor responder com
   HTTP 429 (limite de requisições) ou 503 (instabilidade temporária), a
   aplicação tenta de novo automaticamente (com espera crescente) antes de
   desistir dele; se o erro for permanente (404 modelo inexistente, 401
   chave inválida), ela pula direto para o próximo provedor. Um provedor que
   levou um 429 recentemente fica em "cooldown" por 60 segundos e é evitado
   nas próximas tentativas até lá.
4. **Modelo local isolado**: a chamada ao Ollama roda em uma thread separada
   com timeout configurável (`OLLAMA_TIMEOUT_SEGUNDOS`, padrão 45s) — se o
   modelo local travar ou demorar demais, a aplicação principal não trava
   junto com ele.

### Corrigindo problemas de conexão com um provedor específico

Se um provedor específico começar a falhar (por exemplo, o Google
descontinuar um modelo, como já aconteceu antes neste projeto), normalmente
não é um bug no código — é um `model_id` desatualizado. Veja a seção
"Modelos de IA mudam com frequência" mais abaixo.

## Usando um modelo local com Ollama (opcional)

O modelo local via Ollama funciona como **fallback extremo**: só é chamado
depois que todos os provedores em nuvem configurados no `.env` falharem ou
estiverem com cota esgotada (rate-limit). Ele roda de graça na sua máquina,
sem depender de internet, mas modelos locais leves têm capacidade de
raciocínio bem menor que os modelos em nuvem — por isso ficam por último,
como uma rede de segurança em vez de primeira escolha.

1. Instale o Ollama: https://ollama.com/download
2. Baixe um modelo, por exemplo:
   ```bash
   ollama pull deepseek-r1:1.7b
   ```
3. Configure `backend/.env` com o nome exato do modelo (veja `ollama list`):
   ```
   OLLAMA_ENABLED=true
   OLLAMA_MODEL=deepseek-r1:1.7b
   OLLAMA_API_BASE=http://localhost:11434
   OLLAMA_TIMEOUT_SEGUNDOS=45
   ```

Para desativar e usar só provedores em nuvem, defina `OLLAMA_ENABLED=false`
no `.env`.

**Por que o modelo local roda em uma thread separada com timeout:** modelos
locais pequenos, especialmente com o prompt extenso que o `CodeAgent` usa
internamente (ele sempre tenta resolver a tarefa escrevendo e executando
código Python, mesmo para uma simples saudação), podem demorar muito mais do
que o mesmo modelo rodaria "puro" no terminal do Ollama. Para que isso nunca
trave a aplicação inteira, a chamada ao Ollama roda isolada com um limite de
tempo (`OLLAMA_TIMEOUT_SEGUNDOS`) — se estourar, a aplicação desiste
rapidamente em vez de ficar pendurada esperando.

## Instalação e uso rápido

O jeito mais simples de rodar é usando o script `start.sh`, que cuida de criar
o ambiente virtual Python, instalar dependências e configurar o `.env` na
primeira execução.

### 1. Configure suas chaves de API

```bash
cp backend/.env.example backend/.env
# Edite backend/.env e preencha GEMINI_API_KEY e/ou GROQ_API_KEY
```

(Se você pular este passo, o `start.sh` cria o arquivo automaticamente na
primeira execução, mas você ainda precisa editá-lo com suas chaves.)

### 2. Escolha como rodar

**Modo com interface gráfica (navegador):**
```bash
./start.sh --gui
```
Isso sobe o backend em `http://localhost:8000` e o frontend em
`http://localhost:3000`. Abra essa URL no navegador.

**Modo terminal (sem interface gráfica):**
```bash
./start.sh --cli
```
Conversa direto com o agente no terminal — útil para debug ou uso em
servidores sem ambiente gráfico.

**Somente o backend (API), se você for rodar o frontend separadamente:**
```bash
./start.sh --backend
```

Pare qualquer um dos modos com `Ctrl+C`.

## Rodando manualmente (sem o script)

Caso prefira rodar cada parte manualmente (ou o `start.sh` não funcione no seu
ambiente):

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # depois edite com suas chaves
uvicorn app.api:app --reload --port 8000

# Em outro terminal: Frontend
cd frontend
npm install
npm run dev
```

Para rodar só no terminal, sem frontend:
```bash
cd backend
source venv/bin/activate
python -m app.cli
```

## Build de produção do frontend

```bash
cd frontend
npm run build
```
Isso gera a pasta `frontend/dist`, que pode ser servida por qualquer servidor
estático (nginx, Caddy, `npm run preview`, etc). Lembre-se de configurar esse
servidor para fazer proxy de `/api` até o backend, ou definir
`VITE_API_BASE_URL` no `.env` do frontend apontando para a URL pública do backend.

## Deixando alguém de fora testar (túnel temporário)

Para que uma pessoa em outra rede acesse o app sem precisar mexer no
roteador, use um túnel público temporário como o [Cloudflare
Tunnel](https://github.com/cloudflare/cloudflared) (gratuito, sem conta
necessária). Existem duas formas de fazer isso — a primeira é bem mais
simples e é a recomendada para um teste rápido.

### Opção recomendada: um único túnel

O servidor de desenvolvimento do Vite já tem um proxy embutido que
redireciona qualquer chamada `/api/*` para o backend local (veja
`server.proxy` em `vite.config.ts`). Isso significa que **um único túnel,
apontando só para o frontend, já é suficiente** — o roteamento para o
backend acontece na sua máquina, de forma transparente para quem está
acessando de fora. Não precisa mexer em `ALLOWED_ORIGINS`, `VITE_API_BASE_URL`
nem CORS.

```bash
# Terminal 1: sobe a aplicação normalmente
./start.sh --gui

# Terminal 2: um único túnel, para o frontend
cloudflared tunnel --url http://localhost:3000
```

O `cloudflared` imprime uma URL pública (`https://algo.trycloudflare.com`).
Antes de repassar essa URL, defina no `frontend/.env` a variável
`VITE_ALLOWED_HOST` com esse domínio (sem `https://`), pois o Vite bloqueia
por padrão requisições vindas de hosts desconhecidos:

```
VITE_ALLOWED_HOST=algo.trycloudflare.com
```

Reinicie `./start.sh --gui` para essa variável ser lida, e mande a URL do
túnel para a pessoa testar. Pronto — só isso.

### Opção avançada: dois túneis separados

Só é necessária se você quiser expor o backend também como uma API pública
independente (ex: para outro cliente que não seja este frontend). Nesse
caso, cada serviço tem seu próprio túnel e sua própria URL, e é preciso
configurar CORS manualmente:

```bash
# Terminal 1: sobe a aplicação normalmente
./start.sh --gui

# Terminal 2: túnel do backend
cloudflared tunnel --url http://localhost:8000

# Terminal 3: túnel do frontend
cloudflared tunnel --url http://localhost:3000
```

Configure três variáveis e reinicie `./start.sh --gui` para elas serem lidas:

**`backend/.env`** — adicione a URL do túnel do **frontend** à lista de
origens permitidas (proteção CORS):
```
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,https://url-do-tunel-do-frontend.trycloudflare.com
```

**`frontend/.env`** — aponte para a URL do túnel do **backend**, e libere o
host do túnel do frontend:
```
VITE_API_BASE_URL=https://url-do-tunel-do-backend.trycloudflare.com
VITE_ALLOWED_HOST=url-do-tunel-do-frontend.trycloudflare.com
```

### Atenção (vale para as duas opções)

Túneis "quick" do Cloudflare são temporários — toda vez que você reinicia o
comando `cloudflared`, a URL muda, e as variáveis acima precisam ser
atualizadas de novo. Para um teste pontual isso é tranquilo; para algo mais
permanente, existe a opção de túnel nomeado (fixo) com uma conta gratuita do
Cloudflare.

## Para o desenvolvedor júnior que for dar manutenção

- **Adicionar uma nova ferramenta ao agente** (ex: buscar na web, rodar um
  comando): edite `backend/app/agente.py`, seção "FERRAMENTAS DO AGENTE".
  Siga o padrão de uma função decorada com `@tool`, com docstring explicando
  os parâmetros — o agente usa essa docstring para saber quando/como usar a
  ferramenta.
- **Adicionar ou trocar um provedor/modelo**: edite
  `backend/app/providers/catalogo.py` — não é preciso mexer em mais nada.
  Adicione uma linha em `MODELOS_CATALOGADOS` com o `model_id` correto (veja
  o formato exigido pelo LiteLLM em https://docs.litellm.ai/docs/providers)
  e o `NivelCapacidade` adequado (`RAPIDO`, `EQUILIBRADO` ou `RACIOCINIO`).
  Se for um provedor totalmente novo (nenhum modelo dele ainda catalogado),
  adicione também uma `DefinicaoProvedor` na lista `CATALOGO_PROVEDORES` no
  mesmo arquivo, com o nome da variável de ambiente da chave de API.
- **Ajustar como a complexidade é classificada**: edite
  `backend/app/providers/complexidade.py`. As listas
  `PALAVRAS_CHAVE_ALTA_COMPLEXIDADE` e `PALAVRAS_CHAVE_BAIXA_COMPLEXIDADE`
  são o primeiro lugar a mexer se perceber que tarefas estão sendo roteadas
  para o nível de modelo errado.
- **Ajustar a lógica de fallback/cota/cooldown**: veja
  `backend/app/providers/registry.py` (`ProviderRegistry` descobre provedores
  configurados; `FallbackChain` monta a ordem de tentativa e gerencia o
  cooldown após 429) e a lógica de retry com backoff em
  `_tentar_provedor_com_retry` dentro de `backend/app/agente.py`.
- **Modelos de IA mudam com frequência**: provedores como Google e Groq
  descontinuam modelos regularmente (geralmente com meses de aviso prévio).
  Se você começar a ver erros HTTP 404 "model not found" na esteira de
  fallback, isso normalmente significa que um `model_id` foi descontinuado —
  não é um bug do código. Consulte a lista atual de modelos do provedor
  correspondente e atualize a entrada em
  `backend/app/providers/catalogo.py`.
- **Adicionar um novo endpoint HTTP**: edite `backend/app/api.py`, seguindo o
  padrão dos endpoints existentes (modelo Pydantic de entrada/saída + chamada
  ao `assistente`).
- **Mudar a interface visual**: os componentes React estão em
  `frontend/src/components/`. `ChatConsole.tsx` cuida do chat,
  `DiagnosticLogs.tsx` da aba de logs, e `ProviderChain.tsx` mostra a esteira
  de provedores.
- **Entender o formato de dados trocado entre front e back**: veja
  `frontend/src/api/client.ts` (tipos `*Api`) e `backend/app/api.py` (modelos
  Pydantic). Se mudar um formato de um lado, replique no outro.
- Os logs de falha ficam em `backend/agente_falhas.log` (formato JSON Lines,
  uma falha por linha) e a memória vetorial do agente fica em
  `backend/chroma_db/` — ambos ignorados pelo Git.

## Rodando como serviço em background (systemd)

Se no futuro você quiser que o backend rode continuamente em um servidor
(sem precisar deixar um terminal aberto), veja `docs/systemd.md` para um
exemplo de unit file.