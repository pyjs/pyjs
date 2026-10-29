import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classpath import read_jvm_class
from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    BENCHMARK_PRIMITIVE_CONTRACTS,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
    NARROWED_METHOD_CONTRACT,
    RECEIVER_DOMAIN_CONTRACTS,
    REPLACED_ATTRIBUTE_CONTRACT,
    REPLACED_RECEIVER_CONTRACTS,
)
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("contract", BENCHMARK_PRIMITIVE_CONTRACTS.values(), ids=BENCHMARK_PRIMITIVE_CONTRACTS)
def test_benchmark_primitive_contract(contract, tmp_path):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT], ids=["truth", "split", "pop"])
def test_client_data_contract(contract, tmp_path):
    assert_matches_python(contract.source, tmp_path)


def test_awaited_values_preserve_instance_attributes(tmp_path):
    assert_text_matches_python(AWAIT_ATTRIBUTE_SOURCE + '''
from pyjs.java import run_sync
def main() -> str:
    return run_sync(await_attributes())
''', tmp_path)


def test_narrowed_receivers_and_arguments_keep_their_refined_type(tmp_path):
    assert_matches_python(NARROWED_METHOD_CONTRACT.source, tmp_path)


def test_replaced_attributes_do_not_keep_stale_refinements(tmp_path):
    assert_matches_python(REPLACED_ATTRIBUTE_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("contract", REPLACED_RECEIVER_CONTRACTS.values(), ids=REPLACED_RECEIVER_CONTRACTS)
def test_replaced_receivers_keep_base_declarations_reachable(contract, tmp_path):
    # Each consumer compiles alone: another base call must not retain its body.
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("contract", RECEIVER_DOMAIN_CONTRACTS.values(), ids=RECEIVER_DOMAIN_CONTRACTS)
def test_virtual_bindings_use_the_stored_receiver_domain(contract, tmp_path):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("case", ["default", "keyword"])
def test_virtual_binding_checks_still_include_siblings_inside_the_stored_domain(case):
    source = RECEIVER_DOMAIN_CONTRACTS[case].source
    source = source.replace("class Sibling(Root):", "class Sibling(Middle):")
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(source, filename="domains.py")
    assert str(caught.value) == (
        "JVM virtual call to value has incompatible keyword or default binding "
        "in override Sibling.value at line 33 while compiling domains.guarded"
    )


@pytest.mark.parametrize(("case", "retained", "omitted"), [
    ("local_method", "value", "amount"),
    ("local_property", "amount", "value"),
])
def test_receiver_reachability_retains_only_the_called_base_member(case, retained, omitted):
    compilation = transpile_jvm(REPLACED_RECEIVER_CONTRACTS[case].source)
    base = read_jvm_class(compilation.classes["PyjsProgram$StoredBase"])
    methods = {method.name for method in base.methods}
    assert retained in methods
    assert omitted not in methods


@pytest.mark.parametrize(("base", "child", "arguments"), [
    ("first: int = 1", "first: int = 2", ""),
    ("first: int, second: int", "second: int, first: int", "first=1, second=2"),
])
def test_replaced_receiver_cannot_select_incompatible_override_bindings(base, child, arguments):
    with pytest.raises(JVMUnsupported, match=(
        "JVM virtual call to value has incompatible keyword or default "
        "binding in override Child.value"
    )):
        transpile_jvm(f'''
class Base:
    def value(self, {base}) -> int:
        return 4
class Child(Base):
    def value(self, {child}) -> int:
        return 7
class Holder:
    def __init__(self, item: Base):
        self.item = item
    def reset(self) -> None:
        self.item = Base()
def main() -> int:
    holder = Holder(Child())
    item: Base = Base()
    if isinstance(holder.item, Child):
        holder.reset()
        item = holder.item
        return item.value({arguments})
    return 0
''')
