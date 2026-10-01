#!/usr/bin/env bash
#
# Script de inicialização do Agente Resiliente LLM.
#
# Uso:
#   ./start.sh --gui     Sobe o backend (FastAPI) + frontend (Vite) e abre a interface web
#   ./start.sh --cli     Roda o agente direto no terminal, sem interface gráfica
#   ./start.sh --backend Sobe só o backend (útil se você já tem o frontend rodando à parte)
#   ./start.sh --help    Mostra esta ajuda
#
# Para um dev júnior:
# Este script só orquestra os comandos — ele não contém lógica do agente.
# Se algo der errado, rode os comandos manualmente (veja README.md) para
# ver a mensagem de erro completa.

set -e

DIR_RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR_BACKEND="$DIR_RAIZ/backend"
DIR_FRONTEND="$DIR_RAIZ/frontend"
VENV_DIR="$DIR_BACKEND/venv"

modo="${1:---help}"

verificar_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "🔧 Ambiente virtual Python não encontrado. Criando em $VENV_DIR ..."
        python3 -m venv "$VENV_DIR"
        echo " Instalando dependências do backend..."
        "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
        "$VENV_DIR/bin/pip" install -r "$DIR_BACKEND/requirements.txt"
    fi
}

verificar_env_backend() {
    if [ ! -f "$DIR_BACKEND/.env" ]; then
        echo "  Arquivo backend/.env não encontrado."
        echo "   Copiando backend/.env.example -> backend/.env (edite e preencha suas chaves de API)."
        cp "$DIR_BACKEND/.env.example" "$DIR_BACKEND/.env"
    fi
}

verificar_node_modules() {
    if [ ! -d "$DIR_FRONTEND/node_modules" ]; then
        echo " Instalando dependências do frontend (npm install)..."
        (cd "$DIR_FRONTEND" && npm install)
    fi
}

iniciar_backend() {
    verificar_venv
    verificar_env_backend
    echo " Iniciando backend em http://localhost:8000 ..."
    (cd "$DIR_BACKEND" && "$VENV_DIR/bin/uvicorn" app.api:app --host 0.0.0.0 --port 8000 --reload)
}

iniciar_gui() {
    verificar_venv
    verificar_env_backend
    verificar_node_modules

    echo " Iniciando backend (porta 8000) em segundo plano..."
    (cd "$DIR_BACKEND" && "$VENV_DIR/bin/uvicorn" app.api:app --host 0.0.0.0 --port 8000) &
    PID_BACKEND=$!

    trap 'echo ""; echo " Encerrando backend..."; kill $PID_BACKEND 2>/dev/null' EXIT

    echo " Iniciando frontend (porta 3000)..."
    (cd "$DIR_FRONTEND" && npm run dev)
}

iniciar_cli() {
    verificar_venv
    verificar_env_backend
    echo " Iniciando modo terminal (sem interface gráfica)..."
    (cd "$DIR_BACKEND" && "$VENV_DIR/bin/python" -m app.cli)
}

case "$modo" in
    --gui)
        iniciar_gui
        ;;
    --cli)
        iniciar_cli
        ;;
    --backend)
        iniciar_backend
        ;;
    --help|*)
        echo "Uso: ./start.sh [--gui | --cli | --backend]"
        echo ""
        echo "  --gui       Sobe backend + frontend web (interface gráfica no navegador)"
        echo "  --cli       Roda o agente direto no terminal, sem interface gráfica"
        echo "  --backend   Sobe só o backend (API), sem o frontend"
        ;;
esac