"""
Agent-to-Agent (A2A) Protocol — data model
==========================================
Minimal, spec-shaped implementation of the A2A types the solution needs:
Agent Card (discovery), Message / Part (communication) and Task (invocation
result). Keeping these as plain dataclasses means a LangGraph agent and a Google
ADK agent exchange exactly the same JSON regardless of the framework that
produced it.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    inputModes: List[str] = field(default_factory=lambda: ["application/json"])
    outputModes: List[str] = field(default_factory=lambda: ["application/json"])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentCapabilities:
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentCard:
    """Published at /.well-known/agent-card.json so other agents can discover it."""
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    protocolVersion: str = "0.3.0"
    provider: Dict[str, str] = field(default_factory=lambda: {
        "organization": "AI Invoice Auditor", "url": "http://agent:8000"})
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    defaultInputModes: List[str] = field(default_factory=lambda: ["application/json", "text/plain"])
    defaultOutputModes: List[str] = field(default_factory=lambda: ["application/json", "text/plain"])
    skills: List[AgentSkill] = field(default_factory=list)
    framework: str = "langgraph"           # non-spec hint: which framework implements this agent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocolVersion,
            "provider": self.provider,
            "capabilities": self.capabilities.to_dict(),
            "defaultInputModes": self.defaultInputModes,
            "defaultOutputModes": self.defaultOutputModes,
            "skills": [s.to_dict() for s in self.skills],
            "framework": self.framework,
        }


@dataclass
class Part:
    kind: str = "data"                      # "text" | "data"
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": self.kind}
        if self.text is not None:
            payload["text"] = self.text
        if self.data is not None:
            payload["data"] = self.data
        return payload

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "Part":
        return Part(kind=raw.get("kind", "data"), text=raw.get("text"), data=raw.get("data"))


@dataclass
class Message:
    role: str = "user"                      # "user" (caller) | "agent" (responder)
    parts: List[Part] = field(default_factory=list)
    messageId: str = field(default_factory=lambda: str(uuid.uuid4()))
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    kind: str = "message"

    def data(self) -> Dict[str, Any]:
        """Merged payload of every data part — what a skill handler receives."""
        merged: Dict[str, Any] = {}
        for part in self.parts:
            if part.kind == "data" and isinstance(part.data, dict):
                merged.update(part.data)
        return merged

    def text(self) -> str:
        return "\n".join(p.text or "" for p in self.parts if p.kind == "text").strip()

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "parts": [p.to_dict() for p in self.parts],
                "messageId": self.messageId, "taskId": self.taskId,
                "contextId": self.contextId, "kind": self.kind}

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "Message":
        return Message(
            role=raw.get("role", "user"),
            parts=[Part.from_dict(p) for p in raw.get("parts", [])],
            messageId=raw.get("messageId") or str(uuid.uuid4()),
            taskId=raw.get("taskId"), contextId=raw.get("contextId"),
        )

    @staticmethod
    def of(payload: Dict[str, Any], *, text: str = "", role: str = "user") -> "Message":
        parts = [Part(kind="data", data=payload)]
        if text:
            parts.insert(0, Part(kind="text", text=text))
        return Message(role=role, parts=parts)


@dataclass
class TaskStatus:
    state: str = "submitted"                # submitted | working | completed | failed | rejected
    message: Optional[Message] = None
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return {"state": self.state,
                "message": self.message.to_dict() if self.message else None,
                "timestamp": self.timestamp}


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contextId: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = field(default_factory=TaskStatus)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Message] = field(default_factory=list)
    kind: str = "task"

    def result(self) -> Dict[str, Any]:
        """Convenience accessor for the first data artifact."""
        for artifact in self.artifacts:
            for part in artifact.get("parts", []):
                if part.get("kind") == "data" and isinstance(part.get("data"), dict):
                    return part["data"]
        return {}

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "contextId": self.contextId, "status": self.status.to_dict(),
                "artifacts": self.artifacts, "history": [m.to_dict() for m in self.history],
                "kind": self.kind}

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "Task":
        status_raw = raw.get("status") or {}
        status = TaskStatus(
            state=status_raw.get("state", "completed"),
            message=Message.from_dict(status_raw["message"]) if status_raw.get("message") else None,
            timestamp=status_raw.get("timestamp", _now()),
        )
        return Task(id=raw.get("id", str(uuid.uuid4())),
                    contextId=raw.get("contextId", str(uuid.uuid4())),
                    status=status, artifacts=raw.get("artifacts", []),
                    history=[Message.from_dict(m) for m in raw.get("history", [])])


def completed_task(payload: Dict[str, Any], *, request: Message,
                   name: str = "result") -> Task:
    task = Task(contextId=request.contextId or str(uuid.uuid4()))
    task.history = [request]
    task.status = TaskStatus(state="completed",
                             message=Message.of(payload, role="agent"))
    task.artifacts = [{"artifactId": str(uuid.uuid4()), "name": name,
                       "parts": [Part(kind="data", data=payload).to_dict()]}]
    return task


def failed_task(error: str, *, request: Message) -> Task:
    task = Task(contextId=request.contextId or str(uuid.uuid4()))
    task.history = [request]
    task.status = TaskStatus(state="failed",
                             message=Message.of({"error": error},
                                                text=error, role="agent"))
    return task
