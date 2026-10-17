from pyjs.testing.helpers import ad, at, diagnostic_text


def test_none_guard_narrows_a_union_with_multiple_concrete_members():
    at('''
        @js
        def describe(value: int | str | None) -> str:
            if value is None:
                return "absent"
            if isinstance(value, int):
                return str(value + 1)
            return value.upper()
        def main():
            describe(None)
            describe(4)
            describe("snow")
    ''', '''
        def describe(value: int | str | None) -> str:
            if value.[object]__is__!(None):
                return 'absent'
            if isinstance(value, int):
                return value.[int]__add__!(1).[int]__str__!()
            return value.[str]upper!()

        def main() -> None:
            describe(None)
            describe(4)
            describe('snow')
    ''', '''
        export function describe(value) {
            if (value == null) {
                return 'absent';
            }
            if (((value)=>typeof value==='boolean'||Number.isInteger(value))(value)) {
                return String(value + 1);
            }
            return value.toUpperCase();
        }

        export function main() {
            describe(null);
            describe(4);
            describe('snow');
        }
    ''')


def test_raise_value_error_with_message():
    at(
        """
        @js
        def validate(value: str):
            if value == "":
                raise ValueError("value is required")

        def main():
            validate("")
        """,
        """
        def validate(value: str) -> None:
            if value.[object]__eq__!(''):
                raise ValueError('value is required')

        def main() -> None:
            validate('')
        """,
        """
        export function validate(value) {
            if (value === '') {
                throw new RangeError('value is required');
            }
        }

        export function main() {
            validate('');
        }
        """,
    )


def test_basic_conditionals():
    at(
        """
        def main():
            a = 9
            if a == 9:
                print('a is 9')
            elif a:
                print('a has value')
            else:
                print('no value')
        """,
        """
        def main() -> None:
            a: int = 9
            if a.[int]__eq__!(9):
                print('a is 9')
            elif a.[int]__bool__!():
                print('a has value')
            else:
                print('no value')
        """,
        """
        export function main() {
            var a = 9;
            if (a == 9) {
                console.log('a is 9');
            } else if (a) {
                console.log('a has value');
            } else {
                console.log('no value');
            }
        }
        """
    )


def test_bare_except_and_finally():
    at(
        """
        def main():
            try:
                print("try")
            except:
                print("except")
            finally:
                print("finally")
        """,
        """
        def main() -> None:
            try:
                print('try')
            except:
                print('except')
            finally:
                print('finally')
        """,
        """
        export function main() {
            try {
                console.log('try');
            } catch (_error) {
                console.log('except');
            } finally {
                console.log('finally');
            }
        }
        """,
    )


def test_named_exception_and_finally():
    at(
        """
        def main():
            try:
                print("try")
            except Exception as error:
                print(str(error))
            finally:
                print("finally")
        """,
        """
        def main() -> None:
            try:
                print('try')
            except Exception as error:
                print(error.[Exception]__str__!())
            finally:
                print('finally')
        """,
        """
        export function main() {
            try {
                console.log('try');
            } catch (error) {
                console.log(error.message);
            } finally {
                console.log('finally');
            }
        }
        """,
    )


def test_successful_try_assignment_remains_available_after_finally():
    at(
        """
        async def main():
            try:
                result = 1
            finally:
                marker = False
            print(result)
        """,
        """
        async def main() -> None:
            try:
                result: int = 1
            finally:
                marker: bool = False
            print(result)
        """,
        """
        export async function main() {
            try {
                var result = 1;
            } finally {
                var marker = false;
            }
            console.log(result);
        }
        """,
    )


def test_reserved_exception_binding_is_escaped():
    at(
        """
        def main():
            try:
                raise ValueError("bad")
            except Exception as package:
                print(package)
        """,
        """
        def main() -> None:
            try:
                raise ValueError('bad')
            except Exception as package:
                print(package)
        """,
        """
        export function main() {
            try {
                throw new RangeError('bad');
            } catch ($$package) {
                console.log($$package);
            }
        }
        """,
    )


