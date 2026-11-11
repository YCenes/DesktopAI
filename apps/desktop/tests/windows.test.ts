import {beforeEach,expect,it,vi} from "vitest";
vi.mock('@tauri-apps/api/core',()=>({invoke:vi.fn()}));
import {invoke} from '@tauri-apps/api/core';
import {decodeTask,createTask,type TaskView,type ActionRequest} from '../src/tasks';
import {createWindowsTask,submitWindowsCommand,listWindowsTasks,decideWindowsApproval} from '../src/windows';
import {task} from './taskFixtures';
export function windowsTask(pending=false):TaskView {
  const base=task(pending);
  const action:ActionRequest={task_id:base.action.task_id,action_id:base.action.action_id,tool_id:'windows.open_app',arguments:{app_id:'windows.notepad'},scope:'windows.apps'};
  return {...base,action,simulated:false,approval:base.approval?{...base.approval,action}:null,result:pending?null:{status:'succeeded',message:'Süreç başlatıldı; pencere hazır olduğu doğrulanmadı.',simulated:false,details:{completion:'process_started',process_id:123,files:[],truncated:false}}};
}
beforeEach(()=>vi.clearAllMocks());
it('gerçek action fake IPC üzerinden gönderilemez',async()=>{
  await expect(createTask(windowsTask().action)).rejects.toHaveProperty('error_code','IPC_CONTRACT_ERROR');expect(invoke).not.toHaveBeenCalled();
});
it('komut aynı request kimlikleriyle dar Windows IPC kullanır',async()=>{
  const t=windowsTask(true);vi.mocked(invoke).mockResolvedValue(t);
  await submitWindowsCommand({task_id:t.action.task_id,action_id:t.action.action_id,text:"Not Defteri'ni aç"});
  expect(invoke).toHaveBeenCalledExactlyOnceWith('submit_windows_command',{taskId:t.action.task_id,actionId:t.action.action_id,text:"Not Defteri'ni aç"});
});
it('approval payload gerçek target argümanlarını yeniden yazamaz',async()=>{
  const t=windowsTask(true);vi.mocked(invoke).mockResolvedValue(windowsTask());
  await decideWindowsApproval(t.action.task_id,t.approval!.approval_id,true);
  expect(invoke).toHaveBeenCalledExactlyOnceWith('decide_windows_approval',{taskId:t.action.task_id,approvalId:t.approval!.approval_id,approve:true});
});
it('gerçek ve simülasyon yanıt etiketlerini çapraz kabul etmez',async()=>{
  const t=windowsTask();expect(()=>decodeTask({...t,simulated:true})).toThrow();
  vi.mocked(invoke).mockResolvedValue({tasks:[task()]});await expect(listWindowsTasks()).rejects.toHaveProperty('error_code','IPC_CONTRACT_ERROR');
});
it('dangerous file payload ve bozuk metadata reddedilir',async()=>{
  const t=windowsTask();
  expect(()=>decodeTask({...t,result:{...t.result,details:{completion:'metadata_search',process_id:null,files:[{root_id:'test',relative_path:'../bad.txt',identity:'a'.repeat(64),size:1}],truncated:false}}})).toThrow();
  await expect(createWindowsTask({...t.action,arguments:{app_id:'cmd.exe'}} as unknown as ActionRequest)).rejects.toHaveProperty('error_code','INVALID_ACTION');
});
