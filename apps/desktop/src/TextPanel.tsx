import { useEffect, useRef, useState, type FormEvent } from "react";
import { inputError, intentLabels, MAX_TEXT_LENGTH, processText, TextProcessingError, type TextReply } from "./text";

export function TextPanel({ connected,onAction }: { connected: boolean;onAction?:(text:string)=>void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<TextReply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(false);
  const mounted = useRef(false);
  const submitted = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!busy && submitted.current && connected) input.current?.focus(); }, [busy, connected]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (active.current || !connected) return;
    setError(null); setReply(null);
    const invalid = inputError(text);
    if (invalid) { setError(invalid.message); input.current?.focus(); return; }
    active.current = true; submitted.current = true; setBusy(true);
    try {
      const result = await processText(text);
      if (mounted.current) setReply(result);
    } catch (failure) {
      if (mounted.current) setError(failure instanceof TextProcessingError ? failure.message : "Metin işlenemedi. Lütfen yeniden deneyin.");
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <div className="text-panel">
      <form onSubmit={event => void submit(event)} aria-label="Yerel metin işleme" autoComplete="off">
        <label htmlFor="nova-text">Mesajınız</label>
        <p id="text-help" className="note">Örneğin: 2 + 2 kaç? En fazla 1.024 karakter.</p>
        <div className="text-controls">
          <input ref={input} id="nova-text" type="text" autoComplete="off" value={text} maxLength={MAX_TEXT_LENGTH * 4}
            aria-describedby="text-help" aria-invalid={error !== null} disabled={!connected || busy}
            onChange={event => { setText(event.target.value); setError(null); setReply(null); }} />
          <button type="submit" disabled={!connected || busy}>Gönder</button>
        </div>
      </form>
      {!connected && <p className="note">Metin göndermek için backend bağlantısını bekleyin.</p>}
      {busy && <p role="status">İşleniyor...</p>}
      {error && <p role="alert">{error}</p>}
      {reply && <div className="text-reply" aria-label="NOVA yanıtı">
        <p role="status">{reply.reply}</p>
        <p className="note">Algılanan niyet: {intentLabels[reply.intent]}</p>
        {reply.action && onAction && <button onClick={()=>onAction(reply.original_text)}>İzinli Windows görevine hazırla</button>}
      </div>}
    </div>
  );
}
