import type { CloudState, ChatReply } from '../src/chat';
export const cloud:CloudState={provider:'fake',credential_ready:true,enabled:false,available:false,reason:'Bulut yanıtları kapalı.',model_id:'',simulated:true,
  models:[{model_id:'mistral/ministral-8b',input_usd_per_million:'0.15',output_usd_per_million:'0.15',price_version:'test-v1'}],
  usage:{month:'2026-11',monthly_usd:'0.000000000',per_task_usd:'0.000000000',recorded_usd:'0.000000000',reserved_usd:'0.000000000',remaining_usd:'0.000000000',last_estimate_usd:null,last_actual_usd:null,last_input_tokens:null,last_output_tokens:null,requests:0,blocked:false}};
export function reply(id:string, changes:Partial<ChatReply>={}):ChatReply{return {request_id:id,status:'succeeded',source:'fake',reply:'Simülasyon: Python bir programlama dilidir.',intent:'general_chat',action:null,external_calls:0,error_code:null,estimated_usd:'0.0001',actual_usd:'0.00002',usage_known:true,...changes};}
