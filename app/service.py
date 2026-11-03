"""Оркестрация: промпт → модель → проверка → повторная попытка → итоговая карточка."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .llm import Usage
from .prompts import build_messages, feedback_message
from .schemas import CardDraft, Meta, ProductCard, ProductInput, ProductRef, Quality
from .validation import Violation, finalize_characteristics, finalize_missing_fields, validate_draft

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class GenerationError(Exception):
    """Модель не дала пригодного ответа за отведённое число попыток."""


class DraftParseError(Exception):
    """Ответ модели не разбирается как JSON нужной структуры."""


class Completer(Protocol):
    """Минимальный интерфейс LLM-клиента (удобно подменять в тестах)."""

    @property
    def model(self) -> str: ...

    def complete_json(self, messages: list[dict[str, str]]) -> tuple[str, Usage]: ...


def parse_draft(raw: str) -> CardDraft:
    """JSON из ответа модели → CardDraft. Терпит markdown-обёртку ```json ... ```."""
    text = _FENCE_RE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"ответ не является корректным JSON ({exc.msg}, позиция {exc.pos})") from exc
    if not isinstance(data, dict):
        raise DraftParseError("ответ должен быть JSON-объектом с полями карточки")
    try:
        return CardDraft.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise DraftParseError(f"JSON не соответствует требуемой структуре: {details}") from exc


def generate_card(product: ProductInput, llm: Completer, max_attempts: int = 3) -> ProductCard:
    """Основной сценарий сервиса.

    1. Отправляем модели данные товара.
    2. Проверяем ответ кодом (факты, полнота, длины).
    3. При нарушениях возвращаем модели список замечаний и просим исправить (до max_attempts раз).
    4. Если нарушения остались — чиним безопасно кодом и показываем предупреждения менеджеру.
    """
    messages = build_messages(product)
    best: tuple[CardDraft, list[Violation]] | None = None
    last_error = ""
    prompt_tokens = completion_tokens = 0
    attempts = 0

    for attempts in range(1, max_attempts + 1):
        raw, usage = llm.complete_json(messages)
        prompt_tokens += usage.prompt_tokens or 0
        completion_tokens += usage.completion_tokens or 0
        try:
            draft = parse_draft(raw)
        except DraftParseError as exc:
            last_error = str(exc)
            feedback = [last_error]
            log.warning("Попытка %d: %s", attempts, last_error)
        else:
            violations = validate_draft(draft, product)
            best = (draft, violations)
            if not violations:
                log.info("Попытка %d: черновик принят", attempts)
                break
            feedback = [v.message for v in violations]
            log.info("Попытка %d: %d замечаний — %s", attempts, len(violations), "; ".join(feedback))
        if attempts < max_attempts:
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": feedback_message(feedback)},
            ]

    if best is None:
        raise GenerationError(f"Модель не вернула корректный JSON за {attempts} попыток: {last_error}")

    draft, violations = best
    characteristics, warnings = finalize_characteristics(draft.characteristics, product, violations)
    for v in violations:
        if v.kind in {"number", "claim", "length", "structure"}:
            warnings.append(v.summary)
    missing_fields = finalize_missing_fields(draft.missing_fields, characteristics, product)

    return ProductCard(
        product=ProductRef(name=product.name, manufacturer=product.manufacturer),
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        characteristics=characteristics,
        search_queries=draft.search_queries,
        commercial_block=draft.commercial_block,
        missing_fields=missing_fields,
        quality=Quality(
            seo_title_length=len(draft.seo_title),
            seo_description_length=len(draft.seo_description),
            attempts=attempts,
            warnings=warnings,
        ),
        meta=Meta(
            model=llm.model,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            prompt_tokens=prompt_tokens or None,
            completion_tokens=completion_tokens or None,
        ),
    )
