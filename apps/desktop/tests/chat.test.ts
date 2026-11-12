import { afterEach, expect, it, vi } from 'vitest';
vi.mock('@tauri-apps/api/core',()=>({invoke:vi.fn()}));
import {invoke} from '@tauri-apps/api/core';
import {cloudSettings,configureCloud,decodeChat,decodeCloud,startChat,cancelChat} from '../src/chat';
import {cloud,reply} from './chatFixtures';
afterEach(()=>vi.clearAllMocks());
it('sadece dar IPC kullanır; anahtar payload alanı yoktur',async()=>{
  vi.mocked(invoke).mockResolvedValue(cloud);
  await cloudSettings();expect(invoke).toHaveBeenCalledWith('cloud_settings',undefined);
  const config={enabled:false,model_id:'mistral/ministral-8b',monthly_usd:'5',per_task_usd:'0.01'};
  await configureCloud(config);expect(invoke).toHaveBeenLastCalledWith('configure_cloud',{config});
});
it('cloud output eylem ve secret alanlarını kabul etmez',()=>{
  expect(()=>decodeChat({...reply('id'),api_key:'secret'},'id')).toThrow();
  expect(()=>decodeChat(reply('id',{source:'cloud',external_calls:1,action:{operation:'open_application',target:'notepad',executable:false}}),'id')).toThrow();
  expect(()=>decodeChat(reply('id',{external_calls:1}),'id')).toThrow();
  expect(()=>decodeCloud({...cloud,api_key:'secret'})).toThrow();
  expect(()=>decodeCloud({...cloud,usage:{...cloud.usage,remaining_usd:'NaN'}})).toThrow();
});
it('istek ve cancellation aynı request kimliğiyle gider',async()=>{
  vi.mocked(invoke).mockResolvedValue(reply('id'));
  await startChat('id','Python nedir?');expect(invoke).toHaveBeenLastCalledWith('start_chat',{requestId:'id',text:'Python nedir?'});
  await cancelChat('id');expect(invoke).toHaveBeenLastCalledWith('cancel_chat',{requestId:'id'});
});
it('girdi sınırı aşılırsa IPC çağrısı yoktur; provider exception yansıtılmaz',async()=>{
  await expect(startChat('id','x'.repeat(1025))).rejects.toThrow('1.024');expect(invoke).not.toHaveBeenCalled();
  vi.mocked(invoke).mockRejectedValue(new Error('synthetic-secret'));
  await expect(cloudSettings()).rejects.toThrow('Sohbet bağlantısı');
});
