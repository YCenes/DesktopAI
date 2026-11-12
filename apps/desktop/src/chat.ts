import { invoke } from '@tauri-apps/api/core';
import { TextProcessingError, inputError, intentLabels, type Intent, type TextReply } from './text';

export interface Usage {
  month:string; monthly_usd:string; per_task_usd:string; recorded_usd:string; reserved_usd:string; remaining_usd:string;
  last_estimate_usd:string|null; last_actual_usd:string|null; requests:number; blocked:boolean;
  last_input_tokens:number|null;last_output_tokens:number|null;
}
export interface CloudState {
  provider:'vercel'|'fake'; credential_ready:boolean; enabled:boolean; available:boolean; reason:string|null; model_id:string;
  models:{model_id:string;input_usd_per_million:string;output_usd_per_million:string;price_version:string}[];
  usage:Usage; simulated:boolean;
}
export interface CloudConfig {enabled:boolean;model_id:string;monthly_usd:string;per_task_usd:string}
export interface ChatReply {
  request_id:string;status:'running'|'succeeded'|'failed'|'cancelled';source:'local'|'offline'|'cloud'|'fake';reply:string;
  intent:Intent;action:TextReply['action'];external_calls:0|1;error_code:string|null;estimated_usd:string|null;actual_usd:string|null;usage_known:boolean;
}
function record(v:unknown):v is Record<string,unknown> {return typeof v==='object' && v!==null && !Array.isArray(v);}
function keys(v:Record<string,unknown>,expected:string[]) {return Object.keys(v).sort().join()===expected.sort().join();}
function money(v:unknown):v is string {return typeof v==='string' && /^(0|[1-9][0-9]{0,2})(\.[0-9]{1,9})?$/.test(v);}
function fail():never {throw new TextProcessingError('IPC_CONTRACT_ERROR','Sohbet yanıtı doğrulanamadı.');}
async function ipc(command:string,args?:Record<string,unknown>) {
  try{return await invoke<unknown>(command,args);}catch(error) {
    if(record(error) && keys(error,['error_code','message','request_id']) && typeof error.error_code==='string' && /^[A-Z_]{1,64}$/.test(error.error_code) && typeof error.message==='string' && error.message.length<=512)throw new TextProcessingError(error.error_code,error.message);
    throw new TextProcessingError('CHAT_TRANSPORT_ERROR','Sohbet bağlantısı doğrulanamadı. İstek sürüyor olabilir; aynı isteğin durumunu yenileyin.');
  }
}
export function decodeCloud(v:unknown):CloudState {
  if(!record(v) || !keys(v,['provider','credential_ready','enabled','available','reason','model_id','models','usage','simulated']) ||
    !['vercel','fake'].includes(String(v.provider)) || typeof v.credential_ready!=='boolean' || typeof v.enabled!=='boolean' || typeof v.available!=='boolean' ||
    v.simulated!==(v.provider==='fake') || (v.reason!==null && (typeof v.reason!=='string' || v.reason.length>512)) || typeof v.model_id!=='string' || v.model_id.length>96 ||
    !Array.isArray(v.models) || v.models.length>4 || !record(v.usage))return fail();
  for(const m of v.models)if(!record(m)||!keys(m,['model_id','input_usd_per_million','output_usd_per_million','price_version'])||typeof m.model_id!=='string'||m.model_id.length>96||typeof m.price_version!=='string'||!money(m.input_usd_per_million)||!money(m.output_usd_per_million))return fail();
  const u=v.usage;
  if(!keys(u,['month','monthly_usd','per_task_usd','recorded_usd','reserved_usd','remaining_usd','last_estimate_usd','last_actual_usd','last_input_tokens','last_output_tokens','requests','blocked']) ||
    typeof u.month!=='string'||!/^\d{4}-\d{2}$/.test(u.month)||typeof u.blocked!=='boolean'||typeof u.requests!=='number'||!Number.isSafeInteger(u.requests)||u.requests<0 ||
    ['monthly_usd','per_task_usd','recorded_usd','reserved_usd','remaining_usd'].some(k=>!money(u[k])) || ['last_estimate_usd','last_actual_usd'].some(k=>u[k]!==null&&!money(u[k])) ||
    ['last_input_tokens','last_output_tokens'].some(k=>u[k]!==null&&(typeof u[k]!=='number'||!Number.isSafeInteger(u[k])||(u[k] as number)<0||(u[k] as number)>1000000)))return fail();
  return v as unknown as CloudState;
}
export function decodeChat(v:unknown,id:string):ChatReply {
  if(!record(v)||!keys(v,['request_id','status','source','reply','intent','action','external_calls','error_code','estimated_usd','actual_usd','usage_known'])||v.request_id!==id||
    !['running','succeeded','failed','cancelled'].includes(String(v.status))||!['local','offline','cloud','fake'].includes(String(v.source))||
    typeof v.reply!=='string'||!v.reply.length||Array.from(v.reply).length>4096||typeof v.intent!=='string'||!Object.hasOwn(intentLabels,v.intent)||
    v.external_calls!==(v.source==='cloud'?1:0)||typeof v.usage_known!=='boolean'||(v.error_code!==null&&(typeof v.error_code!=='string'||!/^[A-Z_]{1,64}$/.test(v.error_code)))||
    [v.estimated_usd,v.actual_usd].some(x=>x!==null&&!money(x))||(v.intent==='action_request')!==(v.action!==null)||
    (v.source!=='local'&&v.intent!=='general_chat'))return fail();
  if(v.action!==null && (!record(v.action)||!keys(v.action,['operation','target','executable'])||v.action.executable!==false||typeof v.action.target!=='string'||!v.action.target.length||v.action.target.length>1024||!['open_application','search_files','web_search'].includes(String(v.action.operation))))return fail();
  return v as unknown as ChatReply;
}
export async function cloudSettings(){return decodeCloud(await ipc('cloud_settings'));}
export async function configureCloud(config:CloudConfig){return decodeCloud(await ipc('configure_cloud',{config}));}
export async function startChat(id:string,text:string){const invalid=inputError(text);if(invalid)throw invalid;return decodeChat(await ipc('start_chat',{requestId:id,text}),id);}
export async function pollChat(id:string){return decodeChat(await ipc('poll_chat',{requestId:id}),id);}
export async function cancelChat(id:string){return decodeChat(await ipc('cancel_chat',{requestId:id}),id);}
export async function clearChat(){if(await ipc('clear_chat')!==true)return fail();}
