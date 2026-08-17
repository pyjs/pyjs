from typing import Literal, TypedDict


class InvalidationPayload(TypedDict):
    sequence: int
    topics: list[str]
    type: Literal["invalidate", "resync"]
