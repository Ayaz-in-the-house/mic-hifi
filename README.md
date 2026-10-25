<p align="center"><img src="assets/icon.svg" width="96" alt="mic-hifi"></p>

# mic-hifi

USB mikrofonun sesini PipeWire üzerinde katman katman işleyip **sanal bir mikrofon** olarak sunan yerel bir sistem ve onu yöneten küçük bir web paneli.
Ses bilgisayarından çıkmaz; bulut yok, hesap yok.

Zincir: alt kesim (95 Hz) → seviyeleyici (fısıltıyı yükseltir, sessizlikte donar) → kompresör → gürültü bastırma (DeepFilterNet3) → sessizlik kapısı →
ton (8 bantlı dengeleyici, hazır karakterler) → çok bantlı dinamik (dolgunluk, şişme, sertlik, ıslık) → doygunluk → tavan sınırlayıcı.
İsteğe bağlı: perde/ses yolu kaydırma ve ikinci, gecikmeli bir "kalite" mikrofonu (ekran kartında çalışan daha güçlü bir gürültü giderici).

## Yol haritası — ne yapılırsa nereye ulaşılır

Temizleme zinciri ve panel ölçümle kuruldu ve canlıda çalışıyor. Mikrofonun kendisi (kapsül, konum, cihaz içi işlem) ve dinleyici tarafının doğrulaması ise henüz ayrıştırılmadı. Tablodaki kazançlar **beklentidir, ölçülmüş sonuç değildir**.

| katman | bugün bilinen (yapıldı) | yapılmadı · test edilmedi · bilinmiyor | yapılınca nereye ulaşılır | nasıl / kaynak |
|---|---|---|---|---|
| **L1** akustik: kapsül, mesafe, oda | Gürültünün neredeyse tamamı 80 Hz altında; öz gürültü ~27 dB(A); 16 bit / ~17 kHz | Mikrofonun frekans yanıtı ölçülmedi (referans mikrofon yok) → ton düzeltmesi yok. Ağza mesafenin etkisi yalnız hesap (~+15 dB, ölçülmedi). Oda yankısı ele alınmadı | **En ucuz kazanç:** mikrofonu ağız kenarına 4–5 cm yaklaştırmak (bedava). Ölçülürse ton düzlenir, ses "kendi sesin" gibi duyulur | 5 dk mesafe ölçümü; referans mikrofon ya da bilinen kaynakla yanıt ölçümü |
| **L2** cihaz: USB mikrofonun içi | Halka mikrofonun kazancını cihaz kendi içinde ayarlıyor; cihazın sessiz tuşu panelde görünüyor | Cihaz içi otomatik kazanç / işlem tam karakterize edilmedi. Üretici kontrol kanalına **bilerek yazılmıyor** | Cihazın kendi ayarıyla zincirin birbiriyle "yarışması" önlenir | Yalnız okuma ve ölçüm; cihaza komut gönderilmez |
| **L3** Linux / PipeWire / yakalama | Sanal mikrofon; profil kayarsa bekçi kendiliğinden onarıyor; yeniden başlatma ~2,5 sn | Çok çekirdekli ağır yükte gürültü bastırıcı blok kaçırabiliyor (kısa kesinti) — **açık**; profil kaymasının kök nedeni adlandırılmadı | Yük altında da kesintisiz canlı kullanım | Bastırıcıyı ayrı bir işçi sürece taşımak (taşıyıcı tasarımı yalıtılmış örnekte test edildi) + uzun yük koşusu |
| **L4** temizleme zinciri | **Güçlü:** fısıltı SNR 8,6 → 27,1 dB; seviyeleyici, kompresör, DeepFilterNet3, kapı, bölünmüş bantlı ıslık kısma, dinamik EQ; çıkış hedefi −23 / −16 LUFS, gerçek tepe ≤ −1 dBTP | Yalnız Fısıltı modu kabul testinden geçti; Normal ve Gece değerleri ölçümle oturtulmadı. Ağız sesi / çıtırtı canlıda yok, oda yankısı giderme yok, eko iptali denendi ama bağlanmadı. Çoğu ayar kulakla doğrulanmadı | Stüdyoya yakın teslim; hoparlörle görüşmede eko iptali | Kendi sesinle test seti kaydı (~20 dk) + panelin teşhis kaydı |
| **L5** kalite hattı (ekran kartı) | İkinci, ~1 sn gecikmeli "kalite" mikrofonu canlıda (MossFormer2); kayıtlı dosyayı iyileştirme (`mic enhance`); çevrimdışı ölçümde DeepFilterNet'ten iyi (SNR 37,1 ↔ 30,7 dB) | Kulakla doğrulanmadı; kurulumu bu depoda belgelenmedi; ana mikrofon yapılmadı | Kayıt ve yayında, gecikmenin önemli olmadığı yerde daha temiz ses | Kurulum belgesi + kulak testi |
| **L6** ses karakteri, perde, dönüştürme | 10 karakter (Nötr, Sıcak, Parlak, Radyo, Derin, Yakın, Telefon, Megafon, Kalın, İri), yoğunluk, kendi karakterlerin; perde (Rubber Band) | Formant ayrı ayarlanmıyor; YZ ses dönüştürme yapılmadı | Kendi ses renginin değiştirilmesi; YZ ile başka bir sese dönüşme | Açık kaynak ses dönüştürme modelleri (lisans ve gecikme ölçülerek) |
| **L7** panel, kurulum, dağıtım | Panel, teşhis kaydı, profiller; mikrofon `mic device` ile seçiliyor; Apache-2.0; temiz yayın ağacı | Kurulum temiz bir makinede baştan sona yürünmedi; kurulum sihirbazı ertelendi; İngilizce arayüz yok; CI yok; DeepFilterNet zorunlu | Başkalarının kendi makinesinde kolayca kurup kullanması | Temiz makinede/VM'de kurulum yürüyüşü + sentetik sinyalle CI |

