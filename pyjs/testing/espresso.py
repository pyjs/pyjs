"""Generate the small JVM bridge used by the Python Android testing API."""

from pyjs.java.classfile import Bytecode, ClassFile, Field, Method

CLASS_NAME = "org/pyjs/testing/PyjsView"
ANDROID_CLASS_NAME = "org/pyjs/testing/PyjsAndroid"
MATCHER = "Lorg/hamcrest/Matcher;"
INTERACTION = "Landroidx/test/espresso/ViewInteraction;"
ACTION = "Landroidx/test/espresso/ViewAction;"
ASSERTION = "Landroidx/test/espresso/ViewAssertion;"


def _reference(
    class_file: ClassFile,
    owner: str,
    name: str,
    descriptor: str,
) -> bytes:
    return class_file.method_reference(owner, name, descriptor).to_bytes(2, "big")


def _constructor(class_file: ClassFile) -> Method:
    code = Bytecode()
    code.local(0x19, 0)
    code.emit(0xB7, _reference(class_file, "java/lang/Object", "<init>", "()V"))
    code.local(0x19, 0)
    code.local(0x19, 1)
    field = class_file.field_reference(CLASS_NAME, "matcher", MATCHER)
    code.emit(0xB5, field.to_bytes(2, "big"))
    code.emit(0xB1)
    return Method(0x0001, "<init>", f"({MATCHER})V", code.render(), 2, 2)


def _factory(class_file: ClassFile, name: str, argument: str, matcher: str) -> Method:
    code = Bytecode()
    owner = class_file.constants.class_(CLASS_NAME)
    code.emit(0xBB, owner.to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x15 if argument == "I" else 0x19, 0)
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/matcher/ViewMatchers",
            matcher,
            f"({argument}){MATCHER}",
        ),
    )
    code.emit(0xB7, _reference(class_file, CLASS_NAME, "<init>", f"({MATCHER})V"))
    code.emit(0xB0)
    return Method(
        0x0009,
        name,
        f"({argument})L{CLASS_NAME};",
        code.render(),
        3,
        1,
    )


def _load_interaction(class_file: ClassFile, code: Bytecode) -> None:
    code.local(0x19, 0)
    field = class_file.field_reference(CLASS_NAME, "matcher", MATCHER)
    code.emit(0xB4, field.to_bytes(2, "big"))
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/Espresso",
            "onView",
            f"({MATCHER}){INTERACTION}",
        ),
    )
    root = class_file.field_reference(CLASS_NAME, "root", MATCHER)
    code.local(0x19, 0)
    code.emit(0xB4, root.to_bytes(2, "big"))
    code.branch(0xC6, "root.default")
    code.local(0x19, 0)
    code.emit(0xB4, root.to_bytes(2, "big"))
    code.emit(0xB6, _reference(
        class_file, "androidx/test/espresso/ViewInteraction", "inRoot",
        f"({MATCHER}){INTERACTION}",
    ))
    code.mark("root.default")


def _action(
    class_file: ClassFile,
    name: str,
    espresso_name: str,
    argument: str = "",
) -> Method:
    code = Bytecode()
    _load_interaction(class_file, code)
    code.emit(0x04)
    action_class = class_file.constants.class_("androidx/test/espresso/ViewAction")
    code.emit(0xBD, action_class.to_bytes(2, "big"))
    code.emit(0x59)
    code.emit(0x03)
    if argument:
        code.local(0x15 if argument == "I" else 0x19, 1)
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/action/ViewActions",
            espresso_name,
            f"({argument}){ACTION}",
        ),
    )
    code.emit(0x53)
    code.emit(
        0xB6,
        _reference(
            class_file,
            "androidx/test/espresso/ViewInteraction",
            "perform",
            f"([{ACTION}){INTERACTION}",
        ),
    )
    code.emit(0x57)
    code.emit(0xB1)
    descriptor = f"({argument})V"
    return Method(0x0001, name, descriptor, code.render(), 5, 2 if argument else 1)


