"""Real host models: factories and validators must not run during compilation."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pyjs import int8
from pyjs.server import Page

calls = {"factory": 0, "validator": 0}


def labels() -> list[str]:
    calls["factory"] += 1
    return ["default"]


class Setting(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    count: int = Field(default=1, ge=0, alias="size")
    labels: list[str] = Field(default_factory=labels)
    optional: str | None = None

    @field_validator("name")
    @classmethod
    def uppercase(cls, value: str) -> str:
        calls["validator"] += 1
        return value.upper()


class ExtendedSetting(Setting):
    enabled: bool = True


class Catalog(BaseModel):
    settings: list[Setting]
    featured: Setting | None = None


class NumericSetting(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    count: int8


class CustomTruth(BaseModel):
    name: str

    def __bool__(self) -> bool:
        return False


class CatalogPage(BaseModel):
    page: Page[Setting]
    status: Literal["ready", "empty"] = "ready"


type TextPage = Page[str]


@dataclass
class PageRecord:
    page: TextPage


@dataclass
class InheritedPageRecord(PageRecord):
    count: int = 1


class UnionPages(BaseModel):
    pages: list[Page[str]] | int


class WidgetRow(BaseModel):
    name: str
    description: str
    changed: bool
