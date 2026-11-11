import { beforeEach, expect, it, vi } from "vitest";
vi.mock("@tauri-apps/api/core",()=>({invoke:vi.fn()}));
import { invoke } from "@tauri-apps/api/core";
import { createTask, listTasks, decideApproval, decodeTask, validAction, cancelTask, reconcileTask, getTask } from "../src/tasks";
import { action, task } from "./taskFixtures";
beforeEach(()=>vi.clearAllMocks());
it("yalnızca typed fake action ve dar IPC kullanır",async()=>{
  vi.mocked(invoke).mockResolvedValue(task());
  await createTask(action);
  expect(invoke).toHaveBeenCalledExactlyOnceWith("create_simulated_task",{action});
  expect(validAction({...action,scope:"host.all"})).toBe(false);
  expect(validAction({...action,tool_id:"shell"})).toBe(false);
  expect(validAction({...action,arguments:{app_id:"C:/Windows/cmd.exe"}})).toBe(false);
});
it.each([
  {simulated:false},{external_calls:1},{token:"must not leak"},{status:"executing_shell"},{events:[]},
  {result:{status:"succeeded",message:"wrong",simulated:false}},
])("uyumsuz/secret/cloud yanıtını reddeder",patch=>{
  expect(()=>decodeTask({...task(),...patch})).toThrow("Görev yanıtı doğrulanamadı.");
});
it("değişmiş eyleme onay metadata'sını kabul etmez",()=>{
  const t=task(true);t.approval!.action={...action,action_id:"00000000-0000-0000-0000-000000000009"};
  expect(()=>decodeTask(t)).toThrow();
});
it("onay request'i yalnızca kimlik ve bool taşır; eylem veya risk göndermez",async()=>{
  const t=task(true);vi.mocked(invoke).mockResolvedValue(task());
  await decideApproval(action.task_id,t.approval!.approval_id,true);
  expect(invoke).toHaveBeenCalledExactlyOnceWith("decide_simulated_approval",{taskId:action.task_id,approvalId:t.approval!.approval_id,approve:true});
});
it("list/view/cancel/reconcile komutları sabittir",async()=>{
  vi.mocked(invoke).mockResolvedValue({tasks:[task()]});expect(await listTasks()).toHaveLength(1);
  vi.mocked(invoke).mockResolvedValue(task());
  await getTask(action.task_id);await cancelTask(action.task_id);await reconcileTask(action.task_id);
  expect(vi.mocked(invoke).mock.calls.map(c=>c[0])).toEqual(["list_simulated_tasks","get_simulated_task","cancel_simulated_task","reconcile_simulated_task"]);
});
it("geçersiz kimlik backend'e gönderilmez ve raw IPC hatası gösterilmez",async()=>{
  await expect(getTask("../../secret")).rejects.toHaveProperty("error_code","IPC_CONTRACT_ERROR");
  expect(invoke).not.toHaveBeenCalled();
  vi.mocked(invoke).mockRejectedValue(new Error("secret backend detail"));
  await expect(createTask(action)).rejects.toThrow("Görev isteği tamamlanamadı.");
});
