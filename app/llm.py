import json
import re
import os
import time
import urllib.error
import urllib.request
from .config import get_groq_api_key

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def ask_agent(agent, user_request):
    api_key = get_groq_api_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada")

    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    system_prompt = (
        "Você é um especialista dentro do sistema AUTOMA X. "
        "Responda em português do Brasil, com clareza, objetividade e conteúdo completo. "
        "Sua função é: " + agent["function"] + " "
        "Analise somente a solicitação recebida. Entregue conteúdo organizado, recomendações, "
        "riscos/limitações e próximos passos quando forem pertinentes. "
        "REGRA DE CONFIABILIDADE: nunca invente especificações, funcionalidades, conectividade, "
        "preços, descontos, percentuais, economia, desempenho, garantias, certificações, "
        "depoimentos, estatísticas, pesquisas ou tendências. Se uma informação não estiver "
        "explicitamente nos dados fornecidos, não a apresente como fato; omita-a ou marque "
        "[PENDENTE DE COMPROVAÇÃO]. Prefira conteúdo educativo neutro quando faltarem fontes. "
        "Não invente características de produtos nem presuma que um produto possui recursos. "
        "Não afirme que executou ações externas. Não envie mensagens, não faça compras, "
        "pagamentos, publicações, exclusões ou alterações em sistemas. Essas ações exigem aprovação humana."
    )
    try:
        max_tokens = int(os.getenv("GROQ_MAX_COMPLETION_TOKENS", "1200"))
    except ValueError:
        max_tokens = 1200
    # Um mínimo evita que respostas estruturadas sejam marcadas como concluídas pela metade.
    max_tokens = max(900, min(max_tokens, 1800))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request}
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "reasoning_effort": "low"
    }

    def make_request():
        return urllib.request.Request(
            GROQ_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "AUTOMA-X/1.0 (backend integration)"
            },
            method="POST"
        )

    request = make_request()
    empty_response_attempts = 0
    truncation_retries = 0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                content = "\\n".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            finish_reason = str(choice.get("finish_reason") or "").lower()

            if finish_reason == "length":
                if truncation_retries < 1 and payload["max_tokens"] < 1800:
                    truncation_retries += 1
                    payload["max_tokens"] = min(1800, payload["max_tokens"] + 500)
                    request = make_request()
                    continue
                raise RuntimeError(
                    "A Groq encerrou a resposta por limite de tokens; a etapa não será "
                    "marcada como concluída com conteúdo incompleto."
                )

            if isinstance(content, str) and content.strip():
                return content.strip()
            if empty_response_attempts < 1:
                empty_response_attempts += 1
                payload["max_tokens"] = min(1800, payload["max_tokens"] + 250)
                request = make_request()
                time.sleep(2)
                continue
            raise RuntimeError(
                "A Groq não retornou texto após nova tentativa (finish_reason="
                + (finish_reason or "desconhecido") + ")."
            )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                error_obj = parsed.get("error")
                detail = error_obj.get("message", "") if isinstance(error_obj, dict) else str(error_obj or raw)
                error_code = error_obj.get("code") if isinstance(error_obj, dict) else None
            except (ValueError, TypeError):
                detail, error_code = raw, None
            if exc.code == 429 and attempt < 3:
                wait_seconds = 20.0
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        wait_seconds = max(1.0, float(retry_after))
                    except ValueError:
                        pass
                match = re.search(r"try again in ([0-9.]+)s", str(detail), re.IGNORECASE)
                if match:
                    wait_seconds = max(wait_seconds, float(match.group(1)) + 1.0)
                time.sleep(min(wait_seconds, 90.0))
                continue
            safe_detail = str(detail).replace(api_key, "[REDACTED]")
            safe_detail = re.sub(r"Bearer\\s+\\S+", "Bearer [REDACTED]", safe_detail, flags=re.IGNORECASE)
            safe_detail = " ".join(safe_detail.split())[:350]
            if exc.code == 429:
                raise RuntimeError("Groq HTTP 429 após aguardar o limite de uso: " + safe_detail)
            if exc.code == 403:
                suffix = (" (código " + str(error_code) + ")") if error_code else ""
                raise RuntimeError("Groq negou a solicitação HTTP 403" + suffix + ": " + safe_detail)
            raise RuntimeError("Groq HTTP " + str(exc.code) + ": " + safe_detail)
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError("Falha de conexão com Groq: " + str(reason)[:250])
        except (KeyError, IndexError, ValueError) as exc:
            raise RuntimeError("Resposta inesperada do provedor de IA: " + str(exc)[:200])
