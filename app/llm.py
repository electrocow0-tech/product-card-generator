"""Обёртка над OpenAI-совместимым API с понятными сообщениями об ошибках."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI

from .config import Settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Ошибка обращения к модели, понятная пользователю."""


@dataclass
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient:
    """Один метод: отправить диалог, получить текст ответа (ожидается JSON)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._json_mode = settings.json_mode
        # Повторы при сетевых ошибках, 429 и 5xx делает сам SDK (экспоненциальная пауза)
        self._client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=settings.timeout,
            max_retries=2,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    def complete_json(self, messages: list[dict[str, str]]) -> tuple[str, Usage]:
        try:
            response = self._create(messages, json_mode=self._json_mode)
        except openai.BadRequestError as exc:
            # Не все серверы поддерживают response_format=json_object — тогда работаем без него
            if self._json_mode and "response_format" in str(exc).lower():
                log.warning("API не поддерживает response_format=json_object, повторяю запрос без него")
                self._json_mode = False
                try:
                    response = self._create(messages, json_mode=False)
                except openai.APIError as retry_exc:
                    raise LLMError(self._describe(retry_exc)) from retry_exc
            else:
                raise LLMError(self._describe(exc)) from exc
        except openai.APIError as exc:
            raise LLMError(self._describe(exc)) from exc

        if not response.choices:
            raise LLMError("Модель вернула пустой ответ (нет choices)")
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise LLMError("Модель вернула пустой ответ")
        usage = Usage()
        if response.usage is not None:
            usage = Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        return content, usage

    def _create(self, messages: list[dict[str, str]], json_mode: bool) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return self._client.chat.completions.create(**kwargs)

    def _describe(self, exc: openai.APIError) -> str:
        s = self._settings
        if isinstance(exc, openai.AuthenticationError):
            return f"API отклонил ключ (401). Проверьте LLM_API_KEY для {s.base_url}."
        if isinstance(exc, openai.PermissionDeniedError):
            return f"Доступ запрещён (403): {exc.message}"
        if isinstance(exc, openai.NotFoundError):
            return f"Модель «{s.model}» или адрес {s.base_url} не найдены (404). Проверьте LLM_MODEL и LLM_BASE_URL."
        if isinstance(exc, openai.RateLimitError):
            return "Превышен лимит запросов к API (429). Повторите попытку позже."
        if isinstance(exc, openai.APITimeoutError):
            return f"Модель не ответила за {s.timeout:.0f} с. Увеличьте LLM_TIMEOUT или выберите более быструю модель."
        if isinstance(exc, openai.APIConnectionError):
            return f"Не удалось подключиться к {s.base_url}: {exc}"
        if isinstance(exc, openai.APIStatusError):
            return f"Ошибка API ({exc.status_code}): {exc.message}"
        return f"Ошибка API: {exc}"
