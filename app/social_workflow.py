import json
import logging
import os
import uuid

from . import store
from .llm import ask_agent
from .social import BOTS, PLATFORMS

logger = logging.getLogger("automa_x.social_workflow")

CONTENT_TYPES = {
    "sales_banner": "Banner de vendas",
    "promo_banner": "Banner promocional",
    "carousel": "Carrossel personalizado",
    "video": "Roteiro de vídeo curto",
    "text": "Texto comercial ou educativo",
}


def _business_profile():
    """Carrega somente dados comerciais explicitamente configurados no backend."""
    fields = {
        "name": os.getenv("AUTOMA_X_BRAND_NAME", "").strip(),
        "city": os.getenv("AUTOMA_X_BRAND_CITY", "").strip(),
        "contact": os.getenv("AUTOMA_X_BRAND_CONTACT", "").strip(),
        "visual_identity": os.getenv("AUTOMA_X_BRAND_VISUAL_IDENTITY", "").strip(),
        "website": os.getenv("AUTOMA_X_BRAND_WEBSITE", "").strip(),
    }
    return {key: value for key, value in fields.items() if value}


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


def _recent_history(limit=4):
    history = []

    for item in store.list_tasks()[:limit]:
        task = store.get_task(item["id"])
        if not task:
            continue

        result = task.get("result") or {}
        history.append({
            "request": task.get("request", "")[:120],
            "result": json.dumps(result, ensure_ascii=False)[:180],
        })

    return history


