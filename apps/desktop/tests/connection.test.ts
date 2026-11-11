import { describe, expect, it, vi } from "vitest";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
import { invoke } from "@tauri-apps/api/core";
import { backendStatus, restartBackend } from "../src/connection";

describe("dar IPC sözleşmesi", () => {
  it("yalnızca sabit, argümansız komutlar gönderir", async () => {
    vi.mocked(invoke).mockResolvedValue({ state: "ready", error_code: null });
    await expect(backendStatus()).resolves.toEqual({ state: "ready", error_code: null });
    await restartBackend();
    expect(invoke).toHaveBeenNthCalledWith(1, "backend_status");
    expect(invoke).toHaveBeenNthCalledWith(2, "backend_restart");
  });
  it.each([
    null, { state: "unknown", error_code: null }, { state: "ready", error_code: null, token: "secret" },
    { state: "ready" }, { state: "ready", error_code: 42 },
  ])("uyumsuz veya ek alanlı yanıtı reddeder: %j", async (value) => {
    vi.mocked(invoke).mockResolvedValue(value);
    await expect(backendStatus()).rejects.toThrow("IPC_CONTRACT_ERROR");
  });
});
