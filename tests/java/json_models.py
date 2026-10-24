from typing import Literal

from pydantic import BaseModel, ConfigDict


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    count: int = 0


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
