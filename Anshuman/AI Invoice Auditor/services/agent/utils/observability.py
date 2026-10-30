"""
Observability (LangFuse)
========================
Single tracing facade used by every agent, tool, MCP invocation and A2A message.

A trace is opened once per logical unit of work (an invoice audit run, a RAG
query, an A2A message) and every agent/tool step below it is recorded as a
nested observation carrying its input, output, latency and error state.

SDK compatibility
-----------------
LangFuse changed its Python SDK surface between major versions:

  * v3/v4/v5 ("otel")    OpenTelemetry based: ``start_as_current_observation``,
                         nesting handled by OTel context.
  * v2       ("legacy")  ``client.trace()`` / ``span.span()``, nesting tracked
                         manually.

Which one is installed is detected at startup and both are driven through the
same facade, so upgrading the SDK does not touch any agent code.

LangFuse is optional at runtime: without keys, or when the SDK is missing, this
degrades to structured logging. The stack must never fail because an
observability backend is unavailable — but a *misconfigured* backend is logged
loudly rather than silently swallowed.
"""

import os
import time
import json
import logging
import functools
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger("observability")

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
# SDK v5 renamed LANGFUSE_HOST to LANGFUSE_BASE_URL. Accept either.
LANGFUSE_BASE_URL = (
    os.getenv("LANGFUSE_BASE_URL", "").strip()
    or os.getenv("LANGFUSE_HOST", "").strip()
    or "https://cloud.langfuse.com"
)
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "invoice-auditor-agent")

# Legacy-SDK bookkeeping only; the OTel SDKs propagate context themselves.
_current_trace: ContextVar[Optional[Any]] = ContextVar("lf_trace", default=None)
_current_span: ContextVar[Optional[Any]] = ContextVar("lf_span", default=None)

_client: Optional[Any] = None
_api = "none"            # "otel" | "legacy" | "none"
_init_done = False
_init_error: Optional[str] = None


