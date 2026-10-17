"""Compile typed Python into readable, tree-shaken JavaScript."""

__version__ = (0, 4, 0)

from .decorators import *
from .numeric import (
    StaticArray,
    float32,
    float64,
    int8,
    int16,
    int32,
    int64,
    uint8,
    uint16,
    uint32,
)
from .state import effect, state

__all__ = [
    "StaticArray",
    "effect",
    "float32",
    "float64",
    "int8",
    "int16",
    "int32",
    "int64",
    "js",
    "jvm",
    "llvm",
    "state",
    "uint8",
    "uint16",
    "uint32",
    "wgsl",
]
