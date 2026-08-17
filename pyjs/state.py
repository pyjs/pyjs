import json

SUPPORTED_STATE_TYPES = (str, int, float, bool)


class StateField:
    __pyjs_state__ = True

    def __init__(self, default):
        if type(default) not in SUPPORTED_STATE_TYPES:
            raise TypeError("state() defaults must be str, int, float, or bool")
        self.default = default
        self.value_type = type(default)
        self.name = ""
        self.attribute_name = ""

    def __set_name__(self, owner, name: str):
        self.name = name
        self.attribute_name = name.replace("_", "-")

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self.value_type is bool:
            return instance.hasAttribute(self.attribute_name)
        value = instance.getAttribute(self.attribute_name)
        if value is None:
            return self.default
        if self.value_type is int:
            return int(value)
        if self.value_type is float:
            return float(value)
        return value

    def __set__(self, instance, value):
        # A state descriptor overrides any WebIDL field initialized by its DOM base class.
        if "_initialized" not in instance.__dict__:
            return
        if self.value_type is bool:
            if value:
                instance.setAttribute(self.attribute_name, "")
            else:
                instance.removeAttribute(self.attribute_name)
        else:
            instance.setAttribute(self.attribute_name, str(value))

    def materialize(self, instance):
        if instance.hasAttribute(self.attribute_name):
            return
        if self.value_type is bool and not self.default:
            return
        self.__set__(instance, self.default)

    def javascript(self, class_name: str) -> str:
        default = json.dumps(self.default)
        attribute = json.dumps(self.attribute_name)
        if self.value_type is bool:
            getter = f"return this.hasAttribute({attribute});"
            setter = (
                f"if (value) this.setAttribute({attribute}, ''); "
                f"else this.removeAttribute({attribute});"
            )
        else:
            converted = "value"
            if self.value_type in (int, float):
                converted = "Number(value)"
            getter = (
                f"const value = this.getAttribute({attribute}); "
                f"return value === null ? {default} : {converted};"
            )
            setter = (
                f"if (value === null || value === undefined) "
                f"this.removeAttribute({attribute}); "
                f"else this.setAttribute({attribute}, String(value));"
            )
        return (
            f"Object.defineProperty({class_name}.prototype, {json.dumps(self.name)}, "
            f"{{get() {{ {getter} }}, set(value) {{ {setter} }}}});"
        )

    def javascript_default(self) -> str:
        return (
            f"if (!this.hasAttribute({json.dumps(self.attribute_name)})) "
            f"this.{self.name} = {json.dumps(self.default)};"
        )


def state(default):
    return StateField(default)


def effect(*fields: StateField):
    if not fields or not all(isinstance(field, StateField) for field in fields):
        raise TypeError("effect() requires one or more fields declared with state()")

    def decorate(function):
        function.__pyjs_effect_fields__ = fields
        function.__js_keep__ = True
        return function

    return decorate
