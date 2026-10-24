from typing import Literal

from pydantic import BaseModel, ConfigDict


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    count: int = 0


class ChildItem(Item):
    count: int = 5
    detail: str = "child"


class Page(BaseModel):
    items: list[Item]
    cursor: int | None = None
    scores: dict[str, float | None]
    mode: Literal["grid", "list"] = "grid"
    enabled: bool = False


class OptionalField(BaseModel):
    value: int | None


class Empty(BaseModel):
    pass