**Aşılamayacak tavan.** Ses kalitesindeki en büyük fark donanımdan gelir: öz gürültü ~27 dB(A) ve 16 bit / ~17 kHz. Yazılım gürültüyü sonradan bastırır, iyi bir mikrofon baştan üretmez; bu fark yazılımla kapanmaz. Gerçekçi hedef: görüşme ve yayın için temiz ses; stüdyo vokali bu mikrofonla ulaşılamaz.

**Açık kaynak tarafı.** Fısıltı kipi incelenen ticari ürünlerin hiçbirinde bulunamadı; zincir tamamen yerel ve PipeWire üzerinde. Mikrofon `mic device` ile seçildiği için yöntem başka USB mikrofonlara da uygulanabilir — ölçülen tek mikrofon olsa da.

**Plan:** en büyük iki kazanç hâlâ bedava: mikrofonu yaklaştırmak ve test seti kaydı. Sonra kesintisiz canlı kullanım (L3), sonra kulak doğrulaması ve kalite hattının belgelenmesi.

- [ ] **L1** mesafe ölçümü + frekans yanıtı
- [ ] **L2** cihaz içi kazancın karakterizasyonu (salt okuma)
- [ ] **L3** yük altında kesintisiz (bastırıcıyı ayrı işçiye taşı)
- [ ] **L4** Normal/Gece modlarını ölçümle oturt; ağız sesi, eko iptali
- [ ] **L5** kalite hattının kurulum belgesi + kulak testi
- [ ] **L6** formant + YZ ses dönüştürme
- [ ] **L7** temiz makinede kurulum yürüyüşü, İngilizce arayüz, CI

## Ekran görüntüleri

![Mikrofon konsolu: mod, ses karakteri ve ton ayarları](assets/screenshots/panel.png)

![Teşhis kaydı: oda sesi ve kısa örnek kayıtlarla ince ayar](assets/screenshots/teshis-kaydi.png)

## Gereksinimler

