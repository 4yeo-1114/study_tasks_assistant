const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("study_token"), authMode: "login", tasks: [], taskProgress: null, fitness: null, documents: [], documentError: null, plans: [], profile: null, sessionId: localStorage.getItem("study_session_id"), csvReady: false };
let toastTimer;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char]));
}
function todayIso() { return new Date().toISOString().slice(0, 10); }
function mondayIso() { const day = new Date(); const offset = (day.getDay() + 6) % 7; day.setDate(day.getDate() - offset); return day.toISOString().slice(0, 10); }
function dateLabel(value) { return value ? new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", weekday: "short" }).format(new Date(`${value}T00:00:00`)) : "未设置"; }
function minutesLabel(value) { return value === null || value === undefined ? "—" : `${value} 分钟`; }
function safeId() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function showToast(text, type = "success") { const node = $("toast"); node.textContent = text; node.className = `toast show ${type}`; clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.className = "toast"; }, 3800); }
function apiError(data, fallback) { if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg || String(item)).join("；"); return data?.detail || fallback; }
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let data = null;
  try { data = response.status === 204 ? null : await response.json(); } catch (_) { /* Response was not JSON. */ }
  if (!response.ok) throw new Error(apiError(data, `请求失败（${response.status}）`));
  return data;
}

function setAuthMode(mode) {
  state.authMode = mode;
  const register = mode === "register";
  $("auth-title").textContent = register ? "注册工作台" : "登录工作台";
  $("auth-submit").textContent = register ? "创建账号" : "登录";
  $("auth-switch").textContent = register ? "返回登录" : "注册账号";
  $("confirm-label").classList.toggle("hidden", !register);
  $("confirm-password").classList.toggle("hidden", !register);
  $("auth-error").textContent = "";
}
function enterWorkspace() {
  $("auth-screen").classList.add("hidden");
  $("application").classList.remove("hidden");
  $("today-label").textContent = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "short" }).format(new Date());
  $("workout-date").value = todayIso(); $("weight-date").value = todayIso(); $("plan-week").value = mondayIso();
  if (!$("plan-task-editor").children.length) addPlanTask();
  refreshWorkspace();
}
function leaveWorkspace() { state.token = null; state.sessionId = null; localStorage.removeItem("study_token"); localStorage.removeItem("study_session_id"); location.reload(); }

