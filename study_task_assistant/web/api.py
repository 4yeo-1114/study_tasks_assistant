import os
import secrets
import logging
from datetime import date
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
    AgentSessionRead,
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
    TaskProgressRead,
    BodyWeightCreate,
    BodyWeightRead,
    FitnessProgressRead,
    WorkoutCreate,
    WorkoutRead,
    FitnessCsvRequest,
    FitnessCsvPreviewRead,
    FitnessCsvCommitRead,
    TokenRead,
    UserCreate,
    UserRead,
    UserProfileRead,
    UserProfileUpdate,
    WeeklyPlanCreate,
    WeeklyPlanAdjustmentRequest,
    WeeklyPlanRead,
    WeeklyPlanWorkflowRead,
)
from tasks.service import TaskService
from fitness.repository import FitnessRepository
from fitness.service import FitnessService
from fitness.importer import FitnessCsvError
from user_profile.repository import UserProfileNotFoundError, UserProfileRepository
from user_profile.service import UserProfileService
from weekly_plans.service import (
    WeeklyPlanConflictError,
    WeeklyPlanNotFoundError,
    WeeklyPlanService,
    WeeklyPlanValidationError,
)
from agent.session_store import AgentSessionNotFoundError, AgentSessionStore
from agent.persistent_runtime import create_checkpoint_store, run_agent_graph
from agent.plan_approval import PlanApprovalWorkflow
from agent.planning_tools import PlanningToolExecutor
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
from knowledge.pdf_parser import UnsupportedPdfError, extract_pdf_pages
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
    checkpoint_store = create_checkpoint_store(database.url)
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
            checkpoint_store.close()
            database.dispose()
            raise

    #service处理任务的业务层
    service = TaskService(TaskRepository(database.sessions))
    fitness = FitnessService(FitnessRepository(database.sessions))
    profiles = UserProfileService(UserProfileRepository(database.sessions))
    weekly_plans = WeeklyPlanService(database.sessions)
    plan_approval = PlanApprovalWorkflow(weekly_plans, checkpoint_store.saver)
    agent_sessions = AgentSessionStore(database.sessions)
    #proposal处理创建任务提案的业务层
    proposals = TaskProposalService(database.sessions)
    secret = token_secret or os.environ.get("STUDY_TASK_SECRET_KEY") or secrets.token_hex(32)
    if len(secret.encode("utf-8")) < 32:
        checkpoint_store.close()
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
            checkpoint_store.close()
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

    @app.get("/tasks", response_model=list[TaskRead], response_model_exclude_unset=True)
    #这里的user_id 是fastapi先调用Depends(current_user_id)得到的结果 不是客户端上传的
    def get_tasks(
        user_id: Annotated[int, Depends(current_user_id)],
        status: str | None = None,
        priority: TaskPriority | None = None,
    ):
        return service.list_tasks(user_id, status=status, priority=priority)

    @app.get("/tasks/progress", response_model=TaskProgressRead)
    def get_task_progress(user_id: Annotated[int, Depends(current_user_id)]):
        return service.progress(user_id)

    @app.get("/profile", response_model=UserProfileRead)
    def get_profile(user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return profiles.get(user_id)
        except UserProfileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/profile", response_model=UserProfileRead)
    def replace_profile(
        profile: UserProfileUpdate,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        return profiles.replace(user_id, profile)

    @app.delete("/profile", status_code=status.HTTP_204_NO_CONTENT)
    def delete_profile(user_id: Annotated[int, Depends(current_user_id)]) -> Response:
        if not profiles.delete(user_id):
            raise HTTPException(status_code=404, detail="尚未创建用户档案")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/plans/weekly", response_model=WeeklyPlanRead, status_code=201)
    def create_weekly_plan(request: WeeklyPlanCreate, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            result = weekly_plans.create(user_id, request)
            plan_approval.wait(user_id, result["id"])
            return result
        except WeeklyPlanConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WeeklyPlanValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/plans/current", response_model=WeeklyPlanRead)
    def get_current_weekly_plan(week_start: date, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return weekly_plans.current(user_id, week_start)
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/plans", response_model=list[WeeklyPlanRead])
    def list_weekly_plans(user_id: Annotated[int, Depends(current_user_id)]):
        return weekly_plans.list_recent(user_id)

    @app.post("/plans/{plan_id}/adjust", response_model=WeeklyPlanRead, status_code=201)
    def adjust_weekly_plan(
        plan_id: str,
        request: WeeklyPlanAdjustmentRequest,
        user_id: Annotated[int, Depends(current_user_id)],
        response: Response,
    ):
        try:
            result, created = weekly_plans.adjust(user_id, plan_id, request.idempotency_key)
            plan_approval.wait(user_id, result["id"])
            if not created:
                response.status_code = status.HTTP_200_OK
            return result
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WeeklyPlanConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WeeklyPlanValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/plans/{plan_id}", response_model=WeeklyPlanRead)
    def get_weekly_plan(plan_id: str, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return weekly_plans.get(user_id, plan_id)
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/plans/{plan_id}/workflow", response_model=WeeklyPlanWorkflowRead)
    def get_plan_workflow(plan_id: str, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return plan_approval.wait(user_id, plan_id)
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/plans/{plan_id}/confirm", response_model=WeeklyPlanRead)
    def confirm_weekly_plan(plan_id: str, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return plan_approval.decide(user_id, plan_id, "confirm")
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WeeklyPlanConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/plans/{plan_id}/reject", response_model=WeeklyPlanRead)
    def reject_weekly_plan(plan_id: str, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return plan_approval.decide(user_id, plan_id, "reject")
        except WeeklyPlanNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WeeklyPlanConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/tasks/{task_id}", response_model=TaskRead, response_model_exclude_unset=True)
    def get_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.get_task(user_id, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.patch("/tasks/{task_id}", response_model=TaskRead, response_model_exclude_unset=True)
    def update_task_status(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        update: TaskStatusUpdate,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.update_task_status(user_id, task_id, update.status, update.actual_minutes)
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
        response_model_exclude_unset=True,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate, user_id: Annotated[int, Depends(current_user_id)]):
        return service.create_task(user_id, task)

    @app.post("/fitness/workouts", response_model=WorkoutRead, status_code=201)
    def create_workout(workout: WorkoutCreate, user_id: Annotated[int, Depends(current_user_id)]):
        return fitness.create_workout(user_id, workout)

    @app.post("/fitness/weight", response_model=BodyWeightRead, status_code=201)
    def add_body_weight(record: BodyWeightCreate, user_id: Annotated[int, Depends(current_user_id)]):
        return fitness.add_weight(user_id, record)

    @app.get("/fitness/progress", response_model=FitnessProgressRead)
    def fitness_progress(user_id: Annotated[int, Depends(current_user_id)]):
        return fitness.progress(user_id)

    @app.post("/fitness/import/preview", response_model=FitnessCsvPreviewRead)
    def preview_fitness_import(request: FitnessCsvRequest, user_id: Annotated[int, Depends(current_user_id)]):
        try:
            return fitness.preview_import(request.csv_text)
        except FitnessCsvError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/fitness/import/commit", response_model=FitnessCsvCommitRead)
    def commit_fitness_import(
        request: FitnessCsvRequest,
        response: Response,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            result = fitness.commit_import(user_id, request.csv_text)
            created = result.pop("created", False)
            response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return result
        except FitnessCsvError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".txt", ".pdf"}:
            raise HTTPException(status_code=415, detail="只支持 .md、.txt 和文本 PDF 文件")
        raw = file.file.read()
        if len(raw) > 1_000_000:
            raise HTTPException(status_code=413, detail="文件不能超过 1 MB")
        pages = None
        if suffix == ".pdf":
            try:
                parsed_pages = extract_pdf_pages(raw)
            except UnsupportedPdfError as exc:
                raise HTTPException(status_code=415, detail=str(exc)) from exc
            content = "\n\n".join(page.text for page in parsed_pages)
            pages = tuple(parsed_pages)
        else:
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
                    pages=pages,
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
            conversation = agent_sessions.open(user_id, request.session_id)
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in agent_sessions.detail(user_id, conversation["id"])["messages"]
            ]
            run = agent_sessions.start_run(user_id, conversation["id"])
        except AgentSessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            result = run_agent_graph(
                lambda: agent_runner(
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
                    history=history,
                    planning_executor=PlanningToolExecutor(
                        profiles=profiles, plans=weekly_plans, approval=plan_approval,
                        tasks=service, fitness=fitness, request_key=request.idempotency_key or run["id"],
                    ),
                ),
                checkpointer=checkpoint_store.saver,
                thread_id=conversation["id"],
            )
            agent_sessions.complete_run(
                user_id, conversation["id"], run["id"], request.message, result
            )
        except Exception as exc:
            agent_sessions.fail_run(user_id, conversation["id"], run["id"], exc)
            if isinstance(exc, (AgentBudgetExceededError, AgentStepLimitError)):
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            if isinstance(exc, (DeepSeekConfigurationError, KnowledgeRuntimeError)):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            if isinstance(exc, (DeepSeekAPIError, DeepSeekNetworkError, DeepSeekResponseError, DeepSeekToolResponseError)):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if isinstance(exc, (ToolArgumentsError, ToolNotAllowedError)):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if isinstance(exc, WeeklyPlanValidationError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if isinstance(exc, WeeklyPlanNotFoundError):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if isinstance(exc, (ProposalConflictError, WeeklyPlanConflictError)):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise

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
            event.proposal_id for event in result.trace
            if event.proposal_id and event.tool_name not in {"propose_weekly_plan", "propose_plan_adjustment"}
        )
        pending_proposals = []
        for proposal_id in proposal_ids:
            proposal = proposals.get(user_id, proposal_id)
            if proposal["status"] == "pending":
                pending_proposals.append(proposal)
        pending_plans = []
        for plan_id in dict.fromkeys(event.proposal_id for event in result.trace
                                    if event.proposal_id and event.tool_name in {"propose_weekly_plan", "propose_plan_adjustment"}):
            plan = weekly_plans.get(user_id, plan_id)
            if plan["status"] == "pending":
                pending_plans.append(plan)
        return {
            "session_id": conversation["id"],
            "run_id": run["id"],
            "answer": result.answer,
            "model_steps": result.model_steps,
            "tool_calls": result.tool_calls,
            "total_tokens": result.total_tokens,
            "trace": public_trace,
            "pending_proposals": pending_proposals,
            "pending_plans": pending_plans,
        }

    @app.get("/agent/sessions/{session_id}", response_model=AgentSessionRead)
    def get_agent_session(
        session_id: str,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        try:
            return agent_sessions.detail(user_id, session_id)
        except AgentSessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
