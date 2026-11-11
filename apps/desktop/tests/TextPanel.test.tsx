import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
vi.mock("../src/text", async original => ({ ...await original<typeof import("../src/text")>(), processText: vi.fn() }));
import { processText, TextProcessingError, type TextReply } from "../src/text";
import { TextPanel } from "../src/TextPanel";

const reply: TextReply = { api_version: "1", original_text: "2 + 2 kaç?", normalized_text: "2 + 2 kaç?", intent: "arithmetic",
  reply: "Dört.", action: null, arithmetic: { expression: "2 + 2", value: "4", rounded: false }, external_calls: 0 };
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("yerel metin arayüzü", () => {
  it("bağlantı yokken gönderimi kapatır", () => {
    render(<TextPanel connected={false} />);
    expect((screen.getByLabelText("Mesajınız") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Gönder" }) as HTMLButtonElement).disabled).toBe(true);
    expect(processText).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Mesajınız").getAttribute("autocomplete")).toBe("off");
  });
  it.each(["   ", "x".repeat(1025), "😀".repeat(1025), "\u0344".repeat(600)])("boş veya fazla uzun girdide çağrı yapmadan hata gösterir", text => {
    render(<TextPanel connected />);
    fireEvent.change(screen.getByLabelText("Mesajınız"), { target: { value: text } });
    fireEvent.submit(screen.getByRole("form"));
    expect(screen.getByRole("alert").textContent).toBeTruthy();
    expect(processText).not.toHaveBeenCalled();
  });
  it("loading, deterministik yanıt ve niyeti gösterir; klavye odağını geri verir", async () => {
    let finish!: (value: TextReply) => void;
    vi.mocked(processText).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<TextPanel connected />);
    const input = screen.getByLabelText("Mesajınız");
    fireEvent.change(input, { target: { value: "2 + 2 kaç?" } });
    fireEvent.submit(screen.getByRole("form"));
    expect(screen.getByRole("status").textContent).toBe("İşleniyor...");
    fireEvent.submit(screen.getByRole("form"));
    expect(processText).toHaveBeenCalledExactlyOnceWith("2 + 2 kaç?");
    finish(reply);
    await screen.findByText("Dört.");
    expect(screen.getByText("Algılanan niyet: Hesaplama")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(input));
    fireEvent.change(input, { target: { value: "yeni" } });
    expect(screen.queryByText("Dört.")).toBeNull();
  });
  it("işlem hatasını gösterir ve yeniden göndermeye izin verir", async () => {
    vi.mocked(processText).mockRejectedValue(new TextProcessingError("ARITHMETIC_DIVISION_BY_ZERO", "Sıfıra bölme yapılamaz."));
    render(<TextPanel connected />);
    fireEvent.change(screen.getByLabelText("Mesajınız"), { target: { value: "1/0" } });
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toBe("Sıfıra bölme yapılamaz.");
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false);
  });
});
