from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def browser_packages(request):
    if request.config.getoption("--pyjs-target") != "web":
        return
    from pyjs.tooling.npm import ManagedNpmProject
    from pyjs.web.ui.markdown import __pyjs_npm_imports__

    project = ManagedNpmProject.for_project(Path(__file__))
    if project.vendor_for(__pyjs_npm_imports__) is None:
        project.sync(tuple(item.package for item in __pyjs_npm_imports__),
                     __pyjs_npm_imports__)
