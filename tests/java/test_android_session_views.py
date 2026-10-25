from tests.java.test_exceptions import assert_compiles_to_android_dex


def test_resume_callback_can_disable_sensitive_view_state(tmp_path):
    assert_compiles_to_android_dex('''
from pyjs.android import Activity
from pyjs.android.controls import EditText
class SessionActivity(Activity):
    def onResume(self) -> None:
        super().onResume()
        password = EditText(self)
        password.setSaveEnabled(False)
        self.setContentView(password)
def main() -> int:
    activity = SessionActivity()
    activity.onResume()
    return 0
''', tmp_path)
