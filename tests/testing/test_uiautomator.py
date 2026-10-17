from pyjs.java import read_jvm_class
from pyjs.testing.uiautomator import (
    uiautomator_device_class,
    uiautomator_element_class,
)


def test_uiautomator_device_bridge_exposes_waiting_selectors():
    name, content = uiautomator_device_class()
    value = read_jvm_class(content)

    assert name == "org/pyjs/testing/PyjsDevice"
    assert {
        (method.name, method.descriptor)
        for method in value.methods
        if method.name != "<init>"
    } == {
        ("get", "()Lorg/pyjs/testing/PyjsDevice;"),
        ("press_home", "()V"),
        ("current_package", "()Ljava/lang/String;"),
        (
            "findText",
            "(Ljava/lang/String;J)Lorg/pyjs/testing/PyjsDeviceElement;",
        ),
        (
            "findResource",
            "(Ljava/lang/String;J)Lorg/pyjs/testing/PyjsDeviceElement;",
        ),
    }


def test_uiautomator_element_bridge_exposes_interactions():
    name, content = uiautomator_element_class()
    value = read_jvm_class(content)

    assert name == "org/pyjs/testing/PyjsDeviceElement"
    assert value.declared_methods("click")[0].descriptor == "()V"
    assert value.declared_methods("drag_to")[0].descriptor == (
        "(Lorg/pyjs/testing/PyjsDeviceElement;III)V"
    )
    assert value.declared_methods("text")[0].descriptor == "()Ljava/lang/String;"
