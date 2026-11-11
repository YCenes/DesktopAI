from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nova import __version__
from nova.application.health import HealthService
from nova.application.text_processing import TextProcessingService
from nova.api.text_schemas import ErrorResponse, TextRequest, TextResponse
from nova.domain.text import TextError
from nova.infrastructure.config import Settings
from nova.infrastructure.task_runtime import TaskRuntime
from nova.domain.tasks import TaskError
from nova.api.task_schemas import FakeActionPayload, WindowsActionPayload, WindowsCommandPayload, ApprovalDecisionPayload, TaskView, TaskList
from nova.application.windows_commands import command_action


def error_response(code: str, message: str, status: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(error_code=code, message=message, request_id=request_id).model_dump(),
        status_code=status,
    )


class LocalSessionBoundary:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = scope["headers"]

        def values(name: bytes) -> list[bytes]:
            return [value for key, value in headers if key.lower() == name]

        if values(b"host") != [self.settings.authority.encode("ascii")]:
            response = error_response("INVALID_HOST", "Backend adresi kabul edilmedi.", 400, request_id)
        elif values(b"origin"):
            response = error_response("ORIGIN_FORBIDDEN", "Bu istemci kaynağına izin verilmiyor.", 403, request_id)
        elif scope.get("query_string"):
            response = error_response("QUERY_FORBIDDEN", "URL parametreleri kabul edilmiyor.", 400, request_id)
        else:
            auth = values(b"authorization")
            expected = f"Bearer {self.settings.session_token}".encode("ascii")
            if len(auth) != 1 or not hmac.compare_digest(auth[0], expected):
                response = error_response("SESSION_UNAUTHORIZED", "Oturum doğrulanamadı.", 401, request_id)
            else:
                # Kimlik doğrulamasından sonra, JSON parse edilmeden önce sınırlı body.
                if scope["method"] == "POST":
                    body = bytearray()
                    while True:
                        chunk = await receive()
                        if chunk["type"] == "http.disconnect":
                            return
                        data = chunk.get("body", b"")
                        if len(body) + len(data) > 16_384:
                            response = error_response("REQUEST_TOO_LARGE", "İstek boyutu izin verilen sınırı aşıyor.", 413, request_id)
                            await response(scope, receive, send)
                            return
                        body.extend(data)
                        if not chunk.get("more_body", False):
                            break
                    consumed = False

                    async def limited_receive():
                        nonlocal consumed
                        if not consumed:
                            consumed = True
                            return {"type": "http.request", "body": bytes(body), "more_body": False}
                        return await receive()

                    await self.app(scope, limited_receive, send)
                    return
                await self.app(scope, receive, send)
                return
        await response(scope, receive, send)


class HealthResponse(BaseModel):
    api_version: str = "1"
    app_version: str = __version__
    status: str = "ok"


class ReadinessResponse(BaseModel):
    api_version: str = "1"
    status: str = "ready"


def create_app(settings: Settings) -> FastAPI:
    health = HealthService()
    text_service = TextProcessingService()
    tasks = TaskRuntime(settings.task_database,settings.windows_tools_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        health.ready = True
        try:
            yield
        finally:
            health.ready = False
            tasks.close()

    app = FastAPI(
        title="NOVA yerel backend", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.health = health
    app.state.tasks = tasks

    @app.exception_handler(TaskError)
    async def task_error(request: Request, exc: TaskError):
        return error_response(exc.code, exc.message, exc.status, request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code, message = {
            404: ("NOT_FOUND", "İstenen API yolu bulunamadı."),
            405: ("METHOD_NOT_ALLOWED", "Bu işleme izin verilmiyor."),
        }.get(exc.status_code, ("API_ERROR", "API isteği tamamlanamadı."))
        return error_response(code, message, exc.status_code, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if any(error["type"] == "string_too_long" and error["loc"] == ("body", "text") for error in exc.errors()):
            return error_response("TEXT_TOO_LONG", "Mesaj en fazla 1.024 karakter olabilir.", 422, request.state.request_id)
        return error_response("INVALID_REQUEST", "İstek biçimi geçersiz.", 422, request.state.request_id)

    @app.exception_handler(TextError)
    async def text_error(request: Request, exc: TextError):
        return error_response(exc.code, exc.message, 422, request.state.request_id)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return error_response("INTERNAL_ERROR", "Backend isteği tamamlanamadı.", 500, request.state.request_id)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/v1/ready", response_model=ReadinessResponse, responses={503: {"description": "Hazır değil"}})
    def get_readiness(request: Request):
        if not health.ready:
            return error_response("NOT_READY", "Backend henüz hazır değil.", 503, request.state.request_id)
        return ReadinessResponse()

    @app.post("/api/v1/text", response_model=TextResponse,
              responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 413, 422, 500)})
    def process_text(payload: TextRequest) -> TextResponse:
        return TextResponse(**asdict(text_service.process(payload.text)))

    @app.post("/api/v1/tasks", response_model=TaskView)
    def create_task(payload: FakeActionPayload):
        service = tasks.get()
        return service.create(service.registry.from_dict(payload.model_dump()))

    @app.get("/api/v1/tasks", response_model=TaskList)
    def list_tasks():
        return {"tasks": tasks.get().list_tasks(simulated=True)}

    def check_kind(task_id: str, simulated: bool):
        service=tasks.get()
        if service.view(task_id)['simulated'] is not simulated:
            raise TaskError('TASK_KIND_DENIED','Bu görev bu API kanalına ait değil.',403)
        return service

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskView)
    def get_task(task_id: str):
        return check_kind(task_id,True).view(task_id)

    @app.post("/api/v1/tasks/{task_id}/approval", response_model=TaskView)
    def decide_approval(task_id: str, payload: ApprovalDecisionPayload):
        return check_kind(task_id,True).respond(task_id, payload.approval_id, payload.approve)

    @app.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskView)
    def cancel_task(task_id: str):
        return check_kind(task_id,True).cancel(task_id)

    @app.post("/api/v1/tasks/{task_id}/reconcile", response_model=TaskView)
    def reconcile_task(task_id: str):
        return check_kind(task_id,True).reconcile(task_id)

    @app.post('/api/v1/windows/commands',response_model=TaskView)
    def submit_windows_command(payload: WindowsCommandPayload):
        service=tasks.get()
        action=command_action(payload.text,payload.task_id,payload.action_id,tuple(service.registry.windows.roots))
        return service.create(action)

    @app.post('/api/v1/windows/tasks',response_model=TaskView)
    def create_windows_task(payload: WindowsActionPayload):
        service=tasks.get()
        return service.create(service.registry.from_dict(payload.model_dump()))

    @app.get('/api/v1/windows/tasks',response_model=TaskList)
    def list_windows_tasks():
        return {'tasks':tasks.get().list_tasks(simulated=False)}

    @app.get('/api/v1/windows/tasks/{task_id}',response_model=TaskView)
    def get_windows_task(task_id: str):
        return check_kind(task_id,False).view(task_id)

    @app.post('/api/v1/windows/tasks/{task_id}/approval',response_model=TaskView)
    def approve_windows_task(task_id: str,payload: ApprovalDecisionPayload):
        return check_kind(task_id,False).respond(task_id,payload.approval_id,payload.approve)

    @app.post('/api/v1/windows/tasks/{task_id}/cancel',response_model=TaskView)
    def cancel_windows_task(task_id: str):
        return check_kind(task_id,False).cancel(task_id)

    # Dıştaki sınır, auth/Host hatalarının exception ayrıntısı sızdırmasını önler.
    app.add_middleware(LocalSessionBoundary, settings=settings)
    return app
