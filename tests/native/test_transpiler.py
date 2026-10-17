import errno
import os
from dataclasses import replace
from pathlib import Path

import pytest

from pyjs import js
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.decorators import (
    ParameterLifetime,
    get_native_decoration,
    js_metadata,
    native_operation,
    parameter_lifetimes,
)
from pyjs.native import Document, _declaration, div
from pyjs.native.analysis import NATIVE_ENVIRONMENT

SOURCE = Path(__file__).with_name("settings_source.py")
EXPECTED_IR = SOURCE.with_suffix(".ir")


def test_native_declarations_expose_validated_lifetime_contracts():
    assert parameter_lifetimes(Document.render) == {
        "self": ParameterLifetime.BORROWED,
        "root": ParameterLifetime.BORROWED,
    }
    assert parameter_lifetimes(div) == {
        "document": ParameterLifetime.BORROWED,
        "arguments": ParameterLifetime.BORROWED,
    }

    def invalid_name(value):
        return value

    with pytest.raises(TypeError, match="parameters do not exist: typo"):
        _declaration(typo=ParameterLifetime.BORROWED)(invalid_name)

    def invalid_contract(value):
        return value

    with pytest.raises(TypeError, match="invalid parameter lifetime contracts: value"):
        _declaration(value="borrowed")(invalid_contract)


def test_native_document_descriptor_fallback_writes_utf8_and_reports_errors():
    document = Document()
    root = div(document, "café & ready")
    reader, writer = os.pipe()
    try:
        assert document.write(root, writer) == 0
    finally:
        os.close(writer)
    try:
        output = os.read(reader, 4096)
    finally:
        os.close(reader)

    assert output == b"<div>caf\xc3\xa9 &amp; ready</div>"
    assert document.write(root, -1) == errno.EBADF


def test_javascript_client_substitution_preserves_native_contracts():
    @native_operation("example", value=ParameterLifetime.BORROWED)
    @js
    def example(value: str) -> str:
        return value

    @example.client
    def example(value: str) -> str:
        return value + " client"

    client = js_metadata(example, "client")

    assert get_native_decoration(client) == get_native_decoration(example)
    assert parameter_lifetimes(client) == parameter_lifetimes(example)


def test_native_operation_metadata_does_not_reserve_parameter_names():
    @native_operation(
        "example",
        operation=ParameterLifetime.BORROWED,
        constant=ParameterLifetime.BORROWED,
    )
    def example(operation: str, constant: str) -> str:
        return operation + constant

    @native_operation("element", "section", arguments=ParameterLifetime.BORROWED)
    def element(*arguments: object):
        return arguments

    assert parameter_lifetimes(example) == {
        "operation": ParameterLifetime.BORROWED,
        "constant": ParameterLifetime.BORROWED,
    }
    assert get_native_decoration(element).constant == "section"


@pytest.mark.parametrize(
    ("contract", "boundary"),
    [
        (ParameterLifetime.RETURNED, LifetimeBoundary.CALLER),
        (ParameterLifetime.EXTERNAL, LifetimeBoundary.EXTERNAL),
    ],
)
def test_ir_consumes_native_lifetime_contracts(
    monkeypatch,
    contract,
    boundary,
):
    monkeypatch.setattr(
        div,
        "__pyjs_analysis__",
        replace(div.__pyjs_analysis__, parameter_lifetimes={"document": contract}),
    )

    with analyze_source(
        """
        from pyjs.native import Document, Element, div

        def main() -> Element:
            document = Document()
            return div(document)
        """,
        wrap=False,
        environment=NATIVE_ENVIRONMENT,
    ) as analysis:
        allocation = analysis.entry_point.ir.lifetime.allocations[0]

    assert allocation.boundary is boundary


def test_native_analysis_matches_complete_ir_golden():
    with analyze_source(
        SOURCE.read_text(),
        filename=str(SOURCE),
        module_name="native_settings_ir",
        wrap=False,
        environment=NATIVE_ENVIRONMENT,
    ) as analysis:
        assert analysis.types == EXPECTED_IR.read_text().rstrip("\n")
