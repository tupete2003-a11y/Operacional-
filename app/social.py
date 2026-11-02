from .config import get_groq_api_key

PLATFORMS = ["Instagram", "TikTok", "Facebook", "YouTube", "Kwai"]

BOTS = [
    {"id":"BOT_01","name":"Scheduler AI","role":"Agenda e horários","icon":"calendar","color":"blue","description":"Organiza o calendário editorial e recomenda horários de publicação.","responsibilities":["Calendário diário e semanal","Distribuição de conteúdo por plataforma","Lembretes e prevenção de conflitos"],"status":"READY"},
    {"id":"BOT_02","name":"Trend Writer AI","role":"Pesquisa e redação","icon":"trending","color":"purple","description":"Pesquisa tendências, formatos, temas e oportunidades comerciais; cria roteiros e textos.","responsibilities":["Pesquisa de tendências e assuntos em alta","Ideias de vídeos e produtos","Legendas, roteiros e chamadas"],"status":"READY"},
    {"id":"BOT_03","name":"Publisher AI","role":"Criação e publicação","icon":"send","color":"teal","description":"Prepara títulos, biografias, descrições, hashtags e pacotes de publicação por rede.","responsibilities":["Adaptação de conteúdo por plataforma","Biografias, descrições e hashtags","Fila de publicação com aprovação"],"status":"READY"},
    {"id":"BOT_04","name":"Manager AI","role":"Coordenação","icon":"workflow","color":"amber","description":"Organiza prioridades, dependências e entregas dos bots 01 a 03.","responsibilities":["Distribuição de tarefas","Controle de prazos e dependências","Detecção de conflitos e atrasos"],"status":"READY"},
    {"id":"BOT_05","name":"Master Operacional","role":"Comando central","icon":"brain","color":"cyan","description":"Supervisiona os quatro bots, monitora falhas e apresenta o estado geral do sistema.","responsibilities":["Supervisão geral e relatórios","Monitoramento de falhas","Regras de segurança e aprovação"],"status":"READY"},
]

def dashboard():
    ai_ready = bool(get_groq_api_key())
    return {
        "project":"AUTOMA X",
        "edition":"AI Social Command Center",
        "status":"ONLINE",
        "ai_provider_configured":ai_ready,
        "ai_provider":"Groq" if ai_ready else None,
        "bots_total":len(BOTS),
        "bots":BOTS,
        "platforms":[{"name":name,"connected":False,"status":"Aguardando conexão oficial"} for name in PLATFORMS],
        "publishing_enabled":False,
        "publishing_mode":"MANUAL_APPROVAL",
        "notice":"Painel e equipe configurados. IA e publicação externa dependem de credenciais e permissões oficiais."
    }
