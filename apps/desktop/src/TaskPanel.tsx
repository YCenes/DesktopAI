import { useEffect, useRef, useState } from "react";
import { createTask, listTasks, decideApproval, cancelTask, reconcileTask, taskLabels, type ActionRequest, type TaskView } from "./tasks";
import { TextProcessingError } from "./text";

export function TaskPanel({ connected }: { connected: boolean }) {
  const [tasks, setTasks] = useState<TaskView[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const mounted = useRef(true);
  const pending = useRef<ActionRequest | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function request(work: () => Promise<void>) {
    if (!connected || active.current) return;
    active.current = true; setBusy(true); setError("");
    try { await work(); }
    catch (e) { if (mounted.current) setError(e instanceof TextProcessingError ? e.message : "Simülasyon isteği tamamlanamadı."); }
    finally { active.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh() {
    const latest = await listTasks();
    if (mounted.current) setTasks(latest);
    if (latest.some(t => t.action.task_id === pending.current?.task_id)) pending.current = null;
  }
  useEffect(() => { if (connected) void request(refresh); }, [connected]);
  function update(task: TaskView) { if (mounted.current) setTasks(old => [task, ...old.filter(t => t.action.task_id !== task.action.task_id)].slice(0, 20)); }
  async function start(high: boolean) {
    // Belirsiz HTTP sonucu yeni action_id üretmez; aynı isteği tekrar kullanır.
    pending.current ??= { task_id: crypto.randomUUID(), action_id: crypto.randomUUID(), ...(high ?
      { tool_id: "fake.open_app" as const, arguments: { app_id: "demo.editor" as const }, scope: "simulation.apps" as const } :
      { tool_id: "fake.search_files" as const, arguments: { query: "rapor" as const, root_id: "synthetic.documents" as const }, scope: "simulation.files" as const }) };
    const task = await createTask(pending.current); pending.current = null; update(task);
  }
  return <div className="task-panel" aria-label="Simülasyon görevleri">
    <h2>Görev simülasyonu</h2>
    <p className="note">Bu işlemler simülasyondur. Windows kontrol edilmez; gerçek uygulamalar ve dosyalar kullanılmaz.</p>
    <div className="task-controls">
      <button disabled={!connected || busy} onClick={() => void request(() => start(false))}>Simüle arama başlat</button>
      <button disabled={!connected || busy} onClick={() => void request(() => start(true))}>Onaylı simülasyon başlat</button>
      <button disabled={!connected || busy} onClick={() => void request(refresh)}>Görevleri yenile</button>
    </div>
    {busy && <p aria-live="polite">Simülasyon isteği işleniyor...</p>}
    {error && <p role="alert">{error}</p>}
    <ol className="task-list">{tasks.map(task => <li key={task.action.task_id}>
      <p><strong>{task.action.tool_id}</strong> — {taskLabels[task.status]}</p>
      <small>Görev: {task.action.task_id}</small>
      <p>Argümanlar: {JSON.stringify(task.action.arguments)} · Kapsam: {task.action.scope}</p>
      {task.result && <p>{task.result.message}</p>}
      {task.error_code && <p>Durum kodu: {task.error_code}</p>}
      {task.approval && <div className="approval" aria-label="Simülasyon onayı">
        <p>Risk: Yüksek</p><p>Beklenen etki: {task.approval.expected_effect}</p>
        <p>Onay sonu: {new Date(task.approval.expires_at * 1000).toLocaleString("tr-TR")}</p>
        <button disabled={!connected || busy || Date.now() >= task.approval.expires_at * 1000} onClick={() => void request(async () => update(await decideApproval(task.action.task_id, task.approval!.approval_id, true)))}>Onayla</button>{" "}
        <button disabled={!connected || busy} onClick={() => void request(async () => update(await decideApproval(task.action.task_id, task.approval!.approval_id, false)))}>Reddet</button>
      </div>}
      {["queued", "running", "awaiting_approval"].includes(task.status) && <button disabled={!connected || busy} onClick={() => void request(async () => update(await cancelTask(task.action.task_id)))}>Görevi iptal et</button>}
      {task.status === "unknown" && <><p>Sonuç belirsiz; otomatik tekrar yapılmaz.</p><button disabled={!connected || busy} onClick={() => void request(async () => update(await reconcileTask(task.action.task_id)))}>Simülasyonu tekrar etmeden kapat</button></>}
      <details><summary>Görev olayları ({task.events.length})</summary><ol>{task.events.map(e => <li key={e.sequence}>{e.sequence}. {e.kind} — {taskLabels[e.status]}</li>)}</ol></details>
    </li>)}</ol>
  </div>;
}
