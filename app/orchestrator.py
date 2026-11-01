import uuid
from datetime import datetime, timezone
from .agents import list_agents
from . import store
from .llm import ask_agent

AGENT_MAP = {a["id"]: a for a in list_agents()}
ROUTES = {
    "financeiro": ["AGENT_06", "AGENT_23"], "custo": ["AGENT_06", "AGENT_23"],
    "marketing": ["AGENT_07", "AGENT_09", "AGENT_20", "AGENT_19"],
    "venda": ["AGENT_08", "AGENT_09", "AGENT_07"],
    "site": ["AGENT_12", "AGENT_13", "AGENT_17", "AGENT_22"],
    "sistema": ["AGENT_12", "AGENT_13", "AGENT_14", "AGENT_11"],
    "automação": ["AGENT_11", "AGENT_12", "AGENT_13"],
    "pesquisa": ["AGENT_02", "AGENT_03", "AGENT_21"],
    "empresa": ["AGENT_01", "AGENT_03", "AGENT_04", "AGENT_06", "AGENT_05"],
    "conteúdo": ["AGENT_18", "AGENT_09", "AGENT_19", "AGENT_20"],
}
SENSITIVE_TERMS = ["pagar", "transferir", "comprar", "contratar", "enviar email", "enviar mensagem", "publicar", "excluir", "apagar", "cancelar", "alterar produção", "deploy"]

def choose_agents(request):
    text = request.lower(); chosen = []
    for keyword, ids in ROUTES.items():
        if keyword in text: chosen.extend(ids)
    if not chosen: chosen = ["AGENT_01", "AGENT_03", "AGENT_04"]
    chosen.extend(["AGENT_22", "AGENT_30"])
    return list(dict.fromkeys(chosen))[:10]

def requires_approval(request):
    text = request.lower()
    return any(term in text for term in SENSITIVE_TERMS)

def create_plan(request):
    selected = choose_agents(request); tasks = []
    for agent_id in selected:
        agent = AGENT_MAP[agent_id]
        tasks.append({"task_id": f"SUB-{uuid.uuid4().hex[:8].upper()}", "assigned_agent": agent_id, "agent_name": agent["name"], "objective": f"Contribuir para: {request}", "instructions": agent["function"], "priority": "HIGH" if agent_id in ("AGENT_01", "AGENT_03") else "MEDIUM", "status": "PENDING", "expected_output": "Análise, recomendações, limitações e próximos passos."})
    return {"commander": "AGENT_00", "operating_mode": "HYBRID", "request": request, "selected_agents": selected, "subtasks": tasks, "approval_required": requires_approval(request), "note": "Roteamento inicial baseado em regras; ainda não executa agentes LLM independentes."}

def submit_request(request):
    task_id = f"AX-{uuid.uuid4().hex[:10].upper()}"; plan = create_plan(request)
    task = {"id": task_id, "request": request, "status": "AWAITING_APPROVAL" if plan["approval_required"] else "PLANNED", "plan": plan, "result": {"message": "Plano criado. Configure GROQ_API_KEY no Render para habilitar a execução dos especialistas por IA.", "agent_reports": []}, "created_at": datetime.now(timezone.utc).isoformat()}
    store.save_task(task)
    if plan["approval_required"]:
        approval_id = f"APR-{uuid.uuid4().hex[:8].upper()}"
        store.create_approval(approval_id, task_id, "Autorizar ação sensível relacionada à solicitação")
        task["result"]["approval_id"] = approval_id
        store.save_task(task)
        return task

    import os
    if os.getenv("GROQ_API_KEY", "").strip():
        reports = []
        for agent_id in plan["selected_agents"]:
            agent = AGENT_MAP[agent_id]
            try:
                report = ask_agent(agent, request)
                reports.append({"agent_id": agent_id, "agent_name": agent["name"], "status": "COMPLETED", "report": report})
            except Exception as exc:
                reports.append({"agent_id": agent_id, "agent_name": agent["name"], "status": "FAILED", "error": str(exc)})
        completed = sum(1 for item in reports if item["status"] == "COMPLETED")
        task["result"] = {
            "message": f"Execução por IA concluída parcialmente ou totalmente: {completed}/{len(reports)} especialistas responderam.",
            "agent_reports": reports
        }
        task["status"] = "COMPLETED" if completed == len(reports) else ("PARTIAL" if completed else "FAILED")
        store.save_task(task)
    return task
