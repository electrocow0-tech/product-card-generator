import pytest

from app.schemas import ProductInput
from app.service import GenerationError, generate_card, parse_draft
from tests.conftest import FakeLLM, good_draft


def test_parse_draft_tolerates_markdown_fence():
    draft = parse_draft('```json\n{"seo_title": "x", "seo_description": "y"}\n```')
    assert draft.seo_title == "x"


def test_first_attempt_accepted(manometer):
    llm = FakeLLM(good_draft())
    card = generate_card(manometer, llm, max_attempts=3)
    assert card.quality.attempts == 1
    assert card.quality.warnings == []
    assert [c.status for c in card.characteristics] == ["ok"] * 4 + ["missing"]
    assert card.missing_fields[0].field == "степень защиты"
    assert card.meta.model == "fake-model" and card.meta.prompt_tokens == 10


def test_retry_with_feedback_then_success(manometer):
    bad = good_draft(seo_title="Манометр DM 02 с гарантией 3 года")
    llm = FakeLLM(bad, good_draft())
    card = generate_card(manometer, llm, max_attempts=3)
    assert card.quality.attempts == 2
    assert card.quality.warnings == []
    # Во второй запрос ушёл предыдущий ответ и список замечаний
    second_call = llm.calls[1]
    assert second_call[-2]["role"] == "assistant"
    assert "гарантия" in second_call[-1]["content"] and "3" in second_call[-1]["content"]


def test_invalid_json_then_success(manometer):
    llm = FakeLLM("это не JSON", good_draft())
    card = generate_card(manometer, llm, max_attempts=2)
    assert card.quality.attempts == 2
    assert "не является корректным JSON" in llm.calls[1][-1]["content"]


def test_persistent_violation_is_fixed_and_reported(manometer):
    bad = good_draft()
    bad["characteristics"][1] = {"name": "класс точности", "value": "1,0"}
    llm = FakeLLM(bad)  # модель упорно отвечает одно и то же
    card = generate_card(manometer, llm, max_attempts=2)
    assert card.quality.attempts == 2
    cls = next(c for c in card.characteristics if c.name == "класс точности")
    assert cls.value == "1,5"
    assert any("заменено" in w for w in card.quality.warnings)


def test_never_valid_json_raises(manometer):
    llm = FakeLLM("{оборванный json")
    with pytest.raises(GenerationError):
        generate_card(manometer, llm, max_attempts=2)


def test_missing_manufacturer_and_description_are_reported():
    product = ProductInput(name="Термометр ТБ-63", specs={"диапазон": "0…120 °C", "класс точности": None})
    draft = good_draft(
        seo_title="Термометр ТБ-63, 0…120 °C",
        characteristics=[{"name": "диапазон", "value": "0…120 °C"}],
        search_queries=["термометр тб-63", "термометр 0…120 °C", "биметаллический термометр"],
        missing_fields=[],
    )
    card = generate_card(product, FakeLLM(draft), max_attempts=1)
    fields = [m.field for m in card.missing_fields]
    assert fields[:2] == ["производитель", "описание / паспорт"]
    assert "класс точности" in fields
    assert card.product.manufacturer is None
