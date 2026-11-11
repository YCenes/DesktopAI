import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
vi.mock('../src/windows',()=>({submitWindowsCommand:vi.fn(),createWindowsTask:vi.fn(),listWindowsTasks:vi.fn(),decideWindowsApproval:vi.fn(),cancelWindowsTask:vi.fn()}));
import {submitWindowsCommand,createWindowsTask,listWindowsTasks,decideWindowsApproval} from '../src/windows';
import {WindowsPanel} from '../src/WindowsPanel';
import {task} from './taskFixtures';
import type {TaskView} from '../src/tasks';
import {TextProcessingError} from '../src/text';
function real(pending=false):TaskView {
  const t=task(pending);
  const action={...t.action,tool_id:'windows.open_app' as const,arguments:{app_id:'windows.notepad' as const},scope:'windows.apps' as const};
  return {...t,action,simulated:false,approval:t.approval?{...t.approval,action,expected_effect:'Gerçek Not Defteri başlatılır.'}:null,result:pending?null:{status:'succeeded',message:'Başlatma isteği kabul edildi. Pencere hazır olduğu doğrulanmadı.',simulated:false}};
}
afterEach(()=>{cleanup();vi.clearAllMocks();});
beforeEach(()=>vi.mocked(listWindowsTasks).mockResolvedValue([]));
it('bağlantı yokken gerçek komut göndermez',()=>{
  render(<WindowsPanel connected={false}/>);
  expect((screen.getByRole('button',{name:'Görev oluştur'}) as HTMLButtonElement).disabled).toBe(true);
  expect(submitWindowsCommand).not.toHaveBeenCalled();
});
it('sınıflandırma kendiliğinden onay değildir; açık tıklama gerekir',async()=>{
  vi.mocked(submitWindowsCommand).mockResolvedValue(real(true));vi.mocked(decideWindowsApproval).mockResolvedValue(real());
  render(<WindowsPanel connected draft="Not Defteri'ni aç"/>);
  await waitFor(()=>expect((screen.getByRole('button',{name:'Görev oluştur'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.submit(screen.getByRole('form',{name:'Windows komutu'}));await screen.findByText('Risk: Yüksek');
  expect(decideWindowsApproval).not.toHaveBeenCalled();expect(screen.getByText(/Google hizmetine gönderilir/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Windows işlemini onayla'}));
  await screen.findByText('Başlatma isteği kabul edildi. Pencere hazır olduğu doğrulanmadı.');
  expect(decideWindowsApproval).toHaveBeenCalledOnce();
});
it('arama sonucu dosyayı kendiliğinden açmaz; ayrı action bağlar',async()=>{
  const t=real();t.action={task_id:t.action.task_id,action_id:t.action.action_id,tool_id:'windows.search_files',arguments:{root_id:'test',query:'rapor'},scope:'windows.files'};
  t.result={status:'succeeded',message:'Bir metadata bulundu.',simulated:false,details:{completion:'metadata_search',process_id:null,files:[{root_id:'test',relative_path:'rapor.txt',identity:'a'.repeat(64),size:12}],truncated:false}};
  vi.mocked(listWindowsTasks).mockResolvedValue([t]);vi.mocked(createWindowsTask).mockResolvedValue(real(true));
  render(<WindowsPanel connected/>);await screen.findByText('rapor.txt (12 byte)');
  expect(createWindowsTask).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Dosya açma onayı iste: rapor.txt'}));
  await waitFor(()=>expect(createWindowsTask).toHaveBeenCalledOnce());
  expect(vi.mocked(createWindowsTask).mock.calls[0][0]).toMatchObject({tool_id:'windows.open_file',arguments:{root_id:'test',relative_path:'rapor.txt',identity:'a'.repeat(64)}});
});
it('belirsiz sonuçta otomatik retry veya fake reconcile sunmaz',async()=>{
  const t=real();t.status='unknown';t.result=null;vi.mocked(listWindowsTasks).mockResolvedValue([t]);
  render(<WindowsPanel connected/>);await screen.findByText('Sonuç belirsiz. Otomatik tekrar veya fake uzlaştırma yapılmaz.');
  expect(submitWindowsCommand).not.toHaveBeenCalled();expect(screen.queryByText('Simülasyonu tekrar etmeden kapat')).toBeNull();
});
it('kesin reddedilen komut yeni komutu eski payload ile kilitlemez',async()=>{
  vi.mocked(submitWindowsCommand).mockRejectedValueOnce(new TextProcessingError('APP_NOT_ALLOWED','Uygulama izinli değil.')).mockResolvedValueOnce(real(true));
  render(<WindowsPanel connected draft="Chrome'u aç"/>);
  await waitFor(()=>expect((screen.getByRole('button',{name:'Görev oluştur'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.submit(screen.getByRole('form'));await screen.findByRole('alert');
  fireEvent.change(screen.getByLabelText('Windows komutunuz'),{target:{value:"Not Defteri'ni aç"}});
  fireEvent.submit(screen.getByRole('form'));await screen.findByText('Risk: Yüksek');
  expect(vi.mocked(submitWindowsCommand).mock.calls[1][0].text).toBe("Not Defteri'ni aç");
  expect(vi.mocked(submitWindowsCommand).mock.calls[1][0].action_id).not.toBe(vi.mocked(submitWindowsCommand).mock.calls[0][0].action_id);
});
