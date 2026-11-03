from app.schemas import CardDraft, ProductInput
from app.validation import extract_numbers, finalize_characteristics, normalize, validate_draft
from tests.conftest import good_draft


def test_normalize_unifies_dashes_commas_and_spaces():
    assert normalize("0 – 1,6 МПа") == normalize("0-1.6 МПа") == "0-1.6 мпа"
    assert normalize("G1 / 2") == "g1/2"
    assert normalize("0…120 °C") == normalize("0 ... 120 °C")


def test_extract_numbers_canonical_form():
    assert extract_numbers("DM 02, 0–1,6 МПа, 1,50; 100 мм") == {"2", "0", "1.6", "1.5", "100"}


def test_good_draft_has_no_violations(manometer):
    assert validate_draft(CardDraft.model_validate(good_draft()), manometer) == []


def test_invented_characteristic_value_is_violation(manometer):
    draft = good_draft()
    draft["characteristics"][1] = {"name": "класс точности", "value": "1,0"}
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    assert any(v.kind == "characteristic" and "класс точности" in v.message for v in violations)


def test_converted_value_is_violation(manometer):
    """Пересчёт единиц (МПа → бар) — тоже выдумка, значение должно быть дословным."""
    draft = good_draft()
    draft["characteristics"][0] = {"name": "диапазон измерений", "value": "0–16 бар"}
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    assert any(v.kind == "characteristic" for v in violations)
    assert any(v.kind == "coverage" and "диапазон измерений" in v.message for v in violations)


def test_number_not_in_input_is_violation(manometer):
    draft = good_draft(seo_title="Манометр DM 02, гарантия 2 года, IP54")
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    kinds = {v.kind for v in violations}
    assert "number" in kinds  # 54 и «2 года» нет во входных данных
    assert "claim" in kinds  # гарантия и IP
    assert any("гарантия" in v.message for v in violations)
    assert any("IP" in v.message for v in violations)


def test_claim_present_in_input_is_allowed():
    product = ProductInput(name="Датчик", specs={"степень защиты": "IP65"})
    draft = good_draft(
        seo_title="Датчик IP65",
        seo_description=("Датчик со степенью защиты IP65 предназначен для измерения давления в системах. " * 12)[:900],
        characteristics=[{"name": "степень защиты", "value": "IP65"}],
        search_queries=["датчик ip65", "датчик", "датчик давления"],
    )
    violations = validate_draft(CardDraft.model_validate(draft), product)
    assert not [v for v in violations if v.kind in {"claim", "number", "characteristic", "coverage"}]


def test_length_limits(manometer):
    draft = good_draft(seo_title="М" * 71, seo_description="короткое описание", search_queries=["один"])
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    messages = " | ".join(v.message for v in violations if v.kind == "length")
    assert "seo_title" in messages and "seo_description" in messages and "search_queries" in messages


def test_missing_marker_variants_are_accepted(manometer):
    draft = good_draft()
    draft["characteristics"] += [
        {"name": "питание", "value": "нет данных"},
        {"name": "интерфейс", "value": "Данные нет"},
        {"name": "материал", "value": "н/д"},
        {"name": "масса", "value": "-"},
        {"name": "питание 2", "value": "данных нет (уточнить у поставщика)"},
    ]
    assert validate_draft(CardDraft.model_validate(draft), manometer) == []


def test_too_many_missing_rows_is_violation(manometer):
    draft = good_draft()
    draft["characteristics"] += [{"name": f"параметр {i}", "value": "данных нет"} for i in range(7)]
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    assert any(v.kind == "length" and "строк" in v.message for v in violations)


def test_marketing_claims_are_violation(manometer):
    draft = good_draft()
    draft["commercial_block"]["tasks"] = ["надёжный и долговечный контроль давления"]
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    assert any(v.kind == "claim" and "оценочные" in v.message for v in violations)


def test_finalize_replaces_unverified_values(manometer):
    draft = CardDraft.model_validate(good_draft())
    draft.characteristics[1].value = "1,0"  # модель «уточнила» класс точности
    draft.characteristics.append(draft.characteristics[0].model_copy(update={"name": "масса", "value": "0,5 кг"}))
    violations = validate_draft(draft, manometer)
    items, warnings = finalize_characteristics(draft.characteristics, manometer, violations)
    by_name = {c.name: c for c in items}
    assert by_name["класс точности"].value == "1,5" and by_name["класс точности"].status == "ok"
    assert by_name["масса"].value == "данных нет" and by_name["масса"].status == "missing"
    assert len(warnings) == 2


def test_finalize_adds_skipped_and_empty_specs():
    product = ProductInput(name="Термометр", specs={"диапазон": "0…120 °C", "класс точности": ""})
    draft = CardDraft.model_validate(good_draft(characteristics=[{"name": "диаметр", "value": "данных нет"}]))
    items, warnings = finalize_characteristics(draft.characteristics, product, validate_draft(draft, product))
    names = {c.name: c for c in items}
    assert names["диапазон"].value == "0…120 °C" and names["диапазон"].status == "ok"
    assert names["класс точности"].status == "missing"
    assert any("пропустила" in w for w in warnings)


def test_manufacturer_spelling_must_match_input():
    product = ProductInput(name="Датчик ПД100", manufacturer="ОВЕН", specs={"диапазон": "0…1 МПа"})
    draft = good_draft(
        seo_title="Датчик ПД100 ОВен 0…1 МПа",
        seo_description=("Датчик ПД100 производства ОВЕН измеряет давление в диапазоне 0…1 МПа. " * 14)[:900],
        characteristics=[{"name": "диапазон", "value": "0…1 МПа"}],
        search_queries=["датчик пд100", "овен датчик давления", "датчик 0…1 МПа"],
    )
    violations = validate_draft(CardDraft.model_validate(draft), product)
    spelling = [v for v in violations if "производителя" in v.message]
    assert len(spelling) == 1 and spelling[0].message.startswith("seo_title")
    assert spelling[0].summary == spelling[0].message  # в этом сообщении нет части «— что сделать»


def test_violation_summary_strips_instruction(manometer):
    draft = good_draft(seo_title="Манометр DM 02, гарантия 3 года")
    violations = validate_draft(CardDraft.model_validate(draft), manometer)
    number = next(v for v in violations if v.kind == "number")
    assert number.summary == "seo_title: встречаются числа, которых нет во входных данных: 3"
