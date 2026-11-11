import { invoke } from "@tauri-apps/api/core";

export const MAX_TEXT_LENGTH = 1024;
export const intentLabels = {
  greeting: "Selamlaşma", arithmetic: "Hesaplama", action_request: "Eylem isteği",
  general_chat: "Genel sohbet", unknown: "Tanınmayan istek",
} as const;
export type Intent = keyof typeof intentLabels;
export interface TextReply {
  api_version: "1";
  original_text: string;
  normalized_text: string;
  intent: Intent;
  reply: string;
  external_calls: 0;
  action: { operation: "open_application" | "search_files" | "web_search"; target: string; executable: false } | null;
  arithmetic: { expression: string; value: string; rounded: boolean } | null;
}

export class TextProcessingError extends Error {
  constructor(public readonly error_code: string, message: string) { super(message); }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function keys(value: Record<string, unknown>, expected: string[]): boolean {
  return Object.keys(value).sort().join(",") === expected.sort().join(",");
}
function bounded(value: unknown, limit: number, nonempty = true): value is string {
  return typeof value === "string" && (!nonempty || value.length > 0) && Array.from(value).length <= limit;
}
function contractError(): TextProcessingError {
  return new TextProcessingError("IPC_CONTRACT_ERROR", "Backend yanıtı doğrulanamadı.");
}

function decodeReply(value: unknown, original: string): TextReply {
  if (!record(value) || !keys(value, ["api_version", "original_text", "normalized_text", "intent", "reply", "external_calls", "action", "arithmetic"]) ||
      value.api_version !== "1" || value.original_text !== original || !bounded(value.normalized_text, MAX_TEXT_LENGTH) ||
      !bounded(value.reply, 512) || value.external_calls !== 0 || typeof value.intent !== "string" || !Object.hasOwn(intentLabels, value.intent)) throw contractError();
  if ((value.intent === "action_request") !== (value.action !== null) || (value.intent === "arithmetic") !== (value.arithmetic !== null)) throw contractError();
  if (value.action !== null) {
    const action = value.action;
    if (!record(action) || !keys(action, ["operation", "target", "executable"]) || action.executable !== false ||
        !bounded(action.target, MAX_TEXT_LENGTH) || !["open_application", "search_files", "web_search"].includes(String(action.operation))) throw contractError();
  }
  if (value.arithmetic !== null) {
    const result = value.arithmetic;
    if (!record(result) || !keys(result, ["expression", "value", "rounded"]) || !bounded(result.expression, 256) ||
        typeof result.value !== "string" || !/^-?[0-9]+(?:\.[0-9]{1,6})?$/.test(result.value) ||
        !Number.isFinite(Number(result.value)) || Math.abs(Number(result.value)) > 1e12 || typeof result.rounded !== "boolean") throw contractError();
  }
  return value as unknown as TextReply;
}

export function inputError(text: string): TextProcessingError | null {
  if (Array.from(text).length > MAX_TEXT_LENGTH || Array.from(text.normalize("NFC")).length > MAX_TEXT_LENGTH) return new TextProcessingError("TEXT_TOO_LONG", "Mesaj en fazla 1.024 karakter olabilir.");
  if (/^\p{White_Space}*$/u.test(text)) return new TextProcessingError("TEXT_EMPTY", "Mesaj boş olamaz.");
  return null;
}

export async function processText(text: string): Promise<TextReply> {
  const invalid = inputError(text);
  if (invalid) throw invalid;
  try {
    return decodeReply(await invoke<unknown>("process_text", { text }), text);
  } catch (error) {
    if (error instanceof TextProcessingError) throw error;
    if (record(error) && keys(error, ["error_code", "message", "request_id"]) &&
        typeof error.error_code === "string" && /^[A-Z0-9_]{1,64}$/.test(error.error_code) && bounded(error.message, 512) &&
        (error.request_id === null || bounded(error.request_id, 64))) {
      throw new TextProcessingError(error.error_code, error.message);
    }
    throw new TextProcessingError("TEXT_REQUEST_FAILED", "Metin işlenemedi. Lütfen yeniden deneyin.");
  }
}