def generate_social_workflow(payload):
    platforms = payload["platforms"]
    content_types = payload["content_types"]
    if not isinstance(payload.get("objective"), str) or len(payload["objective"].strip()) < 5:
        raise ValueError("O objetivo precisa ter pelo menos 5 caracteres.")
    unknown_platforms = sorted(set(platforms) - set(PLATFORMS))
    if unknown_platforms:
        raise ValueError("Plataformas não suportadas: " + ", ".join(unknown_platforms))
    unknown_content_types = sorted(set(content_types) - set(CONTENT_TYPES))
    if unknown_content_types:
        raise ValueError("Formatos não suportados: " + ", ".join(unknown_content_types))
    if len(set(platforms)) != len(platforms) or len(set(content_types)) != len(content_types):
        raise ValueError("Não repita plataformas ou formatos na mesma solicitação.")

    business = _business_profile()
    task_id = str(uuid.uuid4())
    created_at = store.now()

    context = {
        "marca_configurada": business or "Nenhuma marca foi configurada no backend.",
        "objetivo": payload["objective"],
        "plataformas": platforms,
        "formatos": {key: CONTENT_TYPES[key] for key in content_types},
        "historico_recente": _recent_history(),
        "regras": [
            "Escreva em português brasileiro.",
            "Não invente preços, descontos ou condições promocionais.",
            "Quando faltarem condições de uma promoção, escreva condição a definir.",
            "Não invente avaliações, depoimentos ou resultados.",
            "Não invente tendências, visualizações ou métricas.",
            "Use somente dados de marca e contatos presentes na configuração ou no pedido.",
            "Se faltarem dados comerciais essenciais, sinalize como informação pendente.",
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
            "Defina a estratégia da campanha, público, objetivos, mensagens principais e distribuição das entregas."
        ),
        (
            "BOT_02",
            "IDEIAS E REDAÇÃO",
            "Crie ideias originais, ganchos, títulos, textos comerciais, textos educativos e roteiros. Não alegue pesquisa ao vivo ou tendências verificadas sem fontes."
        ),
        (
            "BOT_03",
            "PRODUÇÃO DE CONTEÚDO",
            "Monte o pacote solicitado. Para banners, entregue título, subtítulo, CTA e direção visual. Para carrosséis, detalhe cada slide. Para vídeos, detalhe cenas, narração e textos na tela. Adapte legendas e hashtags a cada plataforma. Não gere arquivos de imagem nem publique."
        ),
        (
            "BOT_04",
            "REVISÃO E CONTROLE",
            "Revise clareza, ortografia, diversidade, adequação às redes, consistência da marca e segurança das ofertas. Corrija promessas exageradas e identifique informações pendentes."
        ),
        (
            "BOT_01",
            "CALENDÁRIO EDITORIAL",
            "Organize as entregas em um calendário sugerido, distribuindo formatos e plataformas. Sugira dias e faixas de horário como hipóteses para teste, não como horários comprovadamente ideais. Evite conflitos e repetição."
        ),
    ]

    outputs = {}
    stage_history = []
    task = {
        "id": task_id,
        "request": payload["objective"],
        "status": "IN_PROGRESS",
        "plan": {
            "selected_agents": [stage[0] for stage in stages],
            "platforms": platforms,
            "content_types": content_types,
            "workflow": "FIVE_BOT_SOCIAL_CAMPAIGN",
        },
        "result": {
            "business": business,
            "outputs": outputs,
            "stages": stage_history,
            "approval_required": False,
            "publishing_enabled": False,
        },
        "created_at": created_at,
    }

    store.save_task(task)

    for bot_id, title, instruction in stages:
        stage_record = {
            "bot_id": bot_id,
            "stage": title,
            "status": "RUNNING",
            "started_at": store.now(),
        }
        stage_history.append(stage_record)
        task["result"]["stages"] = stage_history
        task["result"]["current_stage"] = bot_id
        store.save_task(task)
        logger.info("Fluxo %s: início da etapa %s", task_id, bot_id)

        compact_outputs = {key: value[:1600] for key, value in outputs.items()}
        previous = json.dumps(compact_outputs, ensure_ascii=False)
        prompt = (
            "DADOS DA CAMPANHA:\n" + base
            + "\n\nENTREGAS ANTERIORES:\n" + previous
            + "\n\nSUA ETAPA: " + title
            + "\nINSTRUÇÃO: " + instruction
            + "\n\nEntregue conteúdo organizado, objetivo e utilizável."
        )

        try:
            output = ask_agent(_agent(bot_id), prompt)
            if not isinstance(output, str) or not output.strip():
                raise RuntimeError("O provedor de IA retornou uma resposta vazia.")
            outputs[bot_id] = output.strip()
            stage_record["status"] = "COMPLETED"
            stage_record["finished_at"] = store.now()
            task["result"]["outputs"] = outputs
            task["result"]["stages"] = stage_history
            task["result"].pop("current_stage", None)
            store.save_task(task)
            logger.info("Fluxo %s: etapa %s concluída", task_id, bot_id)
        except Exception as exc:
            stage_record["status"] = "FAILED"
            stage_record["finished_at"] = store.now()
            stage_record["error"] = str(exc)[:400]
            task["status"] = "FAILED"
            task["result"]["outputs"] = outputs
            task["result"]["stages"] = stage_history
            task["result"]["failed_stage"] = bot_id
            task["result"].pop("current_stage", None)
            task["result"]["error_type"] = type(exc).__name__
            task["result"]["error"] = str(exc)[:400]
            task["result"]["failed_at"] = store.now()
            task["result"]["approval_required"] = False
            store.save_task(task)
            logger.exception("Fluxo %s: falha na etapa %s", task_id, bot_id)
            raise RuntimeError(
                "Fluxo interrompido na etapa " + bot_id
                + ". O progresso parcial foi registrado na tarefa " + task_id
            ) from exc

    approval_id = str(uuid.uuid4())
    task["status"] = "DRAFT_REVIEW"
    task["result"]["approval_required"] = True
    task["result"]["publishing_enabled"] = False
    task["result"]["approval_status"] = "PENDING"
    task["result"]["approval_id"] = approval_id
    task["result"]["completed_at"] = store.now()
    try:
        store.create_approval(
            approval_id,
            task_id,
            "Revisar campanha completa",
        )
        store.save_task(task)
    except Exception as exc:
        task["status"] = "FAILED"
        task["result"]["approval_required"] = False
        task["result"]["approval_status"] = "NOT_CREATED"
        task["result"]["error_type"] = type(exc).__name__
        task["result"]["error"] = "Não foi possível registrar a aprovação humana: " + str(exc)[:300]
        task["result"]["failed_at"] = store.now()
        store.save_task(task)
        logger.exception("Fluxo %s: falha ao registrar aprovação humana", task_id)
        raise RuntimeError("Campanha gerada, mas o registro de aprovação falhou. Tarefa: " + task_id) from exc

    logger.info("Fluxo %s concluído; aprovação humana %s pendente", task_id, approval_id)

    return {
        "task_id": task_id,
        "approval_id": approval_id,
        "status": "DRAFT_REVIEW",
        "approval_required": True,
        "publishing_enabled": False,
        "business": business,
        "outputs": outputs,
        "stages": stage_history,
    }
