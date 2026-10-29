# Editor analysis

`pyjs lsp --root PATH` starts an experimental language service over standard
LSP stdio framing. By default analysis uses the service's Python interpreter.
Use `--python /project/.venv/bin/python` to execute analysis with a separate
project interpreter containing PyJS and the application's dependencies.
Embedders can pass `interpreter=` to `AnalysisSession` for the same behavior.
The service does not install packages or silently choose a different runtime
when the selected interpreter cannot load the compiler. Relative interpreter
paths are relative to the service launch directory. Bare interpreter command
names are looked up on `PATH`.
Analysis executes module initialization, just as compilation does. Application
entry functions are analyzed without being called.

The initial interface supports initialization, shutdown, full-document
open/change/close notifications, cancellation responses, and custom
whole-module requests:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "pyjs/moduleSnapshot",
  "params": {
    "uri": "file:///project/example.py",
    "version": 1,
    "text": "from pyjs import js\n@js\ndef answer():\n    return 42\n"
  }
}
```

Alternatively, synchronize documents with standard LSP notifications and send
only `uri`. An optional `documents` array of `{uri, version, text}` records
atomically replaces all open buffers before the request. This allows an editor
to submit a coherent batch of unsaved modules and discard closed buffers.
New modules and package initializers can be supplied before their first save.
It represents an authoritative generation; per-document notification versions
otherwise increase monotonically. `force: true` bypasses the snapshot cache.

Successful results include `schemaVersion: 1`, `uri`, document `version`,
service `revision`, `sourceHash`, `status`, `cached`, `symbols`, and
`occurrences`.
Function signatures and identifier types come from the compiler's analysis of
compiler-selected definitions, including methods. Global values reflect their
actual types after Python initialization. This is not yet a general Python type
checker; unsupported source produces an explicit analysis error.

Custom snapshot locations use one-based lines and zero-based Unicode code-point
columns; end positions are exclusive. These are deliberately named `line` and
`column`, not LSP `Position` objects. Function symbols point to their definition
line. Identifier occurrences carry `line`, `column`, `endLine`, `endColumn`,
`name`, `kind`, and `type`. A function occurrence's type is its return type.
They also include a display `signature`, `documentation`, an inferred-variable
`hint` flag, and `definitionPath`, `definitionLine`, `definitionColumn` for
navigation. Definition paths are workspace-relative; an empty path means no
workspace definition was found. Imported aliases and methods resolve through
the compiler's object identities, not name matching.

Results have one of four states:

- `ready`: types belong to this source generation.
- `pending`: an open buffer is not valid Python; nothing was executed.
- `error`: initialization or analysis failed or exceeded its time limit.
- `superseded`: source or a tracked dependency changed during analysis.

Successful snapshots are retained for every workspace module visited by the
analysis, including dependencies. They are persisted in SQLite under
`$XDG_CACHE_HOME/pyjs/analysis` (default `~/.cache/pyjs/analysis`), partitioned
by workspace, interpreter and compiler fingerprint. Source and dependency content
hashes are checked against open buffers or disk before reuse. Unsaved results
can only be reused with matching source; they never replace different disk
content. Cache write failures do not prevent live analysis.
Revisions are allocated through the cache database so they remain distinct
after a restart and between services sharing that cache. If allocation fails,
the session stops reading that cache and continues with local revisions.

`pyjs/indexProject` starts background indexing of `[tool.pyjs].application` and
its reachable modules; module names, packages and workspace `.py` paths are
accepted. `initialized` also starts it. `pyjs/indexState` reports
its state. Cached snapshots remain available while another module is being
analyzed. `pyjs/moduleState` with `{uri}` returns `status: ready|stale` and
`revision` without retransmitting occurrences, for dependency-change polling.

Changed analysis runs in a fresh CPython worker; ordinary output cannot corrupt
the protocol stream. Timeouts and Python exits become failed snapshots. The
worker isolates execution state and failures; it is not a sandbox.
Dependency hashes are recorded before initialization, including when the worker
raises, exits or times out. Such failures are superseded if their observed
source generation has changed. Invalid JSON or request parameters return
protocol errors; an invalid frame terminates the service and its worker.

Current limits: a changed dependency rebuilds the compiler graph. First-time
indexing still costs a full analysis, and indexing covers the configured
application graph rather than executing every unrelated Python file. Filesystem
inputs other than imported Python source, environment changes, external package
changes, and dynamic imports that resolve differently are not automatically
tracked. Use forced refresh for these
inputs and restart after changing interpreters/dependencies. Snapshot diffs,
retained inference graphs, standard hover/completion/rename, and source mappings
for generated declarations are not implemented yet. Cancellation suppresses the
result; it does not yet interrupt running analysis before its timeout.
