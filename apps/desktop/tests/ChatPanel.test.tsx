import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
vi.mock('../src/chat',async original=>({...await original<typeof import('../src/chat')>(),cloudSettings:vi.fn(),configureCloud:vi.fn(),startChat:vi.fn(),pollChat:vi.fn(),cancelChat:vi.fn(),clearChat:vi.fn()}));
import {cloudSettings,configureCloud,startChat,pollChat,cancelChat,clearChat} from '../src/chat';
import {ChatPanel} from '../src/ChatPanel';
import {TextProcessingError} from '../src/text';
import {cloud,reply} from './chatFixtures';
afterEach(()=>{cleanup();vi.clearAllMocks();});
async function ready(){vi.mocked(cloudSettings).mockResolvedValue(cloud);render(<ChatPanel connected onAction={vi.fn()}/>);await screen.findByText('Bulut yanıtları kapalı.');}
function send(){fireEvent.change(screen.getByLabelText('Sohbet mesajınız'),{target:{value:'Python nedir?'}});fireEvent.click(screen.getByText('Sohbet gönder'));}
it('bağlantı yokken sohbet gönderemez',()=>{render(<ChatPanel connected={false} onAction={vi.fn()}/>);expect((screen.getByText('Sohbet gönder') as HTMLButtonElement).disabled).toBe(true);expect(startChat).not.toHaveBeenCalled();});
it('kurulum açık veri aktarımı ve iki USD limiti gerektirir',async()=>{
  await ready();expect(screen.getByText(/Vercel AI Gateway üzerinden/)).toBeDefined();
  vi.mocked(configureCloud).mockResolvedValue({...cloud,enabled:true});
  fireEvent.change(screen.getByLabelText('Aylık limit (USD)'),{target:{value:'5'}});
  fireEvent.change(screen.getByLabelText('Görev başına limit (USD)'),{target:{value:'0.01'}});
  fireEvent.click(screen.getByLabelText('Bulut sohbetini ve metin aktarımını etkinleştir'));
  fireEvent.click(screen.getByText('Ayarları kaydet'));
  await waitFor(()=>expect(configureCloud).toHaveBeenCalledWith({enabled:true,model_id:'mistral/ministral-8b',monthly_usd:'5',per_task_usd:'0.01'}));
});
it('yanıt düz metindir ve LLM çıktısı Windows görevi oluşturmaz',async()=>{
  await ready();vi.mocked(startChat).mockImplementation(async id=>reply(id,{reply:'<script>cmd</script>'}));send();
  await screen.findByText('<script>cmd</script>');expect(screen.queryByText('Windows görevine hazırla')).toBeNull();expect(document.querySelector('script')).toBeNull();
  vi.mocked(clearChat).mockResolvedValue(undefined);fireEvent.click(screen.getByText('Oturum sohbetini temizle'));await waitFor(()=>expect(screen.queryByText('<script>cmd</script>')).toBeNull());
});
it('belirsiz transport sonucu yeni paid request üretmez; aynı ID yenilenir',async()=>{
  await ready();vi.mocked(startChat).mockRejectedValue(new TextProcessingError('CHAT_TRANSPORT_ERROR','İstek sürüyor olabilir.'));send();
  await screen.findByText('İstek sürüyor olabilir.');expect((screen.getByText('Sohbet gönder') as HTMLButtonElement).disabled).toBe(true);
  const id=vi.mocked(startChat).mock.calls[0][0];vi.mocked(pollChat).mockResolvedValue(reply(id));fireEvent.click(screen.getByText('Aynı isteğin durumunu yenile'));
  await screen.findByText('Simülasyon: Python bir programlama dilidir.');expect(startChat).toHaveBeenCalledTimes(1);expect(pollChat).toHaveBeenCalledWith(id);
});
it('cancellation sağlayıcıyı durdurduğunu iddia etmez',async()=>{
  await ready();vi.mocked(startChat).mockImplementation(async id=>reply(id,{status:'running'}));
  vi.mocked(cancelChat).mockImplementation(async id=>reply(id,{status:'cancelled',reply:'Yerel bekleme durdu; sağlayıcı isteği sürebilir.'}));
  send();await screen.findByText('Yerel beklemeyi durdur');fireEvent.click(screen.getByText('Yerel beklemeyi durdur'));
  await screen.findByText('Yerel bekleme durdu; sağlayıcı isteği sürebilir.');expect(cancelChat).toHaveBeenCalledTimes(1);
});
it('kesin bütçe reddi formu kilitlemez',async()=>{
  await ready();vi.mocked(startChat).mockRejectedValue(new TextProcessingError('BUDGET_EXHAUSTED','Bütçe yetersiz.'));send();
  await screen.findByText('Bütçe yetersiz.');expect((screen.getByText('Sohbet gönder') as HTMLButtonElement).disabled).toBe(false);
});
it('yerel aritmetik hatasından sonra yeni mesaj gönderilebilir',async()=>{
  await ready();
  vi.mocked(startChat).mockRejectedValueOnce(new TextProcessingError('ARITHMETIC_DIVISION_BY_ZERO','Sıfıra bölme yapılamaz.'))
    .mockImplementation(async id=>reply(id,{source:'local',intent:'arithmetic',reply:'Dört.',estimated_usd:null,actual_usd:null}));
  fireEvent.change(screen.getByLabelText('Sohbet mesajınız'),{target:{value:'1 / 0'}});
  fireEvent.click(screen.getByText('Sohbet gönder'));
  await screen.findByText('Sıfıra bölme yapılamaz.');
  expect((screen.getByText('Sohbet gönder') as HTMLButtonElement).disabled).toBe(false);
  fireEvent.change(screen.getByLabelText('Sohbet mesajınız'),{target:{value:'2 + 2 kaç?'}});
  fireEvent.click(screen.getByText('Sohbet gönder'));
  await screen.findByText('Dört.');expect(startChat).toHaveBeenCalledTimes(2);
});
