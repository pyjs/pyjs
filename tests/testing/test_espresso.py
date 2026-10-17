from pyjs.java import read_jvm_class
from pyjs.testing.espresso import espresso_android_class, espresso_view_class


def test_espresso_bridge_exposes_the_python_view_operations():
    name, content = espresso_view_class()
    value = read_jvm_class(content)

    assert name == "org/pyjs/testing/PyjsView"
    assert value.name == name
    assert value.declared_field("matcher").descriptor == "Lorg/hamcrest/Matcher;"
    assert {
        (method.name, method.descriptor)
        for method in value.methods
        if method.name != "<init>"
    } == {
        ("fromText", "(Ljava/lang/String;)Lorg/pyjs/testing/PyjsView;"),
        ("fromId", "(I)Lorg/pyjs/testing/PyjsView;"),
        ("click", "()V"),
        ("press_key", "(I)V"),
        ("ime_action", "()V"),
        ("close_keyboard", "()V"),
        ("long_click", "()V"),
        ("replace_text", "(Ljava/lang/String;)V"),
        ("scroll_to", "()V"),
        ("assert_displayed", "()V"),
        ("assert_absent", "()V"),
        ("assert_text", "(Ljava/lang/String;)V"),
        ("check", "(Landroidx/test/espresso/ViewAssertion;)V"),
        ("in_dialog", "()Lorg/pyjs/testing/PyjsView;"),
    }


def test_espresso_android_bridge_launches_activity_scenarios():
    name, content = espresso_android_class()
    value = read_jvm_class(content)

    assert name == "org/pyjs/testing/PyjsAndroid"
    assert value.declared_methods("launch")[0].descriptor == (
        "(Ljava/lang/Class;)V"
    )
    assert value.declared_methods("close")[0].descriptor == "()V"
    assert value.declared_methods("pressBack")[0].descriptor == "()V"
    for operation in ("recreate", "background", "resume"):
        assert value.declared_methods(operation)[0].descriptor == "()V"
