import pytest

from pyjs.android.dispatch import Handler, main_looper
from pyjs.android.testing import application_context, run_on_main
from pyjs.java.concurrent import Runnable, Thread

pytestmark = pytest.mark.pyjs_android_jvm


class PreferenceRoundTrip(Runnable):
    def __init__(self):
        self.completed = False

    def run(self) -> None:
        preferences = application_context().get_shared_preferences(
            "dispatch-contract", 0,
        )
        editor = preferences.edit()
        editor.put_string("snapshot", "saved")
        assert editor.commit()
        assert preferences.get_string("snapshot", "") == "saved"
        editor.put_string("snapshot", None)
        assert editor.commit()
        self.completed = True


def test_main_thread_callback_without_an_activity_can_commit_preferences() -> None:
    task = PreferenceRoundTrip()
    run_on_main(task)
    assert task.completed


class Acknowledgement(Runnable):
    def __init__(self):
        self.completed = False

    def run(self) -> None:
        self.completed = True


class BackgroundPost(Runnable):
    def __init__(self, acknowledgement: Acknowledgement):
        self.acknowledgement = acknowledgement
        self.accepted = False

    def run(self) -> None:
        self.accepted = Handler(main_looper()).post(self.acknowledgement)


class CheckAcknowledgement(Runnable):
    def __init__(self, acknowledgement: Acknowledgement):
        self.acknowledgement = acknowledgement

    def run(self) -> None:
        assert self.acknowledgement.completed


def test_background_task_posts_an_acknowledgement_to_the_main_loop() -> None:
    acknowledgement = Acknowledgement()
    task = BackgroundPost(acknowledgement)
    worker = Thread(task)
    worker.start()
    worker.join()
    assert task.accepted
    run_on_main(CheckAcknowledgement(acknowledgement))
