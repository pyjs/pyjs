import math
from importlib import import_module

import pytest
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from pyjs.analysis import libraries
from pyjs.analysis.libraries import (
    LIBRARIES,
    LibraryCompatibilityError,
    LibraryImplementation,
    LibrarySpec,
    resolve_library_import,
)
from pyjs.lib.pydantic.v2 import BaseModel as ClientBaseModel
from pyjs.stdlib.math import atan as client_atan
from pyjs.stdlib.math import hypot as client_hypot
from pyjs.testing.helpers import ad, assert_compiled_sources, assert_transpile, at


def test_pydantic_v2_import_uses_the_versioned_client_implementation():
    assert resolve_library_import(PydanticBaseModel) is ClientBaseModel


def test_math_module_and_functions_use_stdlib_client_implementations():
    assert resolve_library_import(math) is import_module("pyjs.stdlib.math")
    assert resolve_library_import(math.atan) is client_atan
    assert resolve_library_import(math.hypot) is client_hypot


def test_direct_math_imports_inline_functions_and_import_constants():
    at(
        """
        from math import ceil, pi

        def main():
            angle = pi
            rounded = ceil(angle)
        """,
        """
        pi: __const__ = 3.141592653589793

        def main() -> None:
            angle: float = pi
            rounded: int = ceil(angle)
        """,
        """
        import { pi } from './pyjs.stdlib.math.js';

        export function main() {
            var angle = pi;
            var rounded = Math.ceil(angle);
        }
        """,
    )


def test_math_module_alias_preserves_typed_members():
    at(
        """
        import math as geometry

        def main():
            angle = geometry.pi
            value = geometry.sin(angle)
            distance = geometry.dist([0.0], [value])
        """,
        """
        def main() -> None:
            angle: float = geometry.pi
            value: float = geometry.sin!(angle)
            distance: float = geometry.dist([0.0], [value])
        """,
        """
        import { pi as $geometry$pi, dist as $geometry$dist } from './pyjs.stdlib.math.js';

        export function main() {
            var angle = $geometry$pi;
            var value = Math.sin(angle);
            var distance = $geometry$dist([0.0], [value]);
        }
        """,
    )


def test_typing_cast_refines_types_without_emitting_runtime_code():
    at(
        """
        import typing
        from typing import cast

        def main(value: object):
            direct = cast(list[str], value)
            qualified = typing.cast(list[str], value)
            optional = cast(str | None, value)
            first = direct[0]
            second = qualified[1]
            if optional is not None:
                lowered = optional.lower()
        """,
        """
        def main(value: object) -> None:
            direct: list[str] = value
            qualified: list[str] = value
            optional: str | None = value
            first: str = $get_list_item(direct, 0)
            second: str = $get_list_item(qualified, 1)
            if optional.[object]__is_not__!(None):
                lowered: str = optional.[str]lower!()
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function main(value) {
            var direct = value;
            var qualified = value;
            var optional = value;
            var first = $get_list_item(direct, 0);
            var second = $get_list_item(qualified, 1);
            if (optional != null) {
                var lowered = optional.toLowerCase();
            }
        }
        """,
    )


def test_typing_mapping_and_any_lower_to_python_runtime_types():
    assert_transpile(
        """
        from dataclasses import dataclass
        from typing import Any, Mapping

        @js
        @dataclass
        class Record:
            values: Mapping[str, Any]
            payload: Any

        @js
        def size(values: Mapping[str, Any]) -> int:
            return len(values)

        def main():
            record = Record({"count": 1}, "ready")
            print(size(record.values), record.payload)
        """,
        """
        export class Record {

            constructor(values, payload) {
                this.values = values;
                this.payload = payload;
            }
        }

        export function size(values) {
            return values.size;
        }

        export function main() {
            var record = new Record(new Map([['count', 1]]), 'ready');
            console.log(size(record.values), record.payload);
        }
        """,
    )


def test_typing_cast_reports_an_invalid_call_shape():
    ad(
        """
        from typing import cast

        def main(value: object):
            result = cast(value)
        """,
        """
          File "typing_cast.py", line 5
            result = cast(value)
                     ^^^^^^^^^^^
        pyjs.CompilationError: typing.cast() requires a type and one value [PYJS1104]
        help: Call cast(ExpectedType, value) with positional arguments.
        """,
        filename="typing_cast.py",
    )
    ad(
        """
        from typing import cast

        def main(value: object):
            result = cast(value, value)
        """,
        """
          File "typing_cast_type.py", line 5
            result = cast(value, value)
                          ^^^^^
        pyjs.CompilationError: typing.cast() requires a statically known type [PYJS1104]
        help: Pass a type annotation as the first argument to cast().
        """,
        filename="typing_cast_type.py",
    )