- Linux, **PipeWire** (1.6.8 ile ölçüldü) ve WirePlumber; `pactl`, `pw-link`, `pw-cli`, `pw-record` komutları
- Python 3 (panel ve zincir yalnız standart kitaplığı kullanır); ölçüm araçları ve testler için `requirements.txt` (numpy, scipy)
- LSP Plugins LADSPA paketi (dağıtım deposundan, ör. Fedora'da `lsp-plugins-ladspa`)
- DeepFilterNet LADSPA eklentisi v0.5.6: yukarı akıştan indirilir ve `~/.local/lib/mic-hifi/libdeep_filter_ladspa.so` olarak konur; özeti `plugins.lock.json` içinde kilitlidir
- İsteğe bağlı: Rubber Band LADSPA eklentisi (perde için; Fedora'da `bash tools/install_rubberband.sh` kök yetkisi istemeden kurar)

Bu depo yukarıdaki üçüncü taraf bileşenlerin hiçbirini içermez (bkz. `NOTICE`).

## Kurulum

```bash
bin/mic device list                      # USB mikrofon adayları
bin/mic device set <kaynak adı> --label "Mikrofonum"   # tek aday varsa: bin/mic device auto
python3 tools/plugins.py check           # eklentilerin özeti kilitle aynı mı
python3 tools/gen_conf.py                # PipeWire yapılandırmasını üret (~/.config/mic-hifi/mic-clean.conf)
python3 tools/install_units.py --install # systemd kullanıcı birimlerini bu deponun konumuyla kur
systemctl --user enable --now mic-clean mic-prio mic-console
bin/mic console                          # panel adresi (ilk açılış için kişisel anahtarla)
python3 tests/verify.py                  # canlı zincirde doğrulama
```

Panel: `http://127.0.0.1:8767/` (yalnız bu bilgisayardan erişilir). Uygulamalarda mikrofon olarak "<etiket> (temiz)" seçilir.
Kaldırma: `systemctl --user disable --now mic-clean mic-prio mic-console mic-main mic-watch`.

Sınamalar (kişisel kayıt gerektirmeyenler): `python3 tests/test_console_server.py`, `python3 tests/test_device.py`, `python3 tests/test_install.py`,
`python3 tests/test_plugins.py`, `python3 tests/test_measure.py`, `python3 tests/test_conf_load.py`, `python3 tests/test_tone.py --fast`.

## Sınırlar

- Yalnız PipeWire; PulseAudio ya da JACK tek başına desteklenmez.
- **Tek bir makinede (Fedora 44) ve tek bir mikrofonda ölçüldü.** Kurulum adımları temiz bir makinede baştan sona yürünmedi; başka dağıtımlarda eklenti yolları farklı olabilir (`LADSPA_PATH` desteklenir).
- Gürültü bastırıcı sürekli yaklaşık üçte bir işlemci çekirdeği kullanır. Bellek yoğun ağır bir iş (ör. derleme) aynı anda koşarsa kısa ses kesintileri olabilir; panel son 10 dakikadaki sayıyı gösterir.
- Ses ayarları ölçümle seçildi; **kulakla doğrulama kullanıcıya aittir** — karakterler ve perde kendi sesinde nasıl duyulur, sen karar verirsin.
- Arayüz Türkçedir.
- "Kalite" mikrofonu (`mic-main`, `mic-watch`) ve `bin/mic enhance` ayrı bir Python ortamı, bir NVIDIA ekran kartı ve kullanıcının kendi indireceği bir model (MossFormer2_SE_48K, Apache-2.0) ister; bu depoda model ya da ortam yoktur ve kurulumu burada belgelenmemiştir. Kullanmayacaksan o iki birimi etkinleştirme.
- Tasarım notları ve ölçüm günlükleri bu depoda yayımlanmadı; koddaki `docs/...` göndermeleri o notlara aittir.

## Lisans

Apache-2.0 (`LICENSE`). Çalışma anında kullanılan üçüncü taraf bileşenler ve lisansları: `NOTICE`. Güvenlik bildirimi: `SECURITY.md`. Katkı: `CONTRIBUTING.md`.

## English summary

mic-hifi turns a USB microphone into a processed **virtual microphone** on Linux/PipeWire: high-pass, automatic levelling (lifts whispering, freezes in silence),
compression, noise suppression (DeepFilterNet3), gate, tone presets, multiband dynamics, saturation and a limiter, controlled from a small local web panel
(`http://127.0.0.1:8767/`). Audio never leaves the machine. Third-party plugins are installed by the user and are not part of this repository (see `NOTICE`).
The panel and messages are in Turkish. It has been measured on one machine and one microphone only; the installation steps above have not yet been walked
through on a clean system. Licensed under Apache-2.0.

### Roadmap — what doing it unlocks

The cleaning chain and the panel were built by measurement and run live. The microphone itself (capsule, placement, in-device processing) and listener-side verification have not been broken down yet. Gains in the table are **expectations, not measured results**.

| layer | known today (done) | not done · untested · unknown | when done, it unlocks | method / source |
|---|---|---|---|---|
| **L1** acoustics: capsule, distance, room | Almost all noise is below 80 Hz; self-noise ~27 dB(A); 16 bit / ~17 kHz | Frequency response not measured (no reference mic) → no tone correction. Effect of mouth distance only calculated (~+15 dB, not measured). Room reverb not addressed | **Cheapest gain:** move the mic to 4–5 cm from the mouth (free). Once measured, tone can be flattened to sound like your own voice | 5-minute distance test; response measurement with a reference mic or known source |
| **L2** device: inside the USB mic | The device adjusts the ring-mic gain internally; its mute button shows in the panel | In-device automatic gain / processing not fully characterised. The vendor control channel is **intentionally not written to** | Device and chain stop "fighting" each other | Read-only measurement; no commands sent to the device |
| **L3** Linux / PipeWire / capture | Virtual microphone; a watchdog repairs profile drift; restart ~2.5 s | Under heavy multi-core load the noise suppressor can miss blocks (short dropouts) — **open**; root cause of profile drift not named | Dropout-free live use under load | Move the suppressor into a separate worker process (carrier design tested in isolation) + long soak run |
| **L4** cleaning chain | **Strong:** whisper SNR 8.6 → 27.1 dB; leveller, compressor, DeepFilterNet3, gate, split-band de-esser, dynamic EQ; output targets −23 / −16 LUFS, true peak ≤ −1 dBTP | Only Whisper mode passed its acceptance test; Normal and Night values not settled by measurement. No live mouth-click / crackle removal, no dereverb; echo cancellation tried but not wired in. Most settings not verified by ear | Near-studio delivery; echo cancellation for speaker calls | Test-set recording with your own voice (~20 min) + the panel's diagnostic recording |
| **L5** quality path (GPU) | Second, ~1 s delayed "quality" microphone live (MossFormer2); file enhancement (`mic enhance`); offline it beats DeepFilterNet (SNR 37.1 vs 30.7 dB) | Not verified by ear; setup not documented in this repo; not the main microphone | Cleaner sound for recording and streaming where latency does not matter | Setup documentation + listening test |
| **L6** voice character, pitch, conversion | 10 characters, intensity, your own characters; pitch (Rubber Band) | Formant not adjustable separately; AI voice conversion not done | Change your own voice colour; convert to another voice with AI | Open-source voice-conversion models (licence and latency measured) |
| **L7** panel, install, distribution | Panel, diagnostic recording, profiles; mic chosen with `mic device`; Apache-2.0; clean release tree | Install not walked end to end on a clean machine; setup wizard postponed; no English UI; no CI; DeepFilterNet mandatory | Others can install and use it on their own machine | Clean-machine/VM install walk + CI with synthetic signals |

**The ceiling you cannot pass.** The biggest quality gap is hardware: ~27 dB(A) self-noise and 16 bit / ~17 kHz. Software suppresses noise afterwards; a good microphone never produces it — software cannot close that gap. Realistic target: clean sound for calls and streaming; studio vocals are out of reach with this microphone.

**Open-source angle.** A whisper mode was found in none of the commercial products reviewed; the chain is fully local on PipeWire. Because the microphone is chosen with `mic device`, the method applies to other USB microphones too — even though only one has been measured.

**Plan:** the two biggest gains are still free: move the mic closer and record the test set. Then dropout-free live use (L3), then listening verification and documenting the quality path.

- [ ] **L1** distance measurement + frequency response
- [ ] **L2** characterise in-device gain (read-only)
- [ ] **L3** dropout-free under load (suppressor in a separate worker)
- [ ] **L4** settle Normal/Night by measurement; mouth clicks, echo cancellation
- [ ] **L5** quality-path setup docs + listening test
- [ ] **L6** formant + AI voice conversion
- [ ] **L7** clean-machine install walk, English UI, CI
