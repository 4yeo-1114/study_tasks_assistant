"""UPG-05 工作台浏览器验收运行器（Claude 独立复核用）。

用系统 Edge（channel=msedge，免下载 Chromium）+ 独立临时 SQLite 库 + 本地桩 LLM
启动真实 FastAPI 应用，在真实浏览器中执行 UPG-05 验收清单：

  S1 登录与工作台加载      S4 周计划待确认→确认→任务落库
  S2 任务新增/实际用时/完成 S5 Agent 会话切换与重载恢复
  S3 训练/体重与指标/画布   S6 跨账号 404 隔离
  S7 网络失败降级（503/500/502/延迟重复提交）
  S8 桌面 1440x900 与手机 390x844 截图与布局检查
  S9 Canvas 像素（空/单条/多条状态，CSS 与像素尺寸）

证据输出到 benchmarks/workbench_e2e_upg05/<UTC 时间戳>/，目录存在即拒绝覆盖。
桩模型行为：首步必须 tool_calls（agent loop 强制 tool_choice=required），
收到工具结果后返回最终回答；这证明控制流与业务约束，不代表在线模型质量。
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "study_task_assistant"
BENCH = ROOT / "benchmarks" / "workbench_e2e_upg05"

STUB_FINAL = "已收到你的消息（离线桩模型回答）。"
BASE_URL = ""  # 由 main() 在应用就绪后设置
USER_A = f"e2e_user_a_{datetime.now().strftime('%H%M%S')}"
USER_B = f"e2e_user_b_{datetime.now().strftime('%H%M%S')}"
PASSWORD = "e2e-pass-1234"


# ---------------------------------------------------------------- 桩 LLM

class StubHandler(BaseHTTPRequestHandler):
    server_version = "E2EStub/1.0"

    def log_message(self, *args):  # 静默访问日志
        pass

    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        messages = body.get("messages", [])
        self.server.requests.append(  # type: ignore[attr-defined]
            {"roles": [m.get("role") for m in messages], "model": body.get("model")}
        )
        if messages and messages[-1].get("role") == "tool":
            payload = {
                "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": STUB_FINAL}}],
                "model": "e2e-stub",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        else:
            payload = {
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [{"id": "call_e2e_list", "type": "function",
                                    "function": {"name": "list_tasks", "arguments": "{}"}}],
                }}],
                "model": "e2e-stub",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------- 被测应用

class AppUnderTest:
    def __init__(self, evidence: Path, stub_port: int):
        self.db_path = evidence / "e2e.sqlite3"
        url = f"sqlite+pysqlite:///{self.db_path.as_posix()}"
        sys.path.insert(0, str(APP_DIR))
        from storage.migration import upgrade_database
        upgrade_database(url)
        self.port = free_port()
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": url,
            "DEEPSEEK_API_KEY": "e2e-dummy-key",
            "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{stub_port}",
            "DEEPSEEK_MODEL": "e2e-stub-model",
            "STUDY_TASK_SECRET_KEY": "e2e-fixed-secret-key-0123456789abcdef0123456789abcdef",
            "AGENT_RAG_ENABLED": "0",
        })
        self.log = open(evidence / "app.log", "ab", buffering=0)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "info"],
            cwd=str(APP_DIR), env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        self._wait_ready()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _wait_ready(self) -> None:
        import urllib.request
        deadline = time.time() + 60
        last = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"应用进程提前退出（exit={self.proc.returncode}）")
            try:
                with urllib.request.urlopen(f"{self.base}/app/", timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception as exc:
                last = exc
            time.sleep(0.4)
        raise RuntimeError(f"应用未就绪: {last}")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


class Db:
    def __init__(self, path: Path):
        self.con = sqlite3.connect(str(path), timeout=10, check_same_thread=False)

    def one(self, sql: str, params=()):
        for _ in range(12):
            try:
                row = self.con.execute(sql, params).fetchone()
                return row[0] if row else None
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc):
                    raise
                time.sleep(0.3)
        raise RuntimeError("数据库持续锁定")

    def rows(self, sql: str, params=()):
        for _ in range(12):
            try:
                return self.con.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc):
                    raise
                time.sleep(0.3)
        raise RuntimeError("数据库持续锁定")


# ---------------------------------------------------------------- 页面辅助

class Recorder:
    def __init__(self, page):
        self.entries = []
        self.failed = []
        page.on("response", self._on)
        page.on("requestfailed", self._on_failed)

    def _on(self, response):
        try:
            path = urllib.parse.urlparse(response.url).path
        except Exception:
            return
        self.entries.append((response.request.method, path, response.status))

    def _on_failed(self, request):
        try:
            path = urllib.parse.urlparse(request.url).path
        except Exception:
            return
        self.failed.append((request.method, path, getattr(request, "failure", None)))

    def has(self, method: str, endswith: str, status: int) -> bool:
        return any(m == method and p.endswith(endswith) and s == status
                   for m, p, s in self.entries)

    def list(self, method: str, endswith: str):
        return [s for m, p, s in self.entries if m == method and p.endswith(endswith)]


def wait_until(fn, timeout=10.0, interval=0.15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            result = fn()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(interval)
    return last


def expect_text(page, selector, substr, timeout=8.0):
    def poll():
        text = (page.locator(selector).first.text_content() or "")
        return text if substr in text else None
    return wait_until(poll, timeout)


def nav(page, view: str):
    page.locator(f'[data-view="{view}"]').first.click()
    page.locator(f"#view-{view}").wait_for(state="visible", timeout=5000)


def create_and_login(page, username, password):
    page.goto(f"{BASE_URL}/app/")
    page.locator("#auth-switch").click()
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#confirm-password").fill(password)
    page.locator("#auth-submit").click()
    expect_text(page, "#auth-title", "登录工作台", 8)
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#auth-submit").click()
    page.locator("#application").wait_for(state="visible", timeout=10000)
    expect_text(page, "#metric-pending", "0", 10)


def login(page, username, password):
    page.goto(f"{BASE_URL}/app/")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#auth-submit").click()
    page.locator("#application").wait_for(state="visible", timeout=10000)


def screenshot(page, path: Path):
    page.screenshot(path=str(path), full_page=True)


def canvas_probe(page, canvas_id: str):
    return page.evaluate("""(id) => {
        const c = document.getElementById(id);
        const rect = c.getBoundingClientRect();
        const out = {cssW: Math.round(rect.width), cssH: Math.round(rect.height),
                     pixelW: c.width, pixelH: c.height, attrH: c.getAttribute('height'),
                     dpr: window.devicePixelRatio, nonTransparent: null, total: null};
        try {
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
            out.total = d.length / 4; out.nonTransparent = n;
        } catch (e) { out.error = String(e); }
        return out;
    }""", canvas_id)


# ---------------------------------------------------------------- 检查记账

CHECKS: list[dict] = []
CONSOLE_ERRORS: list[str] = []
PAGE_ERRORS: list[str] = []


def check(name: str, fn, finding: bool = False) -> bool:
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"异常 {type(exc).__name__}: {exc}"
    CHECKS.append({"name": name, "pass": bool(ok), "detail": str(detail), "finding": finding})
    return bool(ok)


def assert_true(name: str, condition, detail, finding: bool = False):
    return check(name, lambda: (bool(condition), detail), finding=finding)


# ---------------------------------------------------------------- 场景

def s1_login(page, recorder):
    check("S1 应用壳可见", lambda: (page.locator("#application").is_visible(), "登录后工作台显示"))
    check("S1 四项指标已加载", lambda: (expect_text(page, "#metric-volume", "—") is not None, "指标区已渲染"))
    check("S1 导航六个视图", lambda: (page.locator("#primary-nav .nav-item").count() == 6,
                                      f"导航项数={page.locator('#primary-nav .nav-item').count()}"))
    check("S1 今日日期标签", lambda: (bool((page.locator("#today-label").text_content() or "").strip()),
                                      f"today={page.locator('#today-label').text_content()}"))
    check("S1 GET /tasks 200", lambda: (recorder.has("GET", "/tasks", 200), "任务接口 200"))
    check("S1 GET /plans 200", lambda: (recorder.has("GET", "/plans", 200), "计划接口 200"))
    check("S1 GET /fitness/progress 200", lambda: (recorder.has("GET", "/fitness/progress", 200), "健身接口 200"))


def s2_task_lifecycle(page, recorder, db, username):
    nav(page, "tasks")
    page.locator("#task-title").fill("E2E 任务 A")
    page.locator("#task-type").select_option("learning")
    page.locator("#task-form button[type='submit']").click()
    check("S2 新任务出现在列表", lambda: (expect_text(page, "#task-list", "E2E 任务 A") is not None,
                                          "列表含新任务"))
    check("S2 POST /tasks 201", lambda: (recorder.has("POST", "/tasks", 201), "创建接口 201"))
    page.locator("#task-list [data-actual-minutes]").first.fill("45")
    page.locator("#task-list [data-complete-task]").first.click()
    check("S2 任务显示已完成与实际用时", lambda: (
        expect_text(page, "#task-list", "已完成") is not None
        and expect_text(page, "#task-list", "实际 45 分钟") is not None,
        "完成状态与实际用时渲染"), finding=True)
    check("S2 PATCH /tasks/{id} 200", lambda: (
        any(m == "PATCH" and p.startswith("/tasks/") and s == 200 for m, p, s in recorder.entries),
        "状态更新接口 200"))
    check("S2 进度 1/1 与完成率 100%", lambda: (
        expect_text(page, "#task-progress-label", "1/1 已完成") is not None,
        f"进度={page.locator('#task-progress-label').text_content()}"))
    nav(page, "overview")
    check("S2 总览待办 0、完成率 100%", lambda: (
        (page.locator("#metric-pending").text_content() or "") == "0"
        and "100%" in (page.locator("#metric-completion").text_content() or ""),
        f"pending={(page.locator('#metric-pending').text_content())}, "
        f"completion={page.locator('#metric-completion').text_content()}"))
    row = db.rows("SELECT status, actual_minutes FROM tasks WHERE title='E2E 任务 A'")
    check("S2 后端任务落库（含实际用时）", lambda: (
        row == [("completed", 45)],
        f"tasks 表实际值={row}（预期 completed+45；任务视图填写的实际分钟被总览隐藏副本覆盖则丢失）"),
        finding=True)


def s3_fitness_canvas(page, db):
    nav(page, "fitness")
    empty = canvas_probe(page, "exercise-chart")
    check("S3a 无记录：训练画布全透明", lambda: (
        (empty.get("nonTransparent") or 0) == 0,
        f"nonTransparent={empty.get('nonTransparent')}/{empty.get('total')} css={empty.get('cssW')}x{empty.get('cssH')} "
        f"pixel={empty.get('pixelW')}x{empty.get('pixelH')} attrH={empty.get('attrH')} dpr={empty.get('dpr')}"))
    check("S3a 无记录：空状态提示可见", lambda: (page.locator("#exercise-empty").is_visible(), "空状态显示"))

    page.locator("#exercise-name").fill("深蹲")
    page.locator("#exercise-weight").fill("60")
    page.locator("#exercise-reps").fill("5")
    page.locator("#workout-form button[type='submit']").click()
    expect_text(page, "#exercise-pr-list", "深蹲", 10)
    check("S3 训练后个人纪录更新", lambda: (
        expect_text(page, "#exercise-pr-list", "60 kg") is not None, "PR 深蹲 60 kg"))
    single = canvas_probe(page, "exercise-chart")
    check("S3a 单条记录：训练画布非空", lambda: (
        (single.get("nonTransparent") or 0) > 0,
        f"nonTransparent={single.get('nonTransparent')} css={single.get('cssW')}x{single.get('cssH')} "
        f"pixel={single.get('pixelW')}x{single.get('pixelH')} dpr={single.get('dpr')}"))

    page.locator("#exercise-name").fill("卧推")
    page.locator("#exercise-weight").fill("40")
    page.locator("#exercise-reps").fill("10")
    page.locator("#workout-form button[type='submit']").click()
    expect_text(page, "#exercise-pr-list", "卧推", 10)
    multi = canvas_probe(page, "exercise-chart")
    check("S3a 多条记录：训练画布非空", lambda: ((multi.get("nonTransparent") or 0) > 0,
                                                 f"nonTransparent={multi.get('nonTransparent')}"))
    nav(page, "overview")
    check("S3 累计训练量 700 kg", lambda: (
        expect_text(page, "#metric-volume", "700 kg") is not None,
        f"volume={page.locator('#metric-volume').text_content()}"))
    check("S3 动作纪录 60 kg（深蹲）", lambda: (
        (page.locator("#metric-pr").text_content() or "") == "60 kg"
        and (page.locator("#metric-pr-name").text_content() or "") == "深蹲",
        "最高重量为深蹲 60 kg"))

    nav(page, "fitness")
    page.locator("#weight-value").fill("70.5")
    page.locator("#weight-form button[type='submit']").click()
    expect_text(page, "#toast", "体重已保存", 10)
    nav(page, "overview")
    check("S3a 单条体重：趋势画布非空且空状态隐藏", lambda: (
        (canvas_probe(page, "overview-weight-chart").get("nonTransparent") or 0) > 0
        and not page.locator("#overview-weight-empty").is_visible(),
        "体重图已绘制"))

    nav(page, "fitness")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    page.locator("#weight-date").fill(next_week)
    page.locator("#weight-value").fill("71.5")
    page.locator("#weight-form button[type='submit']").click()
    expect_text(page, "#toast", "体重已保存", 10)
    nav(page, "overview")
    weight_multi = canvas_probe(page, "overview-weight-chart")
    check("S3a 两条体重：趋势画布非空", lambda: ((weight_multi.get("nonTransparent") or 0) > 0,
                                                 f"nonTransparent={weight_multi.get('nonTransparent')}"))

    progress = page.evaluate("""async () => {
        const token = localStorage.getItem('study_token');
        const r = await fetch('/fitness/progress', {headers: {Authorization: 'Bearer ' + token}});
        return await r.json();
    }""")
    check("S3 API 聚合正确", lambda: (
        progress.get("volume_by_exercise") == {"深蹲": 300.0, "卧推": 400.0}
        and progress.get("exercise_pr") == {"深蹲": 60.0, "卧推": 40.0}
        and 70.5 in [v for v in (progress.get("weekly_weight") or {}).values()],
        f"volume={progress.get('volume_by_exercise')} pr={progress.get('exercise_pr')} "
        f"weekly={progress.get('weekly_weight')}"))


def s4_plan_confirm(page, recorder, db, username):
    nav(page, "planning")
    page.locator("#learning-goal").fill("E2E 学习目标")
    page.locator("#training-days").fill("3")
    page.locator("#daily-minutes").fill("90")
    page.locator("#profile-form button[type='submit']").click()
    check("S4 档案保存后版本为 1", lambda: (
        expect_text(page, "#profile-revision", "档案版本 1") is not None,
        f"revision={page.locator('#profile-revision').text_content()}"))
    check("S4 PUT /profile 200", lambda: (recorder.has("PUT", "/profile", 200), "档案接口 200"))

    page.locator("[data-plan-title]").first.fill("E2E 计划学习任务")
    page.locator("[data-plan-minutes]").first.fill("45")
    page.locator("#plan-form button[type='submit']").click()
    check("S4 计划显示待确认", lambda: (
        expect_text(page, "#plan-list", "待确认") is not None,
        f"plan-list={page.locator('#plan-list').text_content()}"))
    check("S4 POST /plans/weekly 201", lambda: (recorder.has("POST", "/plans/weekly", 201), "提案接口 201"))
    plan_id = db.one("SELECT id FROM weekly_plans ORDER BY id DESC LIMIT 1")
    check("S4 后端计划为 pending", lambda: (
        db.one("SELECT status FROM weekly_plans WHERE id=?", (plan_id,)) == "pending",
        f"plan_id={plan_id}"))
    nav(page, "overview")
    check("S4 总览待确认计划 1", lambda: (
        (page.locator("#metric-plans").text_content() or "") == "1", "metric-plans=1"))

    nav(page, "planning")
    page.locator("#plan-list [data-confirm-plan]").first.click()
    check("S4 确认后计划状态变化", lambda: (
        expect_text(page, "#plan-list", "已确认") is not None,
        "计划行显示已确认"))
    check("S4 POST /plans/{id}/confirm 200", lambda: (
        recorder.has("POST", f"/plans/{plan_id}/confirm", 200), "确认接口 200"))
    check("S4 后端计划 confirmed", lambda: (
        db.one("SELECT status FROM weekly_plans WHERE id=?", (plan_id,)) == "confirmed", "DB confirmed"))
    nav(page, "tasks")
    check("S4 任务列表出现计划项", lambda: (
        expect_text(page, "#task-list", "E2E 计划学习任务") is not None, "任务列表含计划任务"))
    check("S4 计划任务落库", lambda: (
        db.one("SELECT COUNT(*) FROM tasks WHERE title='E2E 计划学习任务'") == 1, "tasks 表 1 行"))


def s5_session_restore(page, db, username):
    nav(page, "agent")
    page.locator("#chat-input").fill("帮我看看今天的任务")
    page.locator("#chat-form button[type='submit']").click()
    check("S5 对话出现用户与 Agent 消息", lambda: (
        expect_text(page, "#conversation", "帮我看看今天的任务") is not None
        and expect_text(page, "#conversation", "离线桩模型") is not None,
        "历史消息渲染"))
    session_id = page.evaluate("localStorage.getItem('study_session_id')")
    check("S5 会话 ID 已持久化", lambda: (bool(session_id), f"session_id={session_id}"))
    check("S5 后端两条消息一条运行", lambda: (
        db.one("SELECT COUNT(*) FROM agent_messages WHERE session_id=?", (session_id,)) == 2
        and db.one("SELECT COUNT(*) FROM agent_runs WHERE session_id=? AND status='succeeded'",
                   (session_id,)) == 1,
        "messages=2, runs=1"))
    # 清单第 5 项：重新载入页面后，当前会话历史必须恢复
    page.reload()
    page.locator("#application").wait_for(state="visible", timeout=10000)
    nav(page, "agent")
    check("S5 重载后历史消息恢复", lambda: (
        expect_text(page, "#conversation", "帮我看看今天的任务") is not None
        and expect_text(page, "#conversation", "离线桩模型") is not None,
        "重载后按 localStorage 会话恢复历史"))
    page.locator("#new-session").click()
    check("S5 新会话清空对话区", lambda: (
        expect_text(page, "#conversation", "当前会话还没有消息") is not None, "空会话提示"))
    return session_id


def s6_cross_account(browser, page_a, session_id, plan_id):
    context_b = browser.new_context(viewport={"width": 1440, "height": 900})
    page_b = context_b.new_page()
    create_and_login(page_b, USER_B, PASSWORD)
    nav(page_b, "planning")
    check("S6 B 账号计划列表为空", lambda: (
        expect_text(page_b, "#plan-list", "没有计划版本") is not None,
        f"plan-list={page_b.locator('#plan-list').text_content()}"))
    nav(page_b, "tasks")
    check("S6 B 账号任务列表为空", lambda: (
        expect_text(page_b, "#task-list", "当前筛选条件下没有任务") is not None, "无 A 的任务"))
    nav(page_b, "agent")
    check("S6 B 账号无会话消息", lambda: (
        expect_text(page_b, "#conversation", "当前会话还没有消息") is not None, "无 A 的会话"))
    statuses = page_b.evaluate("""async ([s, p]) => {
        const token = localStorage.getItem("study_token");
        const headers = {"Authorization": "Bearer " + token};
        const r1 = await fetch("/agent/sessions/" + s, {headers});
        const r2 = await fetch("/plans/" + p, {headers});
        return {session_status: r1.status, plan_status: r2.status};
    }""", [session_id, plan_id])
    check("S6 跨账号会话 404", lambda: (statuses["session_status"] == 404,
                                        f"status={statuses['session_status']}"))
    check("S6 跨账号计划 404", lambda: (statuses["plan_status"] == 404,
                                        f"status={statuses['plan_status']}"))
    context_b.close()


def s7_network(page, recorder, db, username, shots: Path):
    owner_id = db.one("SELECT id FROM users WHERE username=?", (username,))

    def msg_count():
        return db.one(
            "SELECT COUNT(*) FROM agent_messages m JOIN agent_sessions s ON m.session_id = s.id "
            "WHERE s.owner_id=?", (owner_id,))
    # 7a /fitness/progress 503
    nav(page, "tasks")
    check("S7a 前置：任务面板有内容", lambda: (expect_text(page, "#task-list", "E2E 任务 A") is not None, ""))
    nav(page, "planning")
    check("S7a 前置：计划面板有内容", lambda: (expect_text(page, "#plan-list", "已确认") is not None, ""))
    nav(page, "overview")

    def fail_fitness(route):
        route.fulfill(status=503, body='{"detail":"健身服务不可用（503）"}',
                      content_type="application/json")

    page.route("**/fitness/progress", fail_fitness)
    page.locator("#reload-all").click()
    check("S7a 健身 503：页面给出可读错误", lambda: (
        expect_text(page, "#toast", "健身服务不可用（503）") is not None,
        f"toast={page.locator('#toast').text_content()}"))
    nav(page, "tasks")
    check("S7a 健身 503：任务面板仍显示", lambda: (
        expect_text(page, "#task-list", "E2E 任务 A") is not None, "任务内容保留"))
    nav(page, "planning")
    check("S7a 健身 503：计划面板仍显示", lambda: (
        expect_text(page, "#plan-list", "已确认") is not None, "计划内容保留"))
    page.unroute("**/fitness/progress")
    # 恢复验证：解除拦截后新增训练并刷新，总量从 700 变为 850
    nav(page, "fitness")
    page.locator("#exercise-name").fill("硬拉")
    page.locator("#exercise-weight").fill("50")
    page.locator("#exercise-reps").fill("3")
    page.locator("#workout-form button[type='submit']").click()
    expect_text(page, "#toast", "训练记录已保存", 10)
    nav(page, "overview")
    check("S7a 解除后刷新恢复（700→850 kg）", lambda: (
        expect_text(page, "#metric-volume", "850 kg") is not None,
        f"volume={page.locator('#metric-volume').text_content()}"))

    # 7b /plans 首次 500、第二次 200：错误显示后，刷新（重新加载页面）恢复。
    # 恢复验证在全新页面上做（同一上下文共享登录态）：旧页面经过多轮路由注入后，
    # Playwright 网络事件派发会退化（请求/响应事件延迟累积），与应用无关。
    nav(page, "overview")
    calls = {"n": 0}

    def fail_plans_once(route):
        calls["n"] += 1
        route.fulfill(status=500, body='{"detail":"计划服务暂时不可用（500）"}',
                      content_type="application/json")

    page.route("**/plans", fail_plans_once)
    page.locator("#reload-all").click()
    check("S7b 计划 500：页面显示错误", lambda: (
        expect_text(page, "#toast", "计划服务暂时不可用（500）") is not None,
        f"toast={page.locator('#toast').text_content()}"))
    page.unroute("**/plans")

    page2 = page.context.new_page()
    recorder2 = Recorder(page2)
    page2.goto(f"{BASE_URL}/app/")
    page2.locator("#application").wait_for(state="visible", timeout=10000)
    check("S7b 刷新恢复：计划接口再次 200", lambda: (
        wait_until(lambda: recorder2.has("GET", "/plans", 200), 15) is not None,
        f"calls={calls} page2_plans={recorder2.list('GET', '/plans')}"))
    nav(page2, "planning")
    check("S7b 刷新恢复：计划数据重新加载", lambda: (
        expect_text(page2, "#plan-list", "已确认") is not None, "计划行恢复"))
    page2.close()

    # 7c /agent/chat 502 后重试
    nav(page, "agent")
    chat_calls = {"n": 0}

    def fail_chat_once(route):
        chat_calls["n"] += 1
        if chat_calls["n"] == 1:
            route.fulfill(status=502, body='{"detail":"网关错误（502）"}',
                          content_type="application/json")
        else:
            route.continue_()

    before_messages = msg_count()
    page.route("**/agent/chat", fail_chat_once)
    page.locator("#chat-input").fill("网络失败测试")
    page.locator("#chat-form button[type='submit']").click()
    check("S7c 聊天 502：可读错误显示", lambda: (
        expect_text(page, "#chat-status", "网关错误（502）") is not None,
        f"chat-status={page.locator('#chat-status').text_content()}"))
    check("S7c 聊天 502：输入内容保留", lambda: (
        page.locator("#chat-input").input_value() == "网络失败测试", "输入框未被清空"))
    page.locator("#chat-form button[type='submit']").click()
    check("S7c 重试成功：新消息可见", lambda: (
        expect_text(page, "#conversation", "网络失败测试") is not None
        and expect_text(page, "#conversation", "离线桩模型") is not None,
        "重试为真实新请求"))
    after_messages = msg_count()
    check("S7c 失败请求未产生业务写入", lambda: (
        after_messages == before_messages + 2,
        f"messages {before_messages} -> {after_messages}（预期 +2）"))
    page.unroute("**/agent/chat")

    # 7d 请求延迟期间重复提交：在全新页面上做（旧页面网络事件派发已退化，见 7b 注释）；
    # 页面内连发两次 submit，采样第二次提交时按钮状态。
    page3 = page.context.new_page()
    recorder3 = Recorder(page3)
    page3.goto(f"{BASE_URL}/app/")
    page3.locator("#application").wait_for(state="visible", timeout=10000)
    nav(page3, "agent")

    def slow_chat(route):
        time.sleep(2.0)
        route.continue_()

    before2 = msg_count()
    posts_before = len(recorder3.list("POST", "/agent/chat"))
    page3.route("**/agent/chat", slow_chat)
    page3.locator("#chat-input").fill("重复提交测试")
    page3.evaluate("""() => {
        window.__e2e_btn_states = [];
        const form = document.getElementById('chat-form');
        const btn = form.querySelector('button[type=submit]');
        form.addEventListener('submit', () => window.__e2e_btn_states.push(btn.disabled));
    }""")
    page3.evaluate(
        "() => { const f = document.getElementById('chat-form'); f.requestSubmit(); f.requestSubmit(); }")

    # 等待两次提交对应的 POST 响应都落地（每次业务 run 完成、消息落库后才返回响应）。
    # 注意：Playwright 同步 API 的路由 handler 以 greenlet 运行、期间事件循环挂起，
    # 必须用 page.wait_for_timeout 泵动事件循环，纯 Python 轮询会让排队请求饿死。
    # 若按钮禁用已修复，只有一次 POST，超时后读取计数，检查仍按 +2 判定。
    deadline = time.time() + 20
    while time.time() < deadline:
        if len(recorder3.list("POST", "/agent/chat")) - posts_before >= 2:
            break
        page3.wait_for_timeout(300)
    time.sleep(1.0)
    after2 = msg_count()
    states = page3.evaluate("window.__e2e_btn_states")
    # 修复后：第二次 requestSubmit 被禁用按钮阻止，不产生第二次 submit 事件；
    # 未修复：两次事件都发生且按钮始终未禁用。
    second_submit_blocked = bool(states) and (len(states) == 1 or bool(states[1]))
    check("S7d 请求期间提交按钮禁用", lambda: (
        second_submit_blocked,
        f"提交事件采样={states}（第二次提交应被禁用按钮阻止，或发生时按钮已禁用）"), finding=True)
    check("S7d 恢复后只发生一次业务写入", lambda: (
        after2 == before2 + 2,
        f"messages {before2} -> {after2}（预期 +2，实际 +{after2 - before2}）"), finding=True)
    page3.unroute("**/agent/chat")
    page3.close()


def s8_layout(browser, shots: Path):
    # 桌面截图
    context_d = browser.new_context(viewport={"width": 1440, "height": 900})
    page_d = context_d.new_page()
    page_d.goto(f"{BASE_URL}/app/")
    page_d.locator("#auth-screen").wait_for(state="visible", timeout=8000)
    screenshot(page_d, shots / "desktop-1440x900-auth.png")
    login(page_d, USER_A, PASSWORD)
    for view, label in [("overview", "总览"), ("tasks", "任务"), ("fitness", "训练"), ("planning", "计划")]:
        nav(page_d, view)
        time.sleep(0.4)
        screenshot(page_d, shots / f"desktop-1440x900-{view}.png")
    context_d.close()

    # 手机视口
    context_m = browser.new_context(viewport={"width": 390, "height": 844})
    page_m = context_m.new_page()
    page_m.goto(f"{BASE_URL}/app/")
    page_m.locator("#auth-screen").wait_for(state="visible", timeout=8000)
    screenshot(page_m, shots / "mobile-390x844-auth.png")
    login(page_m, USER_A, PASSWORD)
    for view in ["overview", "tasks", "fitness", "planning"]:
        nav(page_m, view)
        time.sleep(0.4)
        screenshot(page_m, shots / f"mobile-390x844-{view}.png")
        overflow = page_m.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})")
        nav_metrics = page_m.evaluate(
            "() => {const n = document.getElementById('primary-nav');"
            " return {scroll: n.scrollWidth, client: n.clientWidth};}")
        overlaps = page_m.evaluate("""() => {
            const view = document.querySelector('.view.active');
            const panels = [...view.querySelectorAll('.panel')].filter(
                p => getComputedStyle(p).display !== 'none');
            const rects = panels.map(p => {const r = p.getBoundingClientRect();
                return {name: (p.querySelector('h2')?.textContent || '').trim(),
                        l: r.left, t: r.top, r: r.right, b: r.bottom};});
            const hits = [];
            for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
                const a = rects[i], b = rects[j];
                const w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
                const h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
                if (w > 2 && h > 2) hits.push([a.name, b.name]);
            }
            return hits;
        }""")
        form_issues = page_m.evaluate("""() => {
            const view = document.querySelector('.view.active');
            const issues = [];
            for (const p of view.querySelectorAll('.panel')) {
                const pr = p.getBoundingClientRect();
                for (const el of p.querySelectorAll('input, textarea, select')) {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0) continue;
                    if (r.right > pr.right + 2)
                        issues.push((p.querySelector('h2')?.textContent || '').trim()
                                    + ':' + (el.id || el.tagName) + '+'
                                    + Math.round(r.right - pr.right) + 'px');
                }
            }
            return issues;
        }""")
        check(f"S8 手机 {view}：页面无横向溢出", lambda: (
            overflow["sw"] <= overflow["iw"] + 1,
            f"scrollWidth={overflow['sw']} innerWidth={overflow['iw']}"))
        check(f"S8 手机 {view}：导航可横向滚动", lambda: (
            nav_metrics["scroll"] > nav_metrics["client"],
            f"scroll={nav_metrics['scroll']} client={nav_metrics['client']}"))
        check(f"S8 手机 {view}：卡片无重叠", lambda: (len(overlaps) == 0,
                                                       f"overlaps={overlaps}"))
        check(f"S8 手机 {view}：表单控件未溢出", lambda: (len(form_issues) == 0,
                                                           f"issues={form_issues}"))
    context_m.close()


# ---------------------------------------------------------------- 主流程

def main() -> int:
    evidence = BENCH / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z")
    evidence.mkdir(parents=True, exist_ok=False)
    shots = evidence / "screenshots"
    shots.mkdir()

    from playwright.sync_api import sync_playwright

    global BASE_URL
    stub = start_stub()
    app = AppUnderTest(evidence, stub.server_address[1])
    BASE_URL = app.base
    db = Db(app.db_path)
    p = sync_playwright().start()
    browser = None
    try:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda msg: CONSOLE_ERRORS.append(msg.text)
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: PAGE_ERRORS.append(str(exc)))
        recorder = Recorder(page)

        scenario_runs = []

        def run_scenario(sid, fn):
            start = time.time()
            try:
                fn()
                status = "ok"
            except Exception as exc:  # noqa: BLE001
                CHECKS.append({"name": f"{sid} 场景异常", "pass": False,
                               "detail": f"{type(exc).__name__}: {exc}", "finding": False})
                status = "error"
            scenario_runs.append({"id": sid, "status": status,
                                  "seconds": round(time.time() - start, 2)})

        screenshot(page, shots / "desktop-1440x900-auth.png")
        run_scenario("S1", lambda: (create_and_login(page, USER_A, PASSWORD), s1_login(page, recorder)))
        run_scenario("S2", lambda: s2_task_lifecycle(page, recorder, db, USER_A))
        run_scenario("S3", lambda: s3_fitness_canvas(page, db))
        plan_id = db.one("SELECT id FROM weekly_plans ORDER BY id DESC LIMIT 1")
        run_scenario("S4", lambda: s4_plan_confirm(page, recorder, db, USER_A))
        plan_id = db.one("SELECT id FROM weekly_plans ORDER BY id DESC LIMIT 1")
        session_id = None
        def run_s5():
            nonlocal session_id
            session_id = s5_session_restore(page, db, USER_A)
        run_scenario("S5", run_s5)
        run_scenario("S6", lambda: s6_cross_account(browser, page, session_id, plan_id))
        run_scenario("S7", lambda: s7_network(page, recorder, db, USER_A, shots))
        run_scenario("S8", lambda: s8_layout(browser, shots))

        # 证据
        git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                  capture_output=True, text=True).stdout.strip()
        git_dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                                   capture_output=True, text=True).stdout.count("\n")
        (evidence / "browser_version.txt").write_text(
            f"channel=msedge\nversion={browser.version}\n", encoding="utf-8")
        (evidence / "git.txt").write_text(
            f"head={git_head}\ndirty_files={git_dirty}\n", encoding="utf-8")
        with open(evidence / "stub_requests.jsonl", "w", encoding="utf-8") as fh:
            for item in stub.requests:  # type: ignore[attr-defined]
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

        checks_total = len(CHECKS)
        checks_pass = sum(1 for c in CHECKS if c["pass"])
        findings = [c for c in CHECKS if c.get("finding") and not c["pass"]]
        report = {
            "runner": "scripts/run_workbench_e2e.py",
            "runner_sha256": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "started_at": evidence.name,
            "app": {"database": "独立临时 SQLite", "llm": "本地桩模型（离线）",
                    "rag": "disabled", "browser": f"msedge {browser.version}"},
            "accounts": [USER_A, USER_B],
            "git": {"head": git_head, "dirty_files": git_dirty},
            "scenarios": scenario_runs,
            "checks_total": checks_total,
            "checks_pass": checks_pass,
            "checks_fail": checks_total - checks_pass,
            "checks": CHECKS,
            "findings": findings,
            "console_errors": CONSOLE_ERRORS,
            "page_errors": PAGE_ERRORS,
            "stub_llm_requests": len(stub.requests),  # type: ignore[attr-defined]
        }
        (evidence / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n===== UPG-05 工作台浏览器验收 =====\n证据目录: {evidence}")
        for run in scenario_runs:
            print(f"  {run['id']}: {run['status']} ({run['seconds']}s)")
        print(f"\n检查: {checks_pass}/{checks_total} 通过")
        for c in CHECKS:
            if not c["pass"]:
                print(f"  FAIL [{c['name']}] {c['detail']}"
                      + ("  <== 待修复发现" if c.get("finding") else ""))
        if findings:
            print(f"\n发现 {len(findings)} 项与验收清单不符，需反馈构建方修复。")
        print(f"桩模型请求数: {len(stub.requests)}  页面 console error: {len(CONSOLE_ERRORS)}  "
              f"pageerror: {len(PAGE_ERRORS)}")
        return 0 if checks_pass == checks_total else 1
    finally:
        if browser is not None:
            browser.close()
        p.stop()
        app.stop()
        stub.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