def _assertion(
    class_file: ClassFile,
    name: str,
    matcher_name: str,
    argument: str = "",
) -> Method:
    code = Bytecode()
    _load_interaction(class_file, code)
    if argument:
        code.local(0x19, 1)
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/matcher/ViewMatchers",
            matcher_name,
            f"({argument}){MATCHER}",
        ),
    )
    code.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/assertion/ViewAssertions",
            "matches",
            f"({MATCHER}){ASSERTION}",
        ),
    )
    code.emit(
        0xB6,
        _reference(
            class_file,
            "androidx/test/espresso/ViewInteraction",
            "check",
            f"({ASSERTION}){INTERACTION}",
        ),
    )
    code.emit(0x57)
    code.emit(0xB1)
    return Method(
        0x0001,
        name,
        f"({argument})V",
        code.render(),
        2,
        2 if argument else 1,
    )


def espresso_view_class() -> tuple[str, bytes]:
    class_file = ClassFile(CLASS_NAME)
    class_file.add_field(Field(0x0012, "matcher", MATCHER))
    class_file.add_field(Field(0x0002, "root", MATCHER))
    class_file.add_method(_constructor(class_file))
    dialog = Bytecode()
    dialog.emit(0xBB, class_file.constants.class_(CLASS_NAME).to_bytes(2, "big"))
    dialog.emit(0x59)
    dialog.local(0x19, 0)
    matcher = class_file.field_reference(CLASS_NAME, "matcher", MATCHER)
    dialog.emit(0xB4, matcher.to_bytes(2, "big"))
    dialog.emit(0xB7, _reference(class_file, CLASS_NAME, "<init>", f"({MATCHER})V"))
    dialog.emit(0x59)
    dialog.emit(0xB8, _reference(
        class_file, "androidx/test/espresso/matcher/RootMatchers", "isDialog", f"(){MATCHER}",
    ))
    root = class_file.field_reference(CLASS_NAME, "root", MATCHER)
    dialog.emit(0xB5, root.to_bytes(2, "big"))
    dialog.emit(0xB0)
    class_file.add_method(Method(
        0x0001, "in_dialog", f"()L{CLASS_NAME};", dialog.render(), 3, 1,
    ))
    class_file.add_method(_factory(class_file, "fromText", "Ljava/lang/String;", "withText"))
    class_file.add_method(_factory(class_file, "fromId", "I", "withId"))
    class_file.add_method(_action(class_file, "click", "click"))
    class_file.add_method(_action(class_file, "press_key", "pressKey", "I"))
    class_file.add_method(_action(class_file, "ime_action", "pressImeActionButton"))
    class_file.add_method(
        _action(class_file, "close_keyboard", "closeSoftKeyboard")
    )
    class_file.add_method(_action(class_file, "long_click", "longClick"))
    class_file.add_method(
        _action(
            class_file,
            "replace_text",
            "replaceText",
            "Ljava/lang/String;",
        )
    )
    class_file.add_method(_action(class_file, "scroll_to", "scrollTo"))
    class_file.add_method(_assertion(class_file, "assert_displayed", "isDisplayed"))
    check = Bytecode()
    _load_interaction(class_file, check)
    check.local(0x19, 1)
    check.emit(0xB6, _reference(
        class_file, "androidx/test/espresso/ViewInteraction", "check",
        f"({ASSERTION}){INTERACTION}",
    ))
    check.emit(0x57)
    check.emit(0xB1)
    class_file.add_method(Method(
        0x0001, "check", f"({ASSERTION})V", check.render(), 2, 2,
    ))
    absent = Bytecode()
    _load_interaction(class_file, absent)
    absent.emit(0xB8, _reference(
        class_file, "androidx/test/espresso/assertion/ViewAssertions",
        "doesNotExist", f"(){ASSERTION}",
    ))
    absent.emit(0xB6, _reference(
        class_file, "androidx/test/espresso/ViewInteraction", "check",
        f"({ASSERTION}){INTERACTION}",
    ))
    absent.emit(0x57)
    absent.emit(0xB1)
    class_file.add_method(Method(0x0001, "assert_absent", "()V", absent.render(), 2, 1))
    class_file.add_method(
        _assertion(
            class_file,
            "assert_text",
            "withText",
            "Ljava/lang/String;",
        )
    )
    return CLASS_NAME, class_file.render()


