"""Общие фикстуры: товар из задания и подменный LLM-клиент без сети."""
from __future__ import annotations

import json

import pytest

from app.llm import Usage
from app.schemas import ProductInput


@pytest.fixture
def manometer() -> ProductInput:
    return ProductInput(
        name="Манометр показывающий DM 02",
        manufacturer="Манотомь",
        specs={
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
            "присоединение": "G1/2",
            "диаметр корпуса": "100 мм",
        },
        description="Прибор предназначен для измерения избыточного давления неагрессивных сред.",
    )


def good_draft(**overrides) -> dict:
    """Черновик, который проходит все проверки для фикстуры manometer."""
    desc = (
        "Манометр показывающий DM 02 производства Манотомь предназначен для измерения избыточного давления "
        "неагрессивных сред. Диапазон измерений 0–1,6 МПа, класс точности 1,5, присоединение G1/2, "
        "диаметр корпуса 100 мм. "
    )
    draft = {
        "seo_title": "Манометр DM 02 Манотомь, 0–1,6 МПа, класс 1,5",
        "seo_description": (desc * 5)[:900],
        "characteristics": [
            {"name": "диапазон измерений", "value": "0–1,6 МПа"},
            {"name": "класс точности", "value": "1,5"},
            {"name": "присоединение", "value": "G1/2"},
            {"name": "диаметр корпуса", "value": "100 мм"},
            {"name": "степень защиты", "value": "данных нет"},
        ],
        "search_queries": ["манометр DM 02", "манометр Манотомь 100 мм", "манометр 1,6 МПа"],
        "commercial_block": {"for_whom": "Службам КИПиА и снабжению.", "tasks": ["контроль давления"]},
        "missing_fields": [{"field": "степень защиты", "comment": "нужна для фильтра"}],
    }
    draft.update(overrides)
    return draft


class FakeLLM:
    """Возвращает заранее заданные ответы по очереди и запоминает полученные сообщения."""

    model = "fake-model"

    def __init__(self, *responses: str | dict):
        self.responses = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in responses]
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages):
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index], Usage(prompt_tokens=10, completion_tokens=5)
