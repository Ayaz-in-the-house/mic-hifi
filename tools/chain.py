"""Mikrofon zincirinin TEK tanımı: kullanıcı durumu (state) → eklenti parametreleri.

Buradan üretilenler: PipeWire yapılandırması (gen_conf.py), çevrimdışı benzetim (chain_offline.py),
canlı ayar (console/server.py → pw-cli set-param) ve paneldeki kontroller.

Sıra (ölçümle belirlendi, docs/STATE.md): HPF → seviyeleyici (otomatik kazanç) → kompresör → gürültü bastırıcı → kapı → ton (EQ) → ıslık kısma → doygunluk → limitleyici.
Ton bastırıcıdan SONRA (bastırıcı giriş dağılımına duyarlı), limitleyiciden ÖNCE (EQ yükseltmesini tavan tutar).
Bastırıcı (DeepFilterNet) seviyeye duyarlı: fısıltı ~−24 dBFS'e yükseltilmeden verilirse neredeyse hiç bastırmıyor.
"""
import json, math, os

LADSPA_DIRS = ("/usr/lib64/ladspa", "/usr/lib/ladspa", "/usr/lib/x86_64-linux-gnu/ladspa", "/usr/local/lib64/ladspa", "/usr/local/lib/ladspa", "~/.ladspa")


def find_plugin(name, env=None, dirs=LADSPA_DIRS):
    """LADSPA eklentisinin tam yolu: önce LADSPA_PATH, sonra bilinen dizinler (dağıtıma göre değişir). Bulunamazsa çıplak ad döner
    (PipeWire kendi arama yoluyla dener; çevrimdışı araçlar açık hata verir)."""
    env = os.environ if env is None else env
    for d in [p for p in env.get("LADSPA_PATH", "").split(":") if p] + [os.path.expanduser(p) for p in dirs]:
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return name


LSP = find_plugin("lsp-plugins-ladspa.so")
PLUGIN_DIR = os.environ.get("MIC_PLUGIN_DIR") or os.path.expanduser("~/.local/lib/mic-hifi")   # kullanıcıya özel ikili eklentiler; özetleri plugins.lock.json'da (tools/plugins.py)
DF = os.path.join(PLUGIN_DIR, "libdeep_filter_ladspa.so")
RB = os.path.join(PLUGIN_DIR, "ladspa-rubberband.so")   # dağıtım paketinden kök gerektirmeden açılır (tools/install_rubberband.sh)
RB_LABEL = "rubberband-live-pitchshifter-mono"                          # ölçüm: 60,5 ms, formantı tam korur (klasik/ince motor 170,7 ms)
LSP_PREFIX = "http://lsp-plug.in/plugins/ladspa/"
CLEAN_SOURCE = "effect_output.mic_clean"
CONTROL_NODE = "effect_input.mic_clean"  # filter-chain parametreleri bu düğümün Props'unda yaşar
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mic-hifi")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
DEVICE_FILE = os.path.join(CONFIG_DIR, "device.json")       # {"source": "<PipeWire kaynak adı>", "label": "<görünen ad>"} — `mic device` yazar
CONF_FILE = os.path.join(CONFIG_DIR, "mic-clean.conf")      # ÜRETİLMİŞ PipeWire yapılandırması (ev dizini ve aygıt adı içerir → depoda izlenmez)
SOURCE_UNSET = "alsa_input.MIKROFON_AYARLANMADI"            # aygıt seçilmemiş: `mic device auto` ya da `mic device set <ad>`


