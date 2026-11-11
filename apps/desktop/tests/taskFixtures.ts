import type { ActionRequest, TaskView } from "../src/tasks";
export const action: ActionRequest = {task_id:"00000000-0000-0000-0000-000000000001",action_id:"00000000-0000-0000-0000-000000000002",tool_id:"fake.open_app",arguments:{app_id:"demo.editor"},scope:"simulation.apps"};
export function task(pending = false): TaskView {
  return {api_version:"1",simulated:true,external_calls:0,action,status:pending?"awaiting_approval":"succeeded",error_code:null,
    result:pending?null:{status:"succeeded",message:"Simülasyon: Windows'ta işlem yapılmadı.",simulated:true},
    approval:pending?{approval_id:"00000000-0000-0000-0000-000000000003",action,risk:"high",expected_effect:"Yalnızca fake sonuç.",expires_at:Date.now()/1000+120,policy_version:"fake-policy-1"}:null,
    events:[{sequence:1,kind:"task_created",status:"queued",created_at:1}]};
}
