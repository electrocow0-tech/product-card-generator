"""Настройки сервиса: читаются из переменных окружения и файла .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(Exception):
    """Отсутствует или некорректна обязательная настройка."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    timeout: float = 60.0
    max_attempts: int = 3
    json_mode: bool = True


def load_settings() -> Settings:
    """Собирает настройки. API-ключ берётся только из окружения — в коде его нет."""
    load_dotenv()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "Не задан LLM_API_KEY. Скопируйте .env.example в .env и укажите ключ API "
            "(или экспортируйте переменную окружения)."
        )
    try:
        return Settings(
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
            api_key=api_key,
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini").strip(),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
            max_attempts=max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "3"))),
            json_mode=os.getenv("LLM_JSON_MODE", "1").strip() not in {"0", "false", "no"},
        )
    except ValueError as exc:
        raise ConfigError(f"Некорректное значение настройки: {exc}") from exc