def _device():
    """Aygıt ayarı: MIC_SOURCE ortam değişkeni > device.json > ayarlanmadı. İçe aktarmada alt süreç ÇAĞRILMAZ (keşif ayrı: discover_sources)."""
    try:
        d = json.load(open(DEVICE_FILE, encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    src = os.environ.get("MIC_SOURCE") or d.get("source")
    src = src if isinstance(src, str) and src.strip() else None
    label = d.get("label") if isinstance(d.get("label"), str) and d.get("label").strip() else "Mikrofon"
    return (src or SOURCE_UNSET), bool(src), label.strip()


RAW_SOURCE, SOURCE_SET, DEVICE_LABEL = _device()


def discover_sources(pactl_json):
    """`pactl -f json list sources` çıktısından USB mikrofon adayları. Dönüş: (seçim | None, adaylar). Yalnız TEK aday varsa seçilir:
    birden çok USB girişi varken tahmin etmek yanlış mikrofonu sessizce bağlar. İzleme (monitor) kaynakları ve USB olmayan girişler aday değildir."""
    try:
        names = [s.get("name", "") for s in json.loads(pactl_json)]
    except (ValueError, AttributeError, TypeError):
        return None, []
    cands = sorted(n for n in names if isinstance(n, str) and n.startswith("alsa_input.usb-") and not n.endswith(".monitor"))
    return (cands[0] if len(cands) == 1 else None), cands

HPF_HZ = 95.0
HPF_Q = (0.5412, 1.3066)  # 4. derece Butterworth; SABİT (bq_* canlı değişirse filtre belleği sıfırlanır → tık)

# Paneldeki kontroller: (anahtar, tür, en az, en çok, adım, varsayılan)
CONTROLS = [
    # ── seviyeleyici (kazancı o sürer; kompresörden AYRI — landscape/L2, PRD-QUALITY A2.1) ──
    ("auto_on", "bool", 0, 1, 1, True),
    ("auto_target", "range", -36, -16, 1, -26),     # hedef yükseklik (LUFS)
    ("auto_max_db", "range", 0, 42, 1, 30),         # en çok yükseltme: fısıltı ne kadar kaldırılsın
    ("auto_silence", "range", -72, -40, 1, -54),    # bunun altı "sessizlik": kazanç DONAR (taban pompalanmaz)
    ("boost_db", "range", 0, 36, 1, 0),             # elle ek yükseltme (eski tasarımın ana kazancıydı; artık varsayılan 0)
    ("level_on", "bool", 0, 1, 1, True),            # ses dengeleme (yüksek sesi kıs)
    ("level_thresh_db", "range", -40, -10, 1, -24),
    ("level_ratio", "range", 1.5, 20, 0.5, 3),      # endüstri pratiği 2–4:1; farkı kapatmak seviyeleyicinin işi
    ("denoise_on", "bool", 0, 1, 1, True),
    ("denoise_db", "range", 6, 60, 1, 40),
    ("gate_on", "bool", 0, 1, 1, False),            # sessizlik kapısı: söz aralarındaki nefes/klavye
    ("gate_thresh_db", "range", -60, -25, 1, -45),
    ("gate_depth_db", "range", 6, 40, 1, 12),
    ("limit_on", "bool", 0, 1, 1, True),
    ("out_db", "range", -12, 12, 0.5, 5),           # zincirin sonunda, tavandan hemen önce
    # ── çıkış hedefi (ikinci eksen): 0 = Görüşme (−23 LUFS), 7 = Yayın (−16 LUFS); tavanın girişinde çıkış kazancına eklenir (A2.5) ──
    ("loud_db", "range", 0, 7, 0.5, 0),
    # ── perde ve ses yolu (ikinci eksen; Aşama 5a). pitch_on YAPISAL: eklentide bypass yok ve 0 yarım tonda da 60 ms gecikme ekler →
    #    düğüm yalnız açıkken grafikte olur, açma/kapama zinciri yeniden başlatır. Yarım ton ve koruma canlı değişir. ──
    ("pitch_on", "bool", 0, 1, 1, False),
    ("pitch_st", "range", -6, 6, 0.5, 0),           # yarım ton
    ("pitch_formant", "bool", 0, 1, 1, True),       # ses yolunu koru: açık = aynı kişi daha kalın/ince · kapalı = daha iri/ufak kişi
    ("pitch_mute", "bool", 0, 1, 1, False),         # fısıltı modları açar: düğüm kalır, kuru geçer (perdesiz sese kaydırma yalnız bozar; yeniden başlatma olmaz)
    # ── ton karakteri (ikinci eksen: moddan bağımsız) ──
    ("tone_on", "bool", 0, 1, 1, True),
    ("tone_hp_hz", "range", 20, 500, 5, 20),        # alt kesim (telefon/megafon etkisi)
    ("tone_low_db", "range", -12, 12, 0.5, 0),      # gövde: alt raf 200 Hz (ölçüm: 120 Hz rafı bu seste +6 dB'in yalnız +2'sini veriyordu)
    ("tone_mud_db", "range", -12, 12, 0.5, 0),        # bulanıklık: 250 Hz
    ("tone_box_db", "range", -12, 12, 0.5, 0),        # kutu sesi: 500 Hz
    ("tone_nasal_db", "range", -12, 12, 0.5, 0),      # genizden: 1,4 kHz
    ("tone_pres_db", "range", -12, 12, 0.5, 0),       # netlik: 3,5 kHz
    ("tone_air_db", "range", -12, 12, 0.5, 0),        # hava: üst raf 10 kHz
    ("tone_lp_hz", "range", 2000, 22000, 100, 22000),   # üst kesim
    ("deess_on", "bool", 0, 1, 1, False),           # ıslık kısma — fısıltıyı da kısar (ölçüldü: −4,9 dB) → fısıltı/gece/ham modlarında kapalı
    ("deess_thresh_db", "range", -50, -24, 1, -36),
    # Dinamik EQ (A2.4): yalnız AŞINCA kısar; sessiz/orta seste ton değişmez. Eşikler referans konuşmada ölçüldü (PRD-QUALITY A2.4).
    ("dyn_body_on", "bool", 0, 1, 1, False),        # dolgunluk: 200 Hz altı yoğunluk (zayıf heceyi kaldırır, güçlüyü bırakır) — A2.6b
    ("dyn_body_db", "range", 0, 9, 0.5, 6),         # telafi: zayıf alt bant en çok bu kadar yükselir
    ("dyn_mud_on", "bool", 0, 1, 1, False),         # şişme: 200–450 Hz (yakınlık etkisi + oda). Fısıltı bu bantta eşiğe ulaşmaz (p99 −40,8 dBFS)
    ("dyn_mud_db", "range", -40, -15, 1, -27),
    ("dyn_harsh_on", "bool", 0, 1, 1, False),       # sertlik: 2–5 kHz. Fısıltı bu bantta normalden YÜKSEK → fısıltı/gece/ham modlarında kapalı
    ("dyn_harsh_db", "range", -45, -20, 1, -33),
    ("sat_on", "bool", 0, 1, 1, False),             # doygunluk (yumuşak kırpma): megafon/telsiz sertliği
    ("sat_db", "range", 0, 24, 1, 8),
]
CEILING_DB = -1.2
# Çıkış hedefleri (A2.5). Ölçüm (referans, Normal mod): normal konuşma ≈ seviyeleyici hedefi (−26) + çıkış kazancı (+5) + loud_db − 2,1 LU.
LOUD_TARGETS = {"gorusme": {"lufs": -23, "loud_db": 0.0}, "yayin": {"lufs": -16, "loud_db": 7.0}}
DEESS_HZ = 5000.0
DYN_BODY_THRESH_DB = -40.0
DYN_SPLITS = (200.0, 450.0, 2000.0, DEESS_HZ)   # çok bantlı dinamik katmanın geçiş frekansları
# Kırpma eşiği = SAT_BASE_DB − sat_db. Eğri yumuşak (sigmoid 1): eşiğin ~10 dB altında bükülmeye başlar (ölçüldü: −8 dB'de THD %0,7, −2 dB'de %3,8).
# Doygunluk girişinde konuşma p99 ≈ −17,4 dBFS (ölçüldü 2026-10-11; çıkış kazancı tavana taşınmadan önce ≈ −15 idi) → taban eşik seviyeyle
# birlikte −4'ten −6,5'e indi: karakterlerin sürüşü konuşmaya göre AYNI kalır. Sürüş 0'da pratikte temiz, 24'te (eşik −30,5) ağır.
# ⚠ Doygunluk seviyeye bağlıdır: girişindeki seviyeyi değiştiren her zincir değişikliğinden sonra T-V1b-4 yeniden koşulur.
SAT_BASE_DB = -6.5
# Sürüşe göre ses yüksekliği kaybı (dB), referans konuşmada ölçüldü 2026-10-10, yeni tabanla 2026-10-11 doğrulandı → çıkışta telafi edilir.
SAT_LOSS = [(0, 0.0), (6, 0.2), (10, 0.61), (13, 1.19), (16, 2.10), (19, 3.39), (22, 5.02), (24, 6.3)]
TONE_LP_MAX = 22000.0
TONE_SLOPE = 1  # kesim süzgeçlerinin eğimi (LSP "x2")

# EQ bantları: (LSP süzgeç türü, frekans [sabit Hz ya da kontrol anahtarı], kazanç anahtarı, Q). TÜRLER SABİT: canlıda tür değişimi tık üretir.
# Q ölçüldü (2026-10-10): kesim ve raflarda 0,5 düz geçiş verir (0 → 60 Hz'te −1,8 dB sarkma; 0,707 → +0,5 dB tümsek).
# Tür numaraları ölçüldü (docs/research/L): 1 çan · 2 yüksek geçiren · 3 üst raf · 4 alçak geçiren · 5 alt raf.
TONE_BANDS = [
    (2, "tone_hp_hz", None, 0.5),
    (5, 200.0, "tone_low_db", 0.5),
    (1, 250.0, "tone_mud_db", 1.2),
    (1, 500.0, "tone_box_db", 1.2),
    (1, 1400.0, "tone_nasal_db", 1.2),
    (1, 3500.0, "tone_pres_db", 1.0),
    (3, 10000.0, "tone_air_db", 0.5),
    (4, "tone_lp_hz", None, 0.5),
]

# Ses karakterleri: yalnız ton anahtarları. Başlangıç değerleri — kulakla doğrulanınca güncellenir.
_FLAT = {"tone_hp_hz": 20, "tone_low_db": 0, "tone_mud_db": 0, "tone_box_db": 0, "tone_nasal_db": 0, "tone_pres_db": 0, "tone_air_db": 0,
         "tone_lp_hz": 22000, "sat_on": False, "sat_db": 8, "pitch_on": False, "pitch_st": 0, "pitch_formant": True}
CHARACTERS = {
    "notr": dict(_FLAT),
    # Değerler referans konuşmada ölçülerek kuruldu (2026-10-11, tests/test_characters.py): "orta"da yükseklik eşitlenmiş en büyük bant farkı
    # ≥ 3 dB (duyulur), "en güçlü"de (× 2) ≥ 6 dB. Önceki tablo ortada 0,8–2,8 dB veriyordu: fark duyulmuyordu.
    "sicak": {**_FLAT, "tone_low_db": 5.5, "tone_box_db": -1.5, "tone_nasal_db": -2, "tone_pres_db": -2.5, "tone_air_db": -2.5},
    "parlak": {**_FLAT, "tone_low_db": -2.5, "tone_mud_db": -3, "tone_pres_db": 4, "tone_air_db": 5},
    "radyo": {**_FLAT, "tone_low_db": 5, "tone_mud_db": -4, "tone_box_db": -3, "tone_pres_db": 4, "tone_air_db": 3},
    "derin": {**_FLAT, "tone_low_db": 7, "tone_mud_db": 3, "tone_nasal_db": -2.5, "tone_pres_db": -2, "tone_air_db": -3},
    "yakin": {**_FLAT, "tone_low_db": 4, "tone_box_db": -3, "tone_nasal_db": -2, "tone_pres_db": 3, "tone_air_db": 8},
    # Perdeyi kullanan karakterler (Aşama 5b; ölçüm PRD-VOICE): seçmek/çıkmak YAPISALDIR (zincir 2–3 sn yeniden başlar); fısıltı modlarında perde kuru geçer.
    "kalin": {**_FLAT, "pitch_on": True, "pitch_st": -2, "pitch_formant": True, "tone_low_db": 4, "tone_mud_db": 2, "tone_nasal_db": -1.5, "tone_pres_db": -1, "tone_air_db": -2},
    "iri": {**_FLAT, "pitch_on": True, "pitch_st": -3, "pitch_formant": False},
    "telefon": {**_FLAT, "tone_hp_hz": 300, "tone_lp_hz": 3400, "tone_pres_db": 3},
    "megafon": {**_FLAT, "tone_hp_hz": 400, "tone_lp_hz": 3000, "tone_nasal_db": 3, "tone_pres_db": 5, "sat_on": True, "sat_db": 18},
}
TONE_KEYS = tuple(_FLAT)

# Karakter yoğunluğu: tablo "orta"dır; kazançlar çarpılır, kesim frekansları düz konumdan hedefe logaritmik yürür, doygunluk sürüşü çarpılır.
AMOUNTS = {"hafif": 0.5, "orta": 1.0, "guclu": 1.5, "cok": 2.0}


def scaled_character(name, amount="orta"):
    f, flat, out = AMOUNTS[amount], CHARACTERS["notr"], {}
    for k, v in CHARACTERS[name].items():
        if k in ("tone_hp_hz", "tone_lp_hz"):
            v = flat[k] * (v / flat[k]) ** f
        elif k == "sat_db":
            v = v * f if CHARACTERS[name]["sat_on"] else v
        elif k == "pitch_st":
            v = v * f
        elif k.endswith("_db"):
            v = v * f
        out[k] = v
    return clamp(out)
# İkinci eksen: mod ön ayarlarının dokunmadığı, oynanınca modu "özel"e düşürmeyen anahtarlar.
AXIS2 = tuple(k for k, *_ in CONTROLS if k.startswith(("tone_", "sat_", "deess_", "dyn_", "loud_", "pitch_")))
DEFAULT_STATE = {k: d for k, _t, _lo, _hi, _st, d in CONTROLS}

# Modlar: seviyeleyicinin en çok kazancı ve sessizlik eşiği değişir; kompresör hep hafif (3:1). Değerler referans kayıtta ölçüldü (2026-10-11).
_MODE = {"auto_on": True, "auto_target": -26, "boost_db": 0, "level_on": True, "level_thresh_db": -24, "level_ratio": 3, "denoise_on": True,
         "denoise_db": 40, "gate_on": False, "limit_on": True, "out_db": 5, "pitch_mute": False}   # +5 dB: çıkış yüksekliği hedefe yaklaşsın (ölçüm PRD-QUALITY A2)
PRESETS = {
    "normal": {**_MODE, "auto_max_db": 18, "auto_silence": -50},
    "fisilti": {**_MODE, "auto_max_db": 30, "auto_silence": -54, "deess_on": False, "dyn_harsh_on": False, "dyn_body_on": False, "pitch_mute": True},
    # Sessizlik eşiği oda gürültüsünün (süzgeçten sonra −60 LUFS, ölçüldü) ÜSTÜNDE kalmalı: −60'ta kazanç sessizlikte +34 dB'e tırmandı (C5).
    # Gece'nin farkı yalnız en çok kazançtır; daha düşük eşik ancak daha sessiz oda/yakın mikrofonla olur (kalibrasyon sihirbazı, Aşama 6).
    "gece": {**_MODE, "auto_max_db": 36, "auto_silence": -54, "deess_on": False, "dyn_harsh_on": False, "dyn_body_on": False, "pitch_mute": True},
    "ham": {"auto_on": False, "boost_db": 0, "level_on": False, "denoise_on": False, "gate_on": False, "limit_on": True, "out_db": 0, "deess_on": False, "dyn_harsh_on": False, "dyn_body_on": False, "pitch_mute": True},
}


def clamp(patch):
    """Bilinmeyen anahtarı reddeder, değeri aralığa ve adıma oturtur."""
    spec = {k: (t, lo, hi, st) for k, t, lo, hi, st, _d in CONTROLS}
    out = {}
    for k, v in patch.items():
        if k not in spec:
            raise KeyError(k)
        t, lo, hi, st = spec[k]
        if t == "bool":
            if not isinstance(v, bool):
                raise ValueError(k)
            out[k] = v
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise ValueError(k)
            v = min(hi, max(lo, float(v)))
            out[k] = round(round((v - lo) / st) * st + lo, 3)
    return out


def load_state(path=None):
    s = dict(DEFAULT_STATE)
    try:
        d = json.load(open(path or STATE_FILE, encoding="utf-8"))
        if "auto_on" not in d and "boost_db" in d:   # seviyeleyiciden önceki kayıt: eski ses AYNEN korunur (çift kazanç olmasın)
            d = {"auto_on": False, **d}
        # Kayıt, sonradan eklenen bir mod anahtarını içermiyorsa (ör. pitch_mute) kaydın modundan doldurulur; yoksa "Fısıltı modundayım ama
        # fısıltı kuralı uygulanmıyor" durumu oluşur (yaşandı 2026-10-11). Kayıtta OLAN hiçbir değere dokunulmaz.
        base = d.get("_base") if d.get("_base") in PRESETS else d.get("_mode")
        if base in PRESETS:
            s.update({k: v for k, v in PRESETS[base].items() if k not in d})
        s.update(clamp({k: v for k, v in d.items() if k in DEFAULT_STATE}))
    except (OSError, ValueError, KeyError):
        pass
    return s


def lin(db):
    return 10 ** (db / 20)


def sat_makeup_db(drive):
    for (d0, l0), (d1, l1) in zip(SAT_LOSS, SAT_LOSS[1:]):
        if drive <= d1:
            return l0 + (l1 - l0) * (max(drive, d0) - d0) / (d1 - d0)
    return SAT_LOSS[-1][1]


def _load_tone_model():
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tone_model.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


TONE_MODEL = _load_tone_model()   # tools/gen_tone_model.py üretir; yoksa telafi 0


def tone_trim_db(s):
    """Ton kazançlarının konuşmada yaratacağı ses yüksekliği değişimi (LU, model). EQ çıkışında geri alınır: karakter tonu değiştirir, yüksekliği değil.
    Model: her bandın ölçülmüş yanıtı (0/±6/±12 dB'de, 1/6 oktav ızgara) kazanca göre aradeğerlenir, dB olarak toplanır, konuşma spektrumu
    (K ağırlıklı) ile ağırlıklanır. Kesim süzgeçleri (telefon/megafon) modele girmez: bant daraltmanın sessizleştirmesi etkinin parçasıdır."""
    m = TONE_MODEL
    if not m or not s.get("tone_on", True):
        return 0.0
    n = len(m["weights"])
    tot = [0.0] * n
    for key, curves in m["bands"].items():
        g = float(s.get(key, 0.0))
        if not g:
            continue
        lo, hi = (curves["6"], curves["12"]) if g > 0 else (curves["-6"], curves["-12"])
        a = abs(g)
        for i in range(n):
            tot[i] += lo[i] * a / 6 if a <= 6 else lo[i] + (hi[i] - lo[i]) * (a - 6) / 6
    p = sum(w * 10 ** (t / 10) for w, t in zip(m["weights"], tot))
    return max(-9.0, min(9.0, 10 * math.log10(p))) if p > 0 else 0.0


def _tone_controls(s):
    # LSP anahtar portları AÇIKÇA yazılır: LADSPA ipucu varsayılanına güvenilmez (docs/research/L).
    c = {"Bypass": 0 if s["tone_on"] else 1, "Input gain (G)": 1.0, "Output gain (G)": lin(-tone_trim_db(s)), "Equalizer mode": 0}
    for i, (typ, freq, gkey, q) in enumerate(TONE_BANDS):
        c[f"Filter type {i}"] = typ
        c[f"Filter mode {i}"] = 0
        c[f"Filter slope {i}"] = TONE_SLOPE if typ in (2, 4) else 0
        c[f"Filter solo {i}"] = 0
        c[f"Filter mute {i}"] = 0
        c[f"Frequency {i} (Hz)"] = float(s[freq]) if isinstance(freq, str) else freq
        c[f"Gain {i} (G)"] = lin(s[gkey]) if gkey else 1.0
        c[f"Quality factor {i}"] = q
    return c


def nodes(state=None):
    """(ad, .so, etiket, giriş portu, çıkış portu, kontroller, gerçek-zaman temposu ister mi)"""
    s = {**DEFAULT_STATE, **(state or {})}
    return [
        ("auto", LSP, LSP_PREFIX + "autogain_mono", "Input", "Output", {
            "Bypass": 0 if s["auto_on"] else 1,
            "Sidechain preamp (dB)": 0.0, "Sidechain lookahead (ms)": 20.0, "Sidechain mode": 0, "Weighting function": 5,
            "Desired loudness level (LUFS)": float(s["auto_target"]),
            "Level drift (dB)": 12.0,
            "The level of silence (LUFS)": float(s["auto_silence"]),
            "Enable maximum amplification gain limitation": 1,
            "The maximum amplification gain (dB)": float(s["auto_max_db"]),
            "Enable quick amplifier": 1,
            "Long gain grow amount": 6.0, "Long gain grow time (ms)": 300.0, "Long gain fall amount": 6.0, "Long gain fall time (ms)": 100.0,
            "Short gain grow amount": 6.0, "Short gain grow time (ms)": 50.0, "Short gain fall amount": 6.0, "Short gain fall time (ms)": 5.0,
        }, False),
        ("level", LSP, LSP_PREFIX + "compressor_mono", "Input", "Output", {
            "Input gain (G)": lin(s["boost_db"]),
            "Compression mode": 0,               # aşağı sıkıştırma
            "Attack threshold (G)": lin(s["level_thresh_db"]),
            "Ratio": float(s["level_ratio"]) if s["level_on"] else 1.0,   # kapalı = oran 1 (yükseltme yine geçer)
            "Knee (G)": 0.5,
            "Attack time (ms)": 3.0,             # 3 ms + 10 ms ileri bakış: seviyeleyici yüksek kazançtayken gelen yüksek ses −1 dBFS'i aşmıyor
            "Release time (ms)": 150.0,          # (ölçüldü 2026-10-11: 5 ms/5 ms → +0,02 dBFS ve 1 örnek taşma; 3 ms/10 ms → −1,11 dBFS, 0)
            "Sidechain lookahead (ms)": 10.0,
            "Sidechain reactivity (ms)": 10.0,
            "Makeup gain (G)": 1.0,              # çıkış kazancı BURADA DEĞİL: bastırıcının girişini taşırır (ölçüldü: 1,57 = +3,9 dBFS)
        }, False),
        ("denoise", DF, "deep_filter_mono", "Audio In", "Audio Out", {
            "Attenuation Limit (dB)": float(s["denoise_db"]) if s["denoise_on"] else 0.0,   # 0 = birebir geçiş (ölçüldü)
        }, True),
        ("gate", LSP, LSP_PREFIX + "gate_mono", "Input", "Output", {
            "Bypass": 0 if s["gate_on"] else 1,
            "Curve threshold (G)": lin(s["gate_thresh_db"]),
            "Curve zone size (G)": 0.5,          # 6 dB yumuşak geçiş
            "Reduction (G)": lin(-s["gate_depth_db"]),   # tam susturma YOK: fısıltının kuyruğu kesilmesin
            "Sidechain lookahead (ms)": 5.0,
            "Attack (ms)": 5.0,
            "Release (ms)": 180.0,
            "Hold time (ms)": 120.0,
        }, False),
        *([("pitch", RB, RB_LABEL, "Input", "Output", {
            "Cents": 0.0, "Semitones": float(s["pitch_st"]), "Octaves": 0.0, "Formant Preserving": 1.0 if s["pitch_formant"] else 0.0,
            "Wet-Dry Mix": 1.0 if (s["pitch_mute"] or not s["pitch_st"]) else 0.0,   # 1 = kuru (ölçüldü): 0 yarım tonda ve fısıltı modlarında sese dokunmaz
        }, False)] if s["pitch_on"] else []),
        ("tone", LSP, LSP_PREFIX + "para_equalizer_x8_mono", "Input", "Output", _tone_controls(s), False),
        # Çok bantlı dinamik katman: şişme (200–450 Hz) · sertlik (2–5 kHz) · ıslık (5 kHz üstü). Yalnız o bant kısılır; "s" anında sesin
        # gövdesi çökmez (tek bantlı sürümde −9 dB çöküyordu, ölçüldü). Bantlar: 0 <200 · 1 200–450 · 2 450–2000 · 3 2–5 k · 4 >5 k.
        # Kip 0 = klasik IIR geçiş (doğrusal fazlı kip 87 ms gecikme ekler). "Envelope boost" KAPALI: açıkken dedektöre pembe telafi ekler,
        # aynı eşikte −8 yerine −20 dB kısar. Spektrum çizimleri kapalı (işlemci). Kullanılmayan bantlar açıkça kapatılır.
        ("dyn", LSP, LSP_PREFIX + "mb_compressor_mono", "Input", "Output", {
            "Bypass": 0 if (s["deess_on"] or s["dyn_mud_on"] or s["dyn_harsh_on"] or s["dyn_body_on"]) else 1,
            "Compressor mode": 0, "Envelope boost": 0,
            "Input gain (G)": 1.0, "Output gain (G)": 1.0, "Dry gain (G)": 0.0, "Wet gain (G)": 1.0, "Dry/Wet balance (%)": 100.0,
            "Input FFT graph enable": 0, "Output FFT graph enable": 0, "Band filter curves": 0,
            **{f"Compression band enable {k}": 1 for k in range(1, 5)}, **{f"Compression band enable {k}": 0 for k in range(5, 8)},
            **{f"Split frequency {k} (Hz)": f for k, f in zip(range(1, 5), DYN_SPLITS)},
            **{f"{n} {k}": 0 for k in range(5) for n in ("Solo band", "Mute band")}, **{f"Makeup gain {k} (G)": 1.0 for k in range(5)},
            **{f"{n} {k}{u}": v for k in (0, 1, 3, 4) for n, u, v in (("Compression mode", "", 0), ("External sidechain source", "", 0), ("Sidechain mode", "", 1),
               ("Sidechain lookahead", " (ms)", 2.0), ("Sidechain preamp", " (G)", 1.0), ("Sidechain custom lo-cut", "", 0), ("Sidechain custom hi-cut", "", 0),
               ("Hold time", " (ms)", 0.0), ("Knee", " (G)", 0.5))},
            "Compressor enable 2": 0,
            # Dolgunluk: aşağı kompresyon + telafi (ölçüm: yukarı kip sessizlikte tabanı +19 dB kaldırıyor; kırpıcıyla harmonik üretme etkisiz + 38 ms)
            "Compressor enable 0": 1 if s["dyn_body_on"] else 0, "Attack threshold 0 (G)": lin(DYN_BODY_THRESH_DB), "Makeup gain 0 (G)": lin(s["dyn_body_db"]),
            "Ratio 0": 3.0, "Attack time 0 (ms)": 5.0, "Release time 0 (ms)": 60.0, "Sidechain reactivity 0 (ms)": 5.0,   # ölçüm: 15/150 ms yayılmayı 3,6, 5/60 ms 4,3 dB daraltır
            "Compressor enable 1": 1 if s["dyn_mud_on"] else 0, "Attack threshold 1 (G)": lin(s["dyn_mud_db"]),
            "Ratio 1": 2.0, "Attack time 1 (ms)": 10.0, "Release time 1 (ms)": 120.0, "Sidechain reactivity 1 (ms)": 10.0,
            "Compressor enable 3": 1 if s["dyn_harsh_on"] else 0, "Attack threshold 3 (G)": lin(s["dyn_harsh_db"]),
            "Ratio 3": 2.5, "Attack time 3 (ms)": 3.0, "Release time 3 (ms)": 80.0, "Sidechain reactivity 3 (ms)": 5.0,
            "Compressor enable 4": 1 if s["deess_on"] else 0, "Attack threshold 4 (G)": lin(s["deess_thresh_db"]),
            "Ratio 4": 4.0, "Attack time 4 (ms)": 1.0, "Release time 4 (ms)": 60.0, "Sidechain reactivity 4 (ms)": 3.0,
        }, False),
        ("sat", LSP, LSP_PREFIX + "clipper_mono", "Input", "Output", {
            "Bypass": 0 if s["sat_on"] else 1,
            "Input gain (G)": 1.0,
            "Output gain (G)": lin(sat_makeup_db(s["sat_db"])),
            "Enable input LUFS limitation": 0,   # varsayılanı AÇIK: açık kalırsa girişi kendi kafasına göre kısar
            "Overdrive protection": 0,
            "Clipper enable": 1,
            "Clipper sigmoid function": 1,
            "Clipper sigmoid threshold (G)": 0.25,
            "Clipper DC offset (%)": 0.0, "Clipper DC compensate": 1, "Clipper sigmoid pumping (dB)": 0.0,
            "Clipping threshold (dB)": SAT_BASE_DB - float(s["sat_db"]),
            "Boosting mode": 0, "Dithering mode": 0,
        }, False),
        ("limit", LSP, LSP_PREFIX + "limiter_mono", "Input", "Output", {
            "Bypass": 0 if s["limit_on"] else 1,
            "Input gain (G)": lin(s["out_db"] + s["loud_db"]),  # çıkış yüksekliği + hedef: zincirin EN SONUNDA (tavan kapalıysa uygulanmaz)
            "Threshold (G)": lin(CEILING_DB),    # −1,2 dBFS + aşırı örnekleme → gerçek tepe ≤ −1 dBTP (ölçüldü: −1 dBFS eşikte +12 dB sürüşte −0,84 dBTP)
            "Oversampling": 9,                   # ölçüldü: kip 9 gerçek tepeyi örnek tepesine eşitler, ek gecikme 20 örnek
            "Gain boost": 0,                     # tavana kadar otomatik yükseltme YOK (gürültüyü pompalar)
            "Automatic level regulation": 0,
            "Lookahead (ms)": 5.0,
        }, False),
    ]


LIVE_KEYS = {"pitch": ("Semitones", "Formant Preserving", "Wet-Dry Mix"),
             "auto": ("Bypass", "Desired loudness level (LUFS)", "The level of silence (LUFS)", "The maximum amplification gain (dB)"),
             "level": ("Input gain (G)", "Attack threshold (G)", "Ratio"), "denoise": ("Attenuation Limit (dB)",),
             "gate": ("Bypass", "Curve threshold (G)", "Reduction (G)"), "limit": ("Bypass", "Input gain (G)"),
             "dyn": ("Bypass", "Compressor enable 0", "Makeup gain 0 (G)", "Compressor enable 1", "Attack threshold 1 (G)", "Compressor enable 3", "Attack threshold 3 (G)", "Compressor enable 4", "Attack threshold 4 (G)"), "sat": ("Bypass", "Clipping threshold (dB)", "Output gain (G)"),
             "tone": ("Bypass", "Output gain (G)") + tuple(f"Gain {i} (G)" for i, b in enumerate(TONE_BANDS) if b[2])
                     + tuple(f"Frequency {i} (Hz)" for i, b in enumerate(TONE_BANDS) if isinstance(b[1], str))}


def live_params(state):
    """Çalışırken değiştirilen parametreler: {"düğüm:Port": değer}. Bypass = bool, diğerleri float."""
    out = {}
    for name, _so, _label, _i, _o, ctl, _rt in nodes(state):
        for port in LIVE_KEYS[name]:
            v = ctl[port]
            out[f"{name}:{port}"] = bool(v) if port == "Bypass" else float(v)
    return out


NODES = nodes()  # varsayılan durumla (geri uyum)
