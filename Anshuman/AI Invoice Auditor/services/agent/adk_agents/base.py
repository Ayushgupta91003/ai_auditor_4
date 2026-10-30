"""
Google ADK agent foundation
===========================
The solution deliberately uses two agentic frameworks. LangGraph orchestrates
the audit pipeline and the RAG loop; Google ADK implements the two agents that
are naturally request/response and benefit from ADK's tool-calling loop:

  * Translation Agent        (adk_translation_agent)
  * Business Validation Agent (adk_business_validation_agent)

Both are reached only over A2A — nothing in the LangGraph side imports them.

ADK is treated as optional at run time. When the SDK or a model is unavailable
the agent executes the same skill deterministically by calling the same MCP
tool directly, so the stack never degrades into a broken state. Which path ran
is always reported in `executor`.
"""

import os
import json
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from ..mcp_server.client import mcp_client
from ..utils import observability as obs

logger = logging.getLogger("adk")

BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "bedrock/amazon.nova-lite-v1:0")
ADK_APP_NAME = "invoice-auditor"
ADK_ENABLED = os.getenv("ADK_ENABLED", "true").strip().lower() not in ("0", "false", "no")


def _has_model_credentials() -> bool:
    key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    return bool(key and key != "your_aws_access_key_here" and os.getenv("AWS_SECRET_ACCESS_KEY", "").strip())


def mcp_tool_function(tool_name: str) -> Callable[..., Dict[str, Any]]:
    """Wraps an MCP tool as a plain Python callable ADK can expose as a FunctionTool.

    The ADK agent therefore reaches the very same tool implementation the
    LangGraph agents use — one tool, two frameworks.
    """
    def _call(**kwargs: Any) -> Dict[str, Any]:
        try:
            return {"status": "success", "result": mcp_client.call(tool_name, **kwargs)}
        except Exception as e:
            return {"status": "error", "error_message": f"{type(e).__name__}: {e}"}

    _call.__name__ = tool_name
    _call.__doc__ = f"Invokes the '{tool_name}' tool through the Model Context Protocol."
    return _call


class ADKAgent:
    """Base class: an ADK LlmAgent with a deterministic fallback execution path."""

    agent_id: str = "adk_agent"
    display_name: str = "ADK Agent"
    instruction: str = ""
    tool_names: List[str] = []

    def __init__(self):
        self._runner = None
        self._session_service = None
        self._build_attempted = False

    # -- ADK wiring ------------------------------------------------------------
    @property
    def adk_available(self) -> bool:
        return self._build() is not None

    def _build(self):
        if self._build_attempted:
            return self._runner
        self._build_attempted = True

        if not ADK_ENABLED:
            logger.info(f"[{self.agent_id}] ADK disabled by configuration; using the deterministic executor.")
            return None
        if not _has_model_credentials():
            logger.info(f"[{self.agent_id}] No model credentials; using the deterministic executor.")
            return None

        try:
            from google.adk.agents import LlmAgent
            from google.adk.models.lite_llm import LiteLlm
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.adk.tools import FunctionTool

            agent = LlmAgent(
                name=self.agent_id,
                model=LiteLlm(model=BEDROCK_MODEL),
                description=self.display_name,
                instruction=self.instruction,
                tools=[FunctionTool(func=mcp_tool_function(name)) for name in self.tool_names],
            )
            self._session_service = InMemorySessionService()
            self._runner = Runner(agent=agent, app_name=ADK_APP_NAME,
                                  session_service=self._session_service)
            logger.info(f"[{self.agent_id}] Google ADK agent initialised (model={BEDROCK_MODEL}).")
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Google ADK unavailable ({e}). Using the deterministic executor.")
            self._runner = None
        return self._runner

    def _run_adk(self, prompt: str, *, user_id: str = "agent", session_id: str = "default") -> str:
        """Drives one ADK turn and returns the final text response."""
        runner = self._build()
        if runner is None:
            raise RuntimeError("ADK runner is not available.")

        from google.genai import types

        self._ensure_session(user_id, session_id)
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        final_text = ""
        for event in runner.run(user_id=user_id, session_id=session_id, new_message=message):
            if getattr(event, "is_final_response", None) and event.is_final_response():
                content = getattr(event, "content", None)
                if content and getattr(content, "parts", None):
                    final_text = "".join(p.text or "" for p in content.parts)
        return final_text

    def _ensure_session(self, user_id: str, session_id: str) -> None:
        create = getattr(self._session_service, "create_session", None)
        if create is None:
            return
        try:
            result = create(app_name=ADK_APP_NAME, user_id=user_id, session_id=session_id)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Session creation skipped: {e}")

    # -- execution -------------------------------------------------------------
    def execute(self, skill: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with obs.span(f"adk:{self.agent_id}:{skill}", kind="adk_agent", input=payload) as sp:
            if self.adk_available:
                try:
                    result = self.run_with_adk(skill, payload)
                    result["executor"] = "google_adk"
                    sp.set_output(result)
                    return result
                except Exception as e:
                    logger.warning(f"[{self.agent_id}] ADK execution failed ({e}). "
                                   f"Falling back to the deterministic executor.")
            result = self.run_deterministic(skill, payload)
            result["executor"] = result.get("executor", "deterministic_tool_call")
            sp.set_output(result)
            return result

    def run_with_adk(self, skill: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def run_deterministic(self, skill: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        blob = (text or "").strip()
        if not blob:
            return None
        if "```" in blob:
            blob = blob.split("```json")[-1].split("```")[0] if "```json" in blob else blob.split("```")[1]
        try:
            parsed = json.loads(blob)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
