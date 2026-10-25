#!/usr/bin/env python3
"""Mikrofon Konsolu — yerel panel sunucusu (yalnız 127.0.0.1, yalnız stdlib).

  GET  /                 panel
  GET  /api/state        durum + kontrol tanımları + hazır modlar + profiller + servis/dinleme durumu
  POST /api/state        {"patch": {...}}            canlıya uygular + kaydeder
  POST /api/preset       {"id": "fisilti" | "user:<ad>"}
  POST /api/loudness     {"target": "gorusme" | "yayin"}   çıkış yükseklik hedefi (ikinci eksen; mod değişmez)
  POST /api/character    {"id": "sicak" | "user:<ad>", "amount": "hafif|orta|guclu|cok"} | {"save": "<ad>"} | {"delete": "<ad>"}   ses karakteri (yalnız ton; mod değişmez)
  POST /api/profile      {"save": "<ad>"} | {"delete": "<ad>"}
  POST /api/monitor      {"mode": "off" | "temiz" | "ham"}
  POST /api/diag         {"action": "record", "step": "sessiz|aaa|ptk|fisilti"} | {"action": "delete"}   (teşhis kaydı: ham mikrofon, yerel)
  POST /api/audition     {"action": "record", "seconds": 3..20} | {"action": "play", "id": "<karakter>|current|off"} | {"action": "stop"}
  GET  /api/delivery[?id=<karakter>|current|off]   kaydın teslim ölçüleri: ses yüksekliği, gerçek tepe, taban, tık (çevrimdışı)
  POST /api/trial        {"seconds": 3..20}          kaydet ve dinle (ham, sonra işlenmiş)
  GET  /api/meter        SSE: giriş/çıkış seviyesi (yalnız bağlı istemci varken ölçer)

Güvenlik: yalnız loopback · Host başlığı denetimi (DNS rebinding) · POST'ta özel başlık + JSON (CSRF) · gövde sınırı ·
kimlik: 0600 izinli anahtar dosyası → sayfa `/#k=<anahtar>` ile bir kez açılır (parça sunucuya GİTMEZ) → anahtar sayfanın
localStorage'ında durur (köken = şema+ana makine+PORT) → her API isteği `X-Mic-Key` başlığı taşır. ÇEREZ KULLANILMAZ: çerez porta
göre yalıtılmaz, 127.0.0.1'deki başka her yerel servise de gönderilirdi. Sayfanın kendisi sır içermez, anahtarsız sunulur.
Kaynak: seviye ölçer yalnız sayfa açıkken koşar; sayfa kapanınca kayıtçılar kapanır.
MIC_DRY=1 → canlı grafiğe dokunmaz (test).
"""
import array, atexit, hmac, json, math, os, re, secrets, shutil, signal, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import chain
import gen_conf

RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
ENV = dict(os.environ, XDG_RUNTIME_DIR=RUN)
DRY = os.environ.get("MIC_DRY") == "1"
PROFILE_DIR = os.path.join(os.path.dirname(chain.STATE_FILE), "profiles")
PAGE = os.path.join(ROOT, "console", "index.html")
I18N = {lang: os.path.join(ROOT, "console", "i18n", lang + ".json") for lang in ("en", "tr")}   # arayüz sözlükleri (D50): sayfaya gömülür, ayrı uç yok
MIC = os.path.join(ROOT, "bin", "mic")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_BODY = 16 * 1024
MAX_METER_CLIENTS = 4
MAX_PROFILES = 50
TOKEN_FILE = os.path.join(os.path.dirname(chain.STATE_FILE), "token")
CONFIG_FILE = os.path.join(os.path.dirname(chain.STATE_FILE), "config.json")


class Msg(str):
    """Görünen ileti (D50): değeri Türkçe metnin KENDİSİ (geriye uyum: testler, günlük, eski sekme), yanında istemcinin dil sözlüğündeki
    karşılığı için kod ve değişkenler. Sözlükte `srv.<kod>` şablonu `{değişken}` yer tutucularıyla yazılır (console/i18n/*.json)."""
    def __new__(cls, code, text, **vars):
        m = super().__new__(cls, text)
        m.code, m.vars = code, {k: v if isinstance(v, (int, float)) else str(v) for k, v in vars.items()}
        return m


def msg_fields(m, prefix="message"):
    """Yanıta eklenen alanlar: <önek>, <önek>_code, <önek>_vars. Düz dize (koda bağlanmamış) → kod boş."""
    return {prefix: str(m or ""), prefix + "_code": getattr(m, "code", ""), prefix + "_vars": getattr(m, "vars", {})}


def require_key():
    """Anahtar zorunlu mu? Varsayılan EVET (paylaşılan/çok kullanıcılı makine için güvenli taraf).
    Tek kullanıcılı makinede `{"require_key": false}` ile kapatılabilir: o zaman bu makinedeki her tarayıcı paneli açar.
    Kapalıyken de başka SİTELER paneli süremez: Host + Origin + Sec-Fetch-Site + özel başlık denetimleri anahtardan bağımsızdır.
    Kaybedilen tek şey: aynı makinedeki BAŞKA Unix kullanıcılarına karşı koruma."""
    try:
        return bool(json.load(open(CONFIG_FILE, encoding="utf-8")).get("require_key", True))
    except (OSError, ValueError, AttributeError):
        return True

# Sunucu öldürülürse (SIGKILL dahil) kayıtçılar da ölsün; yoksa mikrofon açık kalır.
PDEATH = [shutil.which("setpriv"), "--pdeathsig", "TERM"] if shutil.which("setpriv") else []
LOCK = threading.Lock()


def load_token():
    """Kalıcı panel anahtarı (yer imi çalışsın diye kalıcı).

    Var olan dosya ancak şu koşullarda kabul edilir: sembolik bağ değil, düz dosya, sahibi biz, grup/diğer için HİÇ izin yok.
    Aksi hâlde (gevşek izinli, başkasına ait, bağ) anahtar sızmış sayılır: dosya silinir ve yenisi üretilir.
    Yeni dosya O_EXCL|O_NOFOLLOW ile 0600 doğar (umask'tan bağımsız); dizin 0700 yapılır.
    """
    d = os.path.dirname(TOKEN_FILE)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    try:
        fd = os.open(TOKEN_FILE, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            t = os.read(fd, 256).decode("ascii", "replace").strip()
        finally:
            os.close(fd)
        import stat as _stat
        if _stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and not (st.st_mode & 0o077) and len(t) >= 32:
            return t
    except OSError:
        pass
    try:
        os.unlink(TOKEN_FILE)
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, t.encode("ascii"))
    finally:
        os.close(fd)
    return t