def test_pydantic_api_generation_must_be_supported(monkeypatch):
    monkeypatch.setattr(libraries.metadata, "version", lambda distribution: "3.0.0")

    with pytest.raises(
        LibraryCompatibilityError,
        match=(
            r"PyJS supports pydantic >=2\.0,<3\.0, "
            r"but found pydantic==3\.0\.0\."
        ),
    ):
        resolve_library_import(PydanticBaseModel)


def test_pydantic_client_rejects_unsupported_default_factories():
    def new_labels():
        return []

    class Labels(PydanticBaseModel):
        values: list[str] = Field(default_factory=new_labels)

    with pytest.raises(
        TypeError,
        match=(
            r"Labels\.values uses an unsupported default factory\. "
            r"PyJS supports list and dict factories\."
        ),
    ):
        libraries.library_class_info(Labels)


def test_new_api_generations_do_not_displace_older_implementations(monkeypatch):
    pydantic_v2 = LIBRARIES[0].implementations[0]
    pydantic_v3 = LibraryImplementation(
        module="pyjs.lib.pydantic.v3",
        minimum=(3, 0),
        maximum=(4, 0),
        imports=pydantic_v2.imports,
    )
    pydantic = LibrarySpec(
        distribution="pydantic",
        implementations=(pydantic_v2, pydantic_v3),
    )

    monkeypatch.setattr(libraries.metadata, "version", lambda distribution: "2.13.4")
    assert pydantic.implementation_for(PydanticBaseModel) is pydantic_v2

    monkeypatch.setattr(libraries.metadata, "version", lambda distribution: "3.1.0")
    assert pydantic.implementation_for(PydanticBaseModel) is pydantic_v3


def test_standard_library_dates_use_the_javascript_date_type():
    at(
        """
        from datetime import date
        from pydantic import BaseModel

        @js
        class Release(BaseModel):
            due_date: date

        def main(release: Release):
            value = release.due_date
        """,
        """
        class BaseModel:

            def __init__(values: dict__str_object) -> None:
                assign_model_values(self, values)

        class Release(BaseModel):

        def main(release: Release) -> None:
            value: Date = release.due_date
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';

        export class Release extends BaseModel {
        }
        Release.__pyjs_required__ = ['due_date'];
        Release.__pyjs_fields__ = new Map([['due_date', 'Date']]);

        export function main(release) {
            var value = release.due_date;
        }
        """,
    )


def test_pydantic_models_keep_typed_fields_and_use_the_v2_client_base():
    at(
        """
        from pydantic import BaseModel

        @js
        class Task(BaseModel):
            id: int | None = None
            title: str
            completed: bool = False

        def main():
            task = Task(title="Ship")
            title = task.title
            data = task.model_dump()
            restored = Task.model_validate(data)
            restored_title = restored.title
        """,
        """
        class BaseModel:

            def __init__(values: dict__str_object) -> None:
                assign_model_values(self, values)

            def model_validate(value: dict__str_object) -> BaseModel:
                return this(value)

            def model_dump() -> dict[str, object]:
                return model_values(self)

        class Task(BaseModel):

        def main() -> None:
            task: Task = Task(title='Ship')
            title: str = task.title
            data: dict[str, object] = task.[BaseModel]model_dump()
            restored: Task = Task.[BaseModel]model_validate(data)
            restored_title: str = restored.title
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_defaults__ = new Map([['id', null], ['completed', false]]);
        Task.__pyjs_required__ = ['title'];
        Task.__pyjs_fields__ = new Map([['id', ['union', 'int', 'NoneType']], ['title', 'str'], ['completed', 'bool']]);

        export function main() {
            var task = new Task({title: 'Ship'});
            var title = task.title;
            var data = task.model_dump();
            var restored = Task.model_validate(data);
            var restored_title = restored.title;
        }
        """,
    )


