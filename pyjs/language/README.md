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

Imports preserve modules loaded at the selected interpreter's startup, and
the selected PyJS compiler keeps its own module identity. Workspace modules
can replace modules loaded only to bootstrap analysis. A selected source file
that collides with a protected module reports an error instead of analyzing
an unrelated module. Choose an interpreter containing the intended compiler
when working across compiler checkouts.

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
by workspace, interpreter and compiler fingerprint. Source and dependency
content hashes are checked against open buffers or disk before reuse. Unsaved
results
can only be reused with matching source; they never replace different disk
content. Cache write failures do not prevent live analysis.
Revisions are allocated through the cache database so they remain distinct
after a restart and between services sharing that cache. If allocation fails,
the session stops reading that cache and continues with local revisions.
Allocation waits up to one second for a writer; sustained contention can
therefore disable shared-cache reuse for that session.

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

## Cursor queries

`pyjs/completion` and `pyjs/signatureHelp` accept the same source
synchronization fields as `pyjs/moduleSnapshot`, plus `line` and `column`.
Lines are one-based;
columns count Unicode code points from zero, after newline normalization.
Python embedders use `AnalysisSession.completion(uri, line, column)` and
`AnalysisSession.signatures(uri, line, column)`. These are custom methods,
not the standard LSP completion or signature-help protocol.

Queries run in a fresh analysis worker. They execute module initialization
once, then analyze the cursor's function and compiler-required dependencies
without calling application entry points. Unrelated function bodies are not
validated, and declared signatures can be used before their bodies finish.
All open buffers must contain valid Python syntax before execution begins.
Timeouts, dependency checks, selected interpreters and source-generation
statuses behave as they do for snapshots. Query results do not populate or
reuse the module snapshot cache. A `ready` query answers the cursor request;
it does not certify that the whole application compiles.

Completion returns `items` and `truncated`. Each item contains `label`, `kind`,
`detail`, replacement `text`, `startColumn` and `endColumn`. The replacement
range covers the entire identifier on the requested line. Names are filtered
by the prefix before the cursor and capped at 256. Member queries use inferred
receiver types; unions expose only members shared by every alternative.
When a partial identifier determines a later binding's type, candidates are
checked individually through inference rather than assigning a guessed type.

Signature help returns up to 20 `signatures`, each with `label`, `parameters`,
`activeParameter` and `documentation`. The active parameter is a zero-based
index, or null when it cannot be determined. The innermost call is selected.
Resolved calls include generic specialization and union-method alternatives.
Typed callbacks use synthetic argument names when their type has no names.
Missing or incompatible arguments can still show declared signatures. For an
assigned or nested call, the fallback uses known return types and retains
ordinary checks on later use. It does not invent unresolved generic bindings;
when the result type still depends on a missing type argument, a consumed call
currently returns an analysis error. A standalone or directly returned call
can display the unspecialized declaration without consuming its result.

Queries require compiled function context. They do not parse broken Python,
complete a bare trailing dot, or provide project-wide import suggestions.
Large modules and broad partial-assignment prefixes may need substantial
analysis time; use explicit requests rather than triggering on each keystroke.

## Current limits

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
