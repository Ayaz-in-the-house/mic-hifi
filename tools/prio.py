#!/usr/bin/env python3
"""Gürültü bastırıcının iş parçacığına yüksek öncelik verir (rtkit, nice −11). Kök yetkisi gerekmez; yinelenebilir.

Neden: DeepFilterNet LADSPA sesi PipeWire'ın gerçek zamanlı döngüsünde değil, kendi NORMAL öncelikli iş parçacığında işler.
Makine yoğunken bu iş parçacığı geride kalır → "Underrun detected" → seste kesinti (ölçüldü 2026-10-10: bir saatte 114 uyarı).
PipeWire'ın kendi iş parçacıkları (ana, module-rt, data-loop) hariç, mic-clean sürecindeki her iş parçacığı yükseltilir.
Bastırıcı HER etkinleşmede (biri mikrofonu dinlemeye başlayınca) YENİ bir iş parçacığı doğurur (ölçüldü) → tek seferlik yükseltme
yetmez. `--watch` PipeWire olaylarına abone olur (`pactl subscribe`, olay yokken uyur — yoklama yok) ve her kaynak/kayıt olayında yükseltir.
Kullanım: prio.py [--wait SANİYE] | --watch
Çıkış: 0 = en az bir iş parçacığı −11'de · 1 = bulunamadı/yükseltilemedi
"""
import os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain

NICE = -11
SETTLE_S, COOLDOWN_S = 6.0, 20.0
SKIP = ("module-rt", "data-loop")


def main_pid():
    out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", "mic-clean.service"], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() and out != "0" else None


def workers(pid):
    res = []
    for tid in os.listdir(f"/proc/{pid}/task"):
        try:
            comm = open(f"/proc/{pid}/task/{tid}/comm").read().strip()
            stat = open(f"/proc/{pid}/task/{tid}/stat").read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(tid) == pid or comm.startswith(SKIP):
            continue
        res.append((int(tid), int(stat[16])))  # stat alanı 19 = nice
    return res


def boost(pid, tid):
    return subprocess.run(["busctl", "call", "--system", "org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1",
                           "org.freedesktop.RealtimeKit1", "MakeThreadHighPriorityWithPID", "tti", "--", str(pid), str(tid), str(NICE)],
                          capture_output=True, text=True).returncode == 0


def run(wait=0.0):
    end = time.time() + wait
    while True:
        pid = main_pid()
        ws = workers(pid) if pid else []
        for tid, nice in ws:
            if nice > NICE:
                boost(pid, tid)
        ws = workers(pid) if pid else []
        if any(n <= NICE for _t, n in ws):
            return True, ws
        if time.time() >= end:
            return False, ws
        time.sleep(0.5)


def needs_repair(sources, active_seconds, since_last_repair, service_active):
    """Zincir, hedef mikrofon yokken başlarsa sanal mikrofonu hiç oluşturmaz ve mikrofon gelince de toparlanmaz (E30).
    Ham mikrofon görünüyor ama temiz kaynak yoksa servis yeniden başlatılır — servis çalışıyorsa, oturmuşsa ve yakın zamanda onarılmadıysa."""
    return bool(service_active and chain.RAW_SOURCE in sources and chain.CLEAN_SOURCE not in sources
                and active_seconds >= SETTLE_S and since_last_repair >= COOLDOWN_S)


STAMP = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "mic-hifi", "repairs")
BUDGET_N, BUDGET_S = 3, 600.0


def budget_ok(times, now):
    """Onarım bütçesi: 10 dakikada en çok 3 yeniden başlatma (neden başka bir şeyse fırtına olmasın)."""
    return sum(1 for t in times if now - t < BUDGET_S) < BUDGET_N


def repair_times():
    try:
        return [float(x) for x in open(STAMP).read().split()]
    except (OSError, ValueError):
        return []


