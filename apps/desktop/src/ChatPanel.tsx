import { useEffect, useRef, useState, type FormEvent } from 'react';
import { cloudSettings, configureCloud, startChat, pollChat, cancelChat, clearChat, type CloudState, type ChatReply } from './chat';
import { TextProcessingError, inputError } from './text';

export function ChatPanel({connected,onAction}:{connected:boolean;onAction:(text:string)=>void}) {
  const [config,setConfig]=useState<CloudState|null>(null);
  const [model,setModel]=useState('');const [monthly,setMonthly]=useState('');const [task,setTask]=useState('');const [enabled,setEnabled]=useState(false);
  const [text,setText]=useState('');const [messages,setMessages]=useState<{question:string;answer:ChatReply}[]>([]);
  const [pending,setPending]=useState<string|null>(null);const [error,setError]=useState<string|null>(null);const [saving,setSaving]=useState(false);
  const mounted=useRef(false);const active=useRef<string|null>(null);const submitted=useRef('');const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const sending=useRef(false);
  function showError(e:unknown){setError(e instanceof TextProcessingError?e.message:'Sohbet işlemi tamamlanamadı.');}
  async function refresh(){const next=await cloudSettings();if(mounted.current)setConfig(next);return next;}
  useEffect(()=>{
    mounted.current=true;
    if(connected)void refresh().then(c=>{if(!mounted.current)return;setModel(c.model_id||c.models[0]?.model_id||'');setMonthly(c.usage.monthly_usd);setTask(c.usage.per_task_usd);setEnabled(c.enabled);}).catch(e=>{if(mounted.current)showError(e);});
    return()=>{mounted.current=false;if(timer.current)clearTimeout(timer.current);};
  },[connected]);
  async function receive(view:ChatReply){
    if(!mounted.current||active.current!==view.request_id)return;
    if(timer.current)clearTimeout(timer.current);
    if(view.status==='running') {
      timer.current=setTimeout(()=>{void pollChat(view.request_id).then(receive).catch(showError);},250);return;
    }
    active.current=null;setPending(null);
    setMessages(old=>[...old,{question:submitted.current,answer:view}].slice(-3));
    await refresh().catch(showError);
  }
  async function submit(event:FormEvent){
    event.preventDefault();if(!connected||active.current||sending.current)return;
    const invalid=inputError(text);if(invalid){showError(invalid);return;}
    const id=crypto.randomUUID();active.current=id;submitted.current=text;sending.current=true;setPending(id);setError(null);
    try{await receive(await startChat(id,text));}catch(e){
      showError(e);
      if(e instanceof TextProcessingError && ['BUDGET_EXHAUSTED','BUDGET_INVALID','PRICING_INVALID','PROVIDER_DISABLED','CHAT_BUSY','TEXT_TOO_LONG','TEXT_EMPTY','TEXT_INVALID','INVALID_REQUEST',
        'ARITHMETIC_INVALID','ARITHMETIC_DIVISION_BY_ZERO','ARITHMETIC_LIMIT','CONTEXT_LIMIT'].includes(e.error_code)){
        active.current=null;setPending(null);void refresh().catch(showError);
      }
    }
    finally{sending.current=false;}
  }
  async function cancel(){if(!pending)return;if(timer.current)clearTimeout(timer.current);try{await receive(await cancelChat(pending));}catch(e){showError(e);}}
  async function save(event:FormEvent){
    event.preventDefault();if(saving||pending)return;setSaving(true);setError(null);
    try{setConfig(await configureCloud({enabled,model_id:model,monthly_usd:monthly,per_task_usd:task}));setMessages([]);}catch(e){showError(e);}finally{setSaving(false);}
  }
  async function clear(){try{await clearChat();setMessages([]);setText('');}catch(e){showError(e);}}
  return <div className="text-panel chat-panel" role="region" aria-label="Sohbet ve bütçe">
    <h2>Sohbet ve bütçe</h2>
    <p className="note">Bulut AI etkinse genel sohbet metni ve son en fazla üç sohbet turu Vercel AI Gateway üzerinden model sağlayıcısına gönderilir. Yerel komutlar ücretsiz çalışır. Kalıcı kişisel hafıza yoktur.</p>
    {config && <>
      <p>{config.simulated?'Test sağlayıcısı: simülasyon, ağ çağrısı ve gerçek ücret yok.':'Sağlayıcı: Vercel AI Gateway'}</p>
      <p>{config.credential_ready?'Yerel sağlayıcı bağlantı bilgisi hazır.':'Sağlayıcı bağlantı bilgisi yok. Anahtarı yalnızca yerel backend ortamında yapılandırın.'}</p>
      <p>{config.available?'Sohbet sağlayıcısı etkin.':config.reason}</p>
      <form onSubmit={e=>void save(e)} aria-label="Bulut ayarları" autoComplete="off">
        <label>Model <select aria-label="Sohbet modeli" value={model} onChange={e=>setModel(e.target.value)} disabled={!!pending}>
          {config.models.map(m=><option key={m.model_id} value={m.model_id}>{m.model_id}</option>)}
        </select></label>
        <label>Aylık limit (USD) <input aria-label="Aylık limit (USD)" inputMode="decimal" value={monthly} onChange={e=>setMonthly(e.target.value)} disabled={!!pending}/></label>
        <label>Görev başına limit (USD) <input aria-label="Görev başına limit (USD)" inputMode="decimal" value={task} onChange={e=>setTask(e.target.value)} disabled={!!pending}/></label>
        <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)} disabled={!!pending}/> Bulut sohbetini ve metin aktarımını etkinleştir</label>
        <button disabled={!connected||saving||!!pending}>Ayarları kaydet</button>
      </form>
      <p className="note">USD · {config.usage.month} UTC takvim ayı · Kaydedilen: {config.usage.recorded_usd} · Rezervasyon: {config.usage.reserved_usd} · Kalan: {config.usage.remaining_usd}</p>
      <p className="note">Son üst tahmin: {config.usage.last_estimate_usd??'—'} USD · Son kaydedilen maliyet: {config.usage.last_actual_usd??'bilinmiyor'} USD. Ücretsiz krediler limit değildir. İstemci limitleri sağlayıcı faturasını garanti etmez.</p>
      <p className="note">Kayıtlı istek: {config.usage.requests} · Son input/output token: {config.usage.last_input_tokens??'bilinmiyor'} / {config.usage.last_output_tokens??'bilinmiyor'}.</p>
      {config.models.filter(m=>m.model_id===model).map(m=><p className="note" key={m.model_id}>Fiyat sürümü: {m.price_version} · 1M input/output token: {m.input_usd_per_million} / {m.output_usd_per_million} USD.</p>)}
      <button disabled={!connected} onClick={()=>void refresh().catch(showError)}>Kullanımı yenile</button>
    </>}
    <form onSubmit={e=>void submit(e)} aria-label="NOVA sohbeti" autoComplete="off">
      <label htmlFor="chat-text">Sohbet mesajınız</label>
      <input id="chat-text" value={text} maxLength={4096} autoComplete="off" disabled={!connected||!!pending} onChange={e=>setText(e.target.value)}/>
      <button disabled={!connected||!!pending}>Sohbet gönder</button>
    </form>
    {pending && <><p>Yanıt bekleniyor. Bağlantı kesilse de istek sağlayıcıda sürüyor olabilir.</p><button onClick={()=>void cancel()}>Yerel beklemeyi durdur</button><button onClick={()=>void pollChat(pending).then(receive).catch(showError)}>Aynı isteğin durumunu yenile</button></>}
    {error && <p role="alert">{error}</p>}
    {messages.map(m=><div className="text-reply" key={m.answer.request_id}><p>{m.question}</p><p>{m.answer.reply}</p>
      <p className="note">{m.answer.source==='cloud'?'Bulut yanıtı':m.answer.source==='fake'?'Simülasyon':m.answer.source==='offline'?'Çevrimdışı':'Yerel yanıt'} · Tahmin: {m.answer.estimated_usd??'0'} USD · Kayıt: {m.answer.actual_usd??(m.answer.usage_known?'0':'bilinmiyor')} USD</p>
      {m.answer.action && <button onClick={()=>onAction(m.question)}>Windows görevine hazırla</button>}
    </div>)}
    <button disabled={!connected||!!pending} onClick={()=>void clear()}>Oturum sohbetini temizle</button>
  </div>;
}