def run(*cmd, timeout=6):
    try:
        p = subprocess.run(cmd, env=ENV, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


# ── durum ────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self):
        self.restarts = 0   # yapısal değişiklikle zincirin kaç kez yeniden başlatıldığı (panel ve test için)
        self.state = chain.load_state()
        self.amt = "orta"
        self.mode, self.base, self.char = self._read_meta()

    def _read_meta(self):
        try:
            d = json.load(open(chain.STATE_FILE, encoding="utf-8"))
            if d.get("_amt") in chain.AMOUNTS:
                self.amt = d["_amt"]
            return str(d.get("_mode", "fisilti")), str(d.get("_base", "fisilti")), self._char_of(d.get("_char"))
        except (OSError, ValueError):
            return "fisilti", "fisilti", self._char_of(None)

    def _char_of(self, hint):
        """Ton değerlerinden karakteri türetir (dosyadaki ad yalnız ipucudur): yerleşik karakter × yoğunluk, ya da kayıtlı "user:<ad>", değilse "ozel".
        Yoğunluğu da (self.amt) eşleşene göre günceller; ipucu ve seçili yoğunluk önceliklidir (nötr her yoğunlukta aynıdır)."""
        tone = {k: self.state[k] for k in chain.TONE_KEYS}
        hits = [(n, a) for a in sorted(chain.AMOUNTS, key=lambda a: a != self.amt) for n in chain.CHARACTERS if chain.scaled_character(n, a) == tone]
        users = ["user:" + n for n, c in user_characters().items() if c == tone]
        if hint in users:
            return hint
        for n, a in hits:
            if n == hint or hint not in [h[0] for h in hits]:
                self.amt = a
                return n
        return users[0] if users else "ozel"

    def save(self):
        os.makedirs(os.path.dirname(chain.STATE_FILE), exist_ok=True)
        tmp = chain.STATE_FILE + ".tmp"
        json.dump({**self.state, "_mode": self.mode, "_base": self.base, "_char": self.char, "_amt": self.amt}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, chain.STATE_FILE)
        if not DRY:  # servis yeniden başlarsa aynı ayarlarla açılsın
            open(gen_conf.OUT, "w", encoding="utf-8").write(gen_conf.render(self.state))

    def apply(self, patch, mode="ozel", char=None):
        """mode=None → mod ekseni değişmez (karakter uygulanırken). Ton anahtarı değişince karakter yeniden adlandırılır."""
        patch = chain.clamp(patch)
        if patch.get("pitch_on") and not caps()["pitch"]:   # perde eklentisi yok: perdeli karakter (Kalın/İri) yalnız ton kısmıyla uygulanır
            patch = {k: v for k, v in patch.items() if k != "pitch_on"}
        before = [n[0] for n in chain.nodes(self.state)]
        self.state.update(patch)
        structural = before != [n[0] for n in chain.nodes(self.state)]   # düğüm kümesi değişti (ör. perde açıldı/kapandı): canlı yazılamaz
        tone = [k for k in patch if k in chain.AXIS2]
        if mode is not None and not (mode == "ozel" and tone and len(tone) == len(patch)):   # yalnız ton oynandıysa mod "özel"e düşmez
            self.mode = mode
            if mode != "ozel":
                self.base = mode   # "bu modun ayarlarına dön" için: elle oynanınca hangi moddan gelindiği
        if char or any(k in chain.TONE_KEYS for k in patch):
            self.char = self._char_of(char)
        if structural:
            self.save()   # conf yeni düğüm kümesiyle yazılır, sonra zincir yeniden başlar (mikrofon birkaç saniye kesilir; bekçi profili ve varsayılan girişi korur)
            self.restarts += 1
            ok, msg = restart_chain()
            return ok, msg
        ok, msg = push_live(self.state)
        self.save()
        return ok, msg


CHAR_DIR = os.path.join(os.path.dirname(chain.STATE_FILE), "characters")


def user_characters():
    """Kullanıcının kaydettiği karakterler: {ad: yalnız ton anahtarları}. Bozuk/eksik dosya yok sayılır."""
    out = {}
    try:
        names = sorted(f[:-5] for f in os.listdir(CHAR_DIR) if f.endswith(".json") and NAME_RE.match(f[:-5]))
    except OSError:
        return out
    for n in names[:MAX_PROFILES]:
        try:
            d = json.load(open(os.path.join(CHAR_DIR, n + ".json"), encoding="utf-8"))
            flat = chain.CHARACTERS["notr"]
            c = chain.clamp({k: d.get(k, flat[k]) if k.startswith("pitch_") else d[k] for k in chain.TONE_KEYS})   # perde anahtarı sonradan eklendi: eski kayıt "perde kapalı" sayılır
            out[n] = c
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def push_live(state):
    """Çalışan zincire parametreleri yazar. Dönüş: (başarılı mı, ileti)."""
    if DRY:
        return True, "dry"
    parts = []
    for k, v in chain.live_params(state).items():
        parts.append(f'"{k}" {"true" if v is True else "false" if v is False else format(v, ".6g")}')
    rc, out = run("pw-cli", "set-param", chain.CONTROL_NODE, "Props", "{ params = [ " + " ".join(parts) + " ] }")
    if rc != 0 or "Error" in out:
        return False, out[-200:] or "pw-cli"
    return True, ""


def restart_chain():
    if DRY:
        return True, ""
    rc, out = run("systemctl", "--user", "restart", "mic-clean.service")
    return (True, Msg("chain_restarted", "Zincir yeni yapıyla yeniden başlatıldı; mikrofon birkaç saniye içinde geri gelir.")) if rc == 0 \
        else (False, Msg("chain_restart_failed", "Zincir yeniden başlatılamadı: " + out[-160:], detail=out[-160:]))


def service_active():
    return DRY or run("systemctl", "--user", "is-active", "mic-clean.service")[1] == "active"


def monitor_mode():
    rc, out = run("pgrep", "-af", "pw-loopback --name mic_monitor")
    if rc != 0 or not out:
        return "off"
    return "ham" if chain.RAW_SOURCE in out else "temiz"


def profiles():
    try:
        return sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json") and NAME_RE.match(f[:-5]))
    except OSError:
        return []


def quality_line():
    """İkinci sanal mikrofonun ("<etiket> (kalite …)") durumu — gözcünün olay günlüğünün son olayından. Günlük yoksa hat kurulu değildir."""
    import carrier
    path = os.environ.get("MIC_QUALITY_EVENTS") or os.path.join(RUN, "mic-hifi", "watch.jsonl")
    state = "yok"
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - 8192))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            ev = json.loads(line).get("event")
        except (ValueError, AttributeError):
            continue
        state = {"gözcü hazır": "bosta", "kilit kalktı": "bosta", "kuru": "bosta", "işçi kapatıldı": "bosta", "dinleyen": "hazirlaniyor", "işçi başlatıldı": "hazirlaniyor",
                 "işçi bağlandı": "hazirlaniyor", "taşıyıcıda": "hazirlaniyor", "ıslak": "etkin", "kilitli": "kilitli", "gözcü kapandı": "yok"}.get(ev, state)
        # "kilitli"den sonra gelen "kuru/işçi kapatıldı" kilidi kaldırmaz: gözcü önce kuruya çeker, sonra kilitler (sıra: kuru → kapatıldı → kilitli)
    return {"state": state, "delay_ms": carrier.QUALITY_DELAY_MS, "name": carrier.DESCRIPTION}


