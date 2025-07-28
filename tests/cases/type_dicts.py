from typing import cast

def main():
    simple = {"one": "two"}
#    explicit: dict[str, str|int|dict[str,str]] = {}
#    explicit["one"] = "one"
#    explicit["two"] = 2
#    explicit["three"] = {"four": "five"}
#    for key, val in explicit.items():
#        if isinstance(val, dict):
#            for subkey in val.keys():
#                print(f"item: {key} {subkey} {val[subkey]}")
#
#    inferred = {
#        "one": 1,
#        "two": "blue",
#        "three": cast(dict[str,str], {})
#    }
#    inferred["three"]["four"] = "five"
#    for key, val in inferred.items():
#        if isinstance(val, dict):
#            for subkey in val.keys():
#                print(f"item: {key} {subkey} {val[subkey]}")
