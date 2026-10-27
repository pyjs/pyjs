"""Run compiled descriptor operations against real host files."""
# Native Node errors are inspected by code; they are not Python OSError types.
# ruff: noqa: BLE001
import os
import subprocess

import pytest

from pyjs import js
from pyjs.javascript import Uint8Array
from pyjs.node import (
    arguments,
    close_descriptor,
    error_code,
    join,
    open_exclusive,
    read_text_sync,
    write_descriptor,
)
from pyjs.node.files import (
    fstat,
    fsync,
    link,
    lstat,
    open_directory,
    open_readonly,
    read_into,
)
from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


@js
def descriptor_contract():
    root = arguments()[-1]
    path = join(root, "data")
    fd = open_exclusive(path)
    try:
        write_descriptor(fd, "hello")
        fsync(fd)
        info = fstat(fd)
        assert info.isFile() and info.size == 5
        assert not info.isSymbolicLink()
        assert info.dev >= 0 and info.ino >= 0 and info.ctimeMs > 0
    finally:
        close_descriptor(fd)
    fd = open_readonly(path)
    try:
        rejected = False
        try:
            write_descriptor(fd, "must not write")
        except Exception:
            rejected = True
        assert rejected
        data = Uint8Array(8)
        assert read_into(fd, data, 2, 2) == 2
        assert data[0] == 0 and data[2] == 104 and data[3] == 101
        assert read_into(fd, data, 0, 8) == 3
        assert data[0] == 108 and data[1] == 108 and data[2] == 111
        assert read_into(fd, data, 0, 8) == 0
        rejected = False
        try:
            read_into(fd, data, 7, 2)
        except Exception:
            rejected = True
        assert rejected
    finally:
        close_descriptor(fd)
    target = join(root, "published")
    link(path, target)
    assert read_text_sync(target) == "hello"
    assert lstat(target).ino == lstat(path).ino
    refused = False
    try:
        link(path, target)
    except Exception as error:
        refused = error_code(error) == "EEXIST"
    assert refused and read_text_sync(target) == "hello"
    missing = False
    try:
        open_readonly(join(root, "missing"))
    except Exception as error:
        missing = error_code(error) == "ENOENT"
    assert missing


@js
def nofollow_contract():
    root = arguments()[-1]
    path = join(root, "link")
    assert lstat(path).isSymbolicLink()
    refused = False
    try:
        open_readonly(path, nofollow=True, nonblocking=True)
    except Exception as error:
        refused = error_code(error) == "ELOOP"
    assert refused
    fd = open_readonly(join(root, "plain"), nofollow=True, nonblocking=True)
    close_descriptor(fd)
    # FIFO opening cannot hang before the caller can reject its file type.
    fd = open_readonly(join(root, "fifo"), nofollow=True, nonblocking=True)
    try:
        assert not fstat(fd).isFile()
    finally:
        close_descriptor(fd)


@js
def unsupported_flag_contract():
    refused = False
    try:
        open_readonly(arguments()[-1], nofollow=True)
    except Exception as error:
        refused = "O_NOFOLLOW is not supported" in str(error)
    assert refused


@js
async def directory_contract():
    directory = await open_directory(join(arguments()[-1], "entries"))
    names: list[str] = []
    try:
        entry = await directory.read()
        while entry is not None:
            assert entry.isFile() and not entry.isSymbolicLink()
            names.append(entry.name)
            entry = await directory.read()
        assert await directory.read() is None
    finally:
        await directory.close()
    assert sorted(names) == ["a", "b"]
    closed = False
    try:
        await directory.read()
    except Exception as error:
        closed = error_code(error) == "ERR_DIR_CLOSED"
    assert closed


def execute(entry, tmp_path, script=None):
    program = build_node(entry, tmp_path / "test.cjs", executable=script is None)
    command = [str(Node().executable)]
    if script is not None:
        command.extend(["-e", script])
    result = subprocess.run([*command, str(program), str(tmp_path)],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_descriptor_reads_and_no_replace_publication(tmp_path):
    execute(descriptor_contract, tmp_path)
    assert (tmp_path / "data").read_text() == "hello"
    assert not (tmp_path / "missing").exists()


def test_incremental_directory_enumeration_and_close(tmp_path):
    directory = tmp_path / "entries"
    directory.mkdir()
    (directory / "a").touch()
    (directory / "b").touch()
    execute(directory_contract, tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="O_NOFOLLOW, O_NONBLOCK and mkfifo are POSIX")
def test_final_symlink_rejection_and_nonblocking_special_file(tmp_path):
    (tmp_path / "plain").write_text("unchanged")
    (tmp_path / "link").symlink_to(tmp_path / "plain")
    os.mkfifo(tmp_path / "fifo")
    execute(nofollow_contract, tmp_path)
    assert (tmp_path / "plain").read_text() == "unchanged"


def test_unsupported_requested_flags_fail_instead_of_becoming_zero(tmp_path):
    # Exercise the unsupported-platform branch on this host instead of
    # relying on the native platform to lack the requested constant.
    execute(unsupported_flag_contract, tmp_path, """
const Module = require('node:module'), load = Module._load;
Module._load = function(name, ...args) {
    if (name === 'node:fs') return {constants: {O_RDONLY: 0},
        openSync() { throw new Error('must not attempt open'); }};
    return load.call(this, name, ...args);
};
require(process.argv[1]).main();
""")


@js
def flag(events: list[str], name: str) -> bool:
    events.append(name)
    return False


@js
def keyword_order_contract():
    events: list[str] = []
    descriptor = open_readonly(join(arguments()[-1], "plain"), nonblocking=flag(events, "nonblocking"),
                               nofollow=flag(events, "nofollow"))
    try:
        assert events == ["nonblocking", "nofollow"]
    finally:
        close_descriptor(descriptor)


def test_keyword_flags_are_evaluated_once_in_source_order(tmp_path):
    (tmp_path / "plain").write_text("unchanged")
    execute(keyword_order_contract, tmp_path)
