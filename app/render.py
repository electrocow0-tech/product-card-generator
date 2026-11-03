"""Представление карточки в Markdown — удобно копировать контент-менеджеру."""
from __future__ import annotations

import json

from .schemas import MISSING, ProductCard
from .validation import DESC_MAX, DESC_MIN, TITLE_MAX


def to_json(card: ProductCard) -> str:
    return json.dumps(card.model_dump(), ensure_ascii=False, indent=2)


def to_markdown(card: ProductCard) -> str:
    q = card.quality
    lines: list[str] = [f"# Черновик карточки: {card.product.name}", ""]
    lines.append(f"Производитель: {card.product.manufacturer or MISSING}")
    lines.append("")

    title_flag = "" if q.seo_title_length <= TITLE_MAX else " ⚠ превышен лимит"
    lines += [f"## SEO-заголовок ({q.seo_title_length}/{TITLE_MAX}){title_flag}", "", card.seo_title, ""]

    desc_flag = "" if DESC_MIN <= q.seo_description_length <= DESC_MAX else f" ⚠ нужно {DESC_MIN}–{DESC_MAX}"
    lines += [f"## SEO-описание ({q.seo_description_length} символов){desc_flag}", "", card.seo_description, ""]

    lines += ["## Характеристики", "", "| Характеристика | Значение |", "|---|---|"]
    for c in card.characteristics:
        value = c.value if c.status == "ok" else f"{MISSING} ⚠"
        lines.append(f"| {c.name} | {value} |")
    lines.append("")

    lines += ["## Поисковые запросы", ""]
    lines += [f"- {query}" for query in card.search_queries]
    lines.append("")

    lines += ["## Коммерческий блок (для менеджера)", "", f"**Кому подходит:** {card.commercial_block.for_whom}", ""]
    lines.append("**Какие задачи решает:**")
    lines += [f"- {task}" for task in card.commercial_block.tasks]
    lines.append("")

    if card.missing_fields:
        lines += ["## Требует уточнения", ""]
        lines += [f"- **{m.field}** — {m.comment}" if m.comment else f"- **{m.field}**" for m in card.missing_fields]
        lines.append("")

    lines += ["## Контроль качества", "", f"- Обращений к модели: {q.attempts}"]
    if q.warnings:
        lines.append("- Предупреждения (проверьте вручную):")
        lines += [f"  - {w}" for w in q.warnings]
    else:
        lines.append("- Автоматическая проверка пройдена: все значения характеристик найдены во входных данных")
    lines.append("")
    lines.append(f"_Модель: {card.meta.model}, сгенерировано {card.meta.generated_at}_")
    return "\n".join(lines) + "\n"
