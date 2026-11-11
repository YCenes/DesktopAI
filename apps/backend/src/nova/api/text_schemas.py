from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from nova.domain.text import Intent, MAX_TEXT_LENGTH


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str


class TextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(max_length=MAX_TEXT_LENGTH)


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["open_application", "search_files", "web_search"]
    target: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    executable: Literal[False]


class ArithmeticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(max_length=256)
    value: str = Field(pattern=r"^-?[0-9]+(?:\.[0-9]{1,6})?$")
    rounded: bool


class TextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_version: Literal["1"]
    original_text: str = Field(max_length=MAX_TEXT_LENGTH)
    normalized_text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    intent: Intent
    reply: str = Field(min_length=1, max_length=512)
    action: ActionResponse | None
    arithmetic: ArithmeticResponse | None
    external_calls: Literal[0]
