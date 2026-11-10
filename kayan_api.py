import os
import json
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware

DB = os.environ["DATABASE_URL"]
KEY = os.environ["KAYAN_ACCESS_TOKEN"]
GROQ = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

app = FastAPI(title="KAYAN Independent API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

AGENTS = [
    {"id": "KAYAN_ORCHESTRATOR", "name": "KAYAN", "role": "Coordenação central, distribuição e síntese"},
    {"id": "AGENT_01", "name": "RESEARCH", "role": "Pesquisa de mercado, tendências, concorrentes e oportunidades"},
    {"id": "AGENT_02", "name": "STRATEGY", "role": "Estratégia, campanhas, vendas e crescimento"},
    {"id": "AGENT_03", "name": "CREATION", "role": "Textos, roteiros, conceitos visuais e materiais"},
    {"id": "AGENT_04", "name": "QUALITY", "role": "Revisão, checagem de consistência e identificação de lacunas"},
    {"id": "AGENT_05", "name": "OPERATIONS", "role": "Tarefas, arquivos, fluxos e infraestrutura"},
]
PANELS = ["refrigeracao", "modelo_ia", "produtos_marketing"]
AGENT_INSTRUCTIONS = {
    "AGENT_01": "Atue como especialista RESEARCH. Pesquise e estruture hipóteses, público, concorrência e oportunidades. Não invente dados, fontes ou tendências atuais. Separe fatos de hipóteses e diga quando uma pesquisa externa é necessária.",
    "AGENT_02": "Atue como especialista STRATEGY. Transforme o pedido em plano executável, objetivos, etapas, indicadores e riscos. Não prometa resultados comerciais.",
    "AGENT_03": "Atue como especialista CREATION. Produza textos, roteiros, legendas, prompts e materiais prontos para revisão. Não publique nada.",
    "AGENT_04": "Atue como especialista QUALITY. Revise a saída, procure erros, alegações sem suporte, inconsistências e passos ausentes. Devolva uma versão corrigida e liste limitações.",
    "AGENT_05": "Atue como especialista OPERATIONS. Organize tarefas, dependências, estados, checklists e execução técnica segura. Não afirme que executou ações externas sem confirmação real.",
}

def conn():
    return psycopg.connect(DB, row_factory=dict_row)

def auth(key: Optional[str]):
    if key != KEY:
        raise HTTPException(401, "Chave de acesso inválida")

def choose_agent(panel: Optional[str], prompt: str) -> str:
    p = (panel or "").lower()
    m = prompt.lower()
    if p == "refrigeracao" or any(w in m for w in ["roteiro", "legenda", "vídeo", "video", "anúncio", "anuncio", "criar", "imagem"]):
        return "AGENT_03"
    if p == "modelo_ia":
        return "AGENT_03"
    if p == "produtos_marketing" or any(w in m for w in ["venda", "campanha", "produto", "marketing", "estratégia", "estrategia"]):
        return "AGENT_02"
    if any(w in m for w in ["pesquisar", "pesquisa", "mercado", "concorrente", "tendência", "tendencia"]):
        return "AGENT_01"
    return "AGENT_05"

def groq_chat(messages, temperature=0.4):
    if not GROQ:
        raise RuntimeError("GROQ_API_KEY não configurada no Render. A execução foi registrada, mas o modelo de IA não pode ser chamado.")
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": "Bearer " + GROQ, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace")
        raise RuntimeError(f"Provedor Groq respondeu HTTP {exc.code}: {detail}") from exc

