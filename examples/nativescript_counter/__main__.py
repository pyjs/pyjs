from pyjs.tooling.nativescript import NativeScriptProject

from .counter import main


def run() -> None:
    project = NativeScriptProject(
        main,
        name="PyJS Counter",
        app_id="org.pyjs.counter",
    )
    device = project.run_android()
    print(f"PyJS Counter is running on {device.identifier}.")


if __name__ == "__main__":
    run()