def test_pydantic_v2_client_runtime_is_emitted_as_its_own_module():
    assert_compiled_sources(
        """
        from pydantic import BaseModel
        from pyjs import js

        @js
        class Task(BaseModel):
            id: int | None = None
            title: str
            completed: bool = False

        def main():
            task = Task(title="Ship")
            data = task.model_dump()
            restored = Task.model_validate(data)
            print(restored.title)
        """,
        {
            "pyjs.lib.pydantic.v2": """
                export function assign_model_values(model, values) {
                    const data = values === undefined
                        ? {}
                        : values instanceof Map
                            ? Object.fromEntries(values)
                            : values;
                    if (data === null || typeof data !== 'object' || Array.isArray(data)) {
                        throw new TypeError('Model input must be a dict or model');
                    }
                    const defaults = structuredClone(Object.fromEntries(
                        model.constructor.__pyjs_defaults__ || []
                    ));
                    const fields = model.constructor.__pyjs_fields__ || new Map();
                    const fail = (path, expected) => {
                        throw new TypeError(`${path} must be ${expected}`);
                    };
                    const suppliedFields = (input, result) => {
                        if (input === null || typeof input !== 'object' || result === null) return 0;
                        const fields = result.constructor?.__pyjs_fields__;
                        if (fields) {
                            const data = input instanceof Map ? Object.fromEntries(input) : input;
                            let count = 0;
                            for (const name of fields.keys()) {
                                if (Object.hasOwn(data, name)) {
                                    count += 1 + suppliedFields(data[name], result[name]);
                                }
                            }
                            return count;
                        }
                        if (result instanceof Map) {
                            const entries = input instanceof Map ? [...input.values()] : Object.values(input);
                            return [...result.values()].reduce(
                                (count, item, index) => count + suppliedFields(entries[index], item), 0);
                        }
                        if (Array.isArray(result) || result instanceof Set) {
                            const items = [...input];
                            return [...result].reduce(
                                (count, item, index) => count + suppliedFields(items[index], item), 0);
                        }
                        return 0;
                    };
                    const validate = (value, descriptor, path) => {
                        if (Array.isArray(descriptor) && descriptor[0] === 'model') {
                            const modelName = descriptor[1];
                            descriptor = globalThis.$pyjsModels?.get(modelName);
                            if (descriptor === undefined) {
                                fail(path, modelName);
                            }
                        }
                        if (typeof descriptor === 'function') {
                            if (value instanceof descriptor) return value;
                            if (value !== null && typeof value === 'object'
                                    && descriptor.__pyjs_fields__ !== undefined) {
                                return new descriptor(value);
                            }
                            if (value !== null && typeof value === 'object'
                                    && typeof descriptor.model_validate === 'function') {
                                return descriptor.model_validate(value);
                            }
                            fail(path, descriptor.name);
                        }
                        if (descriptor === 'object') return value;
                        if (descriptor === 'NoneType') {
                            if (value === null || value === undefined) return null;
                            fail(path, 'None');
                        }
                        if (descriptor === 'bool') {
                            if (typeof value === 'boolean') return value;
                            fail(path, 'bool');
                        }
                        if (descriptor === 'int') {
                            if (typeof value === 'number' && Number.isInteger(value)) return value;
                            if (typeof value === 'string' && /^[+-]?[0-9]+$/.test(value.trim())) {
                                return Number(value);
                            }
                            fail(path, 'int');
                        }
                        if (descriptor === 'float') {
                            if (typeof value === 'number') return value;
                            fail(path, 'float');
                        }
                        if (descriptor === 'str') {
                            if (typeof value === 'string') return value;
                            fail(path, 'str');
                        }
                        if (descriptor === 'Date') {
                            if (value instanceof Date) return value;
                            if (typeof value === 'string') {
                                const source = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)
                                    ? `${value}T00:00:00`
                                    : value;
                                const parsed = new Date(source);
                                if (!Number.isNaN(parsed.getTime())) return parsed;
                            }
                            fail(path, 'date');
                        }
                        const [kind, ...members] = descriptor;
                        if (kind === 'literal') {
                            if (members.includes(value)) return value;
                            fail(path, `one of ${members.join(', ')}`);
                        }
                        if (kind === 'union') {
                            // A successful parent schema can discard fields supplied for a
                            // child. Prefer the successful branch retaining most model fields,
                            // including nested fields, without counting generated defaults.
                            let best, bestCount = -1;
                            for (const member of members) {
                                try {
                                    const result = validate(value, member, path);
                                    const count = suppliedFields(value, result);
                                    if (count > bestCount) {
                                        best = result;
                                        bestCount = count;
                                    }
                                } catch (error) {
                                    if (!(error instanceof TypeError)) throw error;
                                }
                            }
                            if (bestCount >= 0) return best;
                            fail(path, 'a valid union member');
                        }
                        if (kind === 'list') {
                            if (!Array.isArray(value)) fail(path, 'list');
                            return value.map((item, index) => validate(
                                item, members[0], `${path}[${index}]`
                            ));
                        }
                        if (kind === 'tuple') {
                            if (!Array.isArray(value) || value.length !== members.length) {
                                fail(path, `tuple of length ${members.length}`);
                            }
                            return value.map((item, index) => validate(
                                item, members[index], `${path}[${index}]`
                            ));
                        }
                        if (kind === 'set') {
                            const items = value instanceof Set ? [...value] : value;
                            if (!Array.isArray(items)) fail(path, 'set');
                            return new Set(items.map((item, index) => validate(
                                item, members[0], `${path}[${index}]`
                            )));
                        }
                        if (kind === 'dict') {
                            const entries = value instanceof Map
                                ? [...value.entries()]
                                : value !== null && typeof value === 'object' && !Array.isArray(value)
                                    ? Object.entries(value)
                                    : null;
                            if (entries === null) fail(path, 'dict');
                            return new Map(entries.map(([key, item]) => {
                                let typedKey = key;
                                if (!(value instanceof Map)) {
                                    if (members[0] === 'float' && key.trim() !== '' && Number.isFinite(Number(key))) {
                                        typedKey = Number(key);
                                    } else if (members[0] === 'bool' && (key === 'true' || key === 'false')) {
                                        typedKey = key === 'true';
                                    }
                                }
                                return [validate(typedKey, members[0], `${path}.key`),
                                        validate(item, members[1], `${path}[${key}]`)];
                            }));
                        }
                        fail(path, String(descriptor));
                    };
                    for (const name of model.constructor.__pyjs_required__ || []) {
                        if (!Object.hasOwn(data, name)) {
                            throw new TypeError(`Missing required field: ${name}`);
                        }
                    }
                    for (const [name, descriptor] of fields) {
                        const value = Object.hasOwn(data, name) ? data[name] : defaults[name];
                        model[name] = validate(value, descriptor, name);
                    }
                }

                export function model_values(model) {
                    const resolve = descriptor => Array.isArray(descriptor) && descriptor[0] === 'model'
                        ? globalThis.$pyjsModels?.get(descriptor[1]) : descriptor;
                    const matches = (value, descriptor, exact = false) => {
                        descriptor = resolve(descriptor);
                        if (typeof descriptor === 'function') return exact
                            ? value?.constructor === descriptor : value instanceof descriptor;
                        if (descriptor === 'NoneType') return value === null;
                        if (descriptor === 'object') return true;
                        if (descriptor === 'str') return typeof value === 'string';
                        if (descriptor === 'bool') return typeof value === 'boolean';
                        if (descriptor === 'int') return Number.isInteger(value);
                        if (descriptor === 'float') return typeof value === 'number';
                        if (descriptor === 'Date') return value instanceof Date;
                        if (!Array.isArray(descriptor)) return false;
                        const [kind, ...members] = descriptor;
                        if (kind === 'literal') return members.includes(value);
                        if (kind === 'union') return members.some(member => matches(value, member, exact));
                        if (kind === 'list') return Array.isArray(value) && value.every(item => matches(item, members[0], exact));
                        if (kind === 'tuple') return Array.isArray(value) && value.length === members.length
                            && value.every((item, index) => matches(item, members[index], exact));
                        if (kind === 'set') return value instanceof Set && [...value].every(item => matches(item, members[0], exact));
                        if (kind === 'dict') return value instanceof Map && [...value].every(
                            ([key, item]) => matches(key, members[0], exact) && matches(item, members[1], exact));
                        return false;
                    };
                    const dump = (value, descriptor = null) => {
                        descriptor = resolve(descriptor);
                        if (value === null || value === undefined) return value;
                        if (Array.isArray(descriptor) && descriptor[0] === 'union') {
                            const members = descriptor.slice(1).map(resolve);
                            descriptor = members.find(member => matches(value, member, true))
                                ?? members.find(member => matches(value, member))
                                ?? members.find(member => member !== 'NoneType');
                        }
                        const fields = typeof descriptor === 'function' && descriptor.__pyjs_fields__
                            ? descriptor.__pyjs_fields__
                            : value.constructor?.__pyjs_fields__;
                        if (fields) {
                            return new Map([...fields].map(([name, field]) => [name, dump(value[name], field)]));
                        }
                        const kind = Array.isArray(descriptor) ? descriptor[0] : null;
                        if (Array.isArray(value)) {
                            return value.map((item, index) => dump(item,
                                kind === 'tuple' ? descriptor[index + 1] : kind === 'list' ? descriptor[1] : null));
                        }
                        if (value instanceof Set) return [...value].map(item => dump(item,
                            kind === 'set' ? descriptor[1] : null));
                        if (value instanceof Map) {
                            return new Map([...value].map(([key, item]) => [key, dump(item,
                                kind === 'dict' ? descriptor[2] : null)]));
                        }
                        return value;
                    };
                    return dump(model);
                }

                export class BaseModel {

                    constructor(values) {
                        assign_model_values(this, values);
                    }

                    static model_validate(value) {
                        return new this(value);
                    }

                    model_dump() {
                        return model_values(this);
                    }
                }
            """,
            "_pyjs_source_": """
                import { BaseModel } from './pyjs.lib.pydantic.v2.js';

                export class Task extends BaseModel {
                }
                Task.__pyjs_defaults__ = new Map([['id', null], ['completed', false]]);
                Task.__pyjs_required__ = ['title'];
                Task.__pyjs_fields__ = new Map([['id', ['union', 'int', 'NoneType']], ['title', 'str'], ['completed', 'bool']]);

                export function main() {
                    var task = new Task({title: 'Ship'});
                    var data = task.model_dump();
                    var restored = Task.model_validate(data);
                    console.log(restored.title);
                }
            """,
        },
    )
