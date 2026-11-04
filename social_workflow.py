
import json
import uuid

from . import store
from .llm import ask_agent
from .social import BOTS, PLATFORMS


BUSINESS = {
    "name": "Diamond Refrigeração",
    "city": "Goiânia - GO",
    "whatsapp": "(63) 99985-2293",
    "visual_identity": "Azul, branco e tons de gelo",
}

CONTENT_TYPES = {
    "sales_banner": "Banner de vendas",
    "promo_banner": "Banner promocional",
    "carousel": "Carrossel personalizado",
    "video": "Roteiro de vídeo curto",
    "text": "Texto comercial ou educativo",
}


def _agent(bot_id):
    bot = next((b for b in BOTS if b["id"] == bot_id), None)
    if not bot:
        raise RuntimeError("Bot não encontrado: " + bot_id)

    return {
        "id": bot["id"],
        "name": bot["name"],
        "function": (
            bot["description"] + " Responsabilidades: "
            + "; ".join(bot["responsibilities"])
        ),
    }


def _recent_history(limit=12):
    history = []

    for item in store.list_tasks()[:limit]:
        task = store.get_task(item["id"])
        if not task:
            continue

        result = task.get("result") or {}
        history.append({
            "request": task.get("request", "")[:180],
            "result": json.dumps(
                result, ensure_ascii=False
            )[:350],
        })

    return history


def generate_social_workflow(payload):
    platforms = payload["platforms"]
    content_types = payload["content_types"]

    context = {
        "empresa": BUSINESS,
        "objetivo": payload["objective"],
        "plataformas": platforms,
        "formatos": {
            key: CONTENT_TYPES[key]
            for key in content_types
        },
        "historico_recente": _recent_history(),
        "regras": [
            "Escreva em português brasileiro.",
            "Não invente preços, descontos ou condições promocionais.",
            "Quando faltarem condições de uma promoção, escreva condição a definir.",
            "Não invente avaliações, depoimentos ou resultados.",
            "Não invente tendências, visualizações ou métricas.",
            "Use o WhatsApp informado como chamada para orçamento.",
            "Varie temas, ganchos, títulos e formatos em relação ao histórico.",
            "Não afirme que publicou ou conectou redes sociais.",
            "Entregue rascunhos para aprovação humana.",
        ],
    }

    base = json.dumps(context, ensure_ascii=False, indent=2)

    stages = [
        (
            "BOT_05",
            "ESTRATÉGIA CENTRAL",
            "Defina a estratégia da campanha, público, objetivos, "
            "mensagens principais e distribuição das entregas."
        ),
        (
            "BOT_02",
            "IDEIAS E REDAÇÃO",
            "Crie ideias originais, ganchos, títulos, textos comerciais, "
            "textos educativos e roteiros. Não alegue pesquisa ao vivo "
            "ou tendências verificadas sem fontes."
        ),
        (
            "BOT_03",
            "PRODUÇÃO DE CONTEÚDO",
            "Monte o pacote solicitado. Para banners, entregue título, "
            "subtítulo, CTA e direção visual. Para carrosséis, detalhe "
            "cada slide. Para vídeos, detalhe cenas, narração e textos "
            "na tela. Adapte legendas e hashtags a cada plataforma. "
            "Não gere arquivos de imagem nem publique."
        ),
        (
            "BOT_04",
            "REVISÃO E CONTROLE",
            "Revise clareza, ortografia, diversidade, adequação às redes, "
            "consistência da marca e segurança das ofertas. Corrija "
            "promessas exageradas e identifique informações pendentes."
        ),
        (
            "BOT_01",
            "CALENDÁRIO EDITORIAL",
            "Organize as entregas em um calendário sugerido, distribuindo "
            "formatos e plataformas. Sugira dias e faixas de horário "
            "como hipóteses para teste, não como horários comprovadamente "
            "ideais. Evite conflitos e repetição."
        ),
    ]

    outputs = {}

    for bot_id, title, instruction in stages:
        previous = json.dumps(outputs, ensure_ascii=False)

        prompt = (
            "DADOS DA CAMPANHA:\n" + base
            + "\n\nENTREGAS ANTERIORES:\n" + previous
            + "\n\nSUA ETAPA: " + title
            + "\nINSTRUÇÃO: " + instruction
            + "\n\nEntregue conteúdo organizado, objetivo e utilizável."
        )

        outputs[bot_id] = ask_agent(_agent(bot_id), prompt)

    task_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())
    created_at = store.now()

    task = {
        "id": task_id,
        "request": payload["objective"],
        "status": "DRAFT_REVIEW",
        "plan": {
            "selected_agents": [
                "BOT_05", "BOT_02", "BOT_03", "BOT_04", "BOT_01"
            ],
            "platforms": platforms,
            "content_types": content_types,
            "workflow": "FIVE_BOT_SOCIAL_CAMPAIGN",
        },
        "result": {
            "business": BUSINESS,
            "outputs": outputs,
            "approval_required": True,
            "publishing_enabled": False,
        },
        "created_at": created_at,
    }

    store.save_task(task)

    store.create_approval(
        approval_id,
        task_id,
        "Revisar campanha completa · Diamond Refrigeração",
    )

    return {
        "task_id": task_id,
        "approval_id": approval_id,
        "status": "DRAFT_REVIEW",
        "approval_required": True,
        "publishing_enabled": False,
        "business": BUSINESS,
        "outputs": outputs,
    }
