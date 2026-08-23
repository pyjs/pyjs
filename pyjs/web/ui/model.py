import types
from datetime import date
from typing import Self, Union, get_args, get_origin

from pydantic import BaseModel

from pyjs import js, nojs
from pyjs.server.errors import OperationError
from pyjs.server.pagination import Page
from pyjs.web.crypto import crypto
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, form, input, tag, tw
from pyjs.web.html import HTMLInputElement
from pyjs.web.ui.date import iso_date
from pyjs.web.ui.field import FieldError


@js.inline("{model}[{name}]")
def text_model_value(model: BaseModel, name: str) -> str | None:
    return getattr(model, name)


@js.inline("{model}[{name}]")
def boolean_model_value(model: BaseModel, name: str) -> bool:
    return getattr(model, name)


@js.inline("{model}[{name}]")
def integer_model_value(model: BaseModel, name: str) -> int | None:
    return getattr(model, name)


@js.inline("{model}[{name}]")
def float_model_value(model: BaseModel, name: str) -> float | None:
    return getattr(model, name)


@js.inline("{model}[{name}]")
def date_model_value(model: BaseModel, name: str) -> date | None:
    return getattr(model, name)


@js.inline("new Date({value} + 'T00:00:00')")
def parse_date_value(value: str) -> date:
    return date.fromisoformat(value)


@js
def input_control(element: Element) -> HTMLInputElement:
    if isinstance(element, HTMLInputElement):
        return element
    for child in element.children:
        try:
            return input_control(child)
        except Exception:
            pass
    raise ValueError("Model field does not contain an input control.")


@input_control.client
def input_control(element: Element) -> HTMLInputElement:
    if isinstance(element, HTMLInputElement):
        return element
    control = element.querySelector("[data-model-control]")
    if not isinstance(control, HTMLInputElement):
        raise ValueError("Model field does not contain an input control.")
    return control


@js
class ModelField:
    def __init__(
        self,
        label: str = "",
        *,
        name: str = "",
        required: bool = False,
        nullable: bool = False,
    ):
        self.name = name
        self.label = label or name.replace("_", " ")
        self.required = required
        self.nullable = nullable

    def create(self, model: BaseModel) -> Element:
        raise TypeError("ModelField.create() must be overridden.")

    def read(self, element: Element) -> object:
        raise TypeError("ModelField.read() must be overridden.")

    def update(self, element: Element, model: BaseModel):
        raise TypeError("ModelField.update() must be overridden.")

    @nojs
    def javascript_options(self) -> dict[str, object]:
        options = {
            "label": self.label,
            "name": self.name,
            "required": self.required,
        }
        if self.nullable:
            options["nullable"] = True
        return options

    @nojs
    def configure(self, model_field):
        self.required = model_field.is_required()
        self.nullable = _allows_none(model_field.annotation)

    def wrap(self, control: HTMLInputElement) -> Element:
        return tag(
            "label",
            tw("grid gap-2 text-sm font-medium text-slate-900"),
            tag("span", self.label),
            control,
        )

    def error_control(self, element: Element) -> HTMLInputElement | None:
        try:
            return input_control(element)
        except Exception:
            return None

    def mark_invalid(
        self,
        control: HTMLInputElement,
        error_id: str,
    ):
        control.setAttribute("aria-invalid", "true")
        described_by = control.getAttribute("aria-describedby")
        if described_by is None or described_by == "":
            control.setAttribute("aria-describedby", error_id)
        else:
            control.setAttribute("aria-describedby", described_by + " " + error_id)

