import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
vi.mock("../src/tasks",async original=>({...await original<typeof import("../src/tasks")>(),createTask:vi.fn(),listTasks:vi.fn(),decideApproval:vi.fn(),cancelTask:vi.fn(),reconcileTask:vi.fn()}));
import { createTask, listTasks, decideApproval, cancelTask, reconcileTask } from "../src/tasks";
import { TextProcessingError } from "../src/text";
import { TaskPanel } from "../src/TaskPanel";
import { action, task } from "./taskFixtures";
afterEach(()=>{cleanup();vi.clearAllMocks();});
beforeEach(()=>{vi.mocked(listTasks).mockResolvedValue([]);});
it("bağlantı yokken simülasyon ve onay yapmaz",()=>{
  render(<TaskPanel connected={false}/>);
  expect((screen.getByRole("button",{name:"Onaylı simülasyon başlat"}) as HTMLButtonElement).disabled).toBe(true);
  expect(listTasks).not.toHaveBeenCalled();expect(createTask).not.toHaveBeenCalled();
});
it("gerçek Windows kullanmadığını açıklar ve izinli fake sonucu gösterir",async()=>{
  const result=task();vi.mocked(createTask).mockResolvedValue(result);
  render(<TaskPanel connected/>);
  await waitFor(()=>expect((screen.getByRole("button",{name:"Simüle arama başlat"}) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.getByText(/Windows kontrol edilmez/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Simüle arama başlat"}));
  await screen.findByText("Simülasyon: Windows'ta işlem yapılmadı.");
  expect(vi.mocked(createTask).mock.calls[0][0].tool_id).toBe("fake.search_files");
});
it("yüksek risk hedef/argüman/etkiyi gösterir ve kendiliğinden onaylamaz",async()=>{
  const pending=task(true);vi.mocked(listTasks).mockResolvedValue([pending]);vi.mocked(decideApproval).mockResolvedValue(task());
  render(<TaskPanel connected/>);
  await screen.findByText("Risk: Yüksek");
  expect(screen.getByText(/demo.editor/)).toBeTruthy();expect(screen.getByText(/Yalnızca fake sonuç/)).toBeTruthy();
  expect(decideApproval).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Onayla"}));
  await screen.findByText("Simülasyon: Windows'ta işlem yapılmadı.");
  expect(decideApproval).toHaveBeenCalledExactlyOnceWith(action.task_id,pending.approval!.approval_id,true);
});
it("reddetme ve onay hatasını Türkçe gösterir",async()=>{
  vi.mocked(listTasks).mockResolvedValue([task(true)]);
  vi.mocked(decideApproval).mockRejectedValue(new TextProcessingError("APPROVAL_EXPIRED","Onayın süresi doldu."));
  render(<TaskPanel connected/>);await screen.findByRole("button",{name:"Reddet"});
  fireEvent.click(screen.getByRole("button",{name:"Reddet"}));
  expect((await screen.findByRole("alert")).textContent).toBe("Onayın süresi doldu.");
  expect(vi.mocked(decideApproval).mock.calls[0][2]).toBe(false);
});
it("iptal ve belirsiz sonuç uzlaştırması ayrı işlemlerdir",async()=>{
  const pending=task(true);vi.mocked(listTasks).mockResolvedValue([pending]);
  const unknown={...pending,status:"unknown" as const,approval:null};vi.mocked(cancelTask).mockResolvedValue(unknown);
  vi.mocked(reconcileTask).mockResolvedValue({...task(),status:"failed",result:{status:"failed",message:"Tekrar edilmeden kapatıldı.",simulated:true}});
  render(<TaskPanel connected/>);await screen.findByRole("button",{name:"Görevi iptal et"});
  fireEvent.click(screen.getByRole("button",{name:"Görevi iptal et"}));
  await screen.findByText("Sonuç belirsiz; otomatik tekrar yapılmaz.");
  fireEvent.click(screen.getByRole("button",{name:"Simülasyonu tekrar etmeden kapat"}));
  await screen.findByText("Tekrar edilmeden kapatıldı.");expect(reconcileTask).toHaveBeenCalledExactlyOnceWith(action.task_id);
});
it("çift tıklama tek istek gönderir; belirsiz hatada action kimliği korunur",async()=>{
  let reject!:(e:Error)=>void;
  vi.mocked(createTask).mockReturnValue(new Promise((_,r)=>{reject=r;}));
  render(<TaskPanel connected/>);
  const button=screen.getByRole("button",{name:"Onaylı simülasyon başlat"});
  await waitFor(()=>expect((button as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(button);fireEvent.click(button);expect(createTask).toHaveBeenCalledOnce();
  const first=vi.mocked(createTask).mock.calls[0][0];reject(new Error("private detail"));
  await screen.findByRole("alert");vi.mocked(createTask).mockResolvedValue(task(true));
  fireEvent.click(button);await waitFor(()=>expect(createTask).toHaveBeenCalledTimes(2));
  expect(vi.mocked(createTask).mock.calls[1][0]).toEqual(first);expect(screen.queryByText("private detail")).toBeNull();
});
