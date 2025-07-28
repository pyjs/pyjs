import os
import sys
import argparse
import json
import importlib
from pathlib import Path

from pyjs.transpiler import transpile
from pyjs.server import serve, page


def main():
    sys.path.insert(0, os.getcwd())

    parser = argparse.ArgumentParser()
    parser.add_argument("module", help="module where to look for main entry point, to specify entry point as well use colon, eg. module.submodule:entry_point")
    #parser.add_argument("--js-output", "-js", help="js output file, defaults to module+'.js'", metavar="FILE")
    parser.add_argument("--ssr", help="server side rendering entry point function, in module.submodule:function format")
    parser.add_argument("--ssr-args", help="list of arguments to pass to entry point in JSON format")
    #parser.add_argument("--html-output", "-html", help="html output file", metavar="FILE")
    parser.add_argument("--serve", action="store_true", help="html output file")
    parser.add_argument("--css", help="css file to serve")

    args = parser.parse_args()

    client_entry = "main"
    module_name = args.module
    if ":" in args.module:
        module_name, client_entry = args.module.split(':', 1)

    if args.serve:
        if not args.css:
            print("--serve requires --css file argument")
        with open(args.css) as css_file:
            css = css_file.read()
        if not args.ssr:
            print("--serve requires --ssr argument")
        ssr_args = []
        if args.ssr_args:
            ssr_args = json.loads(args.ssr_args)
            if not isinstance(ssr_args, list):
                print("--ssr_args must be a list of arguments")
        serve(
            module_name,
            client_entry,
            css,
            args.ssr,
            *ssr_args
        )
    else:
        module = importlib.import_module(module_name)
        js_entry_point = getattr(module, client_entry)
        js = transpile(js_entry_point)+f"\n\n{client_entry}();\n"
        js_file_name = f"{module_name}.{client_entry}.js"
        print(f"transpiling {module_name}:{client_entry} to ./{js_file_name}")
        with open(js_file_name, "w") as jsfile:
            jsfile.write(js)
        if args.ssr:
            ssr_args = []
            if args.ssr_args:
                ssr_args = json.loads(args.ssr_args)
                if not isinstance(ssr_args, list):
                    print("--ssr_args must be a list of arguments")
            ssr_entry_point = getattr(module, args.ssr)
            html = page(ssr_entry_point(*ssr_args), js_file_name)
            html_file_name = f"{module_name}.{args.ssr}.html"
            print(f"transpiling {module_name}:{args.ssr} to ./{html_file_name}")
            with open(html_file_name, "w") as htmlfile:
                htmlfile.write(html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
