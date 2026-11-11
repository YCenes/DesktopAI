import { invoke } from "@tauri-apps/api/core";
import { TextProcessingError } from "./text";

export type TaskStatus = "queued" | "running" | "awaiting_approval" | "succeeded" | "failed" | "cancelled" | "unknown";
export const taskLabels: Record<TaskStatus, string> = { queued: "Sırada", running: "Çalışıyor", awaiting_approval: "Onay bekliyor", succeeded: "Başarılı", failed: "Başarısız", cancelled: "İptal edildi", unknown: "Sonuç belirsiz" };
export type ActionRequest = { task_id: string; action_id: string } & (
  { tool_id: "fake.open_app"; arguments: { app_id: "demo.editor" | "demo.admin" }; scope: "simulation.apps" } |
  { tool_id: "fake.search_files"; arguments: { query: "ornek" | "rapor"; root_id: "synthetic.documents" }; scope: "simulation.files" });
export interface TaskView {
  api_version: "1"; simulated: true; external_calls: 0; action: ActionRequest; status: TaskStatus;
  result: { status: "succeeded" | "failed"; message: string; simulated: true } | null;
  error_code: string | null;
  approval: { approval_id: string; action: ActionRequest; risk: "high"; expected_effect: string; expires_at: number; policy_version: string } | null;
  events: { sequence: number; kind: string; status: TaskStatus; created_at: number }[];
}
const id = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string[]) => Object.keys(v).sort().join() === names.sort().join();
const bounded = (v: unknown, n: number): v is string => typeof v === "string" && v.length > 0 && Array.from(v).length <= n;
const status = (v: unknown): v is TaskStatus => typeof v === "string" && Object.hasOwn(taskLabels, v);
const contract = () => new TextProcessingError("IPC_CONTRACT_ERROR", "Görev yanıtı doğrulanamadı.");

export function validAction(v: unknown): v is ActionRequest {
  if (!object(v) || !keys(v, ["task_id", "action_id", "tool_id", "arguments", "scope"]) || !id(v.task_id) || !id(v.action_id) || !object(v.arguments)) return false;
  const a = v.arguments;
  return v.tool_id === "fake.open_app" ? keys(a, ["app_id"]) && ["demo.editor", "demo.admin"].includes(String(a.app_id)) && v.scope === "simulation.apps" :
    v.tool_id === "fake.search_files" && keys(a, ["query", "root_id"]) && ["ornek", "rapor"].includes(String(a.query)) && a.root_id === "synthetic.documents" && v.scope === "simulation.files";
}
function sameAction(a: ActionRequest, b: ActionRequest) {
  return a.task_id === b.task_id && a.action_id === b.action_id && a.tool_id === b.tool_id && a.scope === b.scope &&
    Object.keys(a.arguments).every(k => a.arguments[k as keyof typeof a.arguments] === b.arguments[k as keyof typeof b.arguments]);
}
export function decodeTask(v: unknown): TaskView {
  if (!object(v) || !keys(v, ["api_version", "simulated", "external_calls", "action", "status", "result", "error_code", "approval", "events"]) ||
      v.api_version !== "1" || v.simulated !== true || v.external_calls !== 0 || !validAction(v.action) || !status(v.status) ||
      (v.error_code !== null && !bounded(v.error_code, 64)) || !Array.isArray(v.events) || v.events.length < 1 || v.events.length > 64) throw contract();
  if (v.events.some((e, i) => !object(e) || !keys(e, ["sequence", "kind", "status", "created_at"]) || e.sequence !== i + 1 || !bounded(e.kind, 64) || !status(e.status) || typeof e.created_at !== "number" || !Number.isFinite(e.created_at))) throw contract();
  if (v.result !== null && (!object(v.result) || !keys(v.result, ["status", "message", "simulated"]) || !["succeeded", "failed"].includes(String(v.result.status)) || v.result.status !== v.status || !bounded(v.result.message, 512) || v.result.simulated !== true)) throw contract();
  if (v.status === "succeeded" && v.result === null) throw contract();
  if (v.approval !== null) {
    const a = v.approval;
    if (!object(a) || !keys(a, ["approval_id", "action", "risk", "expected_effect", "expires_at", "policy_version"]) || !id(a.approval_id) || !validAction(a.action) || !sameAction(a.action, v.action) ||
        a.risk !== "high" || v.status !== "awaiting_approval" || !bounded(a.expected_effect, 512) || !bounded(a.policy_version, 64) || typeof a.expires_at !== "number" || !Number.isFinite(a.expires_at)) throw contract();
  }
  return v as unknown as TaskView;
}
async function ipc(command: string, args?: Record<string, unknown>): Promise<unknown> {
  try { return await invoke<unknown>(command, args); }
  catch (e) {
    if (object(e) && keys(e, ["error_code", "message", "request_id"]) && bounded(e.error_code, 64) && bounded(e.message, 512) && (e.request_id === null || bounded(e.request_id, 64))) throw new TextProcessingError(e.error_code, e.message);
    throw new TextProcessingError("TASK_REQUEST_FAILED", "Görev isteği tamamlanamadı. Geçmişi yenileyin; istek aynı kimlikle tekrar denenir.");
  }
}
export async function createTask(action: ActionRequest): Promise<TaskView> {
  if (!validAction(action)) throw contract();
  const task = decodeTask(await ipc("create_simulated_task", { action }));
  if (!sameAction(task.action, action)) throw contract();
  return task;
}
export async function listTasks(): Promise<TaskView[]> {
  const v = await ipc("list_simulated_tasks");
  if (!object(v) || !keys(v, ["tasks"]) || !Array.isArray(v.tasks) || v.tasks.length > 20) throw contract();
  return v.tasks.map(decodeTask);
}
async function taskOperation(command: string, taskId: string, extra = {}): Promise<TaskView> {
  if (!id(taskId)) throw contract();
  const task = decodeTask(await ipc(command, { taskId, ...extra }));
  if (task.action.task_id !== taskId) throw contract();
  return task;
}
export const getTask = (taskId: string) => taskOperation("get_simulated_task", taskId);
export const cancelTask = (taskId: string) => taskOperation("cancel_simulated_task", taskId);
export const reconcileTask = (taskId: string) => taskOperation("reconcile_simulated_task", taskId);
export function decideApproval(taskId: string, approvalId: string, approve: boolean) {
  if (!id(approvalId) || typeof approve !== "boolean") return Promise.reject(contract());
  return taskOperation("decide_simulated_approval", taskId, { approvalId, approve });
}
