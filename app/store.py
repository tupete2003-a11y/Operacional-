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
        "CREATE TABLE IF NOT EXISTS model_references (id TEXT PRIMARY KEY, mime_type TEXT NOT NULL, encrypted_data BYTEA, sha256 TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS model_generated_images (id TEXT PRIMARY KEY, reference_id TEXT NOT NULL, mime_type TEXT NOT NULL, encrypted_data BYTEA NOT NULL, quality_json TEXT NOT NULL, objective TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'PENDING', review_note TEXT)",
        "CREATE TABLE IF NOT EXISTS oauth_states (state_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS social_connections (platform TEXT PRIMARY KEY, access_token_encrypted TEXT NOT NULL, refresh_token_encrypted TEXT NOT NULL, open_id TEXT, scopes TEXT NOT NULL, expires_at TEXT, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, objective TEXT NOT NULL, composition TEXT NOT NULL, style TEXT NOT NULL, reference_id TEXT NOT NULL, status TEXT NOT NULL, current_step TEXT NOT NULL, result_json TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS agent_run_steps (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, bot_id TEXT NOT NULL, step_name TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, input_json TEXT NOT NULL, output_json TEXT, error TEXT, started_at TEXT, completed_at TEXT, UNIQUE(run_id, step_name))",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_status_created ON agent_runs(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run ON agent_run_steps(run_id)",
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


def save_model_reference(image_id, mime_type, encrypted_data, digest, width, height):
    with connect() as conn:
        _execute(conn, "UPDATE model_references SET active=0 WHERE active=1")
        _execute(conn, "INSERT INTO model_references(id, mime_type, encrypted_data, sha256, width, height, created_at, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (image_id, mime_type, encrypted_data, digest, width, height, now()))


def get_model_reference(reference_id=None):
    with connect() as conn:
        if reference_id:
            row = _execute(conn, "SELECT * FROM model_references WHERE id=? AND active=1", (reference_id,)).fetchone()
        else:
            row = _execute(conn, "SELECT * FROM model_references WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def save_model_generated_image(image_id, reference_id, mime_type, encrypted_data, quality_json, objective, model):
    with connect() as conn:
        _execute(conn, "INSERT INTO model_generated_images(id, reference_id, mime_type, encrypted_data, quality_json, objective, model, created_at, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')",
            (image_id, reference_id, mime_type, encrypted_data, quality_json, objective, model, now()))


def get_model_generated_image(image_id):
    with connect() as conn:
        row = _execute(conn, "SELECT * FROM model_generated_images WHERE id=?", (image_id,)).fetchone()
    return dict(row) if row else None


def review_model_generated_image(image_id, status, note=""):
    with connect() as conn:
        cur = _execute(conn, "UPDATE model_generated_images SET review_status=?, review_note=? WHERE id=?",
            (status, note[:1000], image_id))
        return cur.rowcount > 0


# Persistent BOT_05 execution queue and per-agent step history.
def save_agent_run(run):
    sql = """INSERT INTO agent_runs
             (id, objective, composition, style, reference_id, status, current_step,
              result_json, error, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET status=excluded.status,
             current_step=excluded.current_step, result_json=excluded.result_json,
             error=excluded.error, updated_at=excluded.updated_at"""
    with connect() as conn:
        _execute(conn, sql, (
            run["id"], run["objective"], run["composition"], run["style"], run["reference_id"],
            run["status"], run["current_step"],
            json.dumps(run.get("result") or {}, ensure_ascii=False),
            run.get("error"), run["created_at"], run["updated_at"],
        ))


def _decode_agent_run(row):
    if not row:
        return None
    item = dict(row)
    raw = item.pop("result_json", None)
    try:
        item["result"] = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        item["result"] = {}
    return item


def get_agent_run(run_id):
    with connect() as conn:
        row = _execute(conn, "SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    return _decode_agent_run(row)


def list_agent_runs(statuses=None, limit=20):
    sql = "SELECT * FROM agent_runs"
    params = []
    if statuses:
        placeholders = ",".join(["?"] * len(statuses))
        sql += " WHERE status IN (" + placeholders + ")"
        params.extend(statuses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with connect() as conn:
        rows = _execute(conn, sql, tuple(params)).fetchall()
    return [_decode_agent_run(row) for row in rows]


def claim_agent_run(run_id):
    with connect() as conn:
        cur = _execute(conn, "UPDATE agent_runs SET status='RUNNING', updated_at=? WHERE id=? AND status='QUEUED'",
                        (now(), run_id))
        return cur.rowcount == 1


def save_agent_run_step(step):
    sql = """INSERT INTO agent_run_steps
             (id, run_id, bot_id, step_name, status, attempt, input_json, output_json,
              error, started_at, completed_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(run_id, step_name) DO UPDATE SET status=excluded.status,
             attempt=excluded.attempt, output_json=excluded.output_json, error=excluded.error,
             started_at=excluded.started_at, completed_at=excluded.completed_at"""
    with connect() as conn:
        _execute(conn, sql, (
            step["id"], step["run_id"], step["bot_id"], step["step_name"], step["status"],
            int(step.get("attempt") or 0),
            json.dumps(step.get("input") or {}, ensure_ascii=False),
            json.dumps(step.get("output"), ensure_ascii=False) if step.get("output") is not None else None,
            step.get("error"), step.get("started_at"), step.get("completed_at"),
        ))


def _decode_agent_step(row):
    if not row:
        return None
    item = dict(row)
    for source, target in (("input_json", "input"), ("output_json", "output")):
        raw = item.pop(source, None)
        try:
            item[target] = json.loads(raw) if raw else ({} if target == "input" else None)
        except (TypeError, ValueError):
            item[target] = {} if target == "input" else None
    return item


def get_agent_run_step(run_id, step_name):
    with connect() as conn:
        row = _execute(conn, "SELECT * FROM agent_run_steps WHERE run_id=? AND step_name=?",
                        (run_id, step_name)).fetchone()
    return _decode_agent_step(row)


def get_agent_run_steps(run_id):
    sql = """SELECT * FROM agent_run_steps WHERE run_id=?
             ORDER BY CASE bot_id WHEN 'BOT_01' THEN 1 WHEN 'BOT_02' THEN 2
             WHEN 'BOT_03' THEN 3 WHEN 'BOT_04' THEN 4 ELSE 5 END"""
    with connect() as conn:
        rows = _execute(conn, sql, (run_id,)).fetchall()
    return [_decode_agent_step(row) for row in rows]
