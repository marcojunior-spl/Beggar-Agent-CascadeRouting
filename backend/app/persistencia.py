"""
Persistência simples de conversas via SQLite — sem dependência nova, usando a
biblioteca padrão do Python. Guarda mensagens por sessão (o id de sessão é
gerado pelo frontend e enviado junto de cada mensagem).

Para um dev júnior:
- Se um dia precisar trocar SQLite por Postgres, é aqui que se mexe — o resto
  do código (api.py) usa só estas funções, não SQL direto.
- O arquivo do banco fica em AGENTE_DB_PATH (padrão: ./conversas.db), que é
  ignorado pelo git (veja .gitignore).
- Schema novo? Adicione em SCHEMA (para DBs novos) E em _migrar_se_necessario()
  (para DBs já existentes, que não podem recriar a tabela).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("AGENTE_DB_PATH", "./conversas.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mensagens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id TEXT NOT NULL,
    remetente TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    modelo_utilizado TEXT,
    nivel_complexidade TEXT,
    motivo_complexidade TEXT,
    fallback_acionado INTEGER DEFAULT 0,
    duracao_segundos REAL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessao ON mensagens(sessao_id, id);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrar_se_necessario():
    """
    Aplica ALTER TABLE para DBs criados antes de uma coluna nova existir.
    SQLite não tem ADD COLUMN IF NOT EXISTS, então checamos via PRAGMA.
    """
    with _conn() as c:
        colunas = {row[1] for row in c.execute("PRAGMA table_info(mensagens)")}
        if "motivo_complexidade" not in colunas:
            c.execute("ALTER TABLE mensagens ADD COLUMN motivo_complexidade TEXT")


def inicializar():
    """Cria as tabelas se ainda não existirem, e migra colunas novas. Chamado no import de api.py."""
    with _conn() as c:
        c.executescript(SCHEMA)
    _migrar_se_necessario()


def salvar_mensagem(
    sessao_id: str,
    remetente: str,
    conteudo: str,
    modelo_utilizado: Optional[str] = None,
    nivel_complexidade: Optional[str] = None,
    motivo_complexidade: Optional[str] = None,
    fallback_acionado: bool = False,
    duracao_segundos: Optional[float] = None,
):
    with _conn() as c:
        c.execute(
            "INSERT INTO mensagens (sessao_id, remetente, conteudo, modelo_utilizado,"
            " nivel_complexidade, motivo_complexidade, fallback_acionado,"
            " duracao_segundos, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sessao_id,
                remetente,
                conteudo,
                modelo_utilizado,
                nivel_complexidade,
                motivo_complexidade,
                int(fallback_acionado),
                duracao_segundos,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def listar_mensagens(sessao_id: str, limite: int = 100) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM mensagens WHERE sessao_id = ? ORDER BY id DESC LIMIT ?",
            (sessao_id, limite),
        ).fetchall()
        # Ordena de volta para cronológico (mais antiga primeiro).
        return [dict(r) for r in reversed(rows)]


def limpar_sessao(sessao_id: str):
    with _conn() as c:
        c.execute("DELETE FROM mensagens WHERE sessao_id = ?", (sessao_id,))