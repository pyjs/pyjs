"""JSON interchange between Python dictionaries and JavaScript host objects."""
import json

from pyjs import js


@js.inline("JSON.stringify({value}, (_key, item) => item instanceof Map ? Object.fromEntries(item) : item)")
def dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


@js.inline("JSON.parse({value}, (_key, item) => item !== null && typeof item === 'object' && !Array.isArray(item) ? new Map(Object.entries(item)) : item)")
def loads(value: str) -> object:
    return json.loads(value)