@js
class TextModelField(ModelField):
    def __init__(
        self,
        label: str = "",
        *,
        name: str = "",
        required: bool = False,
        nullable: bool = False,
        max_length: int = 0,
        hidden: bool = False,
    ):
        super().__init__(label, name=name, required=required, nullable=nullable)
        self.max_length = max_length
        self.hidden = hidden

    def create(self, model: BaseModel) -> Element:
        input_type = "hidden" if self.hidden else "text"
        attributes = {
            "data-model-control": "",
            "name": self.name,
            "type": input_type,
        }
        if self.hidden:
            control = input(attributes)
        else:
            control = input(
                tw(
                    "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm "
                    "outline-none focus:border-slate-500 "
                    "focus:ring-2 focus:ring-slate-200 "
                    "aria-invalid:border-red-500 aria-invalid:ring-red-100"
                ),
                attributes,
            )
        if self.required:
            control.setAttribute("required", "")
        if self.max_length > 0:
            control.setAttribute("maxlength", str(self.max_length))
        self.update(control, model)
        if self.hidden:
            return control
        return self.wrap(control)

    def read(self, element: Element) -> object:
        value = input_control(element).value
        if self.nullable and value == "":
            return None
        return value

    def error_control(self, element: Element) -> HTMLInputElement | None:
        if self.hidden:
            return None
        return super().error_control(element)

    def update(self, element: Element, model: BaseModel):
        control = input_control(element)
        value = text_model_value(model, self.name)
        if value is None:
            control.value = ""
            control.setAttribute("value", "")
            return
        control.value = value
        control.setAttribute("value", value)

    @nojs
    def javascript_options(self) -> dict[str, object]:
        options = super().javascript_options()
        options["max_length"] = self.max_length
        options["hidden"] = self.hidden
        return options

    @nojs
    def configure(self, model_field):
        super().configure(model_field)
        if self.max_length == 0:
            self.max_length = _maximum_length(model_field)


@js
class BooleanModelField(ModelField):
    def create(self, model: BaseModel) -> Element:
        control = input(
            tw("size-4 rounded border border-slate-300 accent-slate-950"),
            {
                "data-model-control": "",
                "name": self.name,
                "type": "checkbox",
            },
        )
        if self.required:
            control.setAttribute("required", "")
        self.update(control, model)
        return self.wrap(control)

    def read(self, element: Element) -> object:
        return input_control(element).checked

    def update(self, element: Element, model: BaseModel):
        control = input_control(element)
        control.checked = boolean_model_value(model, self.name)
        if control.checked:
            control.setAttribute("checked", "")
        else:
            control.removeAttribute("checked")

    def wrap(self, control: HTMLInputElement) -> Element:
        return tag(
            "label",
            tw("flex items-center gap-2 text-sm font-medium text-slate-900"),
            control,
            tag("span", self.label),
        )


@js
class IntegerModelField(ModelField):
    def __init__(
        self,
        label: str = "",
        *,
        name: str = "",
        required: bool = False,
        nullable: bool = False,
        hidden: bool = False,
    ):
        super().__init__(label, name=name, required=required, nullable=nullable)
        self.hidden = hidden

    def create(self, model: BaseModel) -> Element:
        input_type = "hidden" if self.hidden else "number"
        attributes = {
            "data-model-control": "",
            "name": self.name,
            "type": input_type,
        }
        if self.hidden:
            control = input(attributes)
        else:
            control = input(
                tw(
                    "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm "
                    "outline-none focus:border-slate-500 "
                    "focus:ring-2 focus:ring-slate-200 "
                    "aria-invalid:border-red-500 aria-invalid:ring-red-100"
                ),
                attributes,
            )
        if self.required:
            control.setAttribute("required", "")
        self.update(control, model)
        if self.hidden:
            return control
        return self.wrap(control)

    def read(self, element: Element) -> object:
        value = input_control(element).value
        if self.nullable and value == "":
            return None
        return int(value)

    def error_control(self, element: Element) -> HTMLInputElement | None:
        if self.hidden:
            return None
        return super().error_control(element)

    def update(self, element: Element, model: BaseModel):
        control = input_control(element)
        model_value = integer_model_value(model, self.name)
        if model_value is None:
            control.value = ""
            control.setAttribute("value", "")
            return
        value = str(model_value)
        control.value = value
        control.setAttribute("value", value)

    @nojs
    def javascript_options(self) -> dict[str, object]:
        options = super().javascript_options()
        options["hidden"] = self.hidden
        return options


@js
class FloatModelField(ModelField):
    def create(self, model: BaseModel) -> Element:
        control = input(
            tw(
                "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm "
                "outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200 "
                "aria-invalid:border-red-500 aria-invalid:ring-red-100"
            ),
            {
                "data-model-control": "",
                "name": self.name,
                "step": "any",
                "type": "number",
            },
        )
        if self.required:
            control.setAttribute("required", "")
        self.update(control, model)
        return self.wrap(control)

    def read(self, element: Element) -> object:
        value = input_control(element).value
        if self.nullable and value == "":
            return None
        return float(value)

    def update(self, element: Element, model: BaseModel):
        control = input_control(element)
        model_value = float_model_value(model, self.name)
        if model_value is None:
            control.value = ""
            control.setAttribute("value", "")
            return
        value = str(model_value)
        control.value = value
        control.setAttribute("value", value)


