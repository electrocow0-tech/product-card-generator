"""Проверка черновика карточки: факты только из входных данных, полнота, длины.

Модель может ошибиться, поэтому после генерации черновик проверяется кодом:
- каждое значение характеристики должно дословно встречаться во входных данных либо быть «данных нет»;
- все характеристики из входных данных должны попасть в карточку;
- в текстах не должно быть чисел, которых нет во входных данных;
- не должно быть «рискованных» утверждений (ГОСТ, IP, гарантия, материалы…), если их нет во входных данных;
- ограничения на длину заголовка, описания и количество запросов.
Нарушения отправляются модели для исправления; если исправить не удалось — применяются
безопасные правки кодом, а контент-менеджер получает предупреждения.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .schemas import (
    MISSING,
    CardDraft,
    Characteristic,
    CharacteristicDraft,
    MissingField,
    ProductInput,
)

TITLE_MAX = 70
DESC_MIN, DESC_MAX = 800, 1200
QUERIES_MIN, QUERIES_MAX = 3, 5
TASKS_MAX = 5
MISSING_MAX = 6  # сколько строк «данных нет» модель может добавить от себя (из чек-листа)

ViolationKind = Literal["structure", "characteristic", "coverage", "number", "claim", "length"]


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    message: str  # формулировка для модели: «что не так — что сделать»
    index: int | None = None  # индекс характеристики, если нарушение относится к ней

    @property
    def summary(self) -> str:
        """Та же проблема без инструкции для модели — для предупреждения менеджеру."""
        return self.message.split(" — ", 1)[0]


# ----------------------------------------------------------------------------
# Нормализация текста
# ----------------------------------------------------------------------------
_TRANSLATE = str.maketrans({"–": "-", "—": "-", "−": "-", "…": "...", "ё": "е", "×": "x"})
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_AROUND_SIGNS_RE = re.compile(r"\s*([-/])\s*")
_DOTS_RE = re.compile(r"\s*\.\.\.\s*")
_WS_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def normalize(text: str) -> str:
    """Единый вид для сравнения: регистр, тире, десятичная запятая, пробелы вокруг знаков."""
    text = text.lower().translate(_TRANSLATE)
    text = _DECIMAL_COMMA_RE.sub(".", text)
    text = _DOTS_RE.sub("...", text)
    text = _AROUND_SIGNS_RE.sub(r"\1", text)
    return _WS_RE.sub(" ", text).strip()


def _canon_number(token: str) -> str:
    token = token.replace(",", ".")
    if "." in token:
        whole, frac = token.split(".", 1)
        frac = frac.rstrip("0")
        whole = whole.lstrip("0") or "0"
        return f"{whole}.{frac}" if frac else whole
    return token.lstrip("0") or "0"


def extract_numbers(text: str) -> set[str]:
    """Все числа в тексте в каноническом виде («1,50» → «1.5», «02» → «2»)."""
    return {_canon_number(m.group()) for m in _NUMBER_RE.finditer(text)}


# Утверждения, которые модели особенно любят дописывать. Если паттерн есть в ответе,
# но нет во входных данных, — это выдумка.
CLAIM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ГОСТ", re.compile(r"\bгост\b")),
    ("ТУ", re.compile(r"\bту\s*\d")),
    ("степень защиты IP", re.compile(r"\bip\s?\d{2}")),
    ("стандарт EN/ISO/DIN", re.compile(r"\b(en|iso|din)\s?\d")),
    ("Госреестр СИ", re.compile(r"госреестр|реестр[а-я]*\s+средств\s+измерений|реестр[а-я]*\s+си\b")),
    ("сертификация", re.compile(r"сертифи")),
    ("поверка", re.compile(r"поверк|поверочн")),
    ("гарантия / «гарантирует»", re.compile(r"гарант")),
    ("срок службы", re.compile(r"срок\s+службы|наработк")),
    ("взрывозащита", re.compile(r"взрывозащ|\batex\b|\bex\s?[di]\b")),
    ("материал", re.compile(r"нержавею|латун|бронз|сталь|алюмини|пластик|силикон|глицерин|титан")),
    ("виброустойчивость", re.compile(r"виброуст|вибрац")),
    ("кислородное исполнение", re.compile(r"кислород")),
]

# Оценочные эпитеты: не факты, а обещания, которых в данных нет
MARKETING_RE = re.compile(
    r"надежн|надёжн|долговечн|высокоточн|идеальн|лучш|превосходн|безупречн|премиальн|гарантирован|непревзойд"
    r"|прост(?:ой|ое|ая|ые|ым|ую|ота|оту|отой)?\b|проверенн|удобн|легк"
)


def _check_text_facts(field: str, text: str, input_numbers: set[str], input_norm: str) -> list[Violation]:
    """Числа и рискованные утверждения в тексте, которых нет во входных данных."""
    violations: list[Violation] = []
    extra_numbers = sorted(extract_numbers(text) - input_numbers)
    if extra_numbers:
        violations.append(
            Violation(
                "number",
                f"{field}: встречаются числа, которых нет во входных данных: {', '.join(extra_numbers)} "
                "— убери их или перефразируй без чисел",
            )
        )
    text_norm = normalize(text)
    for label, pattern in CLAIM_PATTERNS:
        if pattern.search(text_norm) and not pattern.search(input_norm):
            violations.append(
                Violation("claim", f"{field}: упоминание «{label}» отсутствует во входных данных — убери это утверждение")
            )
    found = {m.group() for m in MARKETING_RE.finditer(text_norm) if not re.search(m.group(), input_norm)}
    if found:
        violations.append(
            Violation(
                "claim",
                f"{field}: оценочные обещания ({', '.join(sorted(found))}…) не подтверждены данными — "
                "замени на факты или убери",
            )
        )
    return violations


_MISSING_RE = re.compile(
    r"^(данн\w*\s+нет|нет\s+данн\w*|н/д|n/a|null|none|-|не\s+указан\w*|отсутству\w*|не\s+предоставлен\w*|неизвестн\w*)(?!\w)"
)


def _check_manufacturer_spelling(field: str, text: str, manufacturer: str | None) -> Violation | None:
    """Название производителя должно быть написано как во входных данных («ОВЕН», а не «ОВен»)."""
    if not manufacturer or manufacturer in text or manufacturer.lower() not in text.lower():
        return None
    return Violation("claim", f"{field}: название производителя пиши точно как во входных данных: «{manufacturer}»")


def _is_missing(value: str) -> bool:
    """«данных нет» и его варианты: «нет данных», «данные нет», «н/д», пустая строка."""
    v = normalize(value)
    return v == "" or bool(_MISSING_RE.match(v))


# ----------------------------------------------------------------------------
# Проверка черновика
# ----------------------------------------------------------------------------
def validate_draft(draft: CardDraft, product: ProductInput) -> list[Violation]:
    """Возвращает список нарушений; пустой список — черновик принят."""
    violations: list[Violation] = []
    input_norm = normalize(product.fact_text())
    input_numbers = extract_numbers(product.fact_text())

    # Структура
    if not draft.seo_title:
        violations.append(Violation("structure", "seo_title пуст"))
    if not draft.seo_description:
        violations.append(Violation("structure", "seo_description пуст"))
    if not draft.characteristics:
        violations.append(Violation("structure", "список characteristics пуст"))
    if not draft.commercial_block.for_whom:
        violations.append(Violation("structure", "commercial_block.for_whom пуст"))
    if not draft.commercial_block.tasks:
        violations.append(Violation("structure", "commercial_block.tasks пуст"))

    # Характеристики: значение — дословно из входных данных либо «данных нет»
    for i, item in enumerate(draft.characteristics):
        if not item.name:
            violations.append(Violation("characteristic", f"характеристика №{i + 1} без названия", i))
            continue
        if _is_missing(item.value):
            continue
        if normalize(item.value) not in input_norm:
            violations.append(
                Violation(
                    "characteristic",
                    f"характеристика «{item.name}»: значение «{item.value}» не найдено во входных данных "
                    f"— скопируй значение дословно или укажи «{MISSING}»",
                    i,
                )
            )

    # Полнота: каждая характеристика из входных данных должна попасть в карточку
    present_values = [normalize(c.value) for c in draft.characteristics]
    for key, value in product.filled_specs.items():
        value_norm = normalize(value)
        if not any(value_norm in pv for pv in present_values):
            violations.append(
                Violation("coverage", f"характеристика «{key}: {value}» из входных данных не попала в characteristics")
            )

    # Тексты: числа и рискованные утверждения
    texts = [
        ("seo_title", draft.seo_title),
        ("seo_description", draft.seo_description),
        ("commercial_block.for_whom", draft.commercial_block.for_whom),
        ("commercial_block.tasks", " ".join(draft.commercial_block.tasks)),
        ("search_queries", " ".join(draft.search_queries)),
    ]
    for field, text in texts:
        if text:
            violations.extend(_check_text_facts(field, text, input_numbers, input_norm))
            if field != "search_queries":  # запросы обычно пишут строчными — регистр там не важен
                spelling = _check_manufacturer_spelling(field, text, product.manufacturer)
                if spelling:
                    violations.append(spelling)

    # Длины и количество
    title_len = len(draft.seo_title)
    if title_len > TITLE_MAX:
        violations.append(Violation("length", f"seo_title: {title_len} символов, максимум {TITLE_MAX} — сократи"))
    desc_len = len(draft.seo_description)
    if draft.seo_description and desc_len < DESC_MIN:
        violations.append(
            Violation(
                "length",
                f"seo_description: {desc_len} символов, нужно {DESC_MIN}–{DESC_MAX} — допиши ещё примерно "
                f"{DESC_MIN + 150 - desc_len} символов о назначении, характеристиках и применении, "
                "используя только факты из входных данных, ничего не удаляя",
            )
        )
    elif desc_len > DESC_MAX:
        violations.append(
            Violation(
                "length",
                f"seo_description: {desc_len} символов, максимум {DESC_MAX} — сократи примерно на "
                f"{desc_len - DESC_MAX + 150} символов за счёт общих фраз, факты сохрани",
            )
        )
    n_queries = len(draft.search_queries)
    if not QUERIES_MIN <= n_queries <= QUERIES_MAX:
        violations.append(
            Violation("length", f"search_queries: {n_queries} запросов, нужно от {QUERIES_MIN} до {QUERIES_MAX}")
        )
    if len(draft.commercial_block.tasks) > TASKS_MAX:
        violations.append(
            Violation("length", f"commercial_block.tasks: {len(draft.commercial_block.tasks)} пунктов, максимум {TASKS_MAX}")
        )
    n_missing = sum(1 for c in draft.characteristics if _is_missing(c.value))
    missing_limit = MISSING_MAX + len(product.empty_spec_keys)
    if n_missing > missing_limit:
        violations.append(
            Violation(
                "length",
                f"characteristics: {n_missing} строк «{MISSING}», оставь не более {missing_limit} — "
                "только самые важные для выбора прибора этого типа",
            )
        )
    return violations


# ----------------------------------------------------------------------------
# Безопасные правки, если модель так и не исправила ответ
# ----------------------------------------------------------------------------
def _match_spec_key(name: str, specs: dict[str, str]) -> str | None:
    """Ищет характеристику входных данных по названию (точное совпадение или вхождение)."""
    n = normalize(name)
    for key in specs:
        k = normalize(key)
        if n == k or k in n or n in k:
            return key
    return None


def finalize_characteristics(
    draft_items: list[CharacteristicDraft],
    product: ProductInput,
    violations: list[Violation],
) -> tuple[list[Characteristic], list[str]]:
    """Строит итоговый список характеристик, исправляя непроверяемые значения.

    Непроверяемое значение заменяется значением из входных данных (если характеристика
    найдена по названию) либо на «данных нет». Пропущенные характеристики добавляются.
    Возвращает список и предупреждения для контент-менеджера.
    """
    warnings: list[str] = []
    specs = product.filled_specs
    bad_indexes = {v.index for v in violations if v.kind == "characteristic" and v.index is not None}

    result: list[Characteristic] = []
    for i, item in enumerate(draft_items):
        name = item.name or f"характеристика {i + 1}"
        if _is_missing(item.value):
            result.append(Characteristic(name=name, value=MISSING, status="missing"))
            continue
        if i in bad_indexes:
            key = _match_spec_key(name, specs)
            if key is not None:
                warnings.append(
                    f"Характеристика «{name}»: модель написала «{item.value}», значение заменено "
                    f"на исходное «{specs[key]}»"
                )
                result.append(Characteristic(name=name, value=specs[key], status="ok"))
            else:
                warnings.append(
                    f"Характеристика «{name}»: значение «{item.value}» не подтверждено входными данными, "
                    f"заменено на «{MISSING}»"
                )
                result.append(Characteristic(name=name, value=MISSING, status="missing"))
            continue
        result.append(Characteristic(name=name, value=item.value, status="ok"))

    # Характеристики из входных данных, которых нет в карточке, добавляем как есть
    present_values = [normalize(c.value) for c in result]
    for key, value in specs.items():
        if not any(normalize(value) in pv for pv in present_values):
            result.append(Characteristic(name=key, value=value, status="ok"))
            warnings.append(f"Характеристика «{key}» добавлена из входных данных — модель её пропустила")

    # Характеристики, переданные без значения, обязательно показываем как «данных нет»
    present_names = [normalize(c.name) for c in result]
    for key in product.empty_spec_keys:
        if not any(normalize(key) in pn or pn in normalize(key) for pn in present_names):
            result.append(Characteristic(name=key, value=MISSING, status="missing"))
    return result, warnings


def finalize_missing_fields(
    draft_fields: list[MissingField], characteristics: list[Characteristic], product: ProductInput
) -> list[MissingField]:
    """Список «требует уточнения»: из ответа модели + все «данных нет» + пустые базовые поля."""
    result: list[MissingField] = []
    seen: set[str] = set()

    def add(field: str, comment: str) -> None:
        key = normalize(field)
        if key and key not in seen:
            seen.add(key)
            result.append(MissingField(field=field, comment=comment))

    if product.manufacturer is None:
        add("производитель", "не указан во входных данных — нужен для заголовка, фильтров и поисковых запросов")
    if product.description is None:
        add("описание / паспорт", "не передано — описание составлено только по названию и характеристикам")
    for item in draft_fields:
        add(item.field, item.comment)
    for c in characteristics:
        if c.status == "missing":
            add(c.name, "нет во входных данных — запросить у поставщика или взять из паспорта")
    return result