def _truncate(value: Any, limit: int = 4000) -> Any:
    """Keeps payloads small enough to ship without dropping their shape."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, default=str)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit] + f"...[truncated {len(text) - limit} chars]"


# ------------------------------------------------------------------------------
# Client
# ------------------------------------------------------------------------------
def get_client():
    global _client, _api, _init_done, _init_error
    if _init_done:
        return _client
    _init_done = True

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        _init_error = "LANGFUSE_PUBLIC_KEY and/or LANGFUSE_SECRET_KEY are not set"
        logger.info("LangFuse keys not configured. Tracing falls back to structured logs.")
        return None

    try:
        from langfuse import Langfuse

        credentials = {"public_key": LANGFUSE_PUBLIC_KEY, "secret_key": LANGFUSE_SECRET_KEY}
        try:
            client = Langfuse(base_url=LANGFUSE_BASE_URL, **credentials)
        except TypeError:
            client = Langfuse(host=LANGFUSE_BASE_URL, **credentials)

        if hasattr(client, "start_as_current_observation") or hasattr(client, "start_as_current_span"):
            _api = "otel"
        elif hasattr(client, "trace"):
            _api = "legacy"
        else:
            raise RuntimeError("Unrecognised LangFuse SDK surface; neither v2 nor v3+ API found.")

        auth_check = getattr(client, "auth_check", None)
        if auth_check is not None and not auth_check():
            raise RuntimeError(
                f"LangFuse rejected the credentials for {LANGFUSE_BASE_URL}. Verify the keys "
                f"belong to that project and that the URL matches its data region."
            )

        _client = client
        logger.info(f"LangFuse tracing enabled (base_url={LANGFUSE_BASE_URL}, sdk_api={_api}).")
    except Exception as e:
        _init_error = f"{type(e).__name__}: {e}"
        _api = "none"
        _client = None
        # Loud: a configured-but-broken backend is a problem worth surfacing.
        logger.error(f"LangFuse tracing DISABLED — {_init_error}")
    return _client


def is_enabled() -> bool:
    return get_client() is not None


def status() -> Dict[str, Any]:
    """Diagnostics for /health — says why tracing is off, not just that it is."""
    client = get_client()
    return {
        "enabled": client is not None,
        "base_url": LANGFUSE_BASE_URL,
        "sdk_api": _api,
        "public_key_set": bool(LANGFUSE_PUBLIC_KEY),
        "secret_key_set": bool(LANGFUSE_SECRET_KEY),
        "error": _init_error,
    }


# ------------------------------------------------------------------------------
# SDK adapters
# ------------------------------------------------------------------------------
def _observation_cm(client, name: str, as_type: str, *, input: Any = None,
                    metadata: Optional[Dict] = None, model: Optional[str] = None):
    """Context manager for one OTel-era observation, or a no-op if creation fails."""
    kwargs: Dict[str, Any] = {"name": name}
    if input is not None:
        kwargs["input"] = _truncate(input)
    if metadata:
        kwargs["metadata"] = metadata
    if model:
        kwargs["model"] = model
    try:
        starter = getattr(client, "start_as_current_observation", None)
        if starter is not None:
            return starter(as_type=as_type, **kwargs)
        if as_type == "generation":
            return client.start_as_current_generation(**kwargs)
        return client.start_as_current_span(**kwargs)
    except Exception as e:
        logger.warning(f"LangFuse observation '{name}' could not be created: {e}")
        return nullcontext(None)


def _update(handle, **fields) -> None:
    if handle is None:
        return
    try:
        handle.update(**fields)
    except Exception as e:
        logger.warning(f"LangFuse update failed: {e}")


def _end(handle, **fields) -> None:
    if handle is None:
        return
    try:
        handle.end(**fields)
    except Exception as e:
        logger.warning(f"LangFuse end failed: {e}")


def _flush(client) -> None:
    try:
        client.flush()
    except Exception as e:
        logger.warning(f"LangFuse flush failed: {e}")


def _apply_trace_attributes(client, user_id, session_id, tags, metadata) -> None:
    updater = getattr(client, "update_current_trace", None)
    if updater is None:
        return
    attrs = {k: v for k, v in (
        ("user_id", user_id), ("session_id", session_id),
        ("tags", tags or None), ("metadata", metadata),
    ) if v is not None}
    if not attrs:
        return
    try:
        updater(**attrs)
    except Exception as e:
        logger.warning(f"LangFuse trace attributes could not be set: {e}")


# ------------------------------------------------------------------------------
# Traces
# ------------------------------------------------------------------------------
@contextmanager
def trace(name: str, *, user_id: Optional[str] = None, session_id: Optional[str] = None,
          input: Any = None, metadata: Optional[Dict[str, Any]] = None, tags=None):
    """Opens a root trace. Everything entered inside it becomes a nested observation."""
    client = get_client()
    meta = {"service": SERVICE_NAME, **(metadata or {})}
    started = time.time()
    recorder = _TraceRecorder(None, name)

    if client is None:
        try:
            yield recorder
        except Exception as exc:
            recorder.fail(exc)
            raise
        finally:
            logger.info(f"[trace] {name} duration={round(time.time() - started, 3)}s "
                        f"status={recorder.status}")
        return

    if _api == "otel":
        with _observation_cm(client, name, "span", input=input, metadata=meta) as handle:
            recorder._handle = handle
            _apply_trace_attributes(client, user_id, session_id, tags, meta)
            try:
                yield recorder
            except Exception as exc:
                recorder.fail(exc)
                raise
            finally:
                _update(handle, output=_truncate(recorder.output),
                        metadata={**meta, "duration_s": round(time.time() - started, 3),
                                  "status": recorder.status})
                _flush(client)
        return

    # Legacy v2 SDK
    handle = None
    try:
        handle = client.trace(name=name, user_id=user_id, session_id=session_id,
                              input=_truncate(input), metadata=meta, tags=tags or [])
    except Exception as e:
        logger.warning(f"LangFuse trace('{name}') failed: {e}")
    recorder._handle = handle
    token = _current_trace.set(handle)
    try:
        yield recorder
    except Exception as exc:
        recorder.fail(exc)
        raise
    finally:
        _update(handle, output=_truncate(recorder.output),
                metadata={**meta, "duration_s": round(time.time() - started, 3)})
        _flush(client)
        _current_trace.reset(token)


class _TraceRecorder:
    def __init__(self, handle, name: str):
        self._handle = handle
        self.name = name
        self.output: Any = None
        self.status = "ok"

    def set_output(self, value: Any):
        self.output = value

    def fail(self, exc: Exception):
        self.status = "error"
        self.output = f"{type(exc).__name__}: {exc}"

    def score(self, name: str, value: float, comment: str = ""):
        """Attaches an evaluation score (used by the RAG Triad reflection agent)."""
        client = get_client()
        if client is None:
            logger.info(f"[score] {self.name}.{name}={value} {comment}")
            return

        payload = {"name": name, "value": float(value), "comment": comment}
        for method in ("score_current_trace", "create_score", "score"):
            fn = getattr(client, method, None)
            if fn is None:
                continue
            try:
                if method == "score" and self._handle is not None:
                    fn(trace_id=self._handle.id, **payload)
                else:
                    fn(**payload)
                return
            except Exception as e:
                logger.warning(f"LangFuse {method}() failed: {e}")
        logger.info(f"[score] {self.name}.{name}={value} {comment}")


# ------------------------------------------------------------------------------
# Spans
# ------------------------------------------------------------------------------
@contextmanager
def span(name: str, *, kind: str = "agent", input: Any = None,
         metadata: Optional[Dict[str, Any]] = None):
    """Records one agent / tool / model step beneath the active trace."""
    client = get_client()
    meta = {"kind": kind, **(metadata or {})}
    started = time.time()
    recorder = _SpanRecorder(None, name)

    if client is None:
        try:
            yield recorder
        except Exception as exc:
            recorder.fail(exc)
            raise
        finally:
            logger.info(f"[{kind}] {name} duration={round(time.time() - started, 3)}s "
                        f"status={recorder.status}")
        return

    if _api == "otel":
        with _observation_cm(client, name, "span", input=input, metadata=meta) as handle:
            recorder._handle = handle
            try:
                yield recorder
            except Exception as exc:
                recorder.fail(exc)
                raise
            finally:
                _update(handle, output=_truncate(recorder.output),
                        metadata={**meta, "duration_s": round(time.time() - started, 3),
                                  "status": recorder.status})
        return

    # Legacy v2 SDK: attach to whichever parent is currently open.
    parent = _current_span.get() or _current_trace.get()
    handle = None
    if parent is not None:
        try:
            handle = parent.span(name=name, input=_truncate(input), metadata=meta)
        except Exception as e:
            logger.warning(f"LangFuse span('{name}') failed: {e}")
    recorder._handle = handle
    token = _current_span.set(handle or parent)
    try:
        yield recorder
    except Exception as exc:
        recorder.fail(exc)
        raise
    finally:
        _end(handle, output=_truncate(recorder.output),
             metadata={**meta, "duration_s": round(time.time() - started, 3),
                       "status": recorder.status})
        _current_span.reset(token)


class _SpanRecorder:
    def __init__(self, handle, name: str):
        self._handle = handle
        self.name = name
        self.output: Any = None
        self.status = "ok"

    def set_output(self, value: Any):
        self.output = value

    def fail(self, exc: Exception):
        self.status = "error"
        self.output = f"{type(exc).__name__}: {exc}"


def record_generation(name: str, *, model: str, prompt: Any, completion: Any,
                      metadata: Optional[Dict[str, Any]] = None, latency_s: float = 0.0):
    """Records an LLM call as a LangFuse generation so token/latency views work."""
    client = get_client()
    meta = {"latency_s": round(latency_s, 3), **(metadata or {})}

    if client is None:
        logger.info(f"[llm] {name} model={model} latency={meta['latency_s']}s")
        return

    if _api == "otel":
        with _observation_cm(client, name, "generation", input=prompt,
                             metadata=meta, model=model) as handle:
            _update(handle, output=_truncate(completion))
        return

    parent = _current_span.get() or _current_trace.get()
    if parent is None:
        logger.info(f"[llm] {name} model={model} latency={meta['latency_s']}s")
        return
    try:
        generation = parent.generation(name=name, model=model, input=_truncate(prompt), metadata=meta)
        generation.end(output=_truncate(completion))
    except Exception as e:
        logger.warning(f"LangFuse generation('{name}') failed: {e}")


def emit_test_trace() -> Dict[str, Any]:
    """Writes a self-contained trace so a deployment can prove tracing end to end."""
    info = status()
    if not info["enabled"]:
        return {"sent": False, **info}

    with trace("observability.selftest", user_id="selftest",
               input={"check": "connectivity"}, tags=["selftest"]) as tr:
        with span("observability.selftest.step", kind="diagnostic",
                  input={"nested": True}) as sp:
            sp.set_output({"ok": True})
        record_generation("observability.selftest.generation", model="n/a",
                          prompt="ping", completion="pong")
        tr.score("selftest", 1.0, comment="Emitted by /observability/test")
        tr.set_output({"ok": True})

    return {"sent": True, **info}


def observe(name: Optional[str] = None, kind: str = "agent"):
    """Decorator form of `span`, for node / tool functions."""
    def decorator(fn):
        label = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with span(label, kind=kind, input=kwargs or (args[0] if args else None)) as sp:
                result = fn(*args, **kwargs)
                sp.set_output(result)
                return result
        return wrapper
    return decorator