def test_custom_exception_subclasses_extend_and_construct_their_declared_type():
    at(
        """
        @js
        class ValidationError(Exception):
            pass

        def main():
            try:
                raise ValidationError("invalid")
            except Exception as error:
                print(isinstance(error, ValidationError))
                print(str(error))
        """,
        """
        class ValidationError(Exception):

        def main() -> None:
            try:
                raise ValidationError('invalid')
            except Exception as error:
                print(isinstance(error, ValidationError))
                print(error.[Exception]__str__!())
        """,
        """
        export class ValidationError extends Error {
        }

        export function main() {
            try {
                throw new ValidationError('invalid');
            } catch (error) {
                console.log(((error instanceof ValidationError) ? 'True' : 'False'));
                console.log(error.message);
            }
        }
        """,
    )


def test_exception_without_binding():
    at(
        """
        def main():
            try:
                print("try")
            except Exception:
                print("except")
        """,
        """
        def main() -> None:
            try:
                print('try')
            except Exception:
                print('except')
        """,
        """
        export function main() {
            try {
                console.log('try');
            } catch (_error) {
                console.log('except');
            }
        }
        """,
    )


def test_ordered_and_tuple_exception_handlers():
    at(
        """
        @js
        class ValidationError(ValueError):
            pass

        def main():
            try:
                raise TypeError("wrong")
            except ValidationError as error:
                print("validation")
            except (TypeError, ValueError) as error:
                print(error.message)
        """,
        """
        class ValidationError(ValueError):

        def main() -> None:
            try:
                raise TypeError('wrong')
            except ValidationError as error:
                print('validation')
            except (TypeError, ValueError) as error:
                print(error.message)
        """,
        """
        export class ValidationError extends RangeError {
        }

        export function main() {
            try {
                throw new TypeError('wrong');
            } catch ($error0) {
                if ($error0 instanceof ValidationError) {
                    let error = $error0;
                    console.log('validation');
                } else if ($error0 instanceof TypeError || $error0 instanceof RangeError) {
                    let error = $error0;
                    console.log(error.message);
                } else {
                    throw $error0;
                }
            }
        }
        """,
    )


def test_bare_raise_uses_the_innermost_caught_exception():
    at(
        """\
        @js
        class ValidationError(ValueError):
            pass

        def main():
            try:
                raise ValidationError("invalid")
            except ValidationError as error:
                print(str(error))
                raise
        """,
        """\
        class ValidationError(ValueError):

        def main() -> None:
            try:
                raise ValidationError('invalid')
            except ValidationError as error:
                print(error.[Exception]__str__!())
                raise
        """,
        """\
        export class ValidationError extends RangeError {
        }

        export function main() {
            try {
                throw new ValidationError('invalid');
            } catch ($error0) {
                if ($error0 instanceof ValidationError) {
                    let error = $error0;
                    console.log(error.message);
                    throw $error0;
                } else {
                    throw $error0;
                }
            }
        }
        """,
    )


def test_exception_chaining_has_a_focused_diagnostic():
    ad(
        """\
        def main():
            try:
                raise ValueError("first")
            except ValueError as error:
                raise TypeError("second") from error
        """,
        """
          File "exception_chaining.py", line 5
            raise TypeError("second") from error
                                           ^^^^^
        pyjs.CompilationError: exception chaining with 'raise ... from ...' is not supported [PYJS2001]
        help: Raise the exception without an explicit cause.
        """,
        filename="exception_chaining.py",
    )


def test_bare_raise_outside_a_handler_has_a_focused_diagnostic():
    ad(
        """\
        def main():
            raise
        """,
        """
          File "inactive_bare_raise.py", line 2
            raise
            ^^^^^
        pyjs.CompilationError: bare raise requires an active exception handler [PYJS2001]
        help: Raise an explicit exception in this context.
        """,
        filename="inactive_bare_raise.py",
    )