function badge(text, kind = "") { return `<span class="badge ${escapeHtml(kind)}">${escapeHtml(text)}</span>`; }
function renderTasks() {
  const filter = $("task-filter").value;
  const items = state.tasks.filter((task) => filter === "all" || task.status === filter);
  $("task-list").innerHTML = items.length ? items.map(taskRow).join("") : `<div class="empty-state">当前筛选条件下没有任务</div>`;
  const progress = state.taskProgress || { total: 0, completed: 0, completion_rate: 0 };
  $("task-progress-label").textContent = progress.total ? `${progress.completed}/${progress.total} 已完成 · 预计 ${minutesLabel(progress.estimated_minutes)} · 实际 ${minutesLabel(progress.actual_minutes)}` : "暂无任务";
  $("task-progress-bar").style.width = `${Math.round((progress.completion_rate || 0) * 100)}%`;
  $("overview-tasks").innerHTML = state.tasks.filter((task) => task.status === "pending").slice(0, 4).map(taskRow).join("") || `<div class="empty-state">没有待办任务</div>`;
}
function taskRow(task) {
  const completed = task.status === "completed";
  return `<div class="list-row"><div class="list-row-main"><strong>${escapeHtml(task.title)}</strong><div class="row-meta">${badge(completed ? "已完成" : "待办", task.status)}${task.task_type ? badge(task.task_type === "fitness" ? "健身" : "学习") : ""}<span>${dateLabel(task.due_date)}</span><span>${minutesLabel(task.estimated_minutes)}</span>${completed && task.actual_minutes ? `<span>实际 ${minutesLabel(task.actual_minutes)}</span>` : ""}</div></div><div class="row-actions">${completed ? "" : `<input type="number" min="1" max="1440" data-actual-minutes="${task.id}" aria-label="${escapeHtml(task.title)} 实际用时分钟" placeholder="实际分钟"><button class="button-quiet" type="button" data-complete-task="${task.id}">完成</button>`}<button class="button-danger" type="button" data-delete-task="${task.id}">删除</button></div></div>`;
}
function drawChart(canvasId, data, color, suffix = "", kind = "line") {
  const canvas = $(canvasId); const ctx = canvas.getContext("2d"); const points = Object.entries(data || {});
  const width = Math.max(280, canvas.clientWidth || 500); const height = Number(canvas.getAttribute("height")) || 180; const scale = window.devicePixelRatio || 1;
  canvas.width = width * scale; canvas.height = height * scale; ctx.scale(scale, scale); ctx.clearRect(0, 0, width, height);
  if (!points.length) return false;
  const values = points.map(([, value]) => Number(value)); const max = Math.max(...values, 1); const left = 34; const bottom = height - 28; const usableW = width - left - 12; const usableH = bottom - 18;
  ctx.strokeStyle = "#e1e8e6"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(left, 18); ctx.lineTo(left, bottom); ctx.lineTo(width - 12, bottom); ctx.stroke();
  if (kind === "bar") {
    const slot = usableW / points.length; const barWidth = Math.min(36, slot * .52);
    points.forEach(([label, value], index) => { const x = left + slot * index + (slot - barWidth) / 2; const barHeight = (Number(value) / max) * usableH; ctx.fillStyle = color; ctx.fillRect(x, bottom - barHeight, barWidth, barHeight); ctx.fillStyle = "#52616c"; ctx.font = "10px sans-serif"; ctx.textAlign = "center"; ctx.fillText(label.length > 8 ? `${label.slice(0, 7)}…` : label, x + barWidth / 2, height - 7); }); ctx.textAlign = "start"; return true;
  }
  if (points.length === 1) {
    ctx.fillStyle = color; ctx.fillRect(left + usableW * .38, bottom - (values[0] / max) * usableH, usableW * .24, (values[0] / max) * usableH); ctx.fillStyle = "#52616c"; ctx.font = "11px sans-serif"; ctx.fillText(`${values[0].toFixed(1)}${suffix}`, left + usableW * .38, 14); ctx.fillText(points[0][0], left, height - 7); return true;
  }
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach(([label, value], index) => { const x = left + usableW * index / (points.length - 1); const y = bottom - (Number(value) / max) * usableH; index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  ctx.fillStyle = color; points.forEach(([, value], index) => { const x = left + usableW * index / (points.length - 1); const y = bottom - (Number(value) / max) * usableH; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = "#52616c"; ctx.font = "11px sans-serif"; points.forEach(([label, value], index) => { const x = left + usableW * index / (points.length - 1); ctx.fillText(`${Number(value).toFixed(1)}${suffix}`, x - 13, bottom - (Number(value) / max) * usableH - 8); ctx.fillText(label.slice(5), x - 16, height - 7); }); return true;
}
function renderFitness() {
  const data = state.fitness || { volume_by_exercise: {}, exercise_pr: {}, weekly_weight: {} }; const volume = data.volume_by_exercise || {}; const prs = data.exercise_pr || {}; const weights = data.weekly_weight || {};
  const totalVolume = Object.values(volume).reduce((sum, value) => sum + Number(value), 0); const prEntries = Object.entries(prs); const best = prEntries.sort((a, b) => Number(b[1]) - Number(a[1]))[0];
  $("metric-volume").textContent = totalVolume ? `${Math.round(totalVolume).toLocaleString()} kg` : "—";
  $("metric-pr").textContent = best ? `${best[1]} kg` : "—"; $("metric-pr-name").textContent = best ? best[0] : "最高重量";
  $("exercise-empty").classList.toggle("hidden", drawChart("exercise-chart", volume, "#c5664f", "kg", "bar") || Object.keys(volume).length > 0);
  $("overview-weight-empty").classList.toggle("hidden", drawChart("overview-weight-chart", weights, "#176b59", "kg") || Object.keys(weights).length > 0);
  $("exercise-pr-list").innerHTML = prEntries.length ? prEntries.map(([name, value]) => `<div class="data-row"><span>${escapeHtml(name)}</span><strong>${escapeHtml(value)} kg</strong></div>`).join("") : `<div class="empty-state">暂无个人纪录</div>`;
}
function renderDocuments() {
  const list = state.documents;
  const empty = state.documentError ? `资料服务不可用：${escapeHtml(state.documentError)}` : "还没有资料。导入文本后，Agent 可以返回来源引用。";
  const html = list.length ? list.map((document) => `<div class="list-row"><div class="list-row-main"><strong>${escapeHtml(document.source)}</strong><div class="row-meta">${badge(document.state, document.state)}<span>${escapeHtml(document.document_version)}</span><span>${new Date(document.updated_at).toLocaleDateString("zh-CN")}</span></div></div><div class="row-actions"><button class="button-danger" type="button" data-delete-document="${escapeHtml(document.id)}">删除</button></div></div>`).join("") : `<div class="empty-state">${empty}</div>`;
  $("document-list").innerHTML = html; $("overview-documents").innerHTML = state.documentError ? `<div class="empty-state">资料服务不可用</div>` : list.slice(0, 4).map((document) => `<div class="list-row"><div class="list-row-main"><strong>${escapeHtml(document.source)}</strong><div class="row-meta">${badge(document.state, document.state)}<span>${escapeHtml(document.document_version)}</span></div></div></div>`).join("") || `<div class="empty-state">还没有资料</div>`;
}
function planRow(plan) {
  const isPending = plan.status === "pending"; const taskCount = plan.tasks?.length || 0; const detail = plan.adjustment_summary || `${taskCount} 个计划项 · 第 ${plan.plan_version ?? "待确认"} 版`;
  return `<div class="list-row"><div class="list-row-main"><strong>${plan.plan_kind === "adjustment" ? "调整提案" : "周计划"} · ${dateLabel(plan.week_start)}</strong><div class="row-meta">${badge(plan.status === "pending" ? "待确认" : plan.status === "confirmed" ? "已确认" : "已拒绝", plan.status)}${badge(plan.plan_kind === "adjustment" ? "调整" : "初始计划")}<span>${escapeHtml(detail)}</span></div></div><div class="row-actions">${isPending ? `<button type="button" data-confirm-plan="${plan.id}">确认</button><button class="button-danger" type="button" data-reject-plan="${plan.id}">拒绝</button>` : plan.status === "confirmed" ? `<button class="button-quiet" type="button" data-adjust-plan="${plan.id}">生成调整</button>` : ""}</div></div>`;
}
function renderPlans() {
  const filter = $("plan-filter").value; const plans = state.plans.filter((plan) => filter === "all" || plan.status === filter); const pending = state.plans.filter((plan) => plan.status === "pending");
  $("metric-plans").textContent = pending.length; $("plan-list").innerHTML = plans.length ? plans.map(planRow).join("") : `<div class="empty-state">没有计划版本</div>`; $("overview-plans").innerHTML = pending.length ? pending.slice(0, 3).map(planRow).join("") : `<div class="empty-state">没有待确认计划</div>`;
}
function renderProfile() {
  const profile = state.profile;
  ["learning-goal", "training-days", "daily-minutes", "preferences", "limitations"].forEach((id) => { $(id).value = ""; });
  if (!profile) { $("profile-revision").textContent = "尚未创建档案。保存后才可以生成需预算与频次约束的计划。"; return; }
  $("learning-goal").value = profile.learning_goal || ""; $("training-days").value = profile.training_days_per_week ?? ""; $("daily-minutes").value = profile.daily_minutes ?? ""; $("preferences").value = profile.preferences || ""; $("limitations").value = profile.limitations || "";
  $("profile-revision").textContent = `档案版本 ${profile.revision} · 已确认计划版本 ${profile.plan_version}`;
}
function renderOverview() {
  const progress = state.taskProgress || { pending: 0, completion_rate: 0 }; $("metric-pending").textContent = progress.pending ?? 0; $("metric-completion").textContent = `完成率 ${Math.round((progress.completion_rate || 0) * 100)}%`;
}
async function loadProfile() { try { state.profile = await api("/profile"); } catch (error) { if (!String(error.message).includes("尚未创建") && !String(error.message).includes("找不到")) throw error; state.profile = null; } renderProfile(); }
async function refreshWorkspace() {
  try {
    const [tasks, progress, fitness, documents, plans] = await Promise.allSettled([api("/tasks"), api("/tasks/progress"), api("/fitness/progress"), api("/documents"), api("/plans")]);
    for (const [result, key] of [[tasks, "tasks"], [progress, "taskProgress"], [fitness, "fitness"], [plans, "plans"]]) {
      if (result.status === "rejected") throw result.reason;
      state[key] = result.value;
    }
    state.documentError = documents.status === "rejected" ? documents.reason.message : null;
    if (documents.status === "fulfilled") state.documents = documents.value;
    await loadProfile(); renderTasks(); renderFitness(); renderDocuments(); renderPlans(); renderOverview();
  } catch (error) { showToast(error.message, "error"); }
}
async function setTaskStatus(id, taskStatus) {
  // The overview and task views both render pending tasks. Scope the input to
  // the task view so a hidden duplicate cannot overwrite the user's value.
  const input = $("task-list").querySelector(`[data-actual-minutes="${CSS.escape(String(id))}"]`);
  const actual = input?.value ? Number(input.value) : null;
  await api(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status: taskStatus, actual_minutes: actual }) });
  await refreshWorkspace(); showToast("任务状态已更新");
}
async function deleteTask(id) { await api(`/tasks/${id}`, { method: "DELETE" }); await refreshWorkspace(); showToast("任务已删除"); }
async function decidePlan(id, decision) { await api(`/plans/${id}/${decision}`, { method: "POST" }); await refreshWorkspace(); showToast(decision === "confirm" ? "计划已确认，任务已写入" : "计划已拒绝"); }
async function adjustPlan(id) { const result = await api(`/plans/${id}/adjust`, { method: "POST", body: JSON.stringify({ idempotency_key: `workbench-adjust:${id}:${safeId()}` }) }); await refreshWorkspace(); showToast(`已生成待确认调整提案（${result.tasks.length} 项）`); }
function addPlanTask() {
  const node = document.createElement("div"); node.className = "plan-task"; node.innerHTML = `<div class="plan-task-title"><span>计划项</span><button class="button-danger" type="button" data-remove-plan-task>移除</button></div><label>名称</label><input data-plan-title maxlength="200" required><div class="field-pair"><div><label>类型</label><select data-plan-type><option value="learning">学习</option><option value="fitness">健身</option></select></div><div><label>预计分钟</label><input data-plan-minutes type="number" min="1" max="1440" required></div></div><label>日期</label><input data-plan-date type="date" required>`; node.querySelector("[data-plan-date]").value = $("plan-week").value || mondayIso(); $("plan-task-editor").append(node);
}
function renderMessages(messages) {
  $("conversation").innerHTML = messages.length ? messages.map((message) => `<div class="message ${message.role}"><span class="message-label">${message.role === "user" ? "你" : "Agent"}</span>${escapeHtml(message.content)}</div>`).join("") : `<div class="empty-state">当前会话还没有消息。</div>`; $("conversation").scrollTop = $("conversation").scrollHeight;
}
async function loadSession() { if (!state.sessionId) { renderMessages([]); return; } try { const session = await api(`/agent/sessions/${state.sessionId}`); renderMessages(session.messages); } catch (_) { state.sessionId = null; localStorage.removeItem("study_session_id"); renderMessages([]); } }
function renderAgentProposals(data) {
  const taskProposals = (data.pending_proposals || []).map((item) => `<div class="list-row"><div class="list-row-main"><strong>${escapeHtml(item.title)}</strong><div class="row-meta">${badge("待确认", "pending")}${badge(item.priority)}</div></div><div class="row-actions"><button type="button" data-confirm-task-proposal="${item.id}">确认</button><button class="button-danger" type="button" data-reject-task-proposal="${item.id}">拒绝</button></div></div>`);
  const plans = (data.pending_plans || []).map(planRow); $("agent-proposals").innerHTML = [...taskProposals, ...plans].join("");
}
let chatInFlight = false;
async function sendChat() {
  const input = $("chat-input"); const submit = $("chat-form").querySelector("button[type=submit]");
  const message = input.value.trim();
  if (!message || chatInFlight) return;
  chatInFlight = true; submit.disabled = true; $("chat-status").textContent = "Agent 正在处理…";
  try { const data = await api("/agent/chat", { method: "POST", body: JSON.stringify({ message, session_id: state.sessionId, idempotency_key: `workbench-chat:${safeId()}` }) }); state.sessionId = data.session_id; localStorage.setItem("study_session_id", state.sessionId); input.value = ""; await loadSession(); renderAgentProposals(data); $("trace-output").textContent = JSON.stringify(data.trace, null, 2); $("run-summary").textContent = `运行 ${data.run_id.slice(0, 8)} · ${data.model_steps} 模型步骤 · ${data.tool_calls} 工具调用 · ${data.total_tokens} tokens`; $("chat-status").textContent = ""; showToast("Agent 已完成本次运行"); await refreshWorkspace(); } catch (error) { $("chat-status").textContent = error.message; showToast(error.message, "error"); }
  finally { chatInFlight = false; submit.disabled = false; }
}
async function submitProfile(event) { event.preventDefault(); const value = (id) => $(id).value.trim() || null; const number = (id) => $(id).value === "" ? null : Number($(id).value); await api("/profile", { method: "PUT", body: JSON.stringify({ learning_goal: value("learning-goal"), training_days_per_week: number("training-days"), daily_minutes: number("daily-minutes"), preferences: value("preferences"), limitations: value("limitations") }) }); await refreshWorkspace(); showToast("档案已保存；新的计划会使用当前版本"); }
async function submitPlan(event) { event.preventDefault(); $("plan-form-error").textContent = ""; if (!state.profile) { $("plan-form-error").textContent = "请先保存档案，再生成带预算和训练频次约束的计划。"; return; } const weekStart = $("plan-week").value; const tasks = [...document.querySelectorAll(".plan-task")].map((node) => ({ title: node.querySelector("[data-plan-title]").value.trim(), task_type: node.querySelector("[data-plan-type]").value, estimated_minutes: Number(node.querySelector("[data-plan-minutes]").value), due_date: node.querySelector("[data-plan-date]").value }));
  if (tasks.some((task) => !task.title || !task.due_date || !task.estimated_minutes)) { $("plan-form-error").textContent = "请完成每个计划项。"; return; }
  try { await api("/plans/weekly", { method: "POST", body: JSON.stringify({ week_start: weekStart, expected_profile_revision: state.profile.revision, base_plan_version: state.profile.plan_version, idempotency_key: `workbench-plan:${safeId()}`, tasks }) }); await refreshWorkspace(); showToast("待确认计划已生成"); } catch (error) { $("plan-form-error").textContent = error.message; }
}
function bindEvents() {
  $("auth-form").addEventListener("submit", async (event) => { event.preventDefault(); const username = $("username").value.trim(); const password = $("password").value; try { if (state.authMode === "register") { if (password !== $("confirm-password").value) throw new Error("两次输入的密码不一致"); await api("/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }); setAuthMode("login"); showToast("注册成功，请登录", "info"); return; } const response = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ username, password }) }); const data = await response.json(); if (!response.ok) throw new Error(apiError(data, "登录失败")); state.token = data.access_token; localStorage.setItem("study_token", state.token); enterWorkspace(); } catch (error) { $("auth-error").textContent = error.message; } });
  $("auth-switch").addEventListener("click", () => setAuthMode(state.authMode === "login" ? "register" : "login")); $("logout").addEventListener("click", leaveWorkspace); $("reload-all").addEventListener("click", refreshWorkspace);
  $("primary-nav").addEventListener("click", (event) => { const button = event.target.closest("[data-view]"); if (!button) return; document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node === button)); document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${button.dataset.view}`)); const names = { overview: ["YOUR WEEK", "总览"], tasks: ["TASK TRACKER", "任务"], fitness: ["TRAINING LOG", "训练"], knowledge: ["KNOWLEDGE BASE", "资料库"], agent: ["PERSISTENT SESSION", "Agent"], planning: ["PROFILE & PLANS", "档案与计划"] }; $("section-kicker").textContent = names[button.dataset.view][0]; $("page-title").textContent = names[button.dataset.view][1]; if (button.dataset.view === "agent") loadSession(); });
  document.addEventListener("click", async (event) => { const go = event.target.closest("[data-go]"); if (go) document.querySelector(`[data-view="${go.dataset.go}"]`).click(); const complete = event.target.closest("[data-complete-task]"); if (complete) await setTaskStatus(complete.dataset.completeTask, "completed"); const removeTask = event.target.closest("[data-delete-task]"); if (removeTask) await deleteTask(removeTask.dataset.deleteTask); const confirmPlan = event.target.closest("[data-confirm-plan]"); if (confirmPlan) await decidePlan(confirmPlan.dataset.confirmPlan, "confirm"); const rejectPlan = event.target.closest("[data-reject-plan]"); if (rejectPlan) await decidePlan(rejectPlan.dataset.rejectPlan, "reject"); const adjustment = event.target.closest("[data-adjust-plan]"); if (adjustment) await adjustPlan(adjustment.dataset.adjustPlan); const removePlanTask = event.target.closest("[data-remove-plan-task]"); if (removePlanTask) removePlanTask.closest(".plan-task").remove(); const confirmTask = event.target.closest("[data-confirm-task-proposal]"); if (confirmTask) { await api(`/agent/task-proposals/${confirmTask.dataset.confirmTaskProposal}/confirm`, { method: "POST" }); $("agent-proposals").innerHTML = ""; await refreshWorkspace(); showToast("任务提案已确认"); } const rejectTask = event.target.closest("[data-reject-task-proposal]"); if (rejectTask) { await api(`/agent/task-proposals/${rejectTask.dataset.rejectTaskProposal}/reject`, { method: "POST" }); $("agent-proposals").innerHTML = ""; showToast("任务提案已拒绝"); } });
  $("task-filter").addEventListener("change", renderTasks); $("plan-filter").addEventListener("change", renderPlans); $("task-form").addEventListener("submit", async (event) => { event.preventDefault(); const body = { title: $("task-title").value.trim(), task_type: $("task-type").value, priority: $("task-priority").value, due_date: $("task-due").value || null, estimated_minutes: $("task-minutes").value ? Number($("task-minutes").value) : null }; await api("/tasks", { method: "POST", body: JSON.stringify(body) }); event.target.reset(); await refreshWorkspace(); showToast("任务已添加"); });
  $("workout-form").addEventListener("submit", async (event) => { event.preventDefault(); await api("/fitness/workouts", { method: "POST", body: JSON.stringify({ workout_date: $("workout-date").value, sets: [{ exercise_name: $("exercise-name").value.trim(), weight_kg: Number($("exercise-weight").value), reps: Number($("exercise-reps").value) }] }) }); event.target.reset(); $("workout-date").value = todayIso(); await refreshWorkspace(); showToast("训练记录已保存"); });
  $("weight-form").addEventListener("submit", async (event) => { event.preventDefault(); await api("/fitness/weight", { method: "POST", body: JSON.stringify({ recorded_on: $("weight-date").value, weight_kg: Number($("weight-value").value) }) }); event.target.reset(); $("weight-date").value = todayIso(); await refreshWorkspace(); showToast("体重已保存"); });
  $("preview-fitness").addEventListener("click", async () => { try { const result = await api("/fitness/import/preview", { method: "POST", body: JSON.stringify({ csv_text: $("fitness-csv").value }) }); state.csvReady = true; $("commit-fitness").disabled = false; $("fitness-preview").textContent = `校验通过：${result.row_count} 行，${result.workout_count} 条训练，${result.weight_count} 条体重。`; } catch (error) { state.csvReady = false; $("commit-fitness").disabled = true; $("fitness-preview").textContent = error.message; } });
  $("commit-fitness").addEventListener("click", async () => { if (!state.csvReady) return; const result = await api("/fitness/import/commit", { method: "POST", body: JSON.stringify({ csv_text: $("fitness-csv").value }) }); state.csvReady = false; $("commit-fitness").disabled = true; $("fitness-preview").textContent = `已导入：${result.row_count} 行。`; await refreshWorkspace(); showToast("训练 CSV 已导入"); });
  $("document-form").addEventListener("submit", async (event) => { event.preventDefault(); const file = $("document-file").files[0]; if (!file) return; const body = new FormData(); body.append("file", file); body.append("document_version", $("document-version").value); body.append("chunk_size", "500"); body.append("overlap", "50"); const result = await api("/documents/file", { method: "POST", body }); event.target.reset(); $("document-version").value = "v1"; await refreshWorkspace(); showToast(`资料已导入：${result.chunks_ingested} 个分块`); });
  $("new-session").addEventListener("click", () => { state.sessionId = null; localStorage.removeItem("study_session_id"); renderMessages([]); $("agent-proposals").innerHTML = ""; $("trace-output").textContent = "[]"; $("run-summary").textContent = "新会话已开始"; }); $("chat-form").addEventListener("submit", async (event) => { event.preventDefault(); await sendChat(); }); $("profile-form").addEventListener("submit", submitProfile); $("delete-profile").addEventListener("click", async () => { await api("/profile", { method: "DELETE" }); await refreshWorkspace(); showToast("档案已删除"); }); $("add-plan-task").addEventListener("click", addPlanTask); $("plan-form").addEventListener("submit", submitPlan);
}

bindEvents();
if (state.token) enterWorkspace(); else setAuthMode("login");
