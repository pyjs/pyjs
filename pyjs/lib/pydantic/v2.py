from copy import deepcopy
from typing import Self

from pyjs import js


@js
def assign_model_values(model: object, values: dict[str, object]) -> None:
    defaults = deepcopy(getattr(type(model), "__pyjs_defaults__", {}))
    required = getattr(type(model), "__pyjs_required__", [])
    for name in required:
        if name not in values:
            raise TypeError(f"Missing required field: {name}")
    for name, value in defaults.items():
        setattr(model, name, value)
    for name, value in values.items():
        setattr(model, name, value)


assign_model_values.source(
    """
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
            for (const member of members) {
                try {
                    return validate(value, member, path);
                } catch (error) {
                    if (!(error instanceof TypeError)) throw error;
                }
            }
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
                : value !== null && typeof value === 'object'
                    ? Object.entries(value)
                    : null;
            if (entries === null) fail(path, 'dict');
            return new Map(entries.map(([key, item]) => [
                validate(key, members[0], `${path}.key`),
                validate(item, members[1], `${path}[${key}]`),
            ]));
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
    """
)


@js
def model_values(model: object) -> dict[str, object]:
    return vars(model)


model_values.source(
    """
    const dump = (value) => {
        if (Array.isArray(value)) return value.map(dump);
        if (value instanceof Set) return [...value].map(dump);
        if (value instanceof Map) {
            return new Map([...value].map(([key, item]) => [key, dump(item)]));
        }
        if (value !== null && value.constructor?.__pyjs_fields__) {
            return new Map([...value.constructor.__pyjs_fields__.keys()].map(
                (name) => [name, dump(value[name])]
            ));
        }
        return value;
    };
    return dump(model);
    """
)


@js
class BaseModel:
    __pyjs_defaults__: dict[str, object] = {}
    __pyjs_required__: list[str] = []
    __pyjs_fields__: dict[str, object] = {}

    def __init__(self, values: dict[str, object]):
        assign_model_values(self, values)

    @classmethod
    def model_validate(cls, value: dict[str, object]) -> Self:
        return cls(value)

    def model_dump(self) -> dict[str, object]:
        return model_values(self)


def _class_info(
    model: type,
) -> tuple[dict[str, object], dict[str, object], tuple[str, ...]]:
    annotations = {}
    defaults = {}
    required = []
    for name, field in model.model_fields.items():
        annotations[name] = field.annotation
        if field.is_required():
            required.append(name)
            continue
        if field.default_factory is not None:
            if field.default_factory not in {dict, list}:
                raise TypeError(
                    f"{model.__name__}.{name} uses an unsupported default "
                    "factory. PyJS supports list and dict factories."
                )
            defaults[name] = field.default_factory()
        else:
            defaults[name] = field.default
    return annotations, defaults, tuple(required)
