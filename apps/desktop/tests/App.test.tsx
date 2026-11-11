import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
vi.mock("../src/connection", async (original) => ({
  ...await original<typeof import("../src/connection")>(),
  backendStatus: vi.fn(), restartBackend: vi.fn(),
}));
import { backendStatus, restartBackend, type BackendStatus } from "../src/connection";
import { App } from "../src/App";
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Türkçe bağlantı durumları", () => {
  it("ilk istek beklerken bağlanıyor gösterir", () => {
    vi.mocked(backendStatus).mockReturnValue(new Promise(() => {}));
    render(<App />);
    expect(screen.getByRole("status").textContent).toBe("Bağlanıyor...");
  });
  it("doğrulanmış yanıtla hazır gösterir", async () => {
    vi.mocked(backendStatus).mockResolvedValue({ state: "ready", error_code: null });
    render(<App />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Hazır"));
  });
  it("IPC hatasını kullanıcıya sabit Türkçe metinle bildirir", async () => {
    vi.mocked(backendStatus).mockRejectedValue(new Error("private detail"));
    render(<App />);
    await screen.findByText("Backend'e bağlanılamadı");
    expect(screen.queryByText("private detail")).toBeNull();
  });
  it("restart sonucu hazır olana kadar hazır iddiasında bulunmaz", async () => {
    vi.mocked(backendStatus).mockResolvedValue({ state: "failed", error_code: "BACKEND_EXITED" });
    let finish!: (value: BackendStatus) => void;
    vi.mocked(restartBackend).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<App />);
    await screen.findByText("Backend'e bağlanılamadı");
    fireEvent.click(screen.getByRole("button", { name: "Yeniden bağlan" }));
    expect(screen.getByRole("status").textContent).toBe("Yeniden bağlanılıyor...");
    finish({ state: "ready", error_code: null });
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Hazır"));
  });
});
