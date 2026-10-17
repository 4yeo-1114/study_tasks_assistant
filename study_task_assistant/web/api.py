import os
import secrets
import logging
from time import perf_counter
from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path as FastAPIPath, Request, Response, UploadFile, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from web.auth import AuthService
from agent.agent_loop import (
    AgentBudget,
    AgentBudgetExceededError,
    AgentStepLimitError,
    run_readonly_agent,
)
from storage.database import Database
from llm.deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
)
from llm.deepseek_tools import DeepSeekToolResponseError
from agent.readonly_tools import ToolArgumentsError, ToolNotAllowedError
from tasks.repository import TaskRepository
from web.schemas import (
    AgentChatRead,
    AgentChatRequest,
    DocumentIngestRead,
    DocumentRead,
    DocumentUploadRequest,
    TaskCreate,
    TaskPriority,
    TaskProposalConfirmed,
    TaskProposalRead,
    TaskProposalRequest,
    TaskRead,
    TaskStatusUpdate,
    TokenRead,
    UserCreate,
    UserRead,
)
from tasks.service import TaskService
from tasks.task_proposals import (
    ProposalConflictError,
    ProposalExpiredError,
    ProposalNotFoundError,
    TaskProposalService,
    propose_task_from_model,
)
from knowledge.knowledge_runtime import (
    KnowledgeRuntimeError,
    build_production_runtime,
    rag_enabled_from_env,
)
from knowledge.document_lifecycle import DocumentVersionConflictError
from knowledge.document_service import DocumentNotFoundError, DocumentUpload
from core.observability import (
    configure_application_logging,
    log_event,
    new_request_id,
    request_context,
)


http_logger = logging.getLogger("study_task.http")


def normalize_database_url(value: str | Path) -> str:
    if isinstance(value, Path):
        return f"sqlite+pysqlite:///{value.resolve().as_posix()}"
    if "://" in value:
        return value
    return f"sqlite+pysqlite:///{Path(value).resolve().as_posix()}"


def get_default_database_url() -> str:
    default_path = (Path(__file__).resolve().parents[1] / "tasks.db").resolve().as_posix()
    return os.environ.get(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{default_path}",
    )