def ui_version():
    """Panel sayfasının sürümü (sayfa + dil sözlükleri içeriğinin özeti). Sayfaya gömülür ve durum yanıtında döner: açık sekme eskiyse fark eder ve "yenile" der."""
    import hashlib
    h = hashlib.sha256()
    try:
        for f in (PAGE, *I18N.values()):
            h.update(open(f, "rb").read())
        return h.hexdigest()[:12]
    except OSError:
        return ""


def i18n_blob():
    """Sayfaya gömülecek sözlükler: {"en": {...}, "tr": {...}} — betik içinde güvenli JSON ("</" kaçışlı; sözlük depodandır, kullanıcı girdisi değildir).
    Okunamayan sözlük boş sayılır; sayfa o zaman HTML'deki Türkçe metinle açılır."""
    out = {}
    for lang, f in I18N.items():
        try:
            d = json.load(open(f, encoding="utf-8"))
            out[lang] = {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
        except (OSError, ValueError):
            out[lang] = {}
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def caps():
    """Hangi eklentiler kurulu (yetenek yoklaması, PRD-PUBLISH Y3-4). Kuru sunucuda, eklenti dizini açıkça verilmedikçe hepsi "var" sayılır (sınamalar eklentiye bağlı olmasın)."""
    if DRY and "MIC_PLUGIN_DIR" not in os.environ:
        return {"denoise": True, "pitch": True}
    return {"denoise": os.path.exists(chain.DF), "pitch": os.path.exists(chain.RB)}


def mic_present():
    return DRY or chain.RAW_SOURCE in run("pactl", "list", "sources", "short")[1]


def dropouts(minutes=10):
    """Son N dakikada gürültü bastırıcının 'yetişemedim' uyarısı sayısı = duyulur ses kesintisi adayı."""
    if DRY:
        return 0
    return run("journalctl", "--user", "-u", "mic-clean.service", "--since", f"-{minutes}min", "--no-pager", "-g", "Underrun detected", "-o", "cat")[1].count("Underrun")


class Trial:
    """Kaydet ve dinle: N sn ham + işlenmiş aynı anda kaydedilir, sonra sırayla çalınır (Bluetooth gecikmesinden etkilenmez)."""

    def __init__(self):
        self.phase, self.proc, self.restore = "idle", None, "off"

    def start(self, seconds):
        with LOCK:
            if self.phase != "idle":
                return False
            self.phase = "kayit"
        threading.Thread(target=self._run, args=(seconds,), daemon=True).start()
        return True

    def _run(self, seconds):
        try:
            if DRY:
                for ph in ("kayit", "ham", "temiz"):
                    self.phase = ph
                    time.sleep(0.4)
                return
            self.restore = monitor_mode()
            run(sys.executable, MIC, "monitor", "off")   # açık kalırsa kayda kendi yankın girer
            self.proc = subprocess.Popen([sys.executable, MIC, "ab", str(seconds)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in self.proc.stdout:
                if line.startswith("çalıyor: ham"):
                    self.phase = "ham"
                elif line.startswith("çalıyor: temiz"):
                    self.phase = "temiz"
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            if self.proc:
                self.proc.kill()
        finally:   # ne olursa olsun: canlı dinleme eski hâline, durum boşa
            if not DRY and self.restore != "off":
                run(sys.executable, MIC, "monitor", "on", self.restore)
            self.phase, self.proc = "idle", None


TRIAL = Trial()


class Audition:
    """Kulakla karşılaştırma: bir kez konuş, AYNI kaydı farklı karakterlerle dinle. Canlı ayar değişmez.

    Kayıt, ton/dinamik katman (ıslık, şişme, sertlik)/doygunluk kapalı ve çıkış kazancı 0 iken temiz kaynaktan alınır (= ton katmanından önceki ses); çalarken
    tools/audition.py aynı zincir tanımıyla çevrimdışı işler. Kayıt kişisel sestir: çalışma dizininde (tmpfs) 0600 durur, yeni kayıtta,
    15 dk kullanılmayınca ve sunucu kapanınca silinir."""
    TTL = 900
    OFF = {"tone_on": False, "deess_on": False, "dyn_body_on": False, "dyn_mud_on": False, "dyn_harsh_on": False, "sat_on": False, "out_db": 0, "loud_db": 0, "pitch_st": 0}   # işleyicinin (tools/audition.py) yeniden uygulayacağı her şey

    def __init__(self):
        self.phase, self.id, self.proc, self.take_at, self.stop_flag = "idle", "", None, 0.0, False
        self.dir = os.path.join(RUN, "mic-hifi", "audition")
        self.take, self.out, self.st = (os.path.join(self.dir, n) for n in ("take.wav", "out.wav", "state.json"))
        atexit.register(self.wipe)
        self.wipe()   # önceki sunucudan kalan kayıt varsa (SIGTERM'de atexit çalışmayabilir)

    def wipe(self):
        """Kayıt ve türevlerini siler. Silinemeyen dosya kalırsa "kayıt yok" DENMEZ (kapalı-başarısız): bayrak durur, sonraki denemede yine silinir."""
        left = False
        for f in (self.take, self.out, self.st):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
            except OSError:
                left = True
        self.take_at = time.time() - self.TTL - 1 if left else 0.0
        return not left

    def _arm(self):
        """Süre dolunca panel açık olmasa da siler (silme, birinin durumu sormasına bağlı kalmasın)."""
        if getattr(self, "timer", None):
            self.timer.cancel()
        self.timer = threading.Timer(self.TTL + 1, lambda: self.phase == "idle" and time.time() - self.take_at > self.TTL and self.wipe())
        self.timer.daemon = True
        self.timer.start()

    def has_take(self):
        if self.take_at and time.time() - self.take_at > self.TTL and self.phase == "idle":
            self.wipe()
        return bool(self.take_at) and time.time() - self.take_at <= self.TTL

    def info(self):
        return {"phase": self.phase, "take": self.has_take(), "id": self.id}

    def _begin(self, phase, ident=""):
        with LOCK:
            if self.phase != "idle" or TRIAL.phase != "idle" or DIAG.phase != "idle":
                return False
            self.phase, self.id, self.stop_flag = phase, ident, False
        return True

    def record(self, store, seconds):
        if not self._begin("kayit"):
            return Msg("busy", "Başka bir kayıt ya da çalma sürüyor.")
        threading.Thread(target=self._record, args=(store, seconds), daemon=True).start()
        return ""

    def _record(self, store, seconds):
        restore = "off"
        try:
            if not self.wipe():
                return
            if DRY:
                time.sleep(0.5)
                self.take_at = time.time()
                return
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            os.chmod(self.dir, 0o700)
            restore = monitor_mode()
            run(sys.executable, MIC, "monitor", "off")            # açık kalırsa kayda kendi yankın girer
            push_live({**store.state, **self.OFF})
            time.sleep(0.4)
            old = os.umask(0o077)
            try:
                # `timeout`: sunucu öldürülse bile kayıtçı en geç süre + 2 sn sonra kendiliğinden kapanır (yetim mikrofon kaydı kalmaz)
                self.proc = subprocess.Popen(["timeout", "--signal=TERM", "--kill-after=2", str(seconds + 2), "pw-record", "--target", chain.CLEAN_SOURCE, "--rate", "48000", "--channels", "1", "--format", "s16",
                                              self.take], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                os.umask(old)
            t0 = time.time()
            while time.time() - t0 < seconds and not self.stop_flag:
                time.sleep(0.05)
            self.proc.terminate()
            self.proc.wait(timeout=4)
            if os.path.exists(self.take) and os.path.getsize(self.take) > 48000:
                self.take_at = time.time()
                self._arm()
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:                                                   # ne olursa olsun: kayıtçı ölür, canlı zincir gerçek ayarına döner
            p = self.proc
            if p and p.poll() is None:
                p.kill()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            if not self.take_at:
                self.wipe()                                        # yarım kalan kayıt diskte durmasın
            if not DRY:
                push_live(store.state)
                if restore != "off":
                    run(sys.executable, MIC, "monitor", "on", restore)
            self.phase, self.proc = "idle", None

    def variant(self, store, ident):
        if ident == "current":
            return dict(store.state)
        if ident == "off":
            return {**store.state, **self.OFF}
        if ident in chain.CHARACTERS:
            return {**store.state, "tone_on": True, **chain.scaled_character(ident, store.amt)}
        if ident.startswith("user:") and ident[5:] in user_characters():
            return {**store.state, "tone_on": True, **user_characters()[ident[5:]]}
        raise KeyError(ident)

    def play(self, store, ident):
        state = self.variant(store, ident)
        if not self.has_take():
            return Msg("no_take", "Önce bir kayıt al.")
        if not self._begin("caliyor", ident):
            return Msg("busy", "Başka bir kayıt ya da çalma sürüyor.")
        threading.Thread(target=self._play, args=(state,), daemon=True).start()
        return ""

    def _play(self, state):
        restore = "off"
        try:
            if DRY:
                t0 = time.time()
                while time.time() - t0 < 3 and not self.stop_flag:
                    time.sleep(0.05)
                return
            json.dump(state, open(self.st, "w", encoding="utf-8"))
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "audition.py"), "render", self.take, self.st, self.out],
                               env=ENV, capture_output=True, text=True, timeout=40)
            if r.returncode or self.stop_flag:
                return
            restore = monitor_mode()
            run(sys.executable, MIC, "monitor", "off")            # canlı dinleme çalmanın üstüne binmesin
            self.proc = subprocess.Popen(["timeout", "--signal=TERM", "--kill-after=2", "45", "pw-play", self.out], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.proc.wait(timeout=48)
            self.take_at = time.time()
            self._arm()
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            p = self.proc
            if p and p.poll() is None:
                p.kill()
            if not DRY and restore != "off":
                run(sys.executable, MIC, "monitor", "on", restore)
            self.phase, self.id, self.proc = "idle", "", None

    # Teslim hedefleri: R 128 program yüksekliği −23 LUFS; akış/podcast için −16'ya kadar (mono dosyada Apple −19 önerir). Gerçek tepe ≤ −1 dBTP.
    TARGETS = {"integrated": [-23.0, -16.0], "true_peak": -1.0, "floor": -52.0, "clicks_per_min": 6.0}

    def delivery(self, store, ident):
        """Kaydı seçilen ayarla çevrimdışı işleyip teslim ölçülerini döndürür (canlıya dokunmaz)."""
        state = self.variant(store, ident)
        # Seçili çıkış hedefi varsa ses yüksekliği o hedefe göre (−3 … +2 LU: kısa kayıtta duraklar ölçüyü aşağı çeker), yoksa tüm aralık.
        want = next((t["lufs"] for t in chain.LOUD_TARGETS.values() if t["loud_db"] == state.get("loud_db")), None)
        targets = {**self.TARGETS, "integrated": [want - 3.0, want + 2.0] if want is not None else self.TARGETS["integrated"], "loudness_goal": want}
        base = {"ok": False, "id": ident, "targets": targets, "measures": {}, **msg_fields("")}
        if not self.has_take():
            return {**base, **msg_fields(Msg("no_take", "Önce bir kayıt al."))}
        if self.phase != "idle":
            return {**base, **msg_fields(Msg("audition_busy", "Kayıt ya da çalma sürüyor."))}
        if DRY:
            return {**base, "ok": True, "message": "", "measures": {"seconds": 8.0, "integrated": -24.5, "short_max": -22.1, "lra": 4.2, "sample_peak": -1.0,
                                                                     "true_peak": -0.6, "floor": -58.0, "clicks_per_min": 7.5, "clicks": 1, "clicks_in_per_min": 7.5}}
        try:
            st = self.st + ".measure"
            json.dump(state, open(st, "w", encoding="utf-8"))
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "audition.py"), "measure", self.take, st], env=ENV, capture_output=True, text=True, timeout=40)
            os.remove(st)
            if r.returncode:
                err = (r.stderr.strip().splitlines() or ["?"])[-1][:160]
                return {**base, **msg_fields(Msg("measure_failed", "Ölçülemedi: " + (err if err != "?" else "bilinmeyen hata"), detail=err))}
            return {**base, "ok": True, "message": "", "measures": json.loads(r.stdout)}
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            return {**base, **msg_fields(Msg("measure_failed", f"Ölçülemedi: {e}", detail=e))}

    def stop(self):
        self.stop_flag = True
        p = self.proc
        if p and p.poll() is None:
            p.terminate()
        return ""


