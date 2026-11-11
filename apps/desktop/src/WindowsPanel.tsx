import { useEffect,useRef,useState,type FormEvent } from "react";
import { taskLabels,type TaskView,type ActionRequest,type FileMatch } from "./tasks";
import { submitWindowsCommand,createWindowsTask,listWindowsTasks,decideWindowsApproval,cancelWindowsTask,type WindowsCommand } from "./windows";
import { TextProcessingError } from "./text";

export function WindowsPanel({connected,draft=""}:{connected:boolean;draft?:string}) {
  const [text,setText]=useState(draft);const [tasks,setTasks]=useState<TaskView[]>([]);
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const active=useRef(false);const mounted=useRef(true);
  const pending=useRef<WindowsCommand|ActionRequest|null>(null);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{setText(draft);},[draft]);
  function update(t:TaskView){if(mounted.current)setTasks(old=>[t,...old.filter(o=>o.action.task_id!==t.action.task_id)].slice(0,20));}
  async function run(work:()=>Promise<void>){
    if(!connected || active.current)return;active.current=true;setBusy(true);setError("");
    try{await work();}catch(e){
      if(e instanceof TextProcessingError && ['APP_NOT_ALLOWED','COMMAND_UNSUPPORTED','ROOT_SELECTION_REQUIRED','WEB_QUERY_INVALID','INVALID_ACTION','INVALID_REQUEST','TEXT_EMPTY','TEXT_TOO_LONG','TEXT_INVALID'].includes(e.error_code))pending.current=null;
      if(mounted.current)setError(e instanceof TextProcessingError?e.message:"Windows görev isteği tamamlanamadı. Geçmişi yenileyin.");
    }
    finally{active.current=false;if(mounted.current)setBusy(false);}
  }
  async function refresh(){const rows=await listWindowsTasks();if(mounted.current)setTasks(rows);if(rows.some(t=>t.action.task_id===pending.current?.task_id))pending.current=null;}
  useEffect(()=>{if(connected)void run(refresh);},[connected]);
  async function submit(e:FormEvent){e.preventDefault();await run(async()=>{
    pending.current??={task_id:crypto.randomUUID(),action_id:crypto.randomUUID(),text};
    const task='text' in pending.current?await submitWindowsCommand(pending.current):await createWindowsTask(pending.current);
    pending.current=null;update(task);
  });}
  async function open(file:FileMatch){await run(async()=>{
    if(pending.current!==null)throw new TextProcessingError('PENDING_REQUEST','Önce belirsiz isteğin geçmişini yenileyin.');
    pending.current={task_id:crypto.randomUUID(),action_id:crypto.randomUUID(),tool_id:'windows.open_file',arguments:{root_id:file.root_id,relative_path:file.relative_path,identity:file.identity},scope:'windows.files'};
    const task=await createWindowsTask(pending.current);pending.current=null;update(task);
  });}
  return <div className="task-panel" aria-label="İzinli Windows araçları">
    <h2>İzinli Windows araçları</h2>
    <p className="note">Bu bölüm gerçek Windows işlemleri içindir. Açma ve web araması ekran onayı ister. Web aramasında sorgu Google hizmetine gönderilir.</p>
    <form aria-label="Windows komutu" onSubmit={e=>void submit(e)} autoComplete="off">
      <label htmlFor="windows-command">Windows komutunuz</label>
      <p className="note">Örnekler: Not Defteri'ni aç · dosya ara rapor · web'de ara Türkçe hava durumu</p>
      <div className="text-controls"><input id="windows-command" autoComplete="off" value={text} maxLength={4096} disabled={!connected||busy} onChange={e=>setText(e.target.value)}/>
      <button disabled={!connected||busy} type="submit">Görev oluştur</button></div>
    </form>
    <button disabled={!connected||busy} onClick={()=>void run(refresh)}>Windows görevlerini yenile</button>
    {busy&&<p aria-live="polite">Windows görev isteği işleniyor...</p>}
    {error&&<p role="alert">{error}</p>}
    <ol className="task-list">{tasks.map(t=><li key={t.action.task_id}>
      <p><strong>{t.action.tool_id}</strong> — {taskLabels[t.status]}</p>
      <p>Hedef ve argümanlar: {t.action.tool_id==='windows.open_file'?`${t.action.arguments.relative_path} (kök: ${t.action.arguments.root_id})`:JSON.stringify(t.action.arguments)} · Kapsam: {t.action.scope}</p>
      {t.error_code&&<p>Durum kodu: {t.error_code}</p>}
      {t.error_code==='PERMISSION_DENIED'&&<p>İzin reddedildi; hedefin kimliği veya izinli kapsam doğrulanamadı.</p>}
      {t.result&&<p>{t.result.message}</p>}
      {t.result?.details?.files.map(f=><div key={f.relative_path}><p>{f.relative_path} ({f.size} byte)</p><button disabled={!connected||busy} onClick={()=>void open(f)}>Dosya açma onayı iste: {f.relative_path}</button></div>)}
      {t.approval&&<div className="approval" aria-label="Windows işlemi onayı">
        <p>Risk: Yüksek</p><p>Beklenen etki: {t.approval.expected_effect}</p>
        <p>Onay sonu: {new Date(t.approval.expires_at*1000).toLocaleString('tr-TR')}</p>
        <button disabled={!connected||busy} onClick={()=>void run(async()=>update(await decideWindowsApproval(t.action.task_id,t.approval!.approval_id,true)))}>Windows işlemini onayla</button>{' '}
        <button disabled={!connected||busy} onClick={()=>void run(async()=>update(await decideWindowsApproval(t.action.task_id,t.approval!.approval_id,false)))}>Windows işlemini reddet</button>
      </div>}
      {['queued','running','awaiting_approval'].includes(t.status)&&<button disabled={!connected||busy} onClick={()=>void run(async()=>update(await cancelWindowsTask(t.action.task_id)))}>Windows görevini iptal et</button>}
      {t.status==='unknown'&&<p>Sonuç belirsiz. Otomatik tekrar veya fake uzlaştırma yapılmaz.</p>}
      <details><summary>Windows görev olayları ({t.events.length})</summary><ol>{t.events.map(e=><li key={e.sequence}>{e.sequence}. {e.kind} — {taskLabels[e.status]}</li>)}</ol></details>
    </li>)}</ol>
  </div>;
}
