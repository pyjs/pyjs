import os
import sys
import argparse
import json
import importlib
from pathlib import Path

from pyjs.transpiler import bundle
from pyjs.server import page


def main():
    sys.path.insert(0, os.getcwd())

    parser = argparse.ArgumentParser()
    parser.add_argument("module", help="module containing entry point function, to specify function use colon, eg. module.submodule:entry_point, defaults to main()")
    parser.add_argument("--include-main", action="store_true", help="whether to include and call the main entry_point function, default is false")
    parser.add_argument("--args", help="list of arguments to pass to entry point in JSON format")

    args = parser.parse_args()

    if ".py" in args.module:
        try:
            suggestion = f"perhaps try just: {Path(args.module).stem}"
        except:
            suggestion = ""
        parser.error(
            f"{args.module} appears to be a Python file, "
            f"a module name is expected instead, {suggestion}"
        )

    module_name, entry = args.module, "main"
    if ":" in args.module:
        module_name, entry = args.module.split(':', 1)

    entry_args = []
    if args.args:
        entry_args = json.loads(args.args)
        if not isinstance(entry_args, list):
            print("--args must be a JSON list")

    module = importlib.import_module(module_name)
    entry_point = getattr(module, entry)
    file_stem = f"{module_name}.{entry}"

    js_file_name = f"{file_stem}.js"
    print(f"writing {module_name}:{entry} JS to ./{js_file_name}")
    js, css = bundle(entry_point, args.include_main)
    with open(js_file_name, "w") as jsfile:
        jsfile.write(js)

    css_file_name = f"{file_stem}.css"
    print(f"writing {module_name}:{entry} CSS to ./{css_file_name}")
    with open(css_file_name, "w") as cssfile:
        cssfile.write(css)

    html = page(entry_point(*entry_args), js_file_name, css_file_name, "text/javascript")
    html_file_name = f"{file_stem}.html"
    print(f"writing {module_name}:{entry} HTML to ./{html_file_name}")
    with open(html_file_name, "w") as htmlfile:
        htmlfile.write(html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