@js
class DateModelField(ModelField):
    def create(self, model: BaseModel) -> Element:
        control = input(
            tw(
                "h-9 rounded-md border border-slate-300 bg-white px-3 text-sm "
                "outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200 "
                "aria-invalid:border-red-500 aria-invalid:ring-red-100"
            ),
            {
                "data-model-control": "",
                "name": self.name,
                "type": "date",
            },
        )
        if self.required:
            control.setAttribute("required", "")
        self.update(control, model)
        return self.wrap(control)

    def read(self, element: Element) -> object:
        value = input_control(element).value
        if self.nullable and value == "":
            return None
        return parse_date_value(value)

    def update(self, element: Element, model: BaseModel):
        control = input_control(element)
        model_value = date_model_value(model, self.name)
        if model_value is None:
            control.value = ""
            control.setAttribute("value", "")
            return
        value = iso_date(model_value)
        control.value = value
        control.setAttribute("value", value)


class ModelAdapterAlias:
    def __init__(self, adapter_type, model_type):
        self.adapter_type = adapter_type
        self.model_type = model_type

    def __mro_entries__(self, bases):
        return (self.adapter_type,)


def _adapter_model_type(namespace):
    for base in namespace.get("__orig_bases__", ()):
        if isinstance(base, ModelAdapterAlias):
            return base.model_type
    return None


def _declared_members(bases, namespace, metadata_name, member_type):
    members = {
        member.name: member
        for base in bases
        for member in getattr(base, metadata_name, ())
    }
    for name, value in namespace.items():
        if not isinstance(value, member_type):
            continue
        value.name = name
        if not value.label:
            value.label = name.replace("_", " ")
        value.__js__ = False
        members[name] = value
    return members


def _member_javascript(member) -> str:
    class_name = type(member).__name__
    options = ", ".join(
        f"{name}: {_javascript_literal(value)}"
        for name, value in member.javascript_options().items()
    )
    return f"new {class_name}({{{options}}})"


