import os

from .config import get_groq_api_key
from . import store

PLATFORMS = ["Instagram", "TikTok", "Facebook", "YouTube", "Kwai"]

BOTS = [
    {"id":"BOT_01","name":"Scheduler AI","role":"Agenda e horários","icon":"calendar","color":"blue","description":"Organiza o calendário editorial e recomenda horários de publicação.","responsibilities":["Calendário diário e semanal","Distribuição de conteúdo por plataforma","Lembretes e prevenção de conflitos"],"status":"CONFIGURED_NOT_VALIDATED"},
    {"id":"BOT_02","name":"Trend Writer AI","role":"Pesquisa e redação","icon":"trending","color":"purple","description":"Pesquisa tendências, formatos, temas e oportunidades comerciais; cria roteiros e textos.","responsibilities":["Pesquisa de tendências e assuntos em alta","Ideias de vídeos e produtos","Legendas, roteiros e chamadas"],"status":"CONFIGURED_NOT_VALIDATED"},
    {"id":"BOT_03","name":"Publisher AI","role":"Criação e publicação","icon":"send","color":"teal","description":"Prepara títulos, biografias, descrições, hashtags e pacotes de publicação por rede.","responsibilities":["Adaptação de conteúdo por plataforma","Biografias, descrições e hashtags","Fila de publicação com aprovação"],"status":"CONFIGURED_NOT_VALIDATED"},
    {"id":"BOT_04","name":"Manager AI","role":"Coordenação","icon":"workflow","color":"amber","description":"Organiza prioridades, dependências e entregas dos bots 01 a 03.","responsibilities":["Distribuição de tarefas","Controle de prazos e dependências","Detecção de conflitos e atrasos"],"status":"CONFIGURED_NOT_VALIDATED"},
    {"id":"BOT_05","name":"Master Operacional","role":"Comando central","icon":"brain","color":"cyan","description":"Supervisiona os quatro bots, monitora falhas e apresenta o estado geral do sistema.","responsibilities":["Supervisão geral e relatórios","Monitoramento de falhas","Regras de segurança e aprovação"],"status":"CONFIGURED_NOT_VALIDATED"},
]


def dashboard():
    ai_ready = bool(get_groq_api_key())
    storage_backend = store.backend()
    storage_durable = storage_backend == "postgresql"
    tasks = store.list_tasks()
    approvals = store.list_approvals()
    pending = sum(1 for item in approvals if item.get("status") == "PENDING")
    completed = sum(1 for item in tasks if item.get("status") == "COMPLETED")

    # Status por agente vem da última etapa registrada no PostgreSQL, nunca do cadastro estático.
    latest_by_bot = {}
    for task in store.list_agent_execution_history(100):
        result = task.get("result") or {}
        for stage in result.get("stages") or []:
            bot_id = stage.get("bot_id")
            if bot_id and bot_id not in latest_by_bot:
                latest_by_bot[bot_id] = {
                    "status": stage.get("status", "UNKNOWN"),
                    "finished_at": stage.get("finished_at"),
                    "task_id": task.get("id"),
                }
    bots = []
    for original in BOTS:
        bot = dict(original)
        latest = latest_by_bot.get(bot["id"])
        bot["last_execution"] = latest
        if latest and latest["status"] == "COMPLETED":
            bot["status"] = "EXECUTION_COMPLETED"
            bot["status_label"] = "ÚLTIMA EXECUÇÃO CONCLUÍDA"
            bot["validated"] = True
        elif latest and latest["status"] == "FAILED":
            bot["status"] = "EXECUTION_FAILED"
            bot["status_label"] = "FALHA NA ÚLTIMA EXECUÇÃO"
            bot["validated"] = False
        else:
            bot["status"] = "NOT_EXECUTED"
            bot["status_label"] = "AGUARDANDO PRIMEIRA EXECUÇÃO"
            bot["validated"] = False

    if not ai_ready:
        notice = "API disponível. Provedor de IA ainda não foi detectado; geração inteligente está indisponível."
    elif not storage_durable:
        notice = "Groq configurada. Atenção: o armazenamento atual é SQLite; em hospedagem efêmera, os dados podem não sobreviver a reinicializações."
    else:
        notice = "API, provedor de IA configurado e banco PostgreSQL detectados. A conexão real com a IA deve ser verificada separadamente."

    return {
        "project": "AUTOMA X",
        "edition": "AI Social Command Center",
        "status": "ATTENTION" if (not ai_ready or not storage_durable) else "READY",
        "ai_provider_configured": ai_ready,
        "ai_provider": "Groq" if ai_ready else None,
        "storage": {
            "backend": storage_backend,
            "durable": storage_durable,
            "note": "PostgreSQL configurado." if storage_durable else "SQLite detectado; confirme disco persistente ou migre para PostgreSQL gerenciado."
        },
        "bots_total": len(BOTS),
        "bots": bots,
        "platforms": [{"name": name, "connected": False, "status": "Aguardando conexão oficial"} for name in PLATFORMS],
        "metrics": {
            "tasks_total": len(tasks),
            "tasks_completed": completed,
            "approvals_pending": pending
        },
        "recent_tasks": tasks[:8],
        "publishing_enabled": False,
        "publishing_mode": "MANUAL_APPROVAL",
        "notice": notice
    }
