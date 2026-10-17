from typing import Literal, TypedDict


class InvalidationPayload(TypedDict):
    sequence: int
    topics: list[str]
    type: Literal["invalidate", "resync"]


class StreamEventPayload[T](TypedDict):
    scope: str
    sequence: int
    type: Literal["event"]
    value: T


class StreamResyncPayload(TypedDict):
    scope: str
    sequence: int
    type: Literal["resync"]
    value: None
