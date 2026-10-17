"""Generate the JVM bridge for Python UI Automator device interactions."""

from pyjs.java.classfile import Bytecode, ClassFile, Field, Method

DEVICE_CLASS = "org/pyjs/testing/PyjsDevice"
ELEMENT_CLASS = "org/pyjs/testing/PyjsDeviceElement"
UI_DEVICE = "androidx/test/uiautomator/UiDevice"
UI_OBJECT = "Landroidx/test/uiautomator/UiObject2;"


def _reference(
    class_file: ClassFile,
    owner: str,
    name: str,
    descriptor: str,
) -> bytes:
    return class_file.method_reference(owner, name, descriptor).to_bytes(2, "big")


def _default_constructor(class_file: ClassFile) -> Method:
    code = Bytecode()
    code.local(0x19, 0)
    code.emit(
        0xB7,
        _reference(class_file, "java/lang/Object", "<init>", "()V"),
    )
    code.emit(0xB1)
    return Method(0x0001, "<init>", "()V", code.render(), 1, 1)


def _load_device(class_file: ClassFile, code: Bytecode) -> None:
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/platform/app/InstrumentationRegistry",
            "getInstrumentation",
            "()Landroid/app/Instrumentation;",
        ),
    )
    code.emit(
        0xB8,
        _reference(
            class_file,
            UI_DEVICE,
            "getInstance",
            f"(Landroid/app/Instrumentation;)L{UI_DEVICE};",
        ),
    )


def uiautomator_element_class() -> tuple[str, bytes]:
    class_file = ClassFile(ELEMENT_CLASS)
    class_file.add_field(Field(0x0012, "element", UI_OBJECT))
    constructor = Bytecode()
    constructor.local(0x19, 0)
    constructor.emit(
        0xB7,
        _reference(class_file, "java/lang/Object", "<init>", "()V"),
    )
    constructor.local(0x19, 0)
    constructor.local(0x19, 1)
    field = class_file.field_reference(ELEMENT_CLASS, "element", UI_OBJECT)
    constructor.emit(0xB5, field.to_bytes(2, "big"))
    constructor.emit(0xB1)
    class_file.add_method(
        Method(
            0x0001,
            "<init>",
            f"({UI_OBJECT})V",
            constructor.render(),
            2,
            2,
        )
    )
    for name, native_name, result, opcode in (
        ("click", "click", "V", 0xB1),
        ("text", "getText", "Ljava/lang/String;", 0xB0),
    ):
        code = Bytecode()
        code.local(0x19, 0)
        code.emit(0xB4, field.to_bytes(2, "big"))
        code.emit(
            0xB6,
            _reference(
                class_file,
                "androidx/test/uiautomator/UiObject2",
                native_name,
                f"(){result}",
            ),
        )
        code.emit(opcode)
        class_file.add_method(
            Method(0x0001, name, f"(){result}", code.render(), 1, 1)
        )
    drag = Bytecode()
    drag.local(0x19, 0)
    drag.emit(0xB4, field.to_bytes(2, "big"))
    drag.local(0x19, 1)
    drag.emit(0xB4, field.to_bytes(2, "big"))
    drag.emit(
        0xB6,
        _reference(
            class_file,
            "androidx/test/uiautomator/UiObject2",
            "getVisibleCenter",
            "()Landroid/graphics/Point;",
        ),
    )
    drag.emit(0x59)
    drag.local(0x15, 3)
    drag.local(0x15, 4)
    drag.emit(0xB6, _reference(
        class_file, "android/graphics/Point", "offset", "(II)V",
    ))
    drag.local(0x15, 2)
    drag.emit(
        0xB6,
        _reference(
            class_file,
            "androidx/test/uiautomator/UiObject2",
            "drag",
            "(Landroid/graphics/Point;I)V",
        ),
    )
    drag.emit(0xB1)
    class_file.add_method(
        Method(
            0x0001,
            "drag_to",
            f"(L{ELEMENT_CLASS};III)V",
            drag.render(),
            5,
            5,
        )
    )
    return ELEMENT_CLASS, class_file.render()


