from pyjs.analysis.diagnostics import CompilationError


def error_diagnostics(error: BaseException) -> list[dict]:
    """Serialize located errors using zero-based Unicode code-point ranges."""
    if isinstance(error, CompilationError):
        return [error.diagnostic.to_dict()]
    if not isinstance(error, SyntaxError) or not error.filename or not error.lineno:
        return []
    start = (error.lineno - 1, max(0, (error.offset or 1) - 1))
    end = max(start, ((error.end_lineno or error.lineno) - 1,
                      max(0, (error.end_offset or error.offset or 1) - 1)))
    return [{
        'code': type(error).__name__, 'severity': 'error', 'message': error.msg,
        'primary': {'file': error.filename,
                    'start': {'line': start[0], 'column': start[1]},
                    'end': {'line': end[0], 'column': end[1]}, 'message': ''},
        'secondary': [], 'notes': [], 'help': [],
    }]
