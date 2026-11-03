"""Веб-интерфейс и HTTP API.

    uvicorn app.web:app --reload
    GET  /               — форма для контент-менеджера
    POST /api/generate   — JSON о товаре → карточка (JSON + Markdown)
    GET  /api/health     — проверка, что сервис настроен
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .config import ConfigError, Settings, load_settings
from .llm import LLMClient, LLMError
from .render import to_markdown
from .schemas import ProductCard, ProductInput
from .service import Completer, GenerationError, generate_card

app = FastAPI(
    title="Product Card Generator",
    description="Черновик карточки товара для B2B-магазина КИП по данным о приборе",
    version="0.1.0",
)
_TEMPLATE = Path(__file__).parent / "templates" / "index.html"
_runtime: dict[str, object] = {}


class GenerateResponse(BaseModel):
    card: ProductCard
    markdown: str


def get_runtime() -> tuple[Settings, Completer]:
    """Ленивая инициализация клиента: сервис стартует и без ключа, ошибка покажется на запросе."""
    if "client" not in _runtime:
        settings = load_settings()
        _runtime["settings"] = settings
        _runtime["client"] = LLMClient(settings)
    return _runtime["settings"], _runtime["client"]  # type: ignore[return-value]


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        detail = next(e.get("msg", "") for e in errors if e.get("type") == "json_invalid")
        return JSONResponse({"error": f"Некорректный JSON: {detail}"}, status_code=400)
    details = [
        f"{'.'.join(str(x) for x in e['loc'][1:]) or 'body'}: {e['msg'].removeprefix('Value error, ')}" for e in errors
    ]
    return JSONResponse({"error": "Некорректные входные данные", "details": details}, status_code=422)


@app.exception_handler(ConfigError)
async def config_error_handler(_: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse({"error": f"Сервис не настроен: {exc}"}, status_code=500)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


@app.get("/api/health")
def health(runtime: tuple[Settings, Completer] = Depends(get_runtime)) -> dict[str, str]:
    settings, _ = runtime
    return {"status": "ok", "model": settings.model, "base_url": settings.base_url}


@app.post("/api/generate", response_model=GenerateResponse, responses={400: {}, 422: {}, 502: {}})
def api_generate(product: ProductInput, runtime: tuple[Settings, Completer] = Depends(get_runtime)):
    settings, llm = runtime
    try:
        card = generate_card(product, llm, settings.max_attempts)
    except LLMError as exc:
        return JSONResponse({"error": f"Ошибка LLM API: {exc}"}, status_code=502)
    except GenerationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return GenerateResponse(card=card, markdown=to_markdown(card))