def test_raising_a_non_exception_has_a_focused_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        class Item:
            pass

        def main():
            raise Item()
        """,
        """
          File "invalid_raise.py", line 8
            raise Item()
                  ^^^^^^
        pyjs.CompilationError: raise requires an exception instance [PYJS1104]
        help: Raise Exception or an instance of one of its subclasses.
        """,
        filename="invalid_raise.py",
    )


def test_raising_an_exception_class_requires_instantiation():
    ad(
        """\
        def main():
            raise ValueError
        """,
        """
          File "exception_class_raise.py", line 2
            raise ValueError
                  ^^^^^^^^^^
        pyjs.CompilationError: raise requires an exception instance [PYJS1104]
        help: Raise Exception or an instance of one of its subclasses.
        """,
        filename="exception_class_raise.py",
    )


def test_runtime_exception_classes_are_imported_for_raises_bases_and_handlers():
    at(
        """
        @js
        class Missing(KeyError):
            pass

        def main(kind: int):
            try:
                if kind == 1:
                    raise Missing("missing")
                raise IndexError("index")
            except Missing:
                print("missing")
            except LookupError as error:
                print(str(error))
        """,
        """
        class Missing(KeyError):

        def main(kind: int) -> None:
            try:
                if kind.[int]__eq__!(1):
                    raise Missing('missing')
                raise IndexError('index')
            except Missing:
                print('missing')
            except LookupError as error:
                print(error.[Exception]__str__!())
        """,
        """
        import { KeyError as $KeyError, IndexError as $IndexError, LookupError as $LookupError } from './pyjs.python.js';

        export class Missing extends $KeyError {
        }

        export function main(kind) {
            try {
                if (kind == 1) {
                    throw new Missing('missing');
                }
                throw new $IndexError('index');
            } catch ($error0) {
                if ($error0 instanceof Missing) {
                    console.log('missing');
                } else if ($error0 instanceof $LookupError) {
                    let error = $error0;
                    console.log(error.message);
                } else {
                    throw $error0;
                }
            }
        }
        """,
    )


def test_assert_uses_the_typed_assertion_error_runtime():
    at(
        """
        def main():
            try:
                assert False, "broken"
            except AssertionError as error:
                print(str(error))
        """,
        """
        def main() -> None:
            try:
                assert False, 'broken'
            except AssertionError as error:
                print(error.[Exception]__str__!())
        """,
        """
        import { AssertionError as $AssertionError } from './pyjs.python.js';

        export function main() {
            try {
                __pyjsAssert__(false, () => 'broken', $AssertionError);
            } catch ($error0) {
                if ($error0 instanceof $AssertionError) {
                    let error = $error0;
                    console.log(error.message);
                } else {
                    throw $error0;
                }
            }
        }
        """,
    )


def test_try_else_runs_before_finally():
    at(
        """
        def main():
            try:
                print("try")
            except ValueError:
                print("except")
            else:
                print("else")
            finally:
                print("finally")
        """,
        """
        def main() -> None:
            try:
                print('try')
            except ValueError:
                print('except')
            else:
                print('else')
            finally:
                print('finally')
        """,
        """
        export function main() {
            try {
                let $try0 = true;
                try {
                    console.log('try');
                } catch ($error1) {
                    $try0 = false;
                    if ($error1 instanceof RangeError) {
                        console.log('except');
                    } else {
                        throw $error1;
                    }
                }
                if ($try0) {
                    console.log('else');
                }
            } finally {
                console.log('finally');
            }
        }
        """,
    )


def test_not_inline_bool_helper_is_parenthesized():
    # Regression: this used to lower as `!nodeid != null` instead of `!(nodeid != null)`.
    at(
        """
        @js.inline("{value} != null")
        def object_exists(value: object) -> bool:
            return False

        def main():
            nodeid = None
            missing = not object_exists(nodeid)
        """,
        """
        def main() -> None:
            nodeid: None = None
            missing: bool = not object_exists(nodeid)
        """,
        """
        export function main() {
            var nodeid = null;
            var missing = !(nodeid != null);
        }
        """
    )


def test_boolop_assignment_infers_bool():
    at(
        """
        @js.inline("{value} != null")
        def object_exists(value: object) -> bool:
            return False

        def main():
            frame = None
            keep_visible = object_exists(frame) and (True or False)
        """,
        """
        def main() -> None:
            frame: None = None
            keep_visible: bool = object_exists(frame) and (True or False)
        """,
        """
        export function main() {
            var frame = null;
            var keep_visible = frame != null && (true || false);
        }
        """
    )


def test_boolop_assignment_keeps_shared_type():
    at(
        """
        def main():
            primary = ""
            secondary = "log"
            css_class = (primary or secondary) and "console-line"
        """,
        """
        def main() -> None:
            primary: str = ''
            secondary: str = 'log'
            css_class: str = (primary or secondary) and 'console-line'
        """,
        """
        export function main() {
            var primary = '';
            var secondary = 'log';
            var css_class = (primary || secondary) && 'console-line';
        }
        """
    )


def test_or_expression_excludes_none_from_non_final_values():
    at(
        """
        @js
        def fallback(value: int | None) -> int:
            result = value or 0
            return result

        def main():
            fallback(None)
        """,
        """
        def fallback(value: int | None) -> int:
            result: int = value or 0
            return result

        def main() -> None:
            fallback(None)
        """,
        """
        export function fallback(value) {
            var result = value || 0;
            return result;
        }

        export function main() {
            fallback(null);
        }
        """,
    )


def test_boolean_values_use_python_collection_truthiness():
    at(
        """
        def main(values: list[int]):
            selected = values or [1]
            retained = values and "present"
        """,
        """
        def main(values: list__int) -> None:
            selected: list[int] = $evaluate_once(values; $boolop0 if $boolop0.[list__int]__bool__!() else [1])
            retained: list[int] | str = $evaluate_once(values; 'present' if $boolop0.[list__int]__bool__!() else $boolop0)
        """,
        """
        export function main(values) {
            var selected = (($boolop0) => $boolop0.length ? $boolop0 : [1])(values);
            var retained = (($boolop0) => $boolop0.length ? 'present' : $boolop0)(values);
        }
        """,
    )


def test_inline_operator_parenthesizes_conditional_argument():
    at(
        """
        def main():
            count = 2
            label = str(count) + (" person" if count == 1 else " people")
        """,
        """
        def main() -> None:
            count: int = 2
            label: str = count.[int]__str__!().[str]__add__!(' person' if count.[int]__eq__!(1) else ' people')
        """,
        """
        export function main() {
            var count = 2;
            var label = String(count) + (count == 1 ? ' person' : ' people');
        }
        """,
    )


def test_conditional_expression_narrows_optional_value():
    at(
        """
        from pyjs.web.html import HTMLElement

        @js
        def read_value(element: HTMLElement) -> str:
            value = element.getAttribute("data-value")
            return "" if value is None else value

        def main():
            result = read_value(HTMLElement())
        """,
        """
        def read_value(element: HTMLElement) -> str:
            value: str | None = element.[Element]getAttribute('data-value')
            return '' if value.[object]__is__!(None) else value

        def main() -> None:
            result: str = read_value(HTMLElement())
        """,
        """
        export function read_value(element) {
            var value = element.getAttribute('data-value');
            return value == null ? '' : value;
        }

        export function main() {
            var result = read_value(new HTMLElement());
        }
        """,
    )


def test_optional_truth_tests_use_runtime_dispatch_and_narrow_the_value():
    at(
        """
        @js
        class Choice:
            def __init__(self, enabled: bool):
                self.enabled = enabled

            def __bool__(self) -> bool:
                return self.enabled

        @js
        def choose(value: Choice | None) -> str:
            if value:
                return "yes"
            return "no"

        @js
        def expression(value: Choice | None) -> str:
            return "yes" if value else "no"

        def main():
            print(choose(Choice(True)), expression(None))
        """,
        """
        class Choice:

            def __init__(enabled: bool) -> None:
                self.enabled = enabled

            def __bool__() -> bool:
                return self.enabled

        def choose(value: Choice | None) -> str:
            if $truthy(value):
                return 'yes'
            return 'no'

        def expression(value: Choice | None) -> str:
            return 'yes' if $truthy(value) else 'no'

        def main() -> None:
            print(choose(Choice(True)), expression(None))
        """,
        """
        import { truthy as $truthy } from './pyjs.python.js';

        export class Choice {

            constructor(enabled) {
                this.enabled = enabled;
            }

            __bool__() {
                return this.enabled;
            }
        }

        export function choose(value) {
            if ($truthy(value)) {
                return 'yes';
            }
            return 'no';
        }

        export function expression(value) {
            return $truthy(value) ? 'yes' : 'no';
        }

        export function main() {
            console.log(choose(new Choice(true)), expression(null));
        }
        """,
    )


def test_conditional_expression_merges_different_branch_types():
    at(
        """
        @js
        def preserve(value: str | None) -> str | None:
            result = None if value is None else value
            return result

        def main():
            preserve("ready")
        """,
        """
        def preserve(value: str | None) -> str | None:
            result: None | str = None if value.[object]__is__!(None) else value
            return result

        def main() -> None:
            preserve('ready')
        """,
        """
        export function preserve(value) {
            var result = value == null ? null : value;
            return result;
        }

        export function main() {
            preserve('ready');
        }
        """,
    )


def test_conditional_expression_infers_empty_container_from_other_branch():
    at(
        """
        from collections.abc import Iterable

        from pyjs import js

        @js
        def materialize(values: Iterable[int] | None) -> list[int]:
            result = list(values) if values is not None else []
            return result

        def main():
            print(len(materialize(None)))
        """,
        """
        def materialize(values: Iterable[int] | None) -> list[int]:
            result: list[int] = list__int(values) if values.[object]__is_not__!(None) else []
            return result

        def main() -> None:
            print(materialize(None).[list__int]__len__!())
        """,
        """
        export function materialize(values) {
            var result = values != null ? Array.from(((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values)) : [];
            return result;
        }

        export function main() {
            console.log(materialize(null).length);
        }
        """,
    )


def test_legacy_typing_aliases_normalize_to_builtin_types():
    at(
        """
        import typing
        from typing import List

        from pyjs import js

        @js
        def legacy(
            values: typing.Optional[List[int]],
            metadata: typing.Dict[str, str],
            context: typing.Any = None,
        ) -> typing.Optional[typing.Tuple[int, str]]:
            if values is None:
                return None
            return values[0], metadata["label"]

        def main():
            print(legacy([1], {"label": "ready"}))
        """,
        """
        def legacy(values: list[int] | None, metadata: dict__str_str, context: object=None) -> tuple[int, str] | None:
            if values.[object]__is__!(None):
                return None
            return ($get_list_item(values, 0), $get_dict_item(metadata, 'label'))

        def main() -> None:
            print(legacy([1], {'label': 'ready'}))
        """,
        """
        import { get_list_item as $get_list_item, get_dict_item as $get_dict_item } from './pyjs.python.js';

        export function legacy(values, metadata, { context=null} = {}) {
            if (values == null) {
                return null;
            }
            return [$get_list_item(values, 0), $get_dict_item(metadata, 'label')];
        }

        export function main() {
            console.log(((value)=>value===null?'None':value)(legacy([1], new Map([['label', 'ready']]))));
        }
        """,
    )


def test_isinstance_narrowing_survives_inverse_guards_and_elif_conditions():
    at(
        """
        from pyjs.web.dom import Element
        from pyjs.web.html import HTMLInputElement, HTMLTextAreaElement

        @js
        def after_guard(target: Element):
            if not isinstance(target, HTMLInputElement):
                return
            print(target.value)

        @js
        def inside_elif(target: Element, role: str):
            if role == "title":
                return
            elif role == "body" and isinstance(target, HTMLTextAreaElement):
                print(target.value)

        @js
        def inside_and(target: Element):
            if isinstance(target, HTMLInputElement) and target.value != "":
                print(target.value)

        @js
        def after_elif_guard(target: Element, role: str):
            if role == "title":
                return
            elif not isinstance(target, HTMLInputElement):
                return
            print(target.value)

        def main():
            after_guard(HTMLInputElement())
            inside_elif(HTMLTextAreaElement(), "body")
            inside_and(HTMLInputElement())
            after_elif_guard(HTMLInputElement(), "task")
        """,
        """
        def after_guard(target: Element) -> None:
            if not isinstance(target, HTMLInputElement):
                return
            print(target.value)

        def inside_elif(target: Element, role: str) -> None:
            if role.[object]__eq__!('title'):
                return
            elif role.[object]__eq__!('body') and isinstance(target, HTMLTextAreaElement):
                print(target.value)

        def inside_and(target: Element) -> None:
            if isinstance(target, HTMLInputElement) and target.value.[object]__ne__!(''):
                print(target.value)

        def after_elif_guard(target: Element, role: str) -> None:
            if role.[object]__eq__!('title'):
                return
            elif not isinstance(target, HTMLInputElement):
                return
            print(target.value)

        def main() -> None:
            after_guard(HTMLInputElement())
            inside_elif(HTMLTextAreaElement(), 'body')
            inside_and(HTMLInputElement())
            after_elif_guard(HTMLInputElement(), 'task')
        """,
        """
        export function after_guard(target) {
            if (!((target instanceof HTMLInputElement))) {
                return;
            }
            console.log(target.value);
        }

        export function inside_elif(target, role) {
            if (role === 'title') {
                return;
            } else if (role === 'body' && (target instanceof HTMLTextAreaElement)) {
                console.log(target.value);
            }
        }

        export function inside_and(target) {
            if ((target instanceof HTMLInputElement) && target.value !== '') {
                console.log(target.value);
            }
        }

        export function after_elif_guard(target, role) {
            if (role === 'title') {
                return;
            } else if (!((target instanceof HTMLInputElement))) {
                return;
            }
            console.log(target.value);
        }

        export function main() {
            after_guard(new HTMLInputElement());
            inside_elif(new HTMLTextAreaElement(), 'body');
            inside_and(new HTMLInputElement());
            after_elif_guard(new HTMLInputElement(), 'task');
        }
        """,
    )


def test_isinstance_narrows_union_members_in_the_false_branch():
    at(
        """\
        @js
        class Left:
            def left(self) -> str:
                return "left"

        @js
        class Right:
            def right(self) -> str:
                return "right"

        @js
        def choose(value: Left | Right) -> str:
            if isinstance(value, Left):
                return value.left()
            else:
                return value.right()

        def main():
            print(choose(Right()))
        """,
        """
        class Left:

            def left() -> str:
                return 'left'

        class Right:

            def right() -> str:
                return 'right'

        def choose(value: Left | Right) -> str:
            if isinstance(value, Left):
                return value.[Left]left()
            else:
                return value.[Right]right()

        def main() -> None:
            print(choose(Right()))
        """,
        """
        export class Left {

            left() {
                return 'left';
            }
        }

        export class Right {

            right() {
                return 'right';
            }
        }

        export function choose(value) {
            if ((value instanceof Left)) {
                return value.left();
            } else {
                return value.right();
            }
        }

        export function main() {
            console.log(choose(new Right()));
        }
        """,
    )


def test_branch_local_declarations_merge_before_later_narrowing():
    at(
        """\
        @js
        class Left:
            def label(self) -> str:
                return "left"

        @js
        class Right:
            def label(self) -> str:
                return "right"

        def main(flag: bool):
            if flag:
                value = Left()
            else:
                value = Right()
            if isinstance(value, Left):
                print(value.label())
            else:
                print(value.label())
        """,
        """
        class Left:

            def label() -> str:
                return 'left'

        class Right:

            def label() -> str:
                return 'right'

        def main(flag: bool) -> None:
            if flag:
                value: Left = Left()
            else:
                value: Right = Right()
            if isinstance(value, Left):
                print(value.[Left]label())
            else:
                print(value.[Right]label())
        """,
        """
        export class Left {

            label() {
                return 'left';
            }
        }

        export class Right {

            label() {
                return 'right';
            }
        }

        export function main(flag) {
            if (flag) {
                var value = new Left();
            } else {
                value = new Right();
            }
            if ((value instanceof Left)) {
                console.log(value.label());
            } else {
                console.log(value.label());
            }
        }
        """,
    )


def test_isinstance_narrows_bare_container_types():
    at(
        """
        from pyjs import js

        @js
        def update(value: object):
            if isinstance(value, list):
                value.append("item")
            elif isinstance(value, dict):
                value["key"] = "value"
            elif isinstance(value, set):
                value.add("item")

        @js
        def add_after_guard(value: object):
            if not isinstance(value, set):
                return
            value.add("item")

        def main():
            update(["old"])
            update({"old": "value"})
            update({"old"})
            add_after_guard({"old"})
        """,
        """
        def update(value: object) -> None:
            if isinstance(value, list):
                value.[list__object]append!('item')
            elif isinstance(value, dict):
                value.[dict__object_object]__setitem__!('key', 'value')
            elif isinstance(value, set):
                value.[set__object]add!('item')

        def add_after_guard(value: object) -> None:
            if not isinstance(value, set):
                return
            value.[set__object]add!('item')

        def main() -> None:
            update(['old'])
            update({'old': 'value'})
            update({'old'})
            add_after_guard({'old'})
        """,
        """
        export function update(value) {
            if (Array.isArray(value)) {
                (value.push('item'), null);
            } else if ((value instanceof Map)) {
                (value.set('key', 'value'), null);
            } else if ((value instanceof Set)) {
                (value.add('item'), null);
            }
        }

        export function add_after_guard(value) {
            if (!((value instanceof Set))) {
                return;
            }
            (value.add('item'), null);
        }

        export function main() {
            update(['old']);
            update(new Map([['old', 'value']]));
            update(new Set(['old']));
            add_after_guard(new Set(['old']));
        }
        """,
    )


def test_isinstance_preserves_specialized_container_union_members():
    at(
        """
        from pyjs import js

        @js
        def update(value: list[int] | dict[str, str] | str):
            if isinstance(value, list):
                numbers: list[int] = value
                numbers.append(2)
            elif isinstance(value, dict):
                labels: dict[str, str] = value
                labels["status"] = "ready"

        def main():
            update([1])
            update({"status": "waiting"})
        """,
        """
        def update(value: list[int] | dict[str, str] | str) -> None:
            if isinstance(value, list):
                numbers: list[int] = value
                numbers.[list__int]append!(2)
            elif isinstance(value, dict):
                labels: dict[str, str] = value
                labels.[dict__str_str]__setitem__!('status', 'ready')

        def main() -> None:
            update([1])
            update({'status': 'waiting'})
        """,
        """
        export function update(value) {
            if (Array.isArray(value)) {
                var numbers = value;
                (numbers.push(2), null);
            } else if ((value instanceof Map)) {
                var labels = value;
                (labels.set('status', 'ready'), null);
            }
        }

        export function main() {
            update([1]);
            update(new Map([['status', 'waiting']]));
        }
        """,
    )


def test_optional_identity_check_in_condition():
    at(
        """
        @js
        class Label:
            def __init__(self):
                self.text = "ready"

        @js
        def get_label(found: bool) -> Label | None:
            if found:
                return Label()

        def main():
            label = get_label(True)
            if label is not None:
                print(label.text)
            other_label = get_label(False)
            if other_label is None:
                print("missing")
            else:
                print(other_label.text)
        """,
        """
        class Label:

            def __init__() -> None:
                self.text = 'ready'

        def get_label(found: bool) -> Label | None:
            if found:
                return Label()

        def main() -> None:
            label: Label | None = get_label(True)
            if label.[object]__is_not__!(None):
                print(label.text)
            other_label: Label | None = get_label(False)
            if other_label.[object]__is__!(None):
                print('missing')
            else:
                print(other_label.text)
        """,
        """
        export class Label {

            constructor() {
                this.text = 'ready';
            }
        }

        export function get_label(found) {
            if (found) {
                return new Label();
            }
        }

        export function main() {
            var label = get_label(true);
            if (label != null) {
                console.log(label.text);
            }
            var other_label = get_label(false);
            if (other_label == null) {
                console.log('missing');
            } else {
                console.log(other_label.text);
            }
        }
        """
    )


def test_boolean_conditions_narrow_optional_values_across_short_circuit_paths():
    at(
        """
        @js
        class Item:
            def __init__(self):
                self.disabled = False
                self.enabled = True
                self.label = "ready"

        @js
        def get_item() -> Item | None:
            return Item()

        @js
        def read_or(skip: bool) -> str:
            item = get_item()
            if item is None or item.disabled or skip:
                return ""
            return item.label

        @js
        def read_and() -> str:
            item = get_item()
            if item is not None and item.enabled:
                return item.label
            return ""

        def main():
            read_or(False)
            read_and()
        """,
        """
        class Item:

            def __init__() -> None:
                self.disabled = False
                self.enabled = True
                self.label = 'ready'

        def get_item() -> Item | None:
            return Item()

        def read_or(skip: bool) -> str:
            item: Item | None = get_item()
            if item.[object]__is__!(None) or item.disabled or skip:
                return ''
            return item.label

        def read_and() -> str:
            item: Item | None = get_item()
            if item.[object]__is_not__!(None) and item.enabled:
                return item.label
            return ''

        def main() -> None:
            read_or(False)
            read_and()
        """,
        """
        export class Item {

            constructor() {
                this.disabled = false;
                this.enabled = true;
                this.label = 'ready';
            }
        }

        export function get_item() {
            return new Item();
        }

        export function read_or(skip) {
            var item = get_item();
            if (item == null || item.disabled || skip) {
                return '';
            }
            return item.label;
        }

        export function read_and() {
            var item = get_item();
            if (item != null && item.enabled) {
                return item.label;
            }
            return '';
        }

        export function main() {
            read_or(false);
            read_and();
        }
        """,
    )


def test_optional_values_narrow_after_break_and_continue_guards():
    at(
        """
        @js
        class Item:
            def __init__(self, label: str):
                self.label = label

        @js
        def get_item(found: bool) -> Item | None:
            return Item("ready") if found else None

        @js
        def collect(flags: list[bool], stop: bool) -> list[str]:
            result: list[str] = []
            for flag in flags:
                item = get_item(flag)
                if item is None:
                    if stop:
                        break
                    continue
                result.append(item.label)
            return result

        def main():
            print(collect([True, False], False))
        """,
        """
        class Item:

            def __init__(label: str) -> None:
                self.label = label

        def get_item(found: bool) -> Item | None:
            return Item('ready') if found else None

        def collect(flags: list__bool, stop: bool) -> list[str]:
            result: list[str] = []
            for flag: bool in flags:
                item: Item | None = get_item(flag)
                if item.[object]__is__!(None):
                    if stop:
                        break
                    continue
                result.[list__str]append!(item.label)
            return result

        def main() -> None:
            print(collect([True, False], False))
        """,
        """
        export class Item {

            constructor(label) {
                this.label = label;
            }
        }

        export function get_item(found) {
            return found ? new Item('ready') : null;
        }

        export function collect(flags, stop) {
            var result = [];
            for (var flag of flags) {
                var item = get_item(flag);
                if (item == null) {
                    if (stop) {
                        break
                    }
                    continue
                }
                (result.push(item.label), null);
            }
            return result;
        }

        export function main() {
            console.log(collect([true, false], false));
        }
        """,
    )


def test_nested_loop_break_does_not_narrow_an_outer_value():
    ad(
        """\
        from pyjs import js

        @js
        def consume(value: int) -> None:
            pass

        @js
        def process(value: int | None) -> None:
            if value is None:
                for item in [1]:
                    break
            consume(value)

        def main():
            process(None)
        """,
        diagnostic_text(
            "nested_break.py",
            12,
            "consume(value)",
            " " * 8 + "^^^^^",
            "pyjs.CompilationError: Argument 'value' to consume expects int, "
            "got int|NoneType [PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="nested_break.py",
    )