def _javascript_literal(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return repr(value)


def _adapter_javascript(
    class_name: str,
    model_type: type,
    member_name: str,
    members: list,
) -> str:
    values = ", ".join(_member_javascript(member) for member in members)
    return "\n".join(
        (
            f"{class_name}.__pyjs_model__ = {model_type.__name__};",
            f"{class_name}.{member_name} = [{values}];",
        )
    )


def _form_javascript(
    class_name: str,
    model_type: type,
    fields: list,
) -> str:
    model_fields = repr([field.name for field in fields])
    return "\n".join(
        (
            _adapter_javascript(
                class_name,
                model_type,
                "__pyjs_fields__",
                fields,
            ),
            f"{class_name}.__pyjs_model_fields__ = {model_fields};",
            f"{class_name}.__pyjs_fields_by_name__ = "
            f"new Map({class_name}.__pyjs_fields__.map("
            "field => [field.name, field]));",
        )
    )


class ModelFormMetaclass(type):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
        declared_by_name = _declared_members(
            bases,
            namespace,
            "__pyjs_fields__",
            ModelField,
        )
        model_type = _adapter_model_type(namespace)
        if model_type is not None:
            meta = namespace.get("Meta", None)
            if meta is not None:
                meta.__js__ = False
            selected = _selected_model_fields(
                name,
                model_type,
                meta,
                declared_by_name,
            )
            fields_by_name = {}
            for field_name in selected:
                model_field = model_type.model_fields[field_name]
                field = declared_by_name.get(field_name)
                if field is None:
                    field = _automatic_model_field(
                        name,
                        field_name,
                        model_field,
                    )
                field.name = field_name
                if not field.label:
                    field.label = field_name.replace("_", " ")
                field.configure(model_field)
                field.__js__ = False
                fields_by_name[field_name] = field
            fields = list(fields_by_name.values())
            unknown = set(declared_by_name) - set(model_type.model_fields)
            if unknown:
                names = ", ".join(sorted(unknown))
                raise TypeError(f"Unknown {model_type.__name__} field(s): {names}.")
            namespace["__pyjs_model__"] = model_type
            namespace["__pyjs_model_fields__"] = selected
            namespace["__js_append__"] = lambda included: _form_javascript(
                name,
                model_type,
                fields,
            )
            namespace["__js_append_dependencies__"] = (
                model_type,
                *(type(field) for field in fields),
            )
            namespace["__pyjs_fields__"] = fields
            namespace["__pyjs_fields_by_name__"] = fields_by_name
        else:
            namespace["__pyjs_fields__"] = list(declared_by_name.values())
            namespace["__pyjs_fields_by_name__"] = declared_by_name
        return super().__new__(mcls, name, bases, namespace, **kwargs)


def _meta_names(
    value,
    option: str,
    *,
    allow_all: bool = False,
) -> tuple[str, ...] | None:
    if value is None or (allow_all and value == "__all__"):
        return None
    if isinstance(value, str):
        raise TypeError(
            f"ModelForm.Meta.{option} must be a sequence, not a string."
        )
    return tuple(value)


def _selected_model_fields(
    form_name: str,
    model_type: type,
    meta: type | None,
    declared: dict[str, ModelField],
) -> list[str]:
    model_names = list(model_type.model_fields)
    fields_option = getattr(meta, "fields", None)
    if meta is not None and fields_option is None and not hasattr(meta, "exclude"):
        raise TypeError(f"{form_name}.Meta must define fields or exclude.")
    exclude = _meta_names(getattr(meta, "exclude", None), "exclude") or ()
    if fields_option == "__all__" or (fields_option is None and meta is not None):
        selected = list(model_names)
    else:
        selected = list(
            _meta_names(fields_option, "fields", allow_all=True) or ()
        )
    selected.extend(name for name in declared if name not in selected)
    if "id" in model_names and "id" not in selected and "id" not in exclude:
        selected.insert(0, "id")

    unknown = (set(selected) | set(exclude)) - set(model_names)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TypeError(f"Unknown {model_type.__name__} field(s): {names}.")
    conflicting = set(declared) & set(exclude)
    if conflicting:
        names = ", ".join(sorted(conflicting))
        raise TypeError(
            f"{form_name} explicitly declares excluded field(s): {names}."
        )
    return [name for name in model_names if name in selected and name not in exclude]


def _annotation_type(annotation):
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        values = [value for value in get_args(annotation) if value is not type(None)]
        if len(values) == 1:
            return values[0]
    return annotation


def _allows_none(annotation) -> bool:
    origin = get_origin(annotation)
    return origin in (types.UnionType, Union) and type(None) in get_args(annotation)


def _maximum_length(model_field) -> int:
    for constraint in model_field.metadata:
        value = getattr(constraint, "max_length", None)
        if value is not None:
            return value
    return 0


def _automatic_model_field(
    form_name: str,
    name: str,
    model_field,
) -> ModelField:
    value_type = _annotation_type(model_field.annotation)
    required = model_field.is_required()
    label = model_field.title or name.replace("_", " ")
    if name == "id" and value_type is int:
        return IntegerModelField(
            label,
            name=name,
            required=required,
            hidden=True,
        )
    if name == "id" and value_type is str:
        return TextModelField(
            label,
            name=name,
            required=required,
            hidden=True,
        )
    if value_type is str:
        return TextModelField(
            label,
            name=name,
            required=required,
            max_length=_maximum_length(model_field),
        )
    if value_type is int:
        return IntegerModelField(label, name=name, required=required)
    if value_type is float:
        return FloatModelField(label, name=name, required=required)
    if value_type is bool:
        if _allows_none(model_field.annotation):
            raise TypeError(
                f"{form_name} cannot choose a two-state checkbox for nullable "
                f"field {name}; declare a ModelField explicitly."
            )
        return BooleanModelField(label, name=name, required=required)
    if value_type is date:
        return DateModelField(label, name=name, required=required)
    raise TypeError(
        f"{form_name} cannot choose a widget for {name}: {model_field.annotation}; "
        "declare a ModelField explicitly."
    )


@js.inline("{form}.constructor.__pyjs_fields__")
def model_form_fields(form: object) -> list[ModelField]:
    return type(form).__pyjs_fields__


@js.inline("{form}.constructor.__pyjs_model_fields__")
def model_form_model_fields(form: object) -> list[str]:
    return type(form).__pyjs_model_fields__


@js.inline("{form}.constructor.__pyjs_model__.model_validate({values})")
def model_form_validate(
    form: object,
    values: dict[str, object],
) -> BaseModel:
    return type(form).__pyjs_model__.model_validate(values)


@js.inline("{form}.constructor.__pyjs_fields_by_name__.get({name}) ?? null")
def model_form_field(form: object, name: str) -> ModelField | None:
    return type(form).__pyjs_fields_by_name__.get(name)


@js
class ModelForm(ProxyElement, metaclass=ModelFormMetaclass):
    @nojs
    @classmethod
    def __class_getitem__(cls, model_type: type):
        return ModelAdapterAlias(cls, model_type)

    def __init__(self, model: BaseModel | None = None):
        self._field_elements: dict[str, Element] = {}
        self._error_elements: dict[str, Element] = {}
        self._error_controls: list[HTMLInputElement] = []
        self._error_descriptions: list[str] = []
        self.element = form(
            tw("grid gap-4"),
            {"data-slot": "model-form"},
        )
        if model is None:
            return
        for field in model_form_fields(self):
            field_element = field.create(model)
            field_element.setAttribute("data-model-field", field.name)
            self._field_elements[field.name] = field_element
            self.element.append(field_element)

    def set_model(self, model: BaseModel):
        for field in model_form_fields(self):
            if field.name in self._field_elements:
                field.update(self._field_elements[field.name], model)

    def values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name in model_form_model_fields(self):
            values[name] = self.get_value(name)
        return values

    @js
    def read_model(self) -> BaseModel:
        return model_form_validate(self, self.values())

    @read_model.analyze
    def read_model(call):
        return call.receiver_metadata_type(
            "__pyjs_model__",
            runtime_method="model_validate",
        )

    def get_value(self, name: str) -> object:
        return self.get_field(name).read(self.get_field_element(name))

    def get_field(self, name: str) -> ModelField:
        field = model_form_field(self, name)
        if field is None:
            raise ValueError("Unknown model form field: " + name)
        return field

    def get_field_element(self, name: str) -> Element:
        if name not in self._field_elements:
            raise ValueError("Unknown model form field: " + name)
        return self._field_elements[name]

    def get_control(self, name: str) -> HTMLInputElement:
        return input_control(self.get_field_element(name))

    def clear_errors(self):
        for error in self._error_elements.values():
            error.remove()
        for index in range(len(self._error_controls)):
            control: HTMLInputElement = self._error_controls[index]
            control.removeAttribute("aria-invalid")
            described_by: str = self._error_descriptions[index]
            if described_by:
                control.setAttribute("aria-describedby", described_by)
            else:
                control.removeAttribute("aria-describedby")
        self._error_elements = {}
        self._error_controls = []
        self._error_descriptions = []

    def set_errors(self, operation_error: OperationError, argument: str = ""):
        self.clear_errors()
        first_control: HTMLInputElement | None = None
        for issue in operation_error.issues:
            location_index = 0
            if (
                argument != ""
                and len(issue.location) > 0
                and issue.location[0] == argument
            ):
                location_index = 1
            name = ""
            if location_index < len(issue.location):
                candidate = issue.location[location_index]
                if candidate in self._field_elements:
                    name = candidate

            error = self._error_elements.get(name, None)
            if error is not None:
                error.append(" " + issue.detail)
                continue

            error_id = "model-error-" + crypto.randomUUID()
            error = FieldError(issue.detail)
            error.setAttribute("data-model-error", name)
            error.setAttribute("id", error_id)
            self._error_elements[name] = error
            if name == "":
                self.element.append(error)
                continue

            field_element = self._field_elements[name]
            if isinstance(field_element, HTMLInputElement):
                self.element.append(error)
            else:
                field_element.append(error)
            field = self.get_field(name)
            control = field.error_control(field_element)
            if control is not None:
                described_by = control.getAttribute("aria-describedby")
                self._error_controls.append(control)
                self._error_descriptions.append(described_by or "")
                field.mark_invalid(control, error_id)
            if first_control is None and control is not None:
                first_control = control
        if first_control is not None:
            first_control.focus()

    def _hydrate(self, element: Element):
        super()._hydrate(element)
        self._field_elements = {}
        self._error_elements = {}
        self._error_controls = []
        self._error_descriptions = []
        for field in model_form_fields(self):
            field_element = self.element.querySelector(
                '[data-model-field="' + field.name + '"]'
            )
            if not isinstance(field_element, Element):
                raise ValueError("Missing model form field: " + field.name)
            self._field_elements[field.name] = field_element
        return self


@js
class ModelColumn:
    def __init__(self, label: str = "", *, name: str = ""):
        self.name = name
        self.label = label or name.replace("_", " ")

    @nojs
    def javascript_options(self) -> dict[str, object]:
        return {"label": self.label, "name": self.name}

    def render(self, model: BaseModel) -> str:
        raise TypeError("ModelColumn.render() must be overridden.")


@js
class TextModelColumn(ModelColumn):
    def render(self, model: BaseModel) -> str:
        value = text_model_value(model, self.name)
        return "" if value is None else value


@js
class BooleanModelColumn(ModelColumn):
    def render(self, model: BaseModel) -> str:
        return "Yes" if boolean_model_value(model, self.name) else "No"


class DataTableMetaclass(type):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
        columns_by_name = _declared_members(
            bases,
            namespace,
            "__pyjs_columns__",
            ModelColumn,
        )
        columns = list(columns_by_name.values())
        model_type = _adapter_model_type(namespace)
        if model_type is not None:
            unknown = [
                column.name
                for column in columns
                if column.name not in model_type.model_fields
            ]
            if unknown:
                names = ", ".join(unknown)
                raise TypeError(f"Unknown {model_type.__name__} column(s): {names}.")
            namespace["__pyjs_model__"] = model_type
            namespace["__js_append__"] = lambda included: _adapter_javascript(
                name,
                model_type,
                "__pyjs_columns__",
                columns,
            )
            namespace["__js_append_dependencies__"] = (
                model_type,
                *(type(column) for column in columns),
            )
        namespace["__pyjs_columns__"] = columns
        return super().__new__(mcls, name, bases, namespace, **kwargs)


@js.inline("{table}.constructor.__pyjs_columns__")
def data_table_columns(table: object) -> list[ModelColumn]:
    return type(table).__pyjs_columns__


@js
class DataTable(ProxyElement, metaclass=DataTableMetaclass):
    @nojs
    @classmethod
    def __class_getitem__(cls, model_type: type):
        return ModelAdapterAlias(cls, model_type)

    def __init__(self):
        self.element = tag(
            "div",
            tw("grid gap-3 overflow-x-auto"),
            {"data-slot": "data-table"},
        )

    def set_page[Value: BaseModel](
        self,
        page: Page[Value],
    ) -> Self:
        headings: list[Element] = []
        for column in data_table_columns(self):
            headings.append(
                tag(
                    "th",
                    tw("px-3 py-2 text-left text-xs font-semibold text-slate-600"),
                    {"scope": "col"},
                    column.label,
                )
            )
        rows: list[Element] = []
        for item in page.items:
            cells: list[Element] = []
            for column in data_table_columns(self):
                cells.append(
                    tag(
                        "td",
                        tw("border-t border-slate-200 px-3 py-2 text-sm text-slate-800"),
                        column.render(item),
                    )
                )
            rows.append(tag("tr", *cells))
        count = len(page.items)
        summary = f"Showing {count} items"
        if page.total is not None:
            summary = f"Showing {count} of {page.total} items"
        if page.next is None:
            self.element.removeAttribute("data-page-next")
        else:
            self.element.setAttribute("data-page-next", page.next)
        if page.previous is None:
            self.element.removeAttribute("data-page-previous")
        else:
            self.element.setAttribute("data-page-previous", page.previous)
        self.element.replaceChildren(
            tag(
                "table",
                tw("w-full border-collapse rounded-md border border-slate-200 bg-white"),
                tag("thead", tag("tr", *headings)),
                tag("tbody", *rows),
            ),
            tag(
                "p",
                tw("text-sm text-slate-500"),
                summary,
            ),
        )
        return self

    def next_cursor(self) -> str | None:
        return self.element.getAttribute("data-page-next")

    def previous_cursor(self) -> str | None:
        return self.element.getAttribute("data-page-previous")
