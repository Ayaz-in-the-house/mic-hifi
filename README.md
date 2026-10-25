<p align="center"><img src="assets/icon.svg" width="96" alt="mic-hifi"></p>

# mic-hifi

USB mikrofonun sesini PipeWire üzerinde katman katman işleyip **sanal bir mikrofon** olarak sunan yerel bir sistem ve onu yöneten küçük bir web paneli.
Ses bilgisayarından çıkmaz; bulut yok, hesap yok.

Zincir: alt kesim (95 Hz) → seviyeleyici (fısıltıyı yükseltir, sessizlikte donar) → kompresör → gürültü bastırma (DeepFilterNet3) → sessizlik kapısı →
ton (8 bantlı dengeleyici, hazır karakterler) → çok bantlı dinamik (dolgunluk, şişme, sertlik, ıslık) → doygunluk → tavan sınırlayıcı.
İsteğe bağlı: perde/ses yolu kaydırma ve ikinci, gecikmeli bir "kalite" mikrofonu (ekran kartında çalışan daha güçlü bir gürültü giderici).

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