AUDITION = Audition()


class Diag:
    """Teşhis kaydı: dört yönergeli adım, HAM mikrofondan (zincir öncesi) yerel kayıt. Ayar önermez, yalnız veri toplar (docs/PRD-QUALITY.md "Teşhis kaydı kartı").
    Kayıtlar kişisel sestir: durum dizininde (0700) 0600 durur, depoya girmez, çalınmaz, makineden çıkmaz; kullanıcı panelden siler."""
    SENTENCE = "Pazartesi pekmezli tatlıyı tabakta kaptı; tık tık kapıyı çaldı."
    # Konuşma süresi denetimi (S36): çerçeve eşiği oda sesinin 6 dB üstü; adım süresinin en az dörtte biri (uzun seste %40) konuşma olmalı.
    RATE, SPEECH_ABOVE_ROOM_DB, MIN_SPEECH, MIN_SUSTAIN_S, MIN_EVENTS = 48000, 6.0, {"aaa": 0.4}, 2.0, 3
    STEPS = [("sessiz", "Oda sesi", "Hiç konuşma; odanın sesi kaydedilsin.", 8),
             ("aaa", "Uzun ses", "Olağan sesinle, tek nefeste uzun bir “aaa” de.", 6),
             ("ptk", "Sert sesler", "Olağan sesinle oku: “" + SENTENCE + "”", 8),
             ("fisilti", "Fısıltı", "Aynı cümleyi fısıltıyla oku: “" + SENTENCE + "”", 8),
             # Etiketli örnekler (S38): tık sayacı eşikle kalibre edilemedi; bilerek yapılmış olaylar ve duraklamalı uzun okuma gerekir.
             ("tik", "Ağız sesleri", "Konuşma. Saniyede bir kez dudağını şaklat ya da dilinle “tık” yap (5–6 kez).", 8),
             ("metin", "Duraklamalı okuma", "Olağan sesinle, her cümleden sonra 2 saniye susarak oku: “" + SENTENCE + "” — üç kez.", 25)]

    def __init__(self):
        self.phase, self.step, self.proc, self._speech, self._events = "idle", "", None, {}, {}
        self.dir = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mic-hifi", "diag")

    def path(self, step):
        return os.path.join(self.dir, step + ".wav")

    def measure(self, step):
        """(seviye dBFS, uyarı) — kayıt işe yarar mı: tam sessizlik (cihaz kendi tuşundan sessizde), çok alçak ses, kırpılma."""
        import wave
        try:
            with wave.open(self.path(step)) as w:
                a = array.array("h", w.readframes(w.getnframes()))
        except (OSError, EOFError, wave.Error):
            return None, Msg("diag_unreadable", "Kayıt okunamadı; yeniden dene.")
        if not a or not any(a):
            return -120.0, Msg("diag_silent", "Mikrofondan hiç ses gelmedi (cihaz kendi tuşundan sessizde olabilir); yeniden dene.")
        rms = 20 * math.log10(max(math.sqrt(sum(v * v for v in a) / len(a)), 1e-3) / 32768)
        peak = max(max(a), -min(a))
        if peak >= 32760:
            return round(rms, 1), Msg("diag_clipped", "Ses tavana vurdu (kırpılma); biraz uzaklaşıp yeniden dene.")
        if step == "tik":
            # Bilerek yapılan ağız sesleri kısa darbelerdir: konuşma süresi aranmaz, AYRI olay sayılır (oda + 12 dB üstü 50 ms çerçeve kümeleri, arada ≥ 200 ms).
            room = self._room(); n = self.RATE // 20
            lim = (32768 * 10 ** (((room if room is not None else -53.0) + 12.0) / 20)) ** 2 * n
            on = [sum(v * v for v in a[i:i + n]) >= lim for i in range(0, len(a) - n + 1, n)]
            events, last = 0, -99
            for i, f in enumerate(on):
                if f:
                    events += i - last > 4
                    last = i
            self._events[step] = events
            if events < self.MIN_EVENTS:
                return round(rms, 1), Msg("diag_few_events", f"{events} ses olayı duyuldu; en az {self.MIN_EVENTS} gerekiyor. Dudağını ya da dilini biraz daha belirgin şaklatıp yeniden dene.",
                                           events=events, min=self.MIN_EVENTS)
            return round(rms, 1), ""
        if step != "sessiz":
            # Konuşma adımı oda sesinden ayırt edilebilmeli: oda kaydı varsa onun 3 dB üstü, yoksa −50 dBFS (ham oda gürültüsü ≈ −52 dBFS ölçüldü).
            room = self._room()
            if rms < (room + 3.0 if room is not None else -50.0):
                return round(rms, 1), Msg("diag_no_speech", "Konuşma duyulmadı (kayıt oda sesi kadar alçak); yönergeyi uygulayıp yeniden dene.")
            # Ortalama seviye konuşmayı kanıtlamaz: kısa bir darbe (masaya vurma, mikrofona dokunma) ortalamayı tek başına yükseltir (ölçüldü: 8 sn'nin
            # %8–10'u sesliyken "yapıldı" göründü). Ölçü: 50 ms'lik çerçevelerden oda sesinin 6 dB üstünde kalanların toplam süresi.
            thr, n, sec = (room if room is not None else -53.0) + self.SPEECH_ABOVE_ROOM_DB, self.RATE // 20, self._seconds(step)
            lim = (32768 * 10 ** (thr / 20)) ** 2 * n
            on = [sum(v * v for v in a[i:i + n]) >= lim for i in range(0, len(a) - n + 1, n)]
            speech = sum(on) * 0.05
            self._speech[step] = round(speech, 1)
            if speech < sec * (self.MIN_SPEECH.get(step, 0.25)):
                return round(rms, 1), Msg("diag_too_short", f"Konuşma çok kısa sürdü ({speech:.1f} sn);".replace(".", ",") + " duyulan ses bir darbe ya da tıkırtı olabilir. Yönergeyi baştan sona uygulayıp yeniden dene.",
                                           sec=round(speech, 1))
            if step == "aaa":
                # Uzun ses tek parça olmalı: toplamı yeten ama kesik kesik ses (odadaki konuşma) rezonans ölçümüne yaramaz (S37). 100 ms'lik boşluk hoş görülür.
                run = best = gap = 0
                for f in on:
                    gap = 0 if f else gap + 1
                    run = run + 1 if f or gap <= 2 else 0
                    best = max(best, run)
                if best * 0.05 < self.MIN_SUSTAIN_S:
                    return round(rms, 1), Msg("diag_choppy", f"Ses kesik kesik (en uzun kesintisiz bölüm {best * 0.05:.1f} sn);".replace(".", ",") + " tek nefeste, kesintisiz bir “aaa” gerekiyor. Yeniden dene.",
                                               sec=round(best * 0.05, 1))
        return round(rms, 1), ""

    def _seconds(self, step):
        return next(sec for sid, _t, _p, sec in self.STEPS if sid == step)

    def _room(self):
        import wave
        try:
            with wave.open(self.path("sessiz")) as w:
                a = array.array("h", w.readframes(w.getnframes()))
        except (OSError, EOFError, wave.Error):
            return None
        return 20 * math.log10(max(math.sqrt(sum(v * v for v in a) / len(a)), 1e-3) / 32768) if a and any(a) else None

    def info(self):
        steps = []
        for sid, title, prompt, sec in self.STEPS:
            done = os.path.exists(self.path(sid)) and not (self.phase == "kayit" and self.step == sid)
            self._speech.pop(sid, None); self._events.pop(sid, None)
            lv, warn = self.measure(sid) if done else (None, "")
            steps.append({"id": sid, "title": title, "prompt": prompt, "seconds": sec, "done": done, "level_db": lv, **msg_fields(warn, "warn"),
                          "speech_s": self._speech.get(sid), "events": self._events.get(sid)})
        return {"phase": self.phase, "step": self.step, "steps": steps, "room": self.room_report()}

    def room_report(self):
        """Oda payı (tools/diag_report.py): oda kaydı değişmedikçe yeniden ölçülmez. Kayıt yoksa/ölçülemezse None."""
        f = self.path("sessiz")
        try:
            st = os.stat(f)
        except OSError:
            self._room_cache = None
            return None
        key = (st.st_mtime_ns, st.st_size)
        if getattr(self, "_room_cache", None) and self._room_cache[0] == key:
            return self._room_cache[1]
        if self.phase == "kayit" and self.step == "sessiz":
            return None
        res = None
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "diag_report.py"), self.dir], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                res = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        self._room_cache = (key, res)
        return res

    def record(self, step):
        spec = next((x for x in self.STEPS if x[0] == step), None)
        if spec is None:
            raise ValueError("step")
        with LOCK:
            if self.phase != "idle" or AUDITION.phase != "idle" or TRIAL.phase != "idle":
                return Msg("busy", "Başka bir kayıt ya da çalma sürüyor.")
            self.phase, self.step = "kayit", step
        threading.Thread(target=self._record, args=(step, spec[3]), daemon=True).start()
        return ""

    def _record(self, step, seconds):
        tmp = self.path(step) + ".part"
        try:
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            os.chmod(self.dir, 0o700)
            old = os.umask(0o077)
            try:
                if DRY:
                    import wave
                    with wave.open(tmp, "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b"\0\0" * 4800)
                    time.sleep(0.5)
                else:   # `timeout`: sunucu ölse de kayıtçı süre + 2 sn sonra kapanır (yetim mikrofon kaydı kalmaz). Ham kaynak: zincir ayarından bağımsız veri.
                    self.proc = subprocess.Popen(["timeout", "--signal=TERM", "--kill-after=2", str(seconds + 2), "pw-record", "--target", chain.RAW_SOURCE, "--rate", "48000",
                                                  "--channels", "1", "--format", "s16", tmp], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(seconds)
                    self.proc.terminate()
                    self.proc.wait(timeout=4)
            finally:
                os.umask(old)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
                os.replace(tmp, self.path(step))   # yarım kayıt eskisinin üstüne yazılmaz
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            p = self.proc
            if p and p.poll() is None:
                p.kill()
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.phase, self.step, self.proc = "idle", "", None

    def delete(self):
        if self.phase != "idle":
            return Msg("diag_busy_delete", "Kayıt sürerken silinemez.")
        left = 0
        for sid, *_ in self.STEPS:
            try:
                os.remove(self.path(sid))
            except FileNotFoundError:
                pass
            except OSError:
                left += 1
        return Msg("diag_deleted", "Teşhis kayıtları silindi.") if not left else Msg("diag_delete_failed", f"{left} kayıt silinemedi.", n=left)


DIAG = Diag()


def snapshot(store, msg=""):
    return {"state": store.state, "mode": store.mode, "base": store.base, "defaults": chain.DEFAULT_STATE,
            "controls": [{"key": k, "type": t, "min": lo, "max": hi, "step": st} for k, t, lo, hi, st, _d in chain.CONTROLS],
            "presets": sorted(chain.PRESETS), "profiles": profiles(), "character": store.char, "characters": list(chain.CHARACTERS), "amount": store.amt, "amounts": list(chain.AMOUNTS),
            "loudness": next((k for k, t in chain.LOUD_TARGETS.items() if t["loud_db"] == store.state.get("loud_db")), "ozel"), "loud_targets": chain.LOUD_TARGETS,
            "user_characters": list(user_characters()), "service": service_active(), "restarts": store.restarts,
            "monitor": "off" if DRY else monitor_mode(), "hpf_hz": chain.HPF_HZ, **msg_fields(msg),
            "mic": mic_present(), "quality": quality_line(), "diag": DIAG.info(), "label": chain.DEVICE_LABEL, "clean_name": chain.DEVICE_LABEL + " (temiz)", "caps": caps(), "ui": ui_version(), "dropouts": dropouts(), "trial": TRIAL.phase, "audition": AUDITION.info(), "key_required": require_key()}


# ── seviye ölçer (yalnız istemci varken) ─────────────────────────────────────
class Meter:
    def __init__(self):
        self.clients, self.procs, self.level = 0, [], {"in": [-120.0, -120.0], "out": [-120.0, -120.0]}

    def _reader(self, key, proc):
        n = 4096 * 2  # 4096 örnek ≈ 85 ms
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            a = array.array("h", buf)
            rms = math.sqrt(sum(v * v for v in a) / len(a))
            pk = max(max(a), -min(a))
            db = lambda v: round(20 * math.log10(v / 32768), 1) if v > 0 else -120.0
            self.level[key] = [db(rms), db(pk)]
        self.level[key] = [-120.0, -120.0]

    def _stop(self):
        for p in self.procs:
            try:
                p.terminate()
                p.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                p.kill()
        self.procs = []

    def acquire(self):
        """Dönüş False → yer yok ya da kayıtçı açılamadı; çağıran release ÇAĞIRMAZ (sayaç artmadı)."""
        with LOCK:
            if self.clients >= MAX_METER_CLIENTS:
                return False
            if self.clients == 0 and not DRY:
                try:
                    for key, src in (("in", chain.RAW_SOURCE), ("out", chain.CLEAN_SOURCE)):
                        p = subprocess.Popen(PDEATH + ["parec", "-d", src, "--format=s16le", "--rate=48000", "--channels=1", "--latency-msec=40",
                                              "--client-name=mic-console-meter"], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                        self.procs.append(p)
                        threading.Thread(target=self._reader, args=(key, p), daemon=True).start()
                except OSError:
                    self._stop()  # yarım açılan kayıtçı mikrofonu açık bırakmasın
                    return False
            self.clients += 1
            return True

    def release(self):
        with LOCK:
            self.clients = max(0, self.clients - 1)
            if self.clients == 0:
                self._stop()


# ── HTTP ─────────────────────────────────────────────────────────────────────
def make_handler(store, meter, port, token):
    need_key = require_key()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=()):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in extra:
                self.send_header(k, v)
            if code >= 400:  # reddedilen isteğin gövdesi okunmadı; bağlantıyı kapat ki sıradaki istek sanılmasın
                self.close_connection = True
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _err(self, status, m):
            """Hata yanıtı: `error` Türkçe metin (geriye uyum) + `code`/`vars` (istemci sözlüğünde `srv.<kod>`, D50)."""
            self._send(status, {"error": str(m), "code": m.code, "vars": m.vars})

        def _authed(self):
            return hmac.compare_digest((self.headers.get("X-Mic-Key") or "").encode(), token.encode())

        def _guard(self, post=False, auth=True):
            if self.headers.get("Host") not in hosts:
                self._err(403, Msg("err_host", "host")); return False
            o = self.headers.get("Origin")
            if o and o not in origins:
                self._err(403, Msg("err_origin", "origin")); return False
            if not auth:
                return True
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                self._err(403, Msg("err_site", "site")); return False   # başka siteden gelen GET (img/iframe) dahil
            if self.headers.get("X-Mic-Console") != "1":   # GET dahil: yalnız panelin kendi fetch'i bu başlığı koyabilir
                self._err(403, Msg("err_header", "başlık")); return False
            if need_key and not self._authed():
                self._err(401, Msg("err_key", "anahtar yok: terminalde `mic console` çalıştırıp verdiği adresi aç")); return False
            if post and (self.headers.get("X-Mic-Console") != "1" or "application/json" not in (self.headers.get("Content-Type") or "")):
                self._err(403, Msg("err_csrf", "csrf")); return False
            return True

        def do_GET(self):
            if self.path.split("?")[0] == "/":   # statik sayfa: sır içermez, anahtarsız sunulur (anahtar adres parçasından okunur); sorgu (?lang=) yalnız sayfanın betiği içindir
                if not self._guard(auth=False):
                    return
                self._send(200, open(PAGE, "rb").read().replace(b"__UI_VERSION__", ui_version().encode()).replace(b"/*__I18N__*/null", i18n_blob().encode()), "text/html; charset=utf-8", [
                    ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                                "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")])
                return
            if not self._guard():
                return
            if self.path == "/api/state":
                self._send(200, snapshot(store))
            elif self.path.split("?")[0] == "/api/delivery":
                q = self.path.partition("?")[2]
                ident = q[3:] if q.startswith("id=") else "current"
                try:
                    self._send(200, AUDITION.delivery(store, ident))
                except KeyError:
                    self._err(400, Msg("err_unknown_character", "bilinmeyen karakter"))
            elif self.path == "/api/meter":
                if not meter.acquire():
                    self._err(503, Msg("err_meter_busy", "ölçer meşgul")); return
                try:   # acquire'dan sonra ne olursa olsun release: başlık yazarken kopan istemci mikrofonu açık bırakmasın
                    self.connection.settimeout(5)   # okumayan/donmuş istemci yazmayı sonsuza dek bloke edemesin
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while True:
                        self.wfile.write(("data: " + json.dumps(meter.level) + "\n\n").encode())
                        self.wfile.flush()
                        time.sleep(0.09)
                except OSError:   # BrokenPipe, ConnectionReset, zaman aşımı
                    pass
                finally:
                    meter.release()
                self.close_connection = True
            else:
                self._err(404, Msg("err_not_found", "yok"))

        def do_POST(self):
            if not self._guard(post=True):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                self._err(400, Msg("err_length", "uzunluk")); return
            if n > MAX_BODY:
                self._err(413, Msg("err_too_large", "büyük")); return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                assert isinstance(body, dict)
            except (ValueError, AssertionError):
                self._err(400, Msg("err_json", "json")); return
            try:
                msg = self._route(body)
            except (KeyError, ValueError, TypeError, OSError) as e:   # bozuk/okunamayan profil dosyası dahil
                inner = e.args[0] if e.args and isinstance(e.args[0], Msg) else None   # açıklamalı ret (ad kuralı, sınır) kendi koduyla
                if inner is not None:
                    self._err(400, Msg(inner.code, f"geçersiz: {e}", **inner.vars))
                else:
                    self._err(400, Msg("err_invalid", f"geçersiz: {e}", detail=e))
                return
            if msg is None:
                self._err(404, Msg("err_not_found", "yok")); return
            self._send(200, snapshot(store, msg))

        def _route(self, b):
            with_state = lambda ok, m: "" if ok else Msg("live_restart_failed" if getattr(m, "code", "") == "chain_restart_failed" else "live_write_failed",
                                                 f"Canlı zincire yazılamadı: {m}", detail=getattr(m, "vars", {}).get("detail", m))
            if self.path == "/api/state":
                if not isinstance(b.get("patch"), dict):
                    raise ValueError("patch")
                if b["patch"].get("pitch_on") is True and not caps()["pitch"]:
                    return Msg("pitch_missing", "Perde eklentisi kurulu değil; perde açılamadı. Kurulum: bash tools/install_rubberband.sh")
                return with_state(*store.apply(b["patch"]))
            if self.path == "/api/preset":
                pid = str(b.get("id", ""))
                if pid in chain.PRESETS:
                    base = {k: v for k, v in chain.DEFAULT_STATE.items() if k not in chain.AXIS2}   # karakter ikinci eksen: mod değişince korunur
                    return with_state(*store.apply({**base, **chain.PRESETS[pid]}, mode=pid))
                if pid.startswith("user:") and NAME_RE.match(pid[5:]) and pid[5:] in profiles():
                    data = json.load(open(os.path.join(PROFILE_DIR, pid[5:] + ".json"), encoding="utf-8"))
                    return with_state(*store.apply({k: v for k, v in data.items() if k in chain.DEFAULT_STATE}, mode=pid))
                raise KeyError(pid)
            if self.path == "/api/loudness":
                t = chain.LOUD_TARGETS.get(str(b.get("target", "")))
                if not t:
                    raise KeyError(b.get("target"))
                return with_state(*store.apply({"loud_db": t["loud_db"]}))
            if self.path == "/api/character":
                if "save" in b or "delete" in b:
                    name = str(b.get("save") or b.get("delete") or "")
                    if not NAME_RE.match(name) or name in chain.CHARACTERS or name in ("ozel", "off", "current"):
                        raise ValueError(Msg("err_name_rule_char", "ad: küçük harf, rakam, tire (en çok 40); yerleşik karakter adı olamaz"))
                    path = os.path.join(CHAR_DIR, name + ".json")
                    if "save" in b:
                        if name not in user_characters() and len(user_characters()) >= MAX_PROFILES:
                            raise ValueError(Msg("err_max_chars", f"en çok {MAX_PROFILES} karakter", n=MAX_PROFILES))
                        os.makedirs(CHAR_DIR, exist_ok=True)
                        json.dump({k: store.state[k] for k in chain.TONE_KEYS}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                        store.char = store._char_of("user:" + name)
                        store.save()
                        return Msg("char_saved", f"Karakter kaydedildi: {name}", name=name)
                    if os.path.exists(path):
                        os.remove(path)
                    store.char = store._char_of(None)
                    store.save()
                    return Msg("char_deleted", f"Karakter silindi: {name}", name=name)
                cid, amt = str(b.get("id", "")), b.get("amount", store.amt)
                if amt not in chain.AMOUNTS:
                    raise ValueError("amount")
                if cid.startswith("user:") and cid[5:] in user_characters():
                    return with_state(*store.apply(user_characters()[cid[5:]], mode=None, char=cid))
                if cid not in chain.CHARACTERS:
                    raise KeyError(cid)
                store.amt = amt
                return with_state(*store.apply(chain.scaled_character(cid, amt), mode=None, char=cid))
            if self.path == "/api/profile":
                name = str(b.get("save") or b.get("delete") or "")
                if not NAME_RE.match(name):
                    raise ValueError(Msg("err_name_rule", "ad: küçük harf, rakam, tire (en çok 40)"))
                path = os.path.join(PROFILE_DIR, name + ".json")
                if "save" in b:
                    if name not in profiles() and len(profiles()) >= MAX_PROFILES:
                        raise ValueError(Msg("err_max_profiles", f"en çok {MAX_PROFILES} profil", n=MAX_PROFILES))
                    os.makedirs(PROFILE_DIR, exist_ok=True)
                    json.dump(store.state, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    store.mode = store.base = "user:" + name
                    store.save()
                    return Msg("profile_saved", f"Profil kaydedildi: {name}", name=name)
                if os.path.exists(path):
                    os.remove(path)
                return Msg("profile_deleted", f"Profil silindi: {name}", name=name)
            if self.path == "/api/audition":
                act = b.get("action")
                if act == "record":
                    sec = b.get("seconds", 8)
                    if isinstance(sec, bool) or not isinstance(sec, int) or not 3 <= sec <= 20:
                        raise ValueError(Msg("err_seconds_range", "seconds 3–20"))
                    return AUDITION.record(store, sec)
                if act == "play":
                    return AUDITION.play(store, str(b.get("id", "")))
                if act == "stop":
                    return AUDITION.stop()
                raise ValueError("action")
            if self.path == "/api/diag":
                act = b.get("action")
                if act == "record":
                    return DIAG.record(str(b.get("step", "")))
                if act == "delete":
                    return DIAG.delete()
                raise ValueError("action")
            if self.path == "/api/trial":
                sec = b.get("seconds", 8)
                if isinstance(sec, bool) or not isinstance(sec, int) or not 3 <= sec <= 20:
                    raise ValueError(Msg("err_seconds_range", "seconds 3–20"))
                return Msg("recording_busy", "Başka bir kayıt sürüyor.") if (AUDITION.phase != "idle" or DIAG.phase != "idle") else "" if TRIAL.start(sec) else Msg("trial_busy", "Deneme zaten sürüyor.")
            if self.path == "/api/monitor":
                if TRIAL.phase != "idle":
                    return Msg("monitor_during_trial", "Deneme sürerken canlı dinleme değiştirilemez.")
                mode = b.get("mode")
                if mode not in ("off", "temiz", "ham"):
                    raise ValueError("mode")
                if DRY:
                    return ""
                run(sys.executable, MIC, "monitor", "off")
                if mode == "off":
                    return ""
                rc, out = run(sys.executable, MIC, "monitor", "on", mode)
                return "" if rc == 0 else Msg("monitor_failed", (out.splitlines() or [""])[-1], detail=(out.splitlines() or [""])[-1])
            return None

    return H


def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8767
    store, meter = Store(), Meter()
    push_live(store.state)  # sunucu açılırken canlı zincir kayıtlı durumla eşitlenir
    token = load_token()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))   # systemd stop → finally çalışsın
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, meter, port, token))
    srv.daemon_threads = True
    print(f"Mikrofon Konsolu: http://127.0.0.1:{srv.server_address[1]}/ (giriş adresi: mic console)", flush=True)
    try:
        srv.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        with LOCK:
            meter.clients = 0
            meter._stop()


if __name__ == "__main__":
    main()
