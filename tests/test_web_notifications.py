from pyjs.testing.helpers import assert_analysis_transpile, assert_transpile
from pyjs.web.serviceworker import Notification, PushManager


def test_notification_and_push_capabilities_are_class_attributes():
    assert Notification.permission == ""
    assert Notification.maxActions == 0
    assert PushManager.supportedContentEncodings == []
    note = Notification("Preview")
    assert note.title == "Preview"
    assert "permission" not in vars(note) and "maxActions" not in vars(note)
    assert "supportedContentEncodings" not in vars(PushManager())


def test_notification_capabilities_compile_to_native_static_reads():
    assert_transpile(
        '''
        from pyjs.web.serviceworker import Notification, PushManager

        def main():
            print(Notification.permission)
            print(Notification.maxActions)
            print(PushManager.supportedContentEncodings)
        ''',
        '''
        export function main() {
            console.log(Notification.permission);
            console.log(Notification.maxActions);
            console.log(PushManager.supportedContentEncodings);
        }
        ''',
    )


def test_native_static_references_keep_declared_types_and_inheritance():
    assert_analysis_transpile(
        '''
        from typing import ClassVar
        @js.native
        class Platform:
            values: list[str] = []
            optional: ClassVar[list[str] | None] = None
            instance_values: list[str]
        @js.native
        class Child(Platform):
            pass
        def main(value: Platform):
            items = Child.values
            pending = Platform.optional
            instance = value.instance_values
        ''',
        '''
        def main(value: Platform) -> None:
            items: list[str] = Child.values
            pending: list[str] | None = Platform.optional
            instance: list[str] = value.instance_values
        ''',
        '''
        export function main(value) {
            var items = Child.values;
            var pending = Platform.optional;
            var instance = value.instance_values;
        }
        ''',
    )