def note_repair(now):
    os.makedirs(os.path.dirname(STAMP), mode=0o700, exist_ok=True)
    keep = [t for t in repair_times() if now - t < BUDGET_S] + [now]
    open(STAMP, "w").write(" ".join(f"{t:.1f}" for t in keep))


def card_of(source):
    """alsa_input.<kart>.<profil> → alsa_card.<kart>"""
    return "alsa_card." + source[len("alsa_input."):].rsplit(".", 1)[0]


def wanted_profile(active, available):
    """Etkin profilde analog giriş yoksa, analog girişli bir profil döndürür (çıkışı da taşıyanı yeğler); gerekmezse None."""
    if not active or "input:analog-stereo" in active:
        return None
    for cand in ("output:analog-stereo+input:analog-stereo", "input:analog-stereo"):
        if cand in available:
            return cand
    return None


def card_profile(env):
    import json
    try:
        cards = json.loads(subprocess.run(["pactl", "-f", "json", "list", "cards"], env=env, capture_output=True, text=True).stdout or "[]")
    except ValueError:
        return None, []
    c = next((c for c in cards if c.get("name") == card_of(chain.RAW_SOURCE)), None)
    return (c.get("active_profile"), list(c.get("profiles", {}))) if c else (None, [])


def prestart(probe, set_profile, sleep=time.sleep, settle=1.5, timeout=12.0, step=0.5):
    """Zincir BAŞLAMADAN önce: hedef mikrofon görünür olsun (E29/E30'un kök çaresi; bekçi son savunma kalır).
    probe() → (etkin profil, profiller, ham kaynak var mı) · set_profile(ad). Süre sınırlıdır: kaynak gelmezse servis yine başlar.
    Oturma payı: servis durunca varsayılan giriş yok olur ve oturumdaki bir bileşen profili DEĞİŞTİREBİLİR; hemen bakılırsa kayma henüz olmamıştır."""
    sleep(settle)
    waited, fixed = 0.0, []
    while True:
        active, available, raw = probe()
        want = wanted_profile(active, available)
        if want and want not in fixed[-1:]:
            set_profile(want); fixed.append(want)
        elif raw and not want:
            return {"ready": True, "waited": waited, "fixed": fixed}
        if waited >= timeout:
            return {"ready": False, "waited": waited, "fixed": fixed}
        sleep(step); waited += step


def prestart_main():
    env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")

    def probe():
        active, available = card_profile(env)
        out = subprocess.run(["pactl", "list", "sources", "short"], env=env, capture_output=True, text=True).stdout
        return active, available, chain.RAW_SOURCE in out

    r = prestart(probe, lambda p: subprocess.run(["pactl", "set-card-profile", card_of(chain.RAW_SOURCE), p], env=env))
    if r["fixed"]:
        open_pending()
    print(f"ön başlatma: {'hedef hazır' if r['ready'] else 'hedef YOK (yine de başlatılıyor)'} · bekleme {r['waited']:.1f} sn · profil düzeltmesi {r['fixed'] or 'gerekmedi'}", flush=True)


def configured_default_source(text):
    """`wpctl status` çıktısından kullanıcının SEÇTİĞİ varsayılan giriş (o an geçerli olan değil)."""
    on = False
    for line in text.splitlines():
        if "Default Configured" in line:
            on = True
        elif on and "Audio/Source" in line:
            return line.split("Audio/Source", 1)[1].strip()
    return None


