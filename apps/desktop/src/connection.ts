import { invoke } from "@tauri-apps/api/core";

export type ConnectionState = "connecting" | "ready" | "failed" | "reconnecting";
export interface BackendStatus {
  state: ConnectionState;
  error_code: string | null;
}

export const connectionLabels: Record<ConnectionState, string> = {
  connecting: "Bağlanıyor...",
  ready: "Hazır",
  failed: "Backend'e bağlanılamadı",
  reconnecting: "Yeniden bağlanılıyor...",
};

function decodeStatus(value: unknown): BackendStatus {
  if (typeof value !== "object" || value === null) throw new Error("IPC_CONTRACT_ERROR");
  const data = value as Record<string, unknown>;
  if (
    Object.keys(data).sort().join(",") !== "error_code,state" ||
    typeof data.state !== "string" ||
    !Object.hasOwn(connectionLabels, data.state) ||
    !(data.error_code === null || typeof data.error_code === "string")
  ) throw new Error("IPC_CONTRACT_ERROR");
  return data as unknown as BackendStatus;
}

export async function backendStatus(): Promise<BackendStatus> {
  return decodeStatus(await invoke<unknown>("backend_status"));
}

export async function restartBackend(): Promise<BackendStatus> {
  return decodeStatus(await invoke<unknown>("backend_restart"));
}
