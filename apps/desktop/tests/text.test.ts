import { beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
import { invoke } from "@tauri-apps/api/core";
import { processText } from "../src/text";

function response(text = "2 + 2 kaç?") {
  return { api_version: "1", original_text: text, normalized_text: text.trim(), intent: "arithmetic", reply: "Dört.",
    external_calls: 0, action: null, arithmetic: { expression: "2 + 2", value: "4", rounded: false } };
}
beforeEach(() => vi.clearAllMocks());

describe("metin IPC sözleşmesi", () => {
  it("özgün Unicode girdisini yalnızca sabit IPC komutuna gönderir", async () => {
    const text = "  İki artı İKİ  ";
    vi.mocked(invoke).mockResolvedValue(response(text));
    await expect(processText(text)).resolves.toMatchObject({ reply: "Dört.", external_calls: 0 });
    expect(invoke).toHaveBeenCalledExactlyOnceWith("process_text", { text });
  });
  it.each(["", " \t\n", "x".repeat(1025), "😀".repeat(1025), "\u0344".repeat(600)])("geçersiz sınırda IPC çağırmaz", async text => {
    await expect(processText(text)).rejects.toHaveProperty("error_code");
    expect(invoke).not.toHaveBeenCalled();
  });
  it("1024 astral Unicode karakterini byte/UTF-16 sınırıyla karıştırmaz", async () => {
    const text = "😀".repeat(1024);
    vi.mocked(invoke).mockResolvedValue(response(text));
    await processText(text);
    expect(invoke).toHaveBeenCalledOnce();
  });
  it.each([
    null, { ...response(), external_calls: 1 }, { ...response(), original_text: "değişmiş" },
    { ...response(), token: "secret" }, { ...response(), intent: "shell" },
    { ...response(), arithmetic: null }, { ...response(), arithmetic: { expression: "2+2", value: "NaN", rounded: false } },
    { ...response(), intent: "action_request", arithmetic: null, action: { operation: "open_application", target: "Chrome", executable: true } },
  ])("uyumsuz veya yürütme iddialı yanıtı reddeder", async value => {
    vi.mocked(invoke).mockResolvedValue(value);
    await expect(processText("2 + 2 kaç?")).rejects.toHaveProperty("error_code", "IPC_CONTRACT_ERROR");
  });
  it("tipli Türkçe API hatasını korur, ham IPC hatasını gizler", async () => {
    vi.mocked(invoke).mockRejectedValue({ error_code: "ARITHMETIC_DIVISION_BY_ZERO", message: "Sıfıra bölme yapılamaz.", request_id: "test-id" });
    await expect(processText("1/0")).rejects.toThrow("Sıfıra bölme yapılamaz.");
    vi.mocked(invoke).mockRejectedValue(new Error("private detail"));
    await expect(processText("2+2")).rejects.toThrow("Metin işlenemedi. Lütfen yeniden deneyin.");
  });
});
