# Katkı

- Zincirin tek tanımı `tools/chain.py` dosyasıdır; PipeWire yapılandırması ondan üretilir (`tools/gen_conf.py`), elle düzenlenmez.
- Bir değişiklikten önce ne sınanacağını yaz, testi kırmızı gör, sonra kodu yaz. Göndermeden önce: `python3 tests/test_console_server.py`,
  `python3 tests/test_device.py`, `python3 tests/test_install.py`, `python3 tests/test_plugins.py`, `python3 tests/test_oss_audit.py`.
- Kişisel veri (aygıt seri numarası, ev dizini yolu, e-posta, ağ adresi) ve ses/ağırlık dosyası göndermeyin: `python3 tools/oss_audit.py` temiz olmalı.
- Bağımlılıklar sabit sürümle (`==`) eklenir. Katkılar Apache-2.0 ile lisanslanır.
