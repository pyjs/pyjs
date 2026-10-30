"""LSP lifecycle and full-document synchronization with PyJS module snapshots."""

import json
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .session import AnalysisSession

MAX_MESSAGE = 16 * 1024 * 1024


class MessageError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def read_message(stream):
    headers = {}
    while line := stream.readline(8192):
        if line == b"\r\n":
            break
        name, separator, value = line.decode("ascii").partition(":")
        if not separator:
            raise ValueError("Invalid LSP header")
        headers[name.lower()] = value.strip()
    else:
        return None
    size = int(headers.get("content-length", "-1"))
    if not 0 <= size <= MAX_MESSAGE:
        raise ValueError("Invalid LSP message length")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Truncated LSP message")
    try:
        message = json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise MessageError(-32700, "Invalid JSON") from error
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise MessageError(-32600, "Expected JSON-RPC 2.0 object")
    return message


def write_message(stream, message):
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    stream.flush()


def serve(root: Path, *, session=None, methods=None, interpreter=None) -> int:
    session = AnalysisSession(root, interpreter=interpreter) if session is None else session
    methods = {} if methods is None else methods
    output_lock = threading.Lock()
    cancelled = set()
    initialized = False
    stopped = False

    def send(message):
        with output_lock:
            write_message(sys.stdout.buffer, {"jsonrpc": "2.0", **message})

    def analyze(request_id, parameters, query=None):
        try:
            if query is None:
                result = session.snapshot(parameters["uri"], force=parameters.get("force", False))
            else:
                method = session.signatures if query == 'pyjs/signatureHelp' else session.completion
                result = method(parameters['uri'], parameters['line'], parameters['column'])
            if request_id in cancelled:
                cancelled.discard(request_id)
                send({"id": request_id, "error": {"code": -32800, "message": "Request cancelled"}})
            else:
                send({"id": request_id, "result": result})
        except Exception as error:
            send({"id": request_id, "error": {"code": -32602, "message": str(error)}})

    def terminate(signum, frame):
        session.shutdown()
        raise SystemExit(0)

    previous_handler = signal.signal(signal.SIGTERM, terminate)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                while True:
                    try:
                        message = read_message(sys.stdin.buffer)
                    except MessageError as error:
                        send({"id": None, "error": {"code": error.code, "message": str(error)}})
                        continue
                    if message is None:
                        break
                    request_id = message.get("id")
                    method = message.get("method", "")
                    if (not isinstance(method, str) or not method
                            or isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None)))):
                        send({"id": None, "error": {"code": -32600, "message": "Invalid request"}})
                        continue
                    parameters = message.get("params", {})
                    if parameters is None:
                        parameters = {}
                    try:
                        if not isinstance(parameters, dict):
                            raise ValueError("Expected named parameters")
                        if method == "exit":
                            session.shutdown()
                            return 0 if stopped else 1
                        if method == "initialize" and not initialized:
                            initialized = True
                            result = {"capabilities": {"textDocumentSync": {"openClose": True, "change": 1},
                                      "experimental": {"pyjsModuleSnapshots": {"schemaVersion": 1},
                                          "pyjsSourceQueries": {"schemaVersion": 1,
                                              "methods": ["pyjs/completion", "pyjs/signatureHelp"]}}},
                                      "serverInfo": {"name": "pyjs"}}
                        elif not initialized:
                            send({"id": request_id, "error": {"code": -32002, "message": "Server not initialized"}})
                            continue
                        elif method == "shutdown":
                            stopped = True
                            session.shutdown()
                            result = None
                        elif stopped:
                            raise ValueError("Server has shut down")
                        elif method == "initialized":
                            executor.submit(session.index_project)
                            continue
                        elif method == "pyjs/indexProject":
                            executor.submit(session.index_project)
                            result = {"status": session.index_state}
                        elif method == "pyjs/moduleState":
                            cached = session.cached_snapshot(parameters["uri"])
                            result = {"status": "ready" if cached else "stale",
                                      "revision": cached["revision"] if cached else 0}
                        elif method == "pyjs/indexState":
                            result = {"status": session.index_state, "modules": len(session.cache)}
                        elif method in methods:
                            result = methods[method](parameters)
                        elif method == "$/setTrace":
                            continue
                        elif method == "$/cancelRequest":
                            cancelled.add(parameters["id"])
                            continue
                        elif method in ("textDocument/didOpen", "textDocument/didChange"):
                            document = parameters["textDocument"]
                            text = document["text"] if method.endswith("didOpen") else parameters["contentChanges"][-1]["text"]
                            session.update(document["uri"], document["version"], text)
                            continue
                        elif method == "textDocument/didClose":
                            session.close(parameters["textDocument"]["uri"])
                            continue
                        elif method in ("pyjs/moduleSnapshot", "pyjs/completion", "pyjs/signatureHelp"):
                            if "documents" in parameters:
                                session.replace_documents(parameters["documents"])
                            if "text" in parameters:
                                session.update(parameters["uri"], parameters["version"], parameters["text"])
                            query = None if method == 'pyjs/moduleSnapshot' else method
                            cached = None if query or parameters.get("force") else session.cached_snapshot(parameters["uri"])
                            if cached is not None:
                                send({"id": request_id, "result": cached})
                            else:
                                executor.submit(analyze, request_id, parameters, query)
                            continue
                        else:
                            if request_id is not None:
                                send({"id": request_id, "error": {"code": -32601, "message": "Method not found"}})
                            continue
                        if request_id is not None:
                            send({"id": request_id, "result": result})
                    except (KeyError, ValueError, TypeError, OSError, IndexError) as error:
                        if request_id is not None:
                            send({"id": request_id, "error": {"code": -32602, "message": str(error)}})
            finally:
                session.shutdown()
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    return 0
