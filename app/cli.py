"""Командный интерфейс.

    python -m app.cli examples/input/manometer.json            # Markdown в stdout
    python -m app.cli product.json --format json               # JSON в stdout
    python -m app.cli examples/input/*.json --out-dir out/     # <имя>.json и <имя>.md в папку
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import ConfigError, load_settings
from .llm import LLMClient, LLMError
from .render import to_json, to_markdown
from .schemas import ProductInput
from .service import GenerationError, generate_card


class InputError(Exception):
    """Проблема с входным файлом: не читается, не JSON, не та структура."""


def format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'input'}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()
    )


def load_product(path: Path) -> ProductInput:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputError(f"не удалось прочитать файл {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: некорректный JSON — {exc.msg} (строка {exc.lineno}, позиция {exc.colno})") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path}: ожидается JSON-объект с полями name, manufacturer, specs, description")
    try:
        return ProductInput.model_validate(data)
    except ValidationError as exc:
        raise InputError(f"{path}: {format_validation_error(exc)}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Черновик карточки товара по JSON-описанию прибора"
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="JSON-файлы с данными о товаре")
    parser.add_argument("--format", choices=["md", "json"], default="md", help="формат вывода в stdout")
    parser.add_argument("--out-dir", type=Path, help="сохранить результат в папку (<имя>.json и <имя>.md)")
    parser.add_argument("-v", "--verbose", action="store_true", help="показывать ход генерации")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 2
    llm = LLMClient(settings)

    exit_code = 0
    for path in args.inputs:
        try:
            product = load_product(path)
            card = generate_card(product, llm, settings.max_attempts)
        except InputError as exc:
            print(f"Ошибка входных данных: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        except (LLMError, GenerationError) as exc:
            print(f"Ошибка генерации ({path}): {exc}", file=sys.stderr)
            exit_code = 1
            continue

        if args.out_dir:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            (args.out_dir / f"{path.stem}.json").write_text(to_json(card) + "\n", encoding="utf-8")
            (args.out_dir / f"{path.stem}.md").write_text(to_markdown(card), encoding="utf-8")
            print(
                f"{path.name}: готово за {card.quality.attempts} обр., "
                f"предупреждений {len(card.quality.warnings)} → {args.out_dir / path.stem}.{{json,md}}",
                file=sys.stderr,
            )
        else:
            print(to_markdown(card) if args.format == "md" else to_json(card))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
