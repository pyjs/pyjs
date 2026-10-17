"""Android framework declarations resolved from one pinned SDK platform."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Self

from pyjs.java import (
    JVMAnnotation,
    JVMBindingError,
    JVMClass,
    JVMClassBinding,
    JVMClasspath,
    JVMExternalClass,
    JVMField,
    JVMFieldBinding,
    JVMMethod,
    JVMMethodBinding,
    JVMTypeAnnotation,
    render_jvm_bindings,
)


class AndroidNullability(Enum):
    UNKNOWN = "unknown"
    NON_NULL = "non-null"
    NULLABLE = "nullable"

    @classmethod
    def from_annotations(
        cls,
        annotations: tuple[JVMAnnotation | JVMTypeAnnotation, ...],
    ) -> AndroidNullability:
        names = {value.descriptor.rsplit("/", 1)[-1] for value in annotations}
        if "Nullable;" in names:
            return cls.NULLABLE
        if "NonNull;" in names or "NotNull;" in names:
            return cls.NON_NULL
        return cls.UNKNOWN


@dataclass(frozen=True)
class AndroidAvailability:
    since: int
    deprecated: int | None = None
    removed: int | None = None

    def available_at(self, api: int) -> bool:
        return self.since <= api and (self.removed is None or api < self.removed)


def _level(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class AndroidAPI:
    """A lazy classpath plus API-level metadata for one Android SDK platform."""

    def __init__(
        self,
        platform: Path,
        api: int,
        classpath: tuple[Path, ...] = (),
    ) -> None:
        self.platform = Path(platform)
        self.api = api
        self.android_jar = self.platform / "android.jar"
        if not self.android_jar.is_file():
            raise FileNotFoundError(
                f"Android API {api} framework JAR not found at {self.android_jar}"
            )
        self.dependencies = tuple(Path(value) for value in classpath)
        self.classpath = JVMClasspath(*self.dependencies, self.android_jar)
        self._availability: dict[
            tuple[str, str, str | None], AndroidAvailability
        ] | None = None

    @classmethod
    def from_sdk(
        cls,
        api: int,
        sdk=None,
        *,
        classpath: tuple[Path, ...] = (),
    ) -> AndroidAPI:
        if sdk is None:
            from pyjs.tooling.android import AndroidSDK

            sdk = AndroidSDK()
        return cls(
            sdk.root / "platforms" / f"android-{api}",
            api,
            classpath,
        )

    @property
    def sources(self) -> Path | None:
        value = self.platform / "android-stubs-src.jar"
        return value if value.is_file() else None

    @property
    def annotations(self) -> Path | None:
        value = self.platform / "data" / "annotations.zip"
        return value if value.is_file() else None

    @property
    def api_versions(self) -> Path | None:
        value = self.platform / "data" / "api-versions.xml"
        return value if value.is_file() else None

    def find_class(self, name: str) -> JVMClass | None:
        return self.classpath.find_class(name)

    def require_class(self, name: str) -> JVMClass:
        return self.classpath.require_class(name)

    def class_availability(self, value: JVMClass | str) -> AndroidAvailability | None:
        name = value.name if isinstance(value, JVMClass) else value.replace(".", "/")
        return self._availability_for("class", name, None)

    def method_availability(
        self,
        owner: JVMClass | str,
        method: JVMMethod,
    ) -> AndroidAvailability | None:
        name = owner.name if isinstance(owner, JVMClass) else owner.replace(".", "/")
        return self._availability_for(
            "method",
            name,
            method.name + method.descriptor,
        )

    def field_availability(
        self,
        owner: JVMClass | str,
        field: JVMField,
    ) -> AndroidAvailability | None:
        name = owner.name if isinstance(owner, JVMClass) else owner.replace(".", "/")
        return self._availability_for("field", name, field.name)

    @staticmethod
    def method_return_nullability(method: JVMMethod) -> AndroidNullability:
        annotations = method.annotations + tuple(
            value for value in method.type_annotations if not value.path
        )
        return AndroidNullability.from_annotations(annotations)

    @staticmethod
    def parameter_nullability(
        method: JVMMethod,
        index: int,
    ) -> AndroidNullability:
        try:
            parameter = method.parameters[index]
        except IndexError:
            raise IndexError(
                f"Android method parameter index {index} is out of range"
            ) from None
        annotations = parameter.annotations + tuple(
            value for value in parameter.type_annotations if not value.path
        )
        return AndroidNullability.from_annotations(annotations)

    @staticmethod
    def field_nullability(field: JVMField) -> AndroidNullability:
        annotations = field.annotations + tuple(
            value for value in field.type_annotations if not value.path
        )
        return AndroidNullability.from_annotations(annotations)

    def render_bindings(
        self,
        bindings: tuple[JVMClassBinding, ...],
        *,
        min_sdk: int | None = None,
        external_classes: tuple[JVMExternalClass, ...] = (),
    ) -> str:
        """Render selected declarations valid for the chosen Android SDKs."""
        if min_sdk is not None:
            if min_sdk <= 0:
                raise ValueError("Android minimum SDK must be positive")
            if min_sdk > self.api:
                raise ValueError(
                    f"Android minimum SDK {min_sdk} exceeds compile SDK {self.api}"
                )
        resolved_bindings = []
        for binding in bindings:
            value = self.require_class(binding.name)
            self._validate_availability(
                f"class {value.name}",
                self.class_availability(value),
                min_sdk,
            )
            methods = []
            for selected in binding.methods:
                matches = [
                    method
                    for method in value.methods
                    if method.name == selected.name
                    and method.descriptor == selected.descriptor
                ]
                if len(matches) != 1:
                    raise JVMBindingError(
                        f"JVM method {value.name}.{selected.name}"
                        f"{selected.descriptor} was not found exactly once"
                    )
                method = matches[0]
                self._validate_availability(
                    f"method {value.name}.{selected.name}{selected.descriptor}",
                    self.method_availability(value, method),
                    min_sdk,
                )
                methods.append(self._infer_method_nullability(selected, method))
            fields = []
            for selected in binding.fields:
                matches = [
                    field
                    for field in value.fields
                    if field.name == selected.name
                    and field.descriptor == selected.descriptor
                ]
                if len(matches) != 1:
                    raise JVMBindingError(
                        f"JVM field {value.name}.{selected.name}:"
                        f"{selected.descriptor} was not found exactly once"
                    )
                field = matches[0]
                self._validate_availability(
                    f"field {value.name}.{selected.name}",
                    self.field_availability(value, field),
                    min_sdk,
                )
                fields.append(self._infer_field_nullability(selected, field))
            resolved_bindings.append(
                replace(binding, methods=tuple(methods), fields=tuple(fields))
            )
        return render_jvm_bindings(
            self.classpath,
            tuple(resolved_bindings),
            external_classes=external_classes,
        )

    @classmethod
    def _infer_method_nullability(
        cls,
        selected: JVMMethodBinding,
        method: JVMMethod,
    ) -> JVMMethodBinding:
        nullable_return = selected.nullable_return
        if nullable_return is None:
            nullable_return = (
                cls.method_return_nullability(method)
                is AndroidNullability.NULLABLE
            )
        nullable_parameters = selected.nullable_parameters
        if nullable_parameters is None:
            nullable_parameters = tuple(
                index
                for index, _parameter in enumerate(method.parameters)
                if cls.parameter_nullability(method, index)
                is AndroidNullability.NULLABLE
            )
        return replace(
            selected,
            nullable_return=nullable_return,
            nullable_parameters=nullable_parameters,
        )

    @classmethod
    def _infer_field_nullability(
        cls,
        selected: JVMFieldBinding,
        field: JVMField,
    ) -> JVMFieldBinding:
        nullable = selected.nullable
        if nullable is None:
            nullable = cls.field_nullability(field) is AndroidNullability.NULLABLE
        return replace(selected, nullable=nullable)

    def _validate_availability(
        self,
        description: str,
        availability: AndroidAvailability | None,
        min_sdk: int | None,
    ) -> None:
        if availability is None:
            return
        if not availability.available_at(self.api):
            raise JVMBindingError(
                f"Android {description} is unavailable at compile SDK {self.api}"
            )
        if min_sdk is not None and not availability.available_at(min_sdk):
            raise JVMBindingError(
                f"Android {description} requires API {availability.since}, "
                f"but the minimum SDK is {min_sdk}"
            )

    def _availability_for(
        self,
        kind: str,
        owner: str,
        member: str | None,
    ) -> AndroidAvailability | None:
        if self._availability is None:
            self._availability = self._read_availability()
        return self._availability.get((kind, owner, member))

    def _read_availability(
        self,
    ) -> dict[tuple[str, str, str | None], AndroidAvailability]:
        source = self.api_versions
        if source is None:
            return {}
        result = {}
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != "class":
                continue
            name = element.attrib["name"]
            since = _level(element.attrib.get("since"), 1)
            if since is None:
                since = 1
            class_availability = AndroidAvailability(
                since=since,
                deprecated=_level(element.attrib.get("deprecated")),
                removed=_level(element.attrib.get("removed")),
            )
            result[("class", name, None)] = class_availability
            for member in element:
                if member.tag not in {"field", "method"}:
                    continue
                result[(member.tag, name, member.attrib["name"])] = AndroidAvailability(
                    since=_level(member.attrib.get("since"), since) or since,
                    deprecated=_level(member.attrib.get("deprecated")),
                    removed=_level(member.attrib.get("removed")),
                )
            element.clear()
        return result

    def close(self) -> None:
        self.classpath.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["AndroidAPI", "AndroidAvailability", "AndroidNullability"]
