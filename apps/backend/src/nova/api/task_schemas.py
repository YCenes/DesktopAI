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


ActionPayload = Annotated[OpenAction | SearchAction, Field(discriminator="tool_id")]


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


class ResultView(StrictModel):
    status: Literal["succeeded", "failed"]
    message: str
    simulated: Literal[True]


class EventView(StrictModel):
    sequence: int
    kind: str
    status: Status
    created_at: float


class TaskView(StrictModel):
    api_version: Literal["1"]
    simulated: Literal[True]
    external_calls: Literal[0]
    action: ActionPayload
    status: Status
    result: ResultView | None
    error_code: str | None
    approval: ApprovalView | None
    events: list[EventView]


class TaskList(StrictModel):
    tasks: list[TaskView]
