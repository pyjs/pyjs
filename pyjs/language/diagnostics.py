from pyjs.analysis.diagnostics import CompilationError


def error_diagnostics(error: BaseException) -> list[dict]:
    """Serialize located errors using zero-based Unicode code-point ranges."""
    if isinstance(error, CompilationError):
        return [error.diagnostic.to_dict()]
    if (not isinstance(error, SyntaxError) or not isinstance(error.filename, str)
            or not error.filename or type(error.lineno) is not int or error.lineno < 1
            or not isinstance(error.msg, str)
            or any(value is not None and type(value) is not int for value in
                   (error.offset, error.end_lineno, error.end_offset))):
        return []
    start = (error.lineno - 1, max(0, (error.offset or 1) - 1))
    end = max(start, ((error.end_lineno or error.lineno) - 1,
                      max(0, (error.end_offset or error.offset or 1) - 1)))
    return [{
        'code': type(error).__name__, 'severity': 'error', 'message': error.msg,
        'primary': {'file': error.filename,
                    'start': {'line': start[0], 'column': start[1]},
                    'end': {'line': end[0], 'column': end[1]}, 'message': None},
        'secondary': [], 'notes': [], 'help': [],
    }]
