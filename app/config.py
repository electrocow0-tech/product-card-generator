"""Настройки сервиса: читаются из переменных окружения и файла .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


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


def _env(name: str, default: str = "") -> str:
    """Переменная окружения; пустая строка считается незаданной."""
    return os.getenv(name, "").strip() or default


def load_env_files() -> None:
    """Читает настройки из файлов (переменные окружения имеют приоритет над файлами).

    Порядок: сначала `env/*.env` в корне проекта (удобно держать несколько конфигураций),
    затем `.env`. Что загружено раньше, не перезаписывается.
    """
    env_dir = ROOT / "env"
    if env_dir.is_dir():
        for path in sorted(env_dir.glob("*.env")):
            load_dotenv(path, override=False)
    load_dotenv(ROOT / ".env", override=False)


def load_settings() -> Settings:
    """Собирает настройки. API-ключ берётся только из окружения или env-файлов — в коде его нет."""
    load_env_files()
    api_key = _env("LLM_API_KEY")
    if not api_key:
        raise ConfigError(
            "Не задан LLM_API_KEY. Скопируйте .env.example в .env (или в env/local.env) и укажите ключ API, "
            "либо экспортируйте переменную окружения."
        )
    try:
        return Settings(
            base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=api_key,
            model=_env("LLM_MODEL", "gpt-4.1-mini"),
            temperature=float(_env("LLM_TEMPERATURE", "0.2")),
            timeout=float(_env("LLM_TIMEOUT", "60")),
            max_attempts=max(1, int(_env("LLM_MAX_ATTEMPTS", "3"))),
            json_mode=_env("LLM_JSON_MODE", "1").lower() not in {"0", "false", "no"},
        )
    except ValueError as exc:
        raise ConfigError(f"Некорректное значение настройки: {exc}") from exc
