import pytest

from pyjs.testing.helpers import at


@pytest.mark.parametrize("statement", ["if", "while"])
def test_branch_conditions_lower_truth_at_each_operand(statement):
    at(f'''
        def main(values: list[int], enabled: bool) -> int:
            {statement} values and enabled:
                return 1
            return 0
    ''', f'''
        def main(values: list__int, enabled: bool) -> int:
            {statement} values.[list__int]__bool__!() and enabled:
                return 1
            return 0
    ''', f'''
        export function main(values, enabled) {{
            {statement} (values.length && enabled) {{
                return 1;
            }}
            return 0;
        }}
    ''')


def test_conditional_expression_guard_keeps_operand_truth():
    at('''
        def main(values: list[int], enabled: bool) -> int:
            return 1 if values and enabled else 0
    ''', '''
        def main(values: list__int, enabled: bool) -> int:
            return 1 if values.[list__int]__bool__!() and enabled else 0
    ''', '''
        export function main(values, enabled) {
            return values.length && enabled ? 1 : 0;
        }
    ''')
