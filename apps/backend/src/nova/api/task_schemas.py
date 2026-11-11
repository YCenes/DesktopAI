from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
Status = Literal["queued", "running", "awaiting_approval", "succeeded", "failed", "cancelled", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenArguments(StrictModel):
    app_id: Literal["demo.editor", "demo.admin"]


class SearchArguments(StrictModel):
    query: Literal["ornek", "rapor"]
    root_id: Literal["synthetic.documents"]


class OpenAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal["fake.open_app"]
    arguments: OpenArguments
    scope: Literal["simulation.apps"]


class SearchAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal["fake.search_files"]
    arguments: SearchArguments
    scope: Literal["simulation.files"]


class RegisteredAppPayload(StrictModel):
    app_id: Literal['windows.notepad']


class WindowsAppAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal['windows.open_app']
    arguments: RegisteredAppPayload
    scope: Literal['windows.apps']


class ScopedSearchPayload(StrictModel):
    root_id: Annotated[str,Field(pattern='^[a-z][a-z0-9_-]{0,31}$')]
    query: Annotated[str,Field(min_length=1,max_length=64)]


class FileOpenPayload(StrictModel):
    root_id: Annotated[str,Field(pattern='^[a-z][a-z0-9_-]{0,31}$')]
    relative_path: Annotated[str,Field(min_length=1,max_length=180)]
    identity: Annotated[str,Field(pattern='^[a-f0-9]{64}$')]


class ScopedSearchAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal['windows.search_files']
    arguments: ScopedSearchPayload
    scope: Literal['windows.files']


class FileOpenAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal['windows.open_file']
    arguments: FileOpenPayload
    scope: Literal['windows.files']


class WebPayload(StrictModel):
    query: Annotated[str,Field(min_length=1,max_length=256)]


class WebAction(StrictModel):
    task_id: Identifier
    action_id: Identifier
    tool_id: Literal['windows.web_search']
    arguments: WebPayload
    scope: Literal['windows.web']


ActionPayload = Annotated[OpenAction | SearchAction | WindowsAppAction | ScopedSearchAction | FileOpenAction | WebAction, Field(discriminator="tool_id")]
FakeActionPayload = Annotated[OpenAction | SearchAction,Field(discriminator='tool_id')]
WindowsActionPayload = Annotated[WindowsAppAction | ScopedSearchAction | FileOpenAction | WebAction,Field(discriminator='tool_id')]


class WindowsCommandPayload(StrictModel):
    task_id: Identifier
    action_id: Identifier
    text: Annotated[str,Field(min_length=1,max_length=1024)]


class ApprovalDecisionPayload(StrictModel):
    approval_id: Identifier
    approve: bool
    source: Literal["screen"]


class ApprovalView(StrictModel):
    approval_id: Identifier
    action: ActionPayload
    risk: Literal["high"]
    expected_effect: str
    expires_at: float
    policy_version: str


class FileMatchView(FileOpenPayload):
    size: int


class DetailsView(StrictModel):
    completion: Literal['process_started','handoff_requested','metadata_search','search_submitted']
    process_id: int | None = None
    files: list[FileMatchView] = []
    truncated: bool = False


class ResultView(StrictModel):
    status: Literal["succeeded", "failed"]
    message: str
    simulated: bool
    details: DetailsView | None = None


class EventView(StrictModel):
    sequence: int
    kind: str
    status: Status
    created_at: float


class TaskView(StrictModel):
    api_version: Literal["1"]
    simulated: bool
    external_calls: Literal[0]
    action: ActionPayload
    status: Status
    result: ResultView | None
    error_code: str | None
    approval: ApprovalView | None
    events: list[EventView]


class TaskList(StrictModel):
    tasks: list[TaskView]
