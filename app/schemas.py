"""Модели входных данных, ответа модели и итоговой карточки."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Пометка для характеристик, которых нет во входных данных
MISSING = "данных нет"


def clean_text(value: Any) -> str | None:
    """Приводит значение к строке без лишних пробелов; пустое значение → None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


# ----------------------------------------------------------------------------
# Входные данные
# ----------------------------------------------------------------------------
class ProductInput(BaseModel):
    """Данные о товаре, которые присылает контент-менеджер."""

    name: str = Field(..., description="Название товара")
    manufacturer: str | None = Field(None, description="Производитель")
    specs: dict[str, Any] = Field(default_factory=dict, description="Характеристики: название → значение")
    description: str | None = Field(None, description="Описание или фрагмент технического паспорта")

    @field_validator("name", mode="before")
    @classmethod
    def _name_required(cls, value: Any) -> str:
        text = clean_text(value)
        if text is None:
            raise ValueError("название товара (name) обязательно и не может быть пустым")
        return text

    @field_validator("manufacturer", "description", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        return clean_text(value)

    @field_validator("specs", mode="before")
    @classmethod
    def _specs_object(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError('specs должен быть объектом вида {"характеристика": "значение"}')
        return value

    @property
    def filled_specs(self) -> dict[str, str]:
        """Характеристики с непустыми значениями."""
        result: dict[str, str] = {}
        for key, value in self.specs.items():
            k, v = clean_text(key), clean_text(value)
            if k and v is not None:
                result[k] = v
        return result

    @property
    def empty_spec_keys(self) -> list[str]:
        """Характеристики, переданные без значения, — их надо запросить у поставщика."""
        return [k for key, value in self.specs.items() if (k := clean_text(key)) and clean_text(value) is None]

    def fact_text(self) -> str:
        """Все факты о товаре одной строкой — база для проверки ответа модели."""
        parts = [self.name, self.manufacturer or ""]
        for key, value in self.filled_specs.items():
            parts.append(f"{key}: {value}")
        parts.append(self.description or "")
        return "\n".join(p for p in parts if p)

    def to_prompt_json(self) -> dict[str, Any]:
        """Представление для промпта: пустые значения показываем как null."""
        specs = {}
        for key, value in self.specs.items():
            k = clean_text(key)
            if k:
                specs[k] = clean_text(value)
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "specs": specs,
            "description": self.description,
        }


# ----------------------------------------------------------------------------
# Ответ модели (черновик без служебных полей)
# ----------------------------------------------------------------------------
class CharacteristicDraft(BaseModel):
    name: str = ""
    value: str = ""

    @field_validator("name", "value", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value) or ""


class CommercialBlock(BaseModel):
    for_whom: str = Field("", description="Кому подходит прибор")
    tasks: list[str] = Field(default_factory=list, description="Какие задачи решает")

    @field_validator("for_whom", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value) or ""

    @field_validator("tasks", mode="before")
    @classmethod
    def _list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [t for item in value if (t := clean_text(item))]


class MissingField(BaseModel):
    field: str
    comment: str = ""

    @field_validator("field", "comment", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value) or ""


class CardDraft(BaseModel):
    """Структура, которую обязана вернуть модель."""

    seo_title: str = ""
    seo_description: str = ""
    characteristics: list[CharacteristicDraft] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    commercial_block: CommercialBlock = Field(default_factory=CommercialBlock)
    missing_fields: list[MissingField] = Field(default_factory=list)

    @field_validator("seo_title", "seo_description", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value) or ""

    @field_validator("search_queries", mode="before")
    @classmethod
    def _queries(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [t for item in value if (t := clean_text(item))]


# ----------------------------------------------------------------------------
# Итоговая карточка
# ----------------------------------------------------------------------------
class ProductRef(BaseModel):
    name: str
    manufacturer: str | None


class Characteristic(BaseModel):
    name: str
    value: str
    status: Literal["ok", "missing"] = Field(description="ok — значение из входных данных, missing — данных нет")


class Quality(BaseModel):
    seo_title_length: int
    seo_description_length: int
    attempts: int = Field(description="Сколько обращений к модели понадобилось")
    warnings: list[str] = Field(default_factory=list, description="Что контент-менеджеру стоит проверить вручную")


class Meta(BaseModel):
    model: str
    generated_at: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ProductCard(BaseModel):
    """Черновик карточки товара — результат работы сервиса."""

    product: ProductRef
    seo_title: str
    seo_description: str
    characteristics: list[Characteristic]
    search_queries: list[str]
    commercial_block: CommercialBlock
    missing_fields: list[MissingField]
    quality: Quality
    meta: Meta