def poststart(get_sources, get_default, get_configured, set_default, sleep=time.sleep, timeout=10.0, step=0.25, hijacked=False):
    """Zincir başladıktan sonra: temiz kaynak görününce, kullanıcının seçili varsayılanı oysa, varsayılan girişi HEMEN geri yaz.
    Oturum yöneticisi bunu kendiliğinden de yapıyor ama saniyeler sonra (ölçüldü: 6 sn'de hâlâ ham mikrofon); o pencerede açılan uygulama ham sesi alır.
    Kullanıcı başka bir mikrofonu varsayılan seçtiyse DOKUNMAZ."""
    waited = 0.0
    while chain.CLEAN_SOURCE not in get_sources():
        if waited >= timeout:
            return {"restored": False, "why": "temiz kaynak görünmedi", "waited": waited}
        sleep(step); waited += step
    # hijacked: ön başlatma profil kayması düzeltti. Kayma, varsayılan giriş (temiz kaynak) yok olunca başka girişin SEÇİLMESİYLE olur; yani
    # kullanıcının varsayılanı temiz kaynaktı ve "seçili varsayılan" kaydı da o anda ezildi (ölçüldü: kayıt başka kaynağı gösteriyordu).
    if not hijacked and get_configured() != chain.CLEAN_SOURCE:
        return {"restored": False, "why": "kullanıcının seçili varsayılanı başka", "waited": waited}
    if get_default() == chain.CLEAN_SOURCE:
        return {"restored": False, "why": "zaten varsayılan", "waited": waited}
    set_default(chain.CLEAN_SOURCE)
    return {"restored": True, "why": "", "waited": waited}


def poststart_main():
    env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    out = lambda *c: subprocess.run(c, env=env, capture_output=True, text=True).stdout
    hijacked = os.path.exists(PENDING)
    r = poststart(lambda: out("pactl", "list", "sources", "short"), lambda: out("pactl", "get-default-source").strip(),
                  lambda: configured_default_source(out("wpctl", "status")), lambda s: subprocess.run(["pactl", "set-default-source", s], env=env), hijacked=hijacked)
    if hijacked and (r["restored"] or r["why"] == "zaten varsayılan"):
        try:
            os.remove(PENDING)
        except OSError:
            pass
    print(f"son başlatma: varsayılan giriş {'temiz kaynağa geri yazıldı' if r['restored'] else 'değiştirilmedi (' + r['why'] + ')'} · {r['waited']:.2f} sn", flush=True)


def open_pending():
    os.makedirs(os.path.dirname(STAMP), mode=0o700, exist_ok=True)
    open(PENDING, "w").close()


PENDING = STAMP + ".default"   # onarımdan sonra varsayılan giriş temiz kaynağa geri yazılacak


def restore_default(env, sources):
    if os.path.exists(PENDING) and chain.CLEAN_SOURCE in sources:
        subprocess.run(["pactl", "set-default-source", chain.CLEAN_SOURCE], env=env)
        os.remove(PENDING)
        print("varsayılan giriş temiz kaynağa geri yazıldı", flush=True)


def maybe_repair(env):
    """Zincir sağlam mı? Değilse ve bütçe varsa yeniden başlat. Bu servis mic-clean'e bağlı olduğu için kendisi de yeniden başlar;
    son onarım zamanı bu yüzden dosyada tutulur."""
    sources, age, active = chain_status(env)
    now, times = time.time(), repair_times()
    restore_default(env, sources)
    want = wanted_profile(*card_profile(env)) if active and chain.RAW_SOURCE not in sources else None
    if want and budget_ok(times, now):   # kart dijital girişe kaymış (E29): analog profili geri yaz; kaynak gelince zincir onarılır
        note_repair(now - COOLDOWN_S)    # bütçeye sayılır ama ardından gelen zincir onarımını bekletmez
        open(PENDING, "w").close()
        print(f"onarım: kart profili analog girişe geri alınıyor ({want})", flush=True)
        subprocess.run(["pactl", "set-card-profile", card_of(chain.RAW_SOURCE), want], env=env)
        return True
    if not needs_repair(sources, age, now - max(times, default=0.0), active):
        return False
    if not budget_ok(times, now):
        print(f"onarım ATLANDI: {BUDGET_S / 60:.0f} dakikada {BUDGET_N} deneme doldu; elle bak: journalctl --user -u mic-clean", flush=True)
        return False
    note_repair(now)
    open(PENDING, "w").close()
    print("onarım: ham mikrofon var, temiz kaynak yok → mic-clean yeniden başlatılıyor", flush=True)
    subprocess.Popen(["systemctl", "--user", "--no-block", "restart", "mic-clean.service"], env=env)
    return True


