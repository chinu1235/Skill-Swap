"""Backend adapter for isolated Judge0-compatible code execution."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import current_app


class ExecutionConfigurationError(Exception):
    pass


class ExecutionServiceError(Exception):
    pass


class UnsupportedExecutionLanguage(Exception):
    pass


LANGUAGE_PREFIXES = {
    "javascript": ("javascript", "node.js"),
    "python": ("python",),
    "c": ("c (", "c gcc", "c (gcc"),
    "cpp": ("c++", "cpp"),
}
MAX_OUTPUT_BYTES = 20_000
RESOURCE_LIMITS = {
    "cpu_time_limit": 2,
    "cpu_extra_time": 1,
    "wall_time_limit": 7,
    "memory_limit": 128_000,
    "stack_limit": 64_000,
    "max_processes_and_or_threads": 20,
    "max_file_size": 1_024,
}


def _request_json(url, method="GET", payload=None, timeout=5):
    config = current_app.config
    headers = {"Accept": "application/json"}
    token = config.get("CODE_EXECUTION_API_KEY", "")
    if token:
        headers[config.get("CODE_EXECUTION_API_KEY_HEADER", "X-Auth-Token")] = token
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(1_000_001).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        # Do not include provider response bodies or configured URLs in errors/logs.
        raise ExecutionServiceError(type(error).__name__) from None


def _service_url():
    base_url = current_app.config.get("CODE_EXECUTION_API_URL", "").strip().rstrip("/")
    if not base_url:
        raise ExecutionConfigurationError("CODE_EXECUTION_API_URL is not configured")
    if not base_url.startswith(("https://", "http://")):
        raise ExecutionConfigurationError("Execution service URL must use HTTP or HTTPS")
    return base_url


def _language_id(languages, language):
    prefixes = LANGUAGE_PREFIXES[language]
    for item in languages:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str):
            continue
        name = name.strip().lower()
        if language == "c" and name.startswith(("c++", "cpp")):
            continue
        if any(name.startswith(prefix) for prefix in prefixes):
            return item.get("id")
    raise UnsupportedExecutionLanguage(language)


def execute_code(language, source, stdin=""):
    """Submit supported source, poll within a bounded deadline, and cap returned output."""
    base_url = _service_url()
    languages = _request_json(f"{base_url}/languages")
    if not isinstance(languages, list):
        raise ExecutionServiceError("Invalid language list")
    language_id = _language_id(languages, language)
    submission = _request_json(
        f"{base_url}/submissions?base64_encoded=false&wait=false",
        method="POST",
        payload={"source_code": source, "language_id": language_id, "stdin": stdin, **RESOURCE_LIMITS},
        timeout=8,
    )
    token = submission.get("token") if isinstance(submission, dict) else None
    if not isinstance(token, str) or len(token) > 256:
        raise ExecutionServiceError("Invalid submission response")

    deadline = time.monotonic() + 12
    result = None
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutionServiceError("Execution polling timed out")
        time.sleep(min(0.5, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutionServiceError("Execution polling timed out")
        result = _request_json(f"{base_url}/submissions/{quote(token, safe='')}?base64_encoded=false", timeout=min(4, remaining))
        if not isinstance(result, dict) or not isinstance(result.get("status"), dict):
            raise ExecutionServiceError("Invalid execution response")
        if result.get("status", {}).get("id") not in {1, 2}:
            break
    else:
        raise ExecutionServiceError("Execution polling timed out")

    output_parts = [result.get(key) for key in ("stdout", "stderr", "compile_output", "message") if result.get(key)]
    text = "\n".join(str(part) for part in output_parts)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_OUTPUT_BYTES:
        text = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore") + "\n[Output truncated]"
    status = result.get("status", {}).get("description", "Unknown status")
    return {"status": str(status)[:100], "text": text or "Program finished without output.", "time": result.get("time")}
