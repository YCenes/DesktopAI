"""Framework bağımsız, yalnızca simülasyona ait değişmez sözleşmeler."""
from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from typing import Literal
from uuid import UUID


class TaskError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


TERMINAL = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.UNKNOWN})
TRANSITIONS = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.RUNNING: {TaskStatus.AWAITING_APPROVAL, *TERMINAL},
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
    TaskStatus.UNKNOWN: {TaskStatus.SUCCEEDED, TaskStatus.FAILED},
}


def identifier(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    raise TaskError("INVALID_ACTION", "Görev veya eylem kimliği geçersiz.", 422)


@dataclass(frozen=True)
class OpenAppArguments:
    app_id: Literal["demo.editor", "demo.admin"]


@dataclass(frozen=True)
class SearchFilesArguments:
    query: Literal["ornek", "rapor"]
    root_id: Literal["synthetic.documents"]


@dataclass(frozen=True)
class RegisteredAppArguments:
    app_id: Literal["windows.notepad"]


@dataclass(frozen=True)
class ScopedSearchArguments:
    root_id: str
    query: str


@dataclass(frozen=True)
class OpenFileArguments:
    root_id: str
    relative_path: str
    identity: str


@dataclass(frozen=True)
class WebSearchArguments:
    query: str


@dataclass(frozen=True)
class ActionRequest:
    task_id: str
    action_id: str
    tool_id: str
    arguments: OpenAppArguments | SearchFilesArguments | RegisteredAppArguments | ScopedSearchArguments | OpenFileArguments | WebSearchArguments
    scope: str

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    argument_schema: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    side_effect: str
    risk: Literal["low", "high"]
    expected_effect: str
    simulated: bool = True


@dataclass(frozen=True)
class PermissionDecision:
    decision: Literal["allow", "deny", "require_approval"]
    reason: str
    policy_version: str
    risk: Literal["low", "high"]


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    action: ActionRequest
    risk: str
    expected_effect: str
    expires_at: float
    policy_version: str


@dataclass(frozen=True)
class ApprovalGrant:
    approval_id: str
    task_id: str
    action_id: str
    session_id: str
    policy_version: str
    expires_at: float
    specification: str


@dataclass(frozen=True)
class FileMatch:
    root_id: str
    relative_path: str
    identity: str
    size: int


@dataclass(frozen=True)
class ToolResultDetails:
    completion: Literal['process_started','handoff_requested','metadata_search','search_submitted']
    process_id: int | None = None
    files: tuple[FileMatch, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    message: str
    simulated: bool = True
    details: ToolResultDetails | None = None


@dataclass(frozen=True)
class TaskEvent:
    sequence: int
    kind: str
    status: str
    created_at: float


@dataclass(frozen=True)
class Task:
    action: ActionRequest
    status: str
    result: ExecutionResult | None
    error_code: str | None
    events: tuple[TaskEvent, ...]