def chain_status(env):
    out = subprocess.run(["pactl", "list", "sources", "short"], env=env, capture_output=True, text=True).stdout
    sources = {l.split("\t")[1] for l in out.splitlines() if "\t" in l}
    show = subprocess.run(["systemctl", "--user", "show", "mic-clean.service", "-p", "ActiveState", "-p", "ActiveEnterTimestampMonotonic"],
                          capture_output=True, text=True).stdout
    kv = dict(l.split("=", 1) for l in show.splitlines() if "=" in l)
    active = kv.get("ActiveState") == "active"
    try:
        age = time.clock_gettime(time.CLOCK_MONOTONIC) - int(kv.get("ActiveEnterTimestampMonotonic", "0")) / 1e6
    except ValueError:
        age = 0.0
    return sources, age, active


def watch():
    env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    run(1.0)
    time.sleep(SETTLE_S)                   # açılışta mikrofon zincirden SONRA gelmiş olabilir: oturduktan sonra bir kez bak
    maybe_repair(env)
    p = subprocess.Popen(["pactl", "subscribe"], env=env, stdout=subprocess.PIPE, text=True)
    last = 0.0
    for line in p.stdout:   # olay gelene dek burada uyur
        if "source" not in line and "card" not in line:   # kaynak/kayıt olayları + kart (profil) değişimi
            continue
        if "source-output" not in line:    # kaynak geldi/gitti ya da profil değişti → zincir sağlam mı?
            time.sleep(1.0)                # düğümlerin oluşması için kısa pay
            if maybe_repair(env):
                continue
        if time.time() - last < 0.3:       # aynı olayın yinelemeleri
            continue
        ok, ws = run(1.5)
        last = time.time()
        if ok:
            print("yükseltildi: " + ", ".join(f"tid {t} nice {n}" for t, n in ws if n <= NICE), flush=True)
    sys.exit(p.wait() or 1)                # pactl öldüyse servis yeniden başlasın


def plugin_gate():
    """Zincir başlamadan önce: kullanıcı dizinindeki ikili eklentilerin özeti kilitle aynı mı. Uyuşmayan, okunamayan ya da eksik zorunlu eklenti varsa
    ses yoluna YÜKLENMEZ: çıkış 78 (birimde RestartPreventExitStatus=78 → yeniden denenmez). docs/PRD-PUBLISH.md Y3."""
    import plugins
    try:
        st = plugins.status()
        rc = plugins.verdict(st)
    except (OSError, ValueError, KeyError) as e:
        print(f"eklenti kapısı: kilit okunamadı ({e}) → zincir BAŞLATILMIYOR", flush=True)
        return 78
    if rc:
        bad = ", ".join(f"{n} ({v['state']})" for n, v in st.items() if v["state"] in ("mismatch", "unreadable") or (v["state"] == "missing" and v["required"]))
        print(f"eklenti kapısı: {bad} → zincir BAŞLATILMIYOR. Denetle: python3 tools/plugins.py check", flush=True)
        return 78
    return 0


if __name__ == "__main__":
    if "--plugin-gate" in sys.argv:
        sys.exit(plugin_gate())
    if "--prestart" in sys.argv:
        prestart_main()
        sys.exit(0)
    if "--poststart" in sys.argv:
        poststart_main()
        sys.exit(0)   # her durumda 0: ön başlatma servisi ASLA engellemez
    if "--watch" in sys.argv:
        watch()
    w = float(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 0.0
    ok, ws = run(w)
    print(("yükseltildi" if ok else "iş parçacığı yok/yükseltilemedi") + ": " + (", ".join(f"tid {t} nice {n}" for t, n in ws) or "—"))
    sys.exit(0 if ok else 1)