def _find_method(class_file: ClassFile, name: str, selector: str) -> Method:
    code = Bytecode()
    _load_device(class_file, code)
    code.local(0x19, 0)
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/uiautomator/By",
            selector,
            "(Ljava/lang/String;)Landroidx/test/uiautomator/BySelector;",
        ),
    )
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/uiautomator/Until",
            "findObject",
            "(Landroidx/test/uiautomator/BySelector;)"
            "Landroidx/test/uiautomator/SearchCondition;",
        ),
    )
    code.local(0x16, 1)
    code.emit(
        0xB6,
        _reference(
            class_file,
            UI_DEVICE,
            "wait",
            "(Landroidx/test/uiautomator/SearchCondition;J)Ljava/lang/Object;",
        ),
    )
    element = class_file.constants.class_("androidx/test/uiautomator/UiObject2")
    code.emit(0xC0, element.to_bytes(2, "big"))
    code.emit(0x59)
    code.branch(0xC7, "found")
    code.emit(0x57)
    error = class_file.constants.class_("java/lang/AssertionError")
    code.emit(0xBB, error.to_bytes(2, "big"))
    code.emit(0x59)
    message = class_file.constants.string("UI Automator selector did not match")
    if message <= 0xFF:
        code.emit(0x12, message.to_bytes(1, "big"))
    else:
        code.emit(0x13, message.to_bytes(2, "big"))
    code.emit(
        0xB7,
        _reference(
            class_file,
            "java/lang/AssertionError",
            "<init>",
            "(Ljava/lang/Object;)V",
        ),
    )
    code.emit(0xBF)
    code.mark("found")
    code.local(0x3A, 3)
    wrapper = class_file.constants.class_(ELEMENT_CLASS)
    code.emit(0xBB, wrapper.to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x19, 3)
    code.emit(
        0xB7,
        _reference(class_file, ELEMENT_CLASS, "<init>", f"({UI_OBJECT})V"),
    )
    code.emit(0xB0)
    return Method(
        0x0009,
        name,
        f"(Ljava/lang/String;J)L{ELEMENT_CLASS};",
        code.render(),
        4,
        4,
    )


def uiautomator_device_class() -> tuple[str, bytes]:
    class_file = ClassFile(DEVICE_CLASS)
    class_file.add_method(_default_constructor(class_file))
    get = Bytecode()
    owner = class_file.constants.class_(DEVICE_CLASS)
    get.emit(0xBB, owner.to_bytes(2, "big"))
    get.emit(0x59)
    get.emit(
        0xB7,
        _reference(class_file, DEVICE_CLASS, "<init>", "()V"),
    )
    get.emit(0xB0)
    class_file.add_method(
        Method(0x0009, "get", f"()L{DEVICE_CLASS};", get.render(), 2, 0)
    )
    for name, native_name, result, opcode in (
        ("press_home", "pressHome", "Z", 0xB1),
        ("current_package", "getCurrentPackageName", "Ljava/lang/String;", 0xB0),
    ):
        code = Bytecode()
        _load_device(class_file, code)
        code.emit(
            0xB6,
            _reference(class_file, UI_DEVICE, native_name, f"(){result}"),
        )
        if result == "Z":
            code.emit(0x57)
        code.emit(opcode)
        descriptor = "()V" if result == "Z" else f"(){result}"
        class_file.add_method(
            Method(0x0001, name, descriptor, code.render(), 1, 1)
        )
    class_file.add_method(_find_method(class_file, "findText", "text"))
    class_file.add_method(_find_method(class_file, "findResource", "res"))
    return DEVICE_CLASS, class_file.render()


__all__ = ["uiautomator_device_class", "uiautomator_element_class"]
