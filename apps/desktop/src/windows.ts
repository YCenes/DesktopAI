import { decodeTask, ipc, validAction, sameAction, type ActionRequest, type TaskView } from "./tasks";
import { inputError, TextProcessingError } from "./text";

export interface WindowsCommand { task_id: string; action_id: string; text: string }
function check(task: TaskView,id?: string):TaskView {
  if (task.simulated || (id && task.action.task_id !== id)) throw new TextProcessingError("IPC_CONTRACT_ERROR","Windows görev yanıtı doğrulanamadı.");
  return task;
}
export async function submitWindowsCommand(command:WindowsCommand) {
  const invalid=inputError(command.text);if(invalid)throw invalid;
  const task=check(decodeTask(await ipc("submit_windows_command",{taskId:command.task_id,actionId:command.action_id,text:command.text})),command.task_id);
  if(task.action.action_id!==command.action_id)throw new TextProcessingError("IPC_CONTRACT_ERROR","Eylem kimliği eşleşmiyor.");
  return task;
}
export async function createWindowsTask(action:ActionRequest) {
  if(!validAction(action) || action.tool_id.startsWith('fake.'))throw new TextProcessingError("INVALID_ACTION","Windows eylemi geçersiz.");
  const task=check(decodeTask(await ipc("create_windows_task",{action})),action.task_id);
  if(!sameAction(task.action,action))throw new TextProcessingError("IPC_CONTRACT_ERROR","Eylem bağlamı eşleşmiyor.");
  return task;
}
export async function listWindowsTasks():Promise<TaskView[]> {
  const reply=await ipc("list_windows_tasks");
  if(typeof reply!=="object" || reply===null || Object.keys(reply).join()!=="tasks" || !("tasks" in reply) || !Array.isArray(reply.tasks) || reply.tasks.length>20)throw new TextProcessingError("IPC_CONTRACT_ERROR","Windows geçmişi doğrulanamadı.");
  return reply.tasks.map(t=>check(decodeTask(t)));
}
export async function decideWindowsApproval(taskId:string,approvalId:string,approve:boolean) {
  return check(decodeTask(await ipc("decide_windows_approval",{taskId,approvalId,approve})),taskId);
}
export async function cancelWindowsTask(taskId:string) {
  return check(decodeTask(await ipc("cancel_windows_task",{taskId})),taskId);
}
