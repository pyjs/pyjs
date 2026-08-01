from pyjs.server import serve

from .calculator import render, save_result

serve(
    "pyjs_examples.calculator.calculator",
    render=render,
    routes={("POST", "/api/calculator/result"): save_result},
)
