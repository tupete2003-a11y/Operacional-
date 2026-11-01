import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("data/automa_x.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, plan_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")

def now():
    return datetime.now(timezone.utc).isoformat()

def save_task(task):
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO tasks (id, request, status, plan_json, result_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task["id"], task["request"], task["status"], json.dumps(task["plan"], ensure_ascii=False), json.dumps(task.get("result"), ensure_ascii=False), task["created_at"], now()))

def get_task(task_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row: return None
    data = dict(row)
    data["plan"] = json.loads(data.pop("plan_json"))
    raw = data.pop("result_json")
    data["result"] = json.loads(raw) if raw else None
    return data

def list_tasks():
    with connect() as conn:
        rows = conn.execute("SELECT id, request, status, created_at, updated_at FROM tasks ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def add_message(role, content):
    with connect() as conn:
        conn.execute("INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)", (role, content, now()))

def get_messages(limit=30):
    with connect() as conn:
        rows = conn.execute("SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]

def create_approval(approval_id, task_id, action):
    with connect() as conn:
        conn.execute("INSERT INTO approvals(id, task_id, action, status, created_at) VALUES (?, ?, ?, 'PENDING', ?)", (approval_id, task_id, action, now()))

def set_approval(approval_id, status):
    with connect() as conn:
        cur = conn.execute("UPDATE approvals SET status=? WHERE id=?", (status, approval_id))
        return cur.rowcount > 0

def list_approvals():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
