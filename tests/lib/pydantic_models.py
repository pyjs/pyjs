from pydantic import BaseModel

from pyjs import js


@js
class ExternalLabel(BaseModel):
    name: str
