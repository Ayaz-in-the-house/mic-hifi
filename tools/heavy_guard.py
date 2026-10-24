"""Ağır yerel iş kilidi: bellek/önbellek yoğun araç ve testler TEK SIRADA, en düşük öncelikte koşar. Neden: aynı anda koşan ağır işler canlı ses
zincirindeki gürültü bastırıcının hesabını 1,5–2,5 kat yavaşlatır → ses kesintisi (ölçüldü; çizelgeleme çareleri etkisiz: docs/PRD-QUALITY.md "A0.8 teşhisi", D46).

    import heavy_guard; heavy_guard.guard("zincir kabul testi")      # dosyanın en başında, ağır içe aktarmalardan önce

Mikrofonu gerçek bir uygulama dinlerken ağır iş başlamaz (bekler; süre dolarsa çıkış kodu 3).
Kilit `flock` ile tutulur: süreç ölünce çekirdek bırakır. Korumalı sürecin başlattığı alt süreçler (ortamda MIC_HEAVY_HELD) yeniden kilitlemez.
Bitişte, iş sürerken canlı zincirin verdiği "Underrun" uyarısı varsa sayısını yazar (kusur görünür kalsın).
"""
import atexit, fcntl, os, subprocess, sys, time

_lock = None
METERS = ("GNOME Settings", "gnome-control-center", "pavucontrol", "PulseAudio Volume Control", "mic-console-meter", "mic-hifi-meter", "plasmashell", "pw-top")   # TEK tanım: watch.py buradan alır. "mic-console-meter" = panelin kendi göstergesi
MIC_PORTS = ("effect_output.mic_clean:", "effect_output.mic_main:")
INTERNAL = ("effect_input.mic_main", "mic_heavy")   # kalite hattının kendi iç bağları


def mic_listeners(links):
    """`pw-link -l` çıktısından: mikrofonu (temiz ya da kalite) dinleyen GERÇEK uygulamalar (ölçerler ve iç bağlar hariç)."""
    cur, res = None, set()
    for line in links.splitlines():
        if not line.startswith(" "):
            cur = line.strip()
        elif cur and cur.startswith(MIC_PORTS) and "|->" in line:
            node = line.split("|->", 1)[1].strip().rsplit(":", 1)[0]
            if not node.startswith(METERS) and node not in INTERNAL:
                res.add(node)
    return sorted(res)


def _links():
    fake = os.environ.get("MIC_HEAVY_PWLINK")   # sınama: çıktı dosyadan
    if fake:
        try:
            return open(fake, encoding="utf-8").read()
        except OSError:
            return ""
    try:
        return subprocess.run(["pw-link", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def wait_mic_free(name):
    """Mikrofonu gerçek bir uygulama dinliyorsa ağır iş BAŞLAMAZ: tek başına koşan ağır iş de kısa kesinti yapabiliyor (ölçüldü, PRD-QUALITY A0.8).
    MIC_HEAVY_WAIT sn (varsayılan 600) bekler; dolarsa çıkış kodu 3. Bilerek atlamak: MIC_HEAVY_FORCE=1 (yalnız kullanıcı isterse)."""
    if os.environ.get("MIC_HEAVY_FORCE") == "1":
        return
    limit, poll, t0, said = float(os.environ.get("MIC_HEAVY_WAIT", "600")), float(os.environ.get("MIC_HEAVY_POLL", "5")), time.time(), False
    while True:
        who = mic_listeners(_links())
        if not who:
            return
        if not said:
            print(f"[{name}] mikrofon kullanımda ({', '.join(who)}); ağır iş başlamıyor, bekleniyor…", file=sys.stderr, flush=True)
            said = True
        if time.time() - t0 >= limit:
            print(f"[{name}] mikrofon {limit:.0f} sn boyunca boşalmadı; iş koşmadı.", file=sys.stderr, flush=True)
            sys.exit(3)
        time.sleep(poll)


def guard(name):
    global _lock
    try:
        os.nice(19 - os.nice(0))
    except OSError:
        pass
    if os.environ.get("MIC_HEAVY_HELD"):
        return
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    path = os.environ.get("MIC_HEAVY_LOCK") or os.path.join(run, "mic-hifi-heavy.lock")
    _lock = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[{name}] başka bir ağır iş koşuyor; sırada bekliyor…", file=sys.stderr, flush=True)
        fcntl.flock(_lock, fcntl.LOCK_EX)
    wait_mic_free(name)   # kilit alındıktan sonra: sıradaki iş de mikrofon boşken başlar
    os.environ["MIC_HEAVY_HELD"] = "1"
    t0 = time.strftime("%Y-%m-%d %H:%M:%S")

    def report():
        try:
            n = subprocess.run(["journalctl", "--user", "-u", "mic-clean.service", "--since", t0, "--no-pager", "-o", "cat", "-g", "Underrun"],
                               capture_output=True, text=True, timeout=5).stdout.count("Underrun")
        except (OSError, subprocess.TimeoutExpired):
            return
        if n:
            print(f"[{name}] UYARI: bu iş sürerken canlı mikrofon zinciri {n} kesinti uyarısı verdi.", file=sys.stderr, flush=True)
    atexit.register(report)
