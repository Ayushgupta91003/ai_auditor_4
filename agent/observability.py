"""No invoice text, prompts, credentials, or personal data are sent to traces."""
import logging
import os
from contextlib import contextmanager
log = logging.getLogger("invoice-auditor")
@contextmanager
def trace(name):
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        yield
        return
    from langfuse import get_client
    with get_client().start_as_current_observation(as_type="span",name=name) as span:
        try:
            yield
        except Exception:
            span.update(level="ERROR", status_message="Operation failed; see local audit status")
            raise
