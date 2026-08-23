from pathlib import Path

import pytest
from pyjs.testing.android import AndroidTestSession, assert_android_image
from pyjs.testing.interaction.gesture import GestureScript
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.nativescript import NativeScriptProject
from pyjs_examples.notes.notes import APP_ASSETS, main

pytestmark = pytest.mark.pyjs_android


@pytest.fixture(scope="module")
def android_session(request) -> AndroidTestSession:
    android = AndroidSDK()
    project = NativeScriptProject(
        main,
        name="Notes",
        app_id="org.pyjs.notes",
        android=android,
        app_assets=APP_ASSETS,
    )
    device = project.run_android(request.config.getoption("--pyjs-android-avd"))
    return AndroidTestSession(android, device, project.app_id)


def capture_render(
    session: AndroidTestSession,
    request,
    artifacts: Path,
    name: str,
):
    session.capture_artifacts(artifacts, name)
    actual = artifacts / (name + ".png")
    expected = Path(__file__).parent / "renders" / "android" / (name + ".png")
    if request.config.getoption("--pyjs-update-renders"):
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(actual.read_bytes())
        return
    assert expected.exists(), (
        "Missing Android render baseline "
        + str(expected)
        + ". Run with --pyjs-update-renders to create it."
    )
    assert_android_image(
        actual,
        expected,
        pixel_threshold=12,
        max_different_pixel_ratio=0.002,
        diff_path=artifacts / (name + "-diff.png"),
    )


def test_notes_visual_showcase(
    android_session: AndroidTestSession,
    request,
    pyjs_artifacts_dir: Path,
):
    session = android_session
    artifacts = pyjs_artifacts_dir / "android"
    session.force_stop()
    session.launch()

    with session.artifacts_on_failure(artifacts, "notes-showcase"):
        session.wait_for_element(test_id="search-notes")
        session.wait_for_element(test_id="note-title-launch", text="Launch checklist")
        capture_render(session, request, artifacts, "notes-home")

        session.tap_element(test_id="toggle-layout")
        session.wait_for_element(test_id="note-card-recipe")
        capture_render(session, request, artifacts, "notes-list")

        session.tap_element(test_id="note-card-launch")
        session.wait_for_element(test_id="editor-title", text="Launch checklist")
        capture_render(session, request, artifacts, "notes-checklist-editor")

        session.tap_element(test_id="editor-more")
        session.wait_for_element(test_id="note-actions")
        capture_render(session, request, artifacts, "notes-actions")
        session.tap_element(test_id="note-actions-scrim")
        session.wait_for_element(test_id="editor-title", text="Launch checklist")

        session.tap_element(test_id="editor-back")
        session.wait_for_element(test_id="search-notes")
        session.tap_element(test_id="open-navigation")
        session.wait_for_element(test_id="navigation-drawer")
        capture_render(session, request, artifacts, "notes-navigation")

        assert session.log_errors() == ""


def test_notes_long_press_drag_moves_a_card(
    android_session: AndroidTestSession,
    pyjs_artifacts_dir: Path,
):
    session = android_session
    artifacts = pyjs_artifacts_dir / "android"
    session.launch()

    with session.artifacts_on_failure(artifacts, "notes-long-press-drag"):
        source = session.wait_for_element(test_id="note-card-groceries")
        target = session.wait_for_element(test_id="note-card-design")
        start_x, start_y = source.bounds.center
        target_x, target_y = target.bounds.center
        script = (
            GestureScript()
            .long_press(start_x, start_y, 650)
            .line_to(target_x, target_y, 300, steps=6)
        )

        with session.held_gesture(script, settle_ms=300):
            moved = session.wait_for_element(test_id="note-card-groceries")
            assert moved.bounds != source.bounds

        session.wait_for_element(test_id="search-notes")
        assert session.log_errors() == ""