def create_app(
    database_location: str | Path,
    *,
    token_secret: str | None = None,
    agent_runner: Callable = run_readonly_agent,
    settings_factory: Callable[[], DeepSeekSettings] = DeepSeekSettings.from_env,
    knowledge_executor_factory: Callable[[], object] | None = None,
    document_service_factory: Callable[[], object] | None = None,
) -> FastAPI:
    configure_application_logging()
    #创建数据库连接管理对象
    database = Database(normalize_database_url(database_location))
    if (
        knowledge_executor_factory is None
        and document_service_factory is None
        and rag_enabled_from_env()
    ):
        try:
            knowledge_runtime = build_production_runtime(database)
            knowledge_executor_factory = knowledge_runtime.executor_factory
            document_service_factory = knowledge_runtime.document_service
        except Exception:
            database.dispose()
            raise

    #service处理任务的业务层
    service = TaskService(TaskRepository(database.sessions))
    #proposal处理创建任务提案的业务层
    proposals = TaskProposalService(database.sessions)
    secret = token_secret or os.environ.get("STUDY_TASK_SECRET_KEY") or secrets.token_hex(32)
    if len(secret.encode("utf-8")) < 32:
        database.dispose()
        raise ValueError("STUDY_TASK_SECRET_KEY 至少需要 32 字节")
    auth = AuthService(database.sessions, secret)
    #告诉/docs登录接口在哪里
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

    def current_user_id(token: Annotated[str, Depends(oauth2_scheme)]) -> int:
        user_id = auth.user_id_for_token(token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="无效或过期的登录凭据")
        return user_id

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(title="Study Task Assistant", lifespan=lifespan)
    app.state.database = database
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    if frontend_dir.is_dir():
        app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    @app.middleware("http")
    async def observe_http_request(request: Request, call_next):
        request_id = new_request_id()
        started = perf_counter()
        with request_context(request_id):
            try:
                response = await call_next(request)
            except Exception as exc:
                log_event(
                    http_logger,
                    "http_request_failed",
                    level=logging.ERROR,
                    method=request.method,
                    path=request.url.path,
                    duration_ms=(perf_counter() - started) * 1000,
                    error_type=type(exc).__name__,
                )
                raise
            response.headers["X-Request-ID"] = request_id
            log_event(
                http_logger,
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return response

    @app.post("/auth/register", response_model=UserRead, status_code=201)
    def register(user: UserCreate):
        created = auth.register(user.username, user.password)
        if created is None:
            raise HTTPException(status_code=409, detail="用户名已存在")
        return created

    @app.post("/auth/login", response_model=TokenRead)
    def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
        token = auth.login(form.username.strip().lower(), form.password)
        if token is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return {"access_token": token, "token_type": "bearer"}

    @app.get("/tasks", response_model=list[TaskRead])
    #这里的user_id 是fastapi先调用Depends(current_user_id)得到的结果 不是客户端上传的
    def get_tasks(
        user_id: Annotated[int, Depends(current_user_id)],
        status: str | None = None,
        priority: TaskPriority | None = None,
    ):
        return service.list_tasks(user_id, status=status, priority=priority)

    @app.get("/tasks/{task_id}", response_model=TaskRead)
    def get_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.get_task(user_id, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.patch("/tasks/{task_id}", response_model=TaskRead)
    def update_task_status(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        update: TaskStatusUpdate,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.update_task_status(user_id, task_id, update.status)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        user_id: Annotated[int, Depends(current_user_id)],
    ) -> Response:
        if not service.delete_task(user_id, task_id):
            raise HTTPException(status_code=404, detail="找不到任务")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/tasks",
        response_model=TaskRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate, user_id: Annotated[int, Depends(current_user_id)]):
        return service.create_task(user_id, task)

    def _document_service():
        if document_service_factory is None:
            raise HTTPException(status_code=503, detail="文档知识库未启用")
        try:
            return document_service_factory()
        except KnowledgeRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/documents", response_model=DocumentIngestRead, status_code=201)
    def upload_document(
        request: DocumentUploadRequest,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            result = _document_service().ingest(
                user_id,
                DocumentUpload(
                    source=request.source,
                    content=request.content,
                    document_version=request.document_version,
                    chunk_size=request.chunk_size,
                    overlap=request.overlap,
                ),
            )
        except DocumentVersionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": result.document.id,
            "source": result.document.source,
            "document_version": result.document.document_version,
            "state": result.document.state,
            "error_message": result.document.error_message,
            "active_version": result.document.active_version,
            "created_at": result.document.created_at,
            "updated_at": result.document.updated_at,
            "chunks_ingested": result.chunks_ingested,
        }

    @app.post("/documents/file", response_model=DocumentIngestRead, status_code=201)
    def upload_document_file(
        user_id: Annotated[int, Depends(current_user_id)],
        file: UploadFile = File(...),
        document_version: str = Form("v1"),
        chunk_size: int = Form(500),
        overlap: int = Form(50),
    ):
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() not in {".md", ".txt"}:
            raise HTTPException(status_code=415, detail="只支持 .md 和 .txt 文件")
        raw = file.file.read()
        if len(raw) > 1_000_000:
            raise HTTPException(status_code=413, detail="文件不能超过 1 MB")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="文件必须使用 UTF-8 编码") from exc
        try:
            request = DocumentUploadRequest(
                source=filename,
                content=content,
                document_version=document_version,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            result = _document_service().ingest(
                user_id,
                DocumentUpload(
                    source=request.source,
                    content=request.content,
                    document_version=request.document_version,
                    chunk_size=request.chunk_size,
                    overlap=request.overlap,
                ),
            )
        except DocumentVersionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": result.document.id,
            "source": result.document.source,
            "document_version": result.document.document_version,
            "state": result.document.state,
            "error_message": result.document.error_message,
            "active_version": result.document.active_version,
            "created_at": result.document.created_at,
            "updated_at": result.document.updated_at,
            "chunks_ingested": result.chunks_ingested,
        }

    @app.get("/documents", response_model=list[DocumentRead])
    def list_documents(user_id: Annotated[int, Depends(current_user_id)]):
        return _document_service().list(user_id)

    @app.get("/documents/{document_id}", response_model=DocumentRead)
    def get_document(
        document_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            return _document_service().get(user_id, document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/documents/{document_id}", status_code=204)
    def delete_document(
        document_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ) -> Response:
        try:
            _document_service().delete(user_id, document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.post("/agent/chat", response_model=AgentChatRead)
    def agent_chat(
        request: AgentChatRequest,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            result = agent_runner(
                request.message,
                user_id=user_id,
                service=service,
                proposal_service=proposals,
                knowledge_executor=(
                    knowledge_executor_factory()
                    if knowledge_executor_factory is not None
                    else None
                ),
                settings=settings_factory(),
                budget=AgentBudget(max_tool_calls=8, max_total_tokens=10_000),
            )
        except AgentBudgetExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except AgentStepLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except DeepSeekConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KnowledgeRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (
            DeepSeekAPIError,
            DeepSeekNetworkError,
            DeepSeekResponseError,
            DeepSeekToolResponseError,
        ) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except (ToolArgumentsError, ToolNotAllowedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProposalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        public_trace = [
            {
                "step": event.step,
                "state": event.state.value,
                "event": event.event,
                "tool_call_id": event.tool_call_id,
                "proposal_id": event.proposal_id,
                "tool_name": event.tool_name,
            }
            for event in result.trace
        ]
        proposal_ids = dict.fromkeys(
            event.proposal_id for event in result.trace if event.proposal_id
        )
        pending_proposals = []
        for proposal_id in proposal_ids:
            proposal = proposals.get(user_id, proposal_id)
            if proposal["status"] == "pending":
                pending_proposals.append(proposal)
        return {
            "answer": result.answer,
            "model_steps": result.model_steps,
            "tool_calls": result.tool_calls,
            "total_tokens": result.total_tokens,
            "trace": public_trace,
            "pending_proposals": pending_proposals,
        }

    @app.post("/agent/task-proposals", response_model=TaskProposalRead, status_code=201)
    def propose_task(
        request: TaskProposalRequest,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            return propose_task_from_model(
                request.question,
                user_id=user_id,
                service=proposals,
                settings=DeepSeekSettings.from_env(),
            )
        except DeepSeekConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (
            DeepSeekAPIError,
            DeepSeekNetworkError,
            DeepSeekResponseError,
            DeepSeekToolResponseError,
            ToolArgumentsError,
            ValueError,
        ) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def _proposal_action(action, proposal_id: str, user_id: int):
        try:
            return action(user_id, proposal_id)
        except ProposalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProposalExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except ProposalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/agent/task-proposals/{proposal_id}", response_model=TaskProposalRead)
    def get_proposal(
        proposal_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        return _proposal_action(proposals.get, proposal_id, user_id)

    @app.post(
        "/agent/task-proposals/{proposal_id}/confirm",
        response_model=TaskProposalConfirmed,
    )
    def confirm_proposal(
        proposal_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        return _proposal_action(proposals.confirm, proposal_id, user_id)

    @app.post(
        "/agent/task-proposals/{proposal_id}/reject",
        response_model=TaskProposalRead,
    )
    def reject_proposal(
        proposal_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        return _proposal_action(proposals.reject, proposal_id, user_id)

    return app


app = create_app(get_default_database_url())
