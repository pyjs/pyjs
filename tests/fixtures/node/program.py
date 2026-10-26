from pyjs import js
from pyjs.node import (
    cwd,
    join,
    mkdir,
    mkdtemp,
    read_text,
    remove_tree,
    temp_directory,
    write_text,
)


@js
async def main() -> None:
    root = await mkdtemp(join(temp_directory(), "pyjs-node-"))
    try:
        await mkdir(join(root, "child"))
        filename = join(root, "child/example.txt")
        await write_text(filename, "hello")
        assert await read_text(filename) == "hello"
        print("node filesystem works", len(cwd()) > 0)
    finally:
        await remove_tree(root)