def espresso_android_class() -> tuple[str, bytes]:
    scenario = "Landroidx/test/core/app/ActivityScenario;"
    class_file = ClassFile(ANDROID_CLASS_NAME)
    class_file.add_field(Field(0x000A, "scenario", scenario))
    close = Bytecode()
    field = class_file.field_reference(ANDROID_CLASS_NAME, "scenario", scenario)
    close.emit(0xB2, field.to_bytes(2, "big"))
    close.branch(0xC6, "closed")
    close.emit(0xB2, field.to_bytes(2, "big"))
    close.emit(
        0xB6,
        _reference(
            class_file,
            "androidx/test/core/app/ActivityScenario",
            "close",
            "()V",
        ),
    )
    close.emit(0x01)
    close.emit(0xB3, field.to_bytes(2, "big"))
    close.mark("closed")
    close.emit(0xB1)
    class_file.add_method(
        Method(0x0009, "close", "()V", close.render(), 1, 0)
    )
    code = Bytecode()
    code.emit(
        0xB8,
        _reference(class_file, ANDROID_CLASS_NAME, "close", "()V"),
    )
    code.local(0x19, 0)
    reference = class_file.method_reference(
        "androidx/test/core/app/ActivityScenario",
        "launch",
        f"(Ljava/lang/Class;){scenario}",
    )
    code.emit(0xB8, reference.to_bytes(2, "big"))
    code.emit(0xB3, field.to_bytes(2, "big"))
    code.emit(0xB1)
    class_file.add_method(
        Method(0x0009, "launch", "(Ljava/lang/Class;)V", code.render(), 1, 1)
    )
    for name, state in (("recreate", None), ("background", "CREATED"), ("resume", "RESUMED")):
        lifecycle = Bytecode()
        lifecycle.emit(0xB2, field.to_bytes(2, "big"))
        lifecycle.branch(0xC7, "launched")
        error = class_file.constants.class_("java/lang/IllegalStateException")
        lifecycle.emit(0xBB, error.to_bytes(2, "big"))
        lifecycle.emit(0x59)
        lifecycle.emit(0xB7, _reference(
            class_file, "java/lang/IllegalStateException", "<init>", "()V",
        ))
        lifecycle.emit(0xBF)
        lifecycle.mark("launched")
        lifecycle.emit(0xB2, field.to_bytes(2, "big"))
        parameter = ""
        if state is not None:
            parameter = "Landroidx/lifecycle/Lifecycle$State;"
            state_field = class_file.field_reference(
                "androidx/lifecycle/Lifecycle$State", state, parameter,
            )
            lifecycle.emit(0xB2, state_field.to_bytes(2, "big"))
        lifecycle.emit(0xB6, _reference(
            class_file, "androidx/test/core/app/ActivityScenario",
            "recreate" if state is None else "moveToState", f"({parameter}){scenario}",
        ))
        lifecycle.emit(0x57)
        lifecycle.emit(0xB1)
        class_file.add_method(Method(
            0x0009, name, "()V", lifecycle.render(), 2, 0,
        ))
    back = Bytecode()
    back.emit(
        0xB8,
        _reference(
            class_file,
            "androidx/test/espresso/Espresso",
            "pressBack",
            "()V",
        ),
    )
    back.emit(0xB1)
    class_file.add_method(
        Method(0x0009, "pressBack", "()V", back.render(), 0, 0)
    )
    return ANDROID_CLASS_NAME, class_file.render()


__all__ = ["espresso_android_class", "espresso_view_class"]
