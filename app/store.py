import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "data/automa_x.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def backend():
    return "postgresql" if os.getenv("DATABASE_URL", "").strip() else "sqlite"


def connect():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL está configurada, mas psycopg não está instalado.") from exc
        return psycopg.connect(database_url, row_factory=dict_row)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _execute(conn, sql, params=()):
    if backend() == "postgresql":
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def init_db():
    if backend() == "postgresql":
        statements = [
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, plan_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, scheduled_at TEXT NOT NULL, platform TEXT NOT NULL, format TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS messages (id BIGSERIAL PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)",
        ]
    else:
        statements = [
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, plan_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, scheduled_at TEXT NOT NULL, platform TEXT NOT NULL, format TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)",
        ]
    statements.extend([
        "CREATE TABLE IF NOT EXISTS oauth_states (state_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS social_connections (platform TEXT PRIMARY KEY, access_token_encrypted TEXT NOT NULL, refresh_token_encrypted TEXT NOT NULL, open_id TEXT, scopes TEXT NOT NULL, expires_at TEXT, updated_at TEXT NOT NULL)",
    ])
    with connect() as conn:
        for statement in statements:
            conn.execute(statement)


def now():
    return datetime.now(timezone.utc).isoformat()


def save_task(task):
    sql = """INSERT INTO tasks (id, request, status, plan_json, result_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET request=excluded.request, status=excluded.status,
             plan_json=excluded.plan_json, result_json=excluded.result_json, updated_at=excluded.updated_at"""
    with connect() as conn:
        _execute(conn, sql, (task["id"], task["request"], task["status"],
            json.dumps(task["plan"], ensure_ascii=False),
            json.dumps(task.get("result"), ensure_ascii=False),
            task["created_at"], now()))


def get_task(task_id):
    with connect() as conn:
        row = _execute(conn, "SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["plan"] = json.loads(data.pop("plan_json"))
    raw = data.pop("result_json")
    data["result"] = json.loads(raw) if raw else None
    return data


def list_tasks():
    with connect() as conn:
        rows = _execute(conn, "SELECT id, request, status, created_at, updated_at FROM tasks ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def add_message(role, content):
    with connect() as conn:
        _execute(conn, "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)", (role, content, now()))


def get_messages(limit=30):
    with connect() as conn:
        rows = _execute(conn, "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in reversed(rows)]


def create_approval(approval_id, task_id, action):
    with connect() as conn:
        _execute(conn, "INSERT INTO approvals(id, task_id, action, status, created_at) VALUES (?, ?, ?, 'PENDING', ?)",
            (approval_id, task_id, action, now()))


def set_approval(approval_id, status):
    with connect() as conn:
        cur = _execute(conn, "UPDATE approvals SET status=? WHERE id=?", (status, approval_id))
        return cur.rowcount > 0


def list_approvals():
    with connect() as conn:
        rows = _execute(conn, "SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def create_schedule(schedule_id, scheduled_at, platform, content_format, content, status="PLANNED"):
    with connect() as conn:
        _execute(conn, "INSERT INTO schedules(id, scheduled_at, platform, format, content, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (schedule_id, scheduled_at, platform, content_format, content, status, now()))


def list_schedules():
    with connect() as conn:
        rows = _execute(conn, "SELECT * FROM schedules ORDER BY scheduled_at ASC").fetchall()
    return [dict(row) for row in rows]


def delete_schedule(schedule_id):
    with connect() as conn:
        cur = _execute(conn, "DELETE FROM schedules WHERE id=?", (schedule_id,))
        return cur.rowcount > 0

def check_connection():
    """Verifica conectividade real do banco sem alterar dados."""
    with connect() as conn:
        row = conn.execute("SELECT 1").fetchone()
    return bool(row)


def list_agent_execution_history(limit=100):
    """Retorna histórico recente de etapas de agentes para status baseado em execução real."""
    with connect() as conn:
        rows = _execute(conn, "SELECT id, status, created_at, result_json FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        raw = item.pop("result_json", None)
        try:
            item["result"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            item["result"] = {}
        items.append(item)
    return items


def save_oauth_state(state_hash, expires_at):
    with connect() as conn:
        _execute(conn, "DELETE FROM oauth_states WHERE expires_at < ?", (now(),))
        _execute(conn, "INSERT INTO oauth_states(state_hash, expires_at) VALUES (?, ?)", (state_hash, expires_at))


def consume_oauth_state(state_hash):
    with connect() as conn:
        row = _execute(conn, "SELECT expires_at FROM oauth_states WHERE state_hash=?", (state_hash,)).fetchone()
        if not row:
            return False
        _execute(conn, "DELETE FROM oauth_states WHERE state_hash=?", (state_hash,))
        return str(row["expires_at"]) >= now()


def save_social_connection(platform, access_token_encrypted, refresh_token_encrypted, open_id, scopes, expires_at):
    sql = """INSERT INTO social_connections(platform, access_token_encrypted, refresh_token_encrypted, open_id, scopes, expires_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(platform) DO UPDATE SET access_token_encrypted=excluded.access_token_encrypted,
             refresh_token_encrypted=excluded.refresh_token_encrypted, open_id=excluded.open_id,
             scopes=excluded.scopes, expires_at=excluded.expires_at, updated_at=excluded.updated_at"""
    with connect() as conn:
        _execute(conn, sql, (platform, access_token_encrypted, refresh_token_encrypted, open_id, scopes, expires_at, now()))


def get_social_connection(platform):
    with connect() as conn:
        row = _execute(conn, "SELECT * FROM social_connections WHERE platform=?", (platform,)).fetchone()
    return dict(row) if row else None


def get_social_connection_status(platform):
    with connect() as conn:
        row = _execute(conn, "SELECT open_id, scopes, expires_at, updated_at FROM social_connections WHERE platform=?", (platform,)).fetchone()
    return dict(row) if row else None
