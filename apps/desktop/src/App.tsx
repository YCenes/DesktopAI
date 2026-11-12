import { useEffect, useRef, useState } from "react";
import { backendStatus, restartBackend, connectionLabels, type BackendStatus } from "./connection";
import { TextPanel } from "./TextPanel";
import { TaskPanel } from "./TaskPanel";
import { WindowsPanel } from "./WindowsPanel";
import { ChatPanel } from "./ChatPanel";

const failed: BackendStatus = { state: "failed", error_code: "HOST_UNAVAILABLE" };

export function App() {
  const [windowsDraft,setWindowsDraft]=useState("");
  const [status, setStatus] = useState<BackendStatus>({ state: "connecting", error_code: null });
  const restarting = useRef(false);
  const mounted = useRef(false);
  const revision = useRef(0);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (!restarting.current) {
        const requestRevision = revision.current;
        try {
          const next = await backendStatus();
          if (!cancelled && !restarting.current && requestRevision === revision.current) setStatus(next);
        } catch {
          if (!cancelled && !restarting.current && requestRevision === revision.current) setStatus(failed);
        }
      }
      if (!cancelled) timer = setTimeout(poll, 1000);
    }
    void poll();
    return () => { cancelled = true; mounted.current = false; clearTimeout(timer); };
  }, []);

  async function reconnect() {
    if (restarting.current) return;
    restarting.current = true;
    revision.current += 1;
    setStatus({ state: "reconnecting", error_code: null });
    try {
      const next = await restartBackend();
      if (mounted.current) setStatus(next);
    } catch {
      if (mounted.current) setStatus(failed);
    } finally {
      restarting.current = false;
    }
  }

  return (
    <main>
      <p className="eyebrow">NOVA · Masaüstü temeli</p>
      <h1>Merhaba.</h1>
      <p className="intro">Yerel bağlantınızın durumunu buradan izleyebilirsiniz.</p>
      <section aria-label="Backend bağlantısı">
        <span className={`indicator ${status.state}`} aria-hidden="true" />
        <p role="status" aria-live="polite">{connectionLabels[status.state]}</p>
      </section>
      <button onClick={() => void reconnect()} disabled={status.state !== "failed"}>
        Yeniden bağlan
      </button>
      <TextPanel connected={status.state === "ready"} onAction={setWindowsDraft} />
      <ChatPanel connected={status.state === "ready"} onAction={setWindowsDraft} />
      <WindowsPanel connected={status.state === "ready"} draft={windowsDraft} />
      <TaskPanel connected={status.state === "ready"} />
      <p className="note">Yerel kurallar önce çalışır. Bulut sohbeti ayrıca yapılandırılır. Gerçek eylemler yalnızca izinli Windows görev hattından geçer.</p>
    </main>
  );
}
