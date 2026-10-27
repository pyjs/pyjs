"""Low-level Node file operations for bounded reads and safe publication.

These are host bindings, not a transaction or a sandbox. Callers own descriptor
lifetime, path policy, backups and recovery. In particular O_NOFOLLOW protects
the final path component only; ancestor directories remain the caller's concern.
"""
from pyjs import js
from pyjs.javascript import Uint8Array
from pyjs.node import DirectoryEntry, FileInfo


@js.native
class Directory:
    async def read(self) -> DirectoryEntry | None: ...
    async def close(self) -> None: ...


@js.inline("require('node:fs/promises').opendir({path})")
async def open_directory(path: str) -> Directory:
    """Read entries incrementally; callers close the handle in finally."""


@js
def open_readonly(path: str, *, nofollow: bool = False, nonblocking: bool = False) -> int:
    """Open without creating/truncating; unsupported requested flags raise."""
    # A normal function boundary preserves source-order keyword evaluation.
    return _open_readonly(path, nofollow, nonblocking)


@js
def _open_readonly(path: str, nofollow: bool, nonblocking: bool) -> int: ...


@_open_readonly.inline
def _open_readonly(path, nofollow, nonblocking, **kwargs):
    return f"""((path, nofollow, nonblocking) => {{
    const fs = require('node:fs');
    let flags = fs.constants.O_RDONLY;
    for (const [enabled, name] of [[nofollow, 'O_NOFOLLOW'], [nonblocking, 'O_NONBLOCK']]) {{
        if (enabled) {{
            if (!Number.isInteger(fs.constants[name]))
                throw new Error(name + ' is not supported on this platform');
            flags |= fs.constants[name];
        }}
    }}
    return fs.openSync(path, flags);
}})({path}, {nofollow}, {nonblocking})"""


@js.inline("require('node:fs').lstatSync({path})")
def lstat(path: str) -> FileInfo: ...


@js.inline("require('node:fs').fstatSync({descriptor})")
def fstat(descriptor: int) -> FileInfo: ...


@js.inline("require('node:fs').readSync({descriptor}, {buffer}, {offset}, {length}, null)")
def read_into(descriptor: int, buffer: Uint8Array, offset: int, length: int) -> int:
    """Read at the current file offset, returning bytes read (zero at EOF)."""


@js.inline("require('node:fs').fsyncSync({descriptor})")
def fsync(descriptor: int) -> None: ...


@js.inline("require('node:fs').linkSync({source}, {target})")
def link(source: str, target: str) -> None:
    """Create a hard link; an existing target is never replaced."""
