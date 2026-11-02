import os
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import store
from .agents import list_agents
from .orchestrator import submit_request
from .config import get_groq_api_key, get_groq_env_names

app = FastAPI(title="AUTOMA X API", description="Núcleo inicial do sistema multiagente AUTOMA X", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["X-API-Key", "Content-Type"])

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    expected = os.getenv("API_ACCESS_TOKEN", "")
    supplied = request.headers.get("X-API-Key", "")
    if not expected or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return JSONResponse(status_code=401, content={"detail": "API key ausente ou inválida"})
    return await call_next(request)

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=10000)

class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")

@app.on_event("startup")
def startup():
    if not os.getenv("API_ACCESS_TOKEN"):
        raise RuntimeError("API_ACCESS_TOKEN precisa estar configurado")
    store.init_db()

@app.get("/")
def root():
    return {"project": "AUTOMA X", "orchestrator": "AGENT_00", "status": "RUNNING", "groq_configured": bool(get_groq_api_key()), "groq_variable_names": get_groq_env_names(), "notice": "Diagnóstico seguro: informa apenas se a variável Groq existe; nunca revela seu valor."}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/agents")
def agents():
    return {"total": 31, "orchestrator": {"id": "AGENT_00", "name": "OPERACIONAL", "role": "Coordenador central"}, "specialists": list_agents()}

@app.post("/chat")
def chat(payload: ChatRequest):
    store.add_message("user", payload.message)
    task = submit_request(payload.message)
    response = {"task_id": task["id"], "status": task["status"], "operational_agent": "AGENT_00", "agents_selected": task["plan"]["selected_agents"], "plan": task["plan"], "result": task["result"]}
    store.add_message("assistant", f"Plano {task['id']} criado com status {task['status']}.")
    return response

@app.get("/tasks")
def tasks():
    return {"tasks": store.list_tasks()}

@app.get("/tasks/{task_id}")
def task_detail(task_id: str):
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task

@app.get("/approvals")
def approvals():
    return {"approvals": store.list_approvals()}

@app.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, payload: ApprovalRequest):
    status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    if not store.set_approval(approval_id, status):
        raise HTTPException(status_code=404, detail="Aprovação não encontrada")
    return {"approval_id": approval_id, "status": status, "note": "A decisão foi registrada. Nenhuma ação externa é executada por este protótipo."}

@app.get("/memory")
def memory():
    return {"recent_messages": store.get_messages()}

# Wrap the complete ASGI app so CORS handles browser preflight before API-key middleware.
app = CORSMiddleware(app, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
