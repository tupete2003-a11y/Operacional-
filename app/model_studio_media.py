"""Encrypted reference/generated image storage and OpenAI Images edit adapter."""
import base64
import hashlib
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, ImageStat, UnidentifiedImageError

from . import store

MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ModelStudioError(Exception):
    pass


def _cipher():
    key = os.getenv("AUTOMA_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise ModelStudioError("Configure AUTOMA_TOKEN_ENCRYPTION_KEY no Render para habilitar armazenamento criptografado.")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise ModelStudioError("AUTOMA_TOKEN_ENCRYPTION_KEY inválida; gere uma chave Fernet válida.") from exc


def _inspect_and_normalize(raw: bytes):
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ModelStudioError("A imagem precisa ter conteúdo e no máximo 12 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ModelStudioError("Formato não aceito. Envie JPEG, PNG ou WEBP.")
            im.verify()
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            width, height = im.size
            if width < 512 or height < 512:
                raise ModelStudioError("A imagem precisa ter pelo menos 512 px em cada dimensão.")
            output = io.BytesIO()
            im.save(output, format="JPEG", quality=94, optimize=True)
            clean = output.getvalue()
        return clean, "image/jpeg", width, height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ModelStudioError("Arquivo de imagem inválido ou inseguro.") from exc


def save_reference(raw: bytes):
    if store.backend() != "postgresql":
        raise ModelStudioError("Armazenamento persistente de referências exige PostgreSQL; SQLite local/efêmero não é aceito.")
    cipher = _cipher()
    clean, mime, width, height = _inspect_and_normalize(raw)
    image_id = str(uuid.uuid4())
    digest = hashlib.sha256(clean).hexdigest()
    encrypted = cipher.encrypt(clean)
    store.save_model_reference(image_id, mime, encrypted, digest, width, height)
    return {"reference_id": image_id, "mime_type": mime, "width": width, "height": height, "sha256": digest, "stored_encrypted": True}


def get_reference(reference_id=None):
    record = store.get_model_reference(reference_id)
    if not record:
        return None
    try:
        raw = _cipher().decrypt(bytes(record["encrypted_data"]))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ModelStudioError("Não foi possível descriptografar a referência; confira a chave de criptografia do Render.") from exc
    return record, raw


def reference_status():
    record = store.get_model_reference()
    if not record:
        return {"registered": False, "status": "awaiting_reference_upload"}
    return {"registered": True, "reference_id": record["id"], "mime_type": record["mime_type"], "width": record["width"], "height": record["height"], "created_at": record["created_at"], "encrypted": True}


def _quality_report(raw: bytes):
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            width, height = im.size
            gray = im.convert("L")
            contrast = round(float(ImageStat.Stat(gray).stddev[0]), 2)
            edge = gray.filter(Image.Filter.FIND_EDGES) if False else gray
            checks = {
                "readable_image": True,
                "minimum_resolution": width >= 768 and height >= 768,
                "reasonable_contrast": contrast >= 8,
                "file_size_ok": len(raw) <= MAX_IMAGE_BYTES * 2,
            }
            passed = all(checks.values())
            return {
                "status": "PASS_WITH_HUMAN_REVIEW" if passed else "REVIEW_REQUIRED",
                "width": width, "height": height, "contrast_score": contrast,
                "checks": checks,
                "identity_consistency": "NOT_AUTOMATICALLY_VERIFIED",
                "human_identity_review_required": True,
                "note": "A avaliação automática cobre legibilidade, resolução e contraste. A semelhança de identidade deve ser confirmada visualmente por uma pessoa; nenhum reconhecimento facial biométrico é executado.",
            }
    except Exception:
        return {"status": "REVIEW_REQUIRED", "checks": {"readable_image": False}, "human_identity_review_required": True}


def _multipart(fields, file_field, filename, mime, content):
    boundary = "----AutomaX" + secrets.token_hex(16)
    chunks = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode("utf-8"), b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(), content, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return boundary, b"".join(chunks)


def generate_from_reference(reference_bytes: bytes, objective: str, composition="group", style="photorealistic"):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ModelStudioError("Provedor de imagens não configurado. Cadastre OPENAI_API_KEY como segredo no serviço automa-x-api do Render.")
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst").strip()
    prompt = (
        "Create a photorealistic new photograph using the uploaded reference as the identity reference for the main model. "
        "Preserve her recognizable facial appearance, hairstyle, natural skin texture, proportions and overall look as closely as possible. "
        "Do not beautify excessively, change ethnicity, age, body shape, or invent identifying details. "
        f"Scene objective: {objective}. Composition: {composition}. Visual style: {style}. "
        "Natural photographic lighting, realistic anatomy, hands and background, candid camera quality. "
        "If other people are requested, include them as distinct secondary people while keeping the reference model clearly recognizable. "
        "Do not add text, logos, watermarks, captions or artificial skin smoothing."
    )
    boundary, body = _multipart(
        {"model": model, "prompt": prompt, "quality": "high", "size": "1024x1024", "n": "1", "output_format": "jpeg"},
        "image[]", "model-reference.jpg", "image/jpeg", reference_bytes,
    )
    req = Request(
        "https://api.openai.com/v1/images/edits",
        data=body,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Never expose upstream response bodies; they may contain request metadata.
        raise ModelStudioError(f"O provedor de imagens recusou a solicitação (HTTP {exc.code}).") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise ModelStudioError("Não foi possível concluir a solicitação ao provedor de imagens.") from exc
    items = payload.get("data") or []
    encoded = items[0].get("b64_json") if items else None
    if not encoded:
        raise ModelStudioError("O provedor não retornou a imagem esperada.")
    try:
        result = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ModelStudioError("A resposta de imagem do provedor estava inválida.") from exc
    return result, model


def save_generated(raw: bytes, reference_id: str, objective: str, model: str):
    cipher = _cipher()
    clean, mime, width, height = _inspect_and_normalize(raw)
    report = _quality_report(clean)
    image_id = str(uuid.uuid4())
    store.save_model_generated_image(
        image_id, reference_id, mime, cipher.encrypt(clean),
        json.dumps(report, ensure_ascii=False), objective, model
    )
    return {"image_id": image_id, "mime_type": mime, "width": width, "height": height, "quality": report}


def load_generated(image_id: str):
    record = store.get_model_generated_image(image_id)
    if not record:
        return None
    try:
        raw = _cipher().decrypt(bytes(record["encrypted_data"]))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ModelStudioError("Não foi possível descriptografar a imagem armazenada.") from exc
    return record, raw