@app.on_event("startup")
def init():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS kayan_tasks(
            id TEXT PRIMARY KEY, panel TEXT, title TEXT, input TEXT,
            result TEXT DEFAULT '', status TEXT DEFAULT 'created',
            created_at TIMESTAMPTZ DEFAULT now())""")
        c.execute("""ALTER TABLE kayan_tasks ADD COLUMN IF NOT EXISTS assigned_agent TEXT""")
        c.execute("""ALTER TABLE kayan_tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ""")
        c.execute("""ALTER TABLE kayan_tasks ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ""")
        c.execute("""ALTER TABLE kayan_tasks ADD COLUMN IF NOT EXISTS error TEXT""")
        c.execute("""CREATE TABLE IF NOT EXISTS kayan_messages(
            id BIGSERIAL PRIMARY KEY, role TEXT, content TEXT, panel TEXT,
            created_at TIMESTAMPTZ DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS kayan_files(
            id TEXT PRIMARY KEY, name TEXT, mime_type TEXT, size_bytes BIGINT,
            data BYTEA, created_at TIMESTAMPTZ DEFAULT now())""")

@app.get("/", response_class=HTMLResponse)
def home():
    return open("kayan_index.html", encoding="utf-8").read()

@app.get("/health")
def health():
    database = False
    database_error = None
    try:
        with conn() as c:
            c.execute("SELECT 1")
        database = True
    except Exception as exc:
        database_error = type(exc).__name__
    return {
        "api": "online",
        "database_connected": database,
        "database_error": database_error,
        "ai_configured": bool(GROQ),
        "provider": "Groq" if GROQ else None,
        "model": GROQ_MODEL if GROQ else None,
        "version": "2.0",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/agents")
def agents(x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    return {
        "central": "KAYAN_ORCHESTRATOR",
        "agents": AGENTS,
        "execution_mode": "specialist_routing_with_quality_review",
        "llm_configured": bool(GROQ),
    }

def save_message(role, content, panel=None):
    with conn() as c:
        c.execute(
            "INSERT INTO kayan_messages(role,content,panel) VALUES(%s,%s,%s)",
            (role, content, panel),
        )

@app.post("/api/chat")
def chat(p: dict, x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    message = str(p.get("message", "")).strip()
    panel = p.get("panel")
    if len(message) < 2 or len(message) > 10000:
        raise HTTPException(422, "Mensagem inválida")
    if panel not in PANELS and panel is not None:
        raise HTTPException(422, "Painel inválido")
    agent_id = choose_agent(panel, message)
    agent = next(a for a in AGENTS if a["id"] == agent_id)
    with conn() as c:
        history = c.execute(
            "SELECT role,content FROM kayan_messages WHERE panel IS NOT DISTINCT FROM %s ORDER BY id DESC LIMIT 12",
            (panel,),
        ).fetchall()
    messages = [{
        "role": "system",
        "content": (
            "Você é KAYAN_ORCHESTRATOR, coordenador central do KAYAN. "
            "Responda sempre em português brasileiro. Encaminhe o trabalho ao especialista indicado e integre a resposta. "
            "Nunca invente dados, fontes, métricas, execução de tarefas ou integrações. "
            "Diferencie claramente fatos, hipóteses e ações que ainda dependem de credenciais ou aprovação. "
            f"Especialista responsável: {agent['name']}. {AGENT_INSTRUCTIONS.get(agent_id, '')}"
        ),
    }]
    for item in reversed(history):
        if item["role"] in ("user", "assistant"):
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})
    try:
        answer = groq_chat(messages)
    except Exception as exc:
        raise HTTPException(503, str(exc))
    save_message("user", message, panel)
    save_message("assistant", answer, panel)
    return {"agent": "KAYAN_ORCHESTRATOR", "specialist": agent, "answer": answer, "ai_live": True}

@app.get("/api/chat/history")
def history(x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    with conn() as c:
        rows = c.execute(
            "SELECT role,content,panel,created_at FROM kayan_messages ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"messages": list(reversed(rows))}

def execute_task(task_id: str):
    with conn() as c:
        task = c.execute("SELECT * FROM kayan_tasks WHERE id=%s", (task_id,)).fetchone()
        if not task or task["status"] not in ("created", "queued", "failed"):
            return
        c.execute(
            "UPDATE kayan_tasks SET status='running',started_at=now(),finished_at=NULL,error=NULL WHERE id=%s",
            (task_id,),
        )
    agent_id = choose_agent(task["panel"], task["input"] or task["title"])
    agent = next(a for a in AGENTS if a["id"] == agent_id)
    try:
        draft = groq_chat([
            {"role": "system", "content": "Você é o especialista KAYAN responsável por executar a tarefa. " + AGENT_INSTRUCTIONS[agent_id] + " Entregue resultado estruturado em português. Não declare publicação ou ação externa."},
            {"role": "user", "content": f"Painel: {task['panel']}\nTarefa: {task['title']}\nInstruções: {task['input']}"},
        ])
        reviewed = groq_chat([
            {"role": "system", "content": AGENT_INSTRUCTIONS["AGENT_04"] + " Revise o trabalho abaixo. Retorne o resultado final corrigido e uma seção curta 'Verificações e limitações'."},
            {"role": "user", "content": draft},
        ], temperature=0.2)
        with conn() as c:
            c.execute(
                "UPDATE kayan_tasks SET status='completed',assigned_agent=%s,result=%s,finished_at=now(),error=NULL WHERE id=%s",
                (agent_id, reviewed, task_id),
            )
        save_message("assistant", f"Tarefa concluída por {agent['name']} com revisão QUALITY.\n{reviewed}", task["panel"])
    except Exception as exc:
        with conn() as c:
            c.execute(
                "UPDATE kayan_tasks SET status='failed',assigned_agent=%s,error=%s,finished_at=now() WHERE id=%s",
                (agent_id, str(exc)[:2000], task_id),
            )

@app.post("/api/tasks")
def create_task(p: dict, background: BackgroundTasks, x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    panel = p.get("panel", "refrigeracao")
    if panel not in PANELS:
        raise HTTPException(422, "Painel inválido")
    title = str(p.get("title", "Nova operação")).strip()[:200]
    task_input = str(p.get("input", "")).strip()[:10000]
    if not title or not task_input:
        raise HTTPException(422, "Informe o título e as instruções da operação")
    task_id = str(uuid.uuid4())
    agent_id = choose_agent(panel, task_input)
    with conn() as c:
        c.execute(
            "INSERT INTO kayan_tasks(id,panel,title,input,status,assigned_agent) VALUES(%s,%s,%s,%s,'queued',%s)",
            (task_id, panel, title, task_input, agent_id),
        )
    background.add_task(execute_task, task_id)
    return {"id": task_id, "status": "queued", "assigned_agent": agent_id, "message": "Operação adicionada à fila de execução."}

@app.post("/api/tasks/{task_id}/run")
def run_task(task_id: str, background: BackgroundTasks, x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    with conn() as c:
        task = c.execute("SELECT id,status FROM kayan_tasks WHERE id=%s", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Operação não encontrada")
    if task["status"] == "running":
        return {"id": task_id, "status": "running"}
    with conn() as c:
        c.execute("UPDATE kayan_tasks SET status='queued' WHERE id=%s", (task_id,))
    background.add_task(execute_task, task_id)
    return {"id": task_id, "status": "queued"}

@app.get("/api/tasks")
def tasks(x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    with conn() as c:
        rows = c.execute(
            "SELECT id,panel,title,input,result,status,assigned_agent,error,created_at,started_at,finished_at FROM kayan_tasks ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {"tasks": rows}

@app.post("/api/files")
async def upload(file: UploadFile = File(...), x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Limite de 10 MB por arquivo")
    file_id = str(uuid.uuid4())
    with conn() as c:
        c.execute(
            "INSERT INTO kayan_files(id,name,mime_type,size_bytes,data) VALUES(%s,%s,%s,%s,%s)",
            (file_id, file.filename or "arquivo", file.content_type or "application/octet-stream", len(data), data),
        )
    return {"id": file_id, "name": file.filename or "arquivo", "size_bytes": len(data), "stored": "PostgreSQL"}

@app.get("/api/files")
def files(x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    with conn() as c:
        rows = c.execute(
            "SELECT id,name,mime_type,size_bytes,created_at FROM kayan_files ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {"files": rows}

@app.get("/api/files/{file_id}")
def get_file(file_id: str, x_api_key: Optional[str] = Header(default=None)):
    auth(x_api_key)
    with conn() as c:
        row = c.execute("SELECT name,mime_type,data FROM kayan_files WHERE id=%s", (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Arquivo não encontrado")
    return Response(
        bytes(row["data"]),
        media_type=row["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["name"]}"'},
    )
