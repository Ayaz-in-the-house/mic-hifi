#!/usr/bin/env python3
"""V3 gözcü (tools/watch.py) + anahtarlayıcı + sahte modelli işçi BİRLİKTE — yalıtılmış PipeWire'da; canlıya dokunmaz. Tanımlar: docs/PRD-VOICE.md "Aşama 4".

W3 yalnız ölçer sınıfı dinleyen ("GNOME Settings") → işçi başlamaz (3 sn)            neden: ayar penceresi açıkken model boşuna koşmasın
W2 gerçek dinleyen bağlanınca başlatma kararı ≤ 300 ms; gidince (bekleme 1 sn) işçi yok, karıştırıcı (1, 0)   neden: kimse dinlemiyorken tüketme
W1 çıkış önce kuru (L), sonra ıslak (L − 6 dB; işçi kazancı 0,5); karıştırıcı (0, 1)     neden: üç parça birlikte, geçiş çalışıyor
W4 ıslakken işçiye SIGKILL → "kuru" olayı ≤ 300 ms; sonra yeniden ıslak, yeni süreç    neden: mikrofon işçiye bağlı ölmemeli
W5 ıslakken işçiye SIGSTOP → kalp atışı bayatlar, ≤ 1,5 sn içinde kuru + işçi öldürülür, sonra yeniden ıslak   neden: donmuş işçi sesi susturur
W6 gözcüye SIGKILL, yeniden başlat → açılışta karıştırıcı (1, 0), sahipsiz işçi kapatılır, sonra yeniden ıslak   neden: yarım durum kalıcı olmasın
W8 tüm senaryoda dinleyenin kaydı: sessiz koşu ≤ 1,5 sn VE duvar saati − kayıt süresi ≤ 1,5 sn   neden: donmuş işçi grafiği durdurur; bu sessizlik
   olarak değil EKSİK ZAMAN olarak görünür (ölçüldü: SIGSTOP → ~0,65 sn ses hiç gelmez)
W9 işçi çıkış kodu 75 ("kaynak yok") ile ölürse İLK denemede "kilitli", yeniden deneme yok    neden: kalıcı hata denemeyle düzelmez, her deneme kaynak harcar
W11 gözcü kuru bağı kendisi kurar; koparılınca ≤ 2 sn'de geri kurar   neden: canlıda bağı kuracak başka kimse yok; bağ yoksa mikrofon sessiz
W15 kalite mikrofonu gecikmesini bildirir: kuru/boşta 0 · taşıyıcıda/ıslakta işçinin D'si (14400 örnek) · işçi ölünce ve dinleyen gidince yeniden 0
    neden: görüntüyle kaydeden uygulama sesi eşleyebilsin; yanlış gecikme bildirmek, bildirmemekten kötü (O09)
W14 yüklemesi 3 sn süren işçi: dinleyenden ≤ 1,5 sn sonra "taşıyıcıda" (karıştırıcı (0, 1), işçi henüz kuru veriyor); yükleme sırasında SIGKILL → kuru ≤ 300 ms;
    sonra yeniden "taşıyıcıda" → "ıslak"     neden: açılıştaki zaman sıçraması başa çekilir (kaydın ortasına düşmez), güvenlik korunur
W13 kuru kaynak (temiz mikrofon süreci) yok olup geri gelince kuru bağ ≤ 2 sn'de yeniden kurulur   neden: mic-clean yeniden başlar (mod/perde); kalite mikrofonu sessiz kalmamalı
W12 boşta (dinleyen yok) gözcü + alt süreçleri 6 sn'de ≤ 0,12 sn işlemci kullanır (≤ %2 çekirdek)   neden: gözcü 7/24 koşar; kimse dinlemiyorken bedel ödenmez
W10 ıslaktayken kuantum 256 / 2048'e zorlanır → işçi ve gözcü yaşar, çıkış sürer (sessiz koşu ≤ 0,5 sn), sonda ıslak   neden: uygulamalar kuantumu değiştirir
W7 işçi her açılışta hemen ölürse: 3 denemeden sonra "kilitli", karıştırıcı kuru, yeni deneme yok   neden: çökme fırtınası olmasın
"""
import json, os, signal, subprocess, sys, time, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools"))
import carrier
from iso import Iso

PY = os.path.join(ROOT, "heavy", ".venv", "bin", "python")
if not os.path.exists(PY):
    print("ATLANDI: heavy/.venv yok → cd heavy && uv sync --frozen"); sys.exit(0)
SR = 48000
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


def events(path):
    try:
        return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except OSError:
        return []


def wait_event(path, pred, timeout, after=0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        hit = [e for e in events(path)[after:] if pred(e)]
        if hit:
            return hit[0]
        time.sleep(0.05)
    return None


def mixer(iso):
    for o in json.loads(iso.out("pw-dump", timeout=10) or "[]"):
        if (o.get("info") or {}).get("props", {}).get("node.name") == carrier.MAIN_IN:
            d = {}
            for pr in o["info"].get("params", {}).get("Props", []):
                p = pr.get("params") or []
                d.update(zip(p[::2], p[1::2]))
            return round(float(d.get("mix:Gain 1", -1)), 3), round(float(d.get("mix:Gain 2", -1)), 3)
    return None


def setup(iso, link_dry=True):
    conf = os.path.join(iso.dir, "main.conf")
    open(conf, "w").write(carrier.render_main("iso"))
    iso.spawn("pipewire", "-c", conf)
    if not iso.wait_port(carrier.DRY_PORT, 8):
        raise RuntimeError("anahtarlayıcı ayağa kalkmadı")
    if link_dry:
        iso.link("fake_mic:capture_FL", carrier.DRY_PORT)
    tone = os.path.join(iso.dir, "tone.wav")
    w = wave.open(tone, "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((0.3 * np.sin(2 * np.pi * 1000 * np.arange(SR * 90) / SR) * 32767).astype(np.int16).tobytes()); w.close()
    iso.play(tone, "fake_mic", wait=False)


def start_watch(iso, ev, worker_cmd, status):
    return iso.spawn(sys.executable, os.path.join(ROOT, "tools", "watch.py"), "--worker-cmd", worker_cmd, "--status", status, "--model-src", "fake_mic:capture_FL",
                     "--dry-src", "fake_mic:capture_FL", "--hold", "1", "--events", ev, "--start-timeout", "10")


def listener(iso, name, wav):
    return iso.spawn("pw-cat", "-r", "--target", carrier.MAIN_OUT, "-P", '{ node.name = "%s" }' % name, "--channels", "1", "--rate", "48000", "--format", "s16", wav)


def alive(pid):
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    cmd = f"pw-jack {PY} {os.path.join(ROOT, 'heavy', 'worker.py')} --delay-ms 300 --block 4800 --gain 0.5 --status {status}"
    w = start_watch(iso, ev, cmd, status)
    ready = wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    # W3
    m = listener(iso, "GNOME Settings", os.path.join(iso.dir, "meter.wav"))
    time.sleep(3.0)
    started = [e for e in events(ev) if e["event"] == "işçi başlatıldı"]
    check("W3", ready is not None and not started, f"gözcü hazır: {ready is not None} · ölçer dinlerken işçi başlatma sayısı {len(started)} (= 0)")
    m.terminate(); m.wait()
    # W2a + W1
    rec = os.path.join(iso.dir, "app.wav")
    app = listener(iso, "gorusme-uygulamasi", rec)
    t_app0 = time.time()
    t_link = None
    for _ in range(200):
        if "gorusme-uygulamasi" in iso.out("pw-link", "-l"):
            t_link = time.time(); break
        time.sleep(0.02)
    e_start = wait_event(ev, lambda e: e["event"] == "işçi başlatıldı", 5)
    e_wet = wait_event(ev, lambda e: e["event"] == "ıslak", 15)
    time.sleep(1.5)
    mx = mixer(iso)
    lat = (e_start["t"] - t_link) if (e_start and t_link) else None
    ok2a = lat is not None and lat <= 0.3
    pid1 = json.load(open(status)).get("pid") if os.path.exists(status) else None
    # W4
    n0 = len(events(ev)); t_kill = time.time()
    os.kill(pid1, signal.SIGKILL)
    e_dry = wait_event(ev, lambda e: e["event"] == "kuru", 5, n0)
    e_wet2 = wait_event(ev, lambda e: e["event"] == "ıslak", 15, n0)
    time.sleep(1.0)
    pid2 = json.load(open(status)).get("pid")
    check("W4", e_dry is not None and e_dry["t"] - t_kill <= 0.3 and e_wet2 is not None and pid2 != pid1 and mixer(iso) == (0.0, 1.0),
          f"SIGKILL → kuru {(e_dry['t'] - t_kill) * 1000 if e_dry else -1:.0f} ms (≤ 300) · yeniden ıslak: {e_wet2 is not None} · yeni süreç: {pid2 != pid1}")
    # W5
    n0 = len(events(ev)); t_stop = time.time()
    os.kill(pid2, signal.SIGSTOP)
    e_dry5 = wait_event(ev, lambda e: e["event"] == "kuru", 5, n0)
    e_wet5 = wait_event(ev, lambda e: e["event"] == "ıslak", 15, n0)
    time.sleep(1.0)
    pid3 = json.load(open(status)).get("pid")
    check("W5", e_dry5 is not None and e_dry5.get("neden") == "işçi dondu" and e_dry5["t"] - t_stop <= 1.5 and not alive(pid2) and e_wet5 is not None and pid3 != pid2,
          f"SIGSTOP → kuru {(e_dry5['t'] - t_stop) * 1000 if e_dry5 else -1:.0f} ms (≤ 1500), neden {e_dry5.get('neden') if e_dry5 else None} · donmuş süreç öldü: {not alive(pid2)} · yeniden ıslak: {e_wet5 is not None}")
    # W6
    w.send_signal(signal.SIGKILL); w.wait()
    ev2 = os.path.join(iso.dir, "ev2.jsonl")
    w = start_watch(iso, ev2, cmd, status)
    e_ready2 = wait_event(ev2, lambda e: e["event"] == "gözcü hazır", 5)
    mx_boot = mixer(iso)
    orphan = [e for e in events(ev2) if e["event"] == "sahipsiz işçi kapatıldı"]
    e_wet6 = wait_event(ev2, lambda e: e["event"] == "ıslak", 15)
    time.sleep(1.0)
    check("W6", e_ready2 is not None and mx_boot == (1.0, 0.0) and len(orphan) == 1 and not alive(pid3) and e_wet6 is not None and mixer(iso) == (0.0, 1.0),
          f"açılışta karıştırıcı {mx_boot} (= (1, 0)) · sahipsiz işçi kapatıldı: {len(orphan) == 1 and not alive(pid3)} · yeniden ıslak: {e_wet6 is not None}")
    # W2b: dinleyen gider
    pid4 = json.load(open(status)).get("pid")
    t_app1 = time.time()
    app.terminate(); app.wait()
    e_gone = wait_event(ev2, lambda e: e["event"] == "işçi kapatıldı" and e.get("neden") == "dinleyen yok", 6)
    time.sleep(0.5)
    mx_end = mixer(iso)
    check("W2", ok2a and e_gone is not None and not alive(pid4) and mx_end == (1.0, 0.0),
          f"başlatma kararı {lat * 1000 if lat is not None else -1:.0f} ms (≤ 300) · dinleyen gidince işçi kapandı: {e_gone is not None and not alive(pid4)} · karıştırıcı {mx_end}")
    # W1 + W8: kayıt
    # Veri dosya boyutundan okunur (başlığa güvenmeden).
    raw = open(rec, "rb").read()
    data = raw[raw.index(b"data") + 8:]
    y = np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float64) / 32768
    n = SR // 50
    f = 20 * np.log10(np.sqrt((y[:len(y) // n * n].reshape(-1, n) ** 2).mean(1)) + 1e-9)
    first = int(np.argmax(f > -40))
    L = float(np.median(f[first + 2:first + 12]))                     # ilk plato: kuru
    wet_frames = np.where(np.abs(f - (L - 6.02)) <= 1.0)[0]
    dry_frames = np.where(np.abs(f - L) <= 1.0)[0]
    check("W1", e_wet is not None and mx == (0.0, 1.0) and len(wet_frames) > 100 and len(dry_frames) > 20 and wet_frames[0] > first,
          f"kuru plato {L:.1f} dBFS ({len(dry_frames) * 20} ms) → ıslak plato {L - 6:.1f} ± 1 dBFS ({len(wet_frames) * 20} ms) · ıslaktayken karıştırıcı {mx}")
    quiet = (f[first:] < -50).astype(int)
    runs = [len(r) for r in "".join(map(str, quiet)).split("0") if r]
    missing = (t_app1 - t_app0) - len(y) / SR   # dinleyene HİÇ ulaşmayan süre (grafik durması sessizlik olarak değil, eksik zaman olarak görünür)
    check("W8", (max(runs) if runs else 0) * 0.02 <= 1.5 and missing <= 1.5,
          f"ilk sesten sonra sessiz kare toplamı {sum(runs) * 20} ms, en uzun koşu {(max(runs) if runs else 0) * 20} ms (≤ 1500) · dinleyene ulaşmayan süre {missing * 1000:.0f} ms (≤ 1500; donma senaryosu + kayıt başlangıcı dahil) · kayıt {len(y) / SR:.1f} sn")

with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    w = start_watch(iso, ev, "false", status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    app = listener(iso, "gorusme-uygulamasi", os.path.join(iso.dir, "app.wav"))
    e_lock = wait_event(ev, lambda e: e["event"] == "kilitli", 12)
    n_start = len([e for e in events(ev) if e["event"] == "işçi başlatıldı"])
    time.sleep(3.0)
    n_after = len([e for e in events(ev) if e["event"] == "işçi başlatıldı"])
    check("W7", e_lock is not None and n_start == 3 and n_after == 3 and mixer(iso) == (1.0, 0.0),
          f"başlatma denemesi {n_start} (= 3) · kilitli: {e_lock is not None} · sonraki 3 sn'de yeni deneme {n_after - n_start} (= 0) · karıştırıcı {mixer(iso)}")

with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    w = start_watch(iso, ev, "sh -c 'exit 75'", status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    app = listener(iso, "gorusme-uygulamasi", os.path.join(iso.dir, "app.wav"))
    e_lock = wait_event(ev, lambda e: e["event"] == "kilitli", 8)
    time.sleep(2.0)
    n_start = len([e for e in events(ev) if e["event"] == "işçi başlatıldı"])
    check("W9", e_lock is not None and n_start == 1 and "75" in str(e_lock.get("neden")) and mixer(iso) == (1.0, 0.0),
          f"çıkış kodu 75 → başlatma denemesi {n_start} (= 1) · kilitli: {e_lock is not None} ({e_lock.get('neden') if e_lock else None}) · karıştırıcı {mixer(iso)}")

with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    cmd = f"pw-jack {PY} {os.path.join(ROOT, 'heavy', 'worker.py')} --delay-ms 300 --block 4800 --gain 0.5 --status {status}"
    w = start_watch(iso, ev, cmd, status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    rec = os.path.join(iso.dir, "app.wav")
    app = listener(iso, "gorusme-uygulamasi", rec)
    ok_wet = wait_event(ev, lambda e: e["event"] == "ıslak", 15) is not None
    time.sleep(1.0)
    pid = json.load(open(status)).get("pid")
    quanta = []
    for q in (256, 2048, 0):
        iso.run("pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(q))
        time.sleep(2.5)
        applied = f"value:'{q}'" in iso.out("pw-metadata", "-n", "settings", "0", "clock.force-quantum").replace('"', "'")   # gerçekten uygulandı mı (yanlış nedenle geçmesin)
        quanta.append((q, alive(pid) and applied, w.poll() is None))
    time.sleep(1.0)
    st = json.load(open(status))
    app.terminate(); app.wait()
    raw = open(rec, "rb").read(); data = raw[raw.index(b"data") + 8:]
    y = np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float64) / 32768
    n = SR // 50; f = 20 * np.log10(np.sqrt((y[:len(y) // n * n].reshape(-1, n) ** 2).mean(1)) + 1e-9)
    first = int(np.argmax(f > -40)); quiet = (f[first:] < -50).astype(int)
    runs = [len(r) for r in "".join(map(str, quiet)).split("0") if r]
    final_wet = [e["event"] for e in events(ev) if e["event"] in ("ıslak", "kuru")][-1] == "ıslak"
    check("W10", ok_wet and all(a and b for _q, a, b in quanta) and (max(runs) if runs else 0) * 0.02 <= 0.5 and final_wet,
          f"kuantum 256 / 2048 / serbest: işçi ve gözcü yaşıyor {[(q, a and b) for q, a, b in quanta]} · en uzun sessiz koşu {(max(runs) if runs else 0) * 20} ms (≤ 500) · sonda ıslak: {final_wet} · işçi xrun {st.get('xruns')} · düşüş {st.get('fallback_count')}")

with Iso() as iso:
    setup(iso, link_dry=False)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    w = start_watch(iso, ev, "false", status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    has = lambda: any(carrier.DRY_PORT in l for l in iso.out("pw-link", "-l").splitlines())
    time.sleep(0.5)
    at_boot = has()
    iso.run("pw-link", "-d", "fake_mic:capture_FL", carrier.DRY_PORT)
    cut = not has()
    t0 = time.time(); back = None
    while time.time() - t0 < 4:
        if has():
            back = time.time() - t0; break
        time.sleep(0.05)
    check("W11", at_boot and cut and back is not None and back <= 2.0, f"açılışta kuru bağ: {at_boot} · koparıldı: {cut} · geri kuruldu: {f'{back * 1000:.0f} ms' if back is not None else 'HAYIR'} (≤ 2000)")

    def cpu(pid):
        f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        return sum(int(f[i]) for i in (11, 12, 13, 14)) / os.sysconf("SC_CLK_TCK")   # kendi + toplanmış alt süreçler
    time.sleep(1.0)
    c0 = cpu(w.pid); time.sleep(6.0); used = cpu(w.pid) - c0
    check("W12", used <= 0.12, f"boşta 6 sn'de gözcü + alt süreçleri {used:.2f} sn işlemci (%{used / 6 * 100:.1f} çekirdek; ≤ 0,12 sn)")

with Iso() as iso:
    conf = os.path.join(iso.dir, "main.conf"); open(conf, "w").write(carrier.render_main("iso")); iso.spawn("pipewire", "-c", conf)
    assert iso.wait_port(carrier.DRY_PORT, 8)
    mk = lambda: iso.spawn("pw-loopback", "--capture-props", "{ node.name = tmp_cap node.autoconnect = false }",
                           "--playback-props", "{ media.class = Audio/Source node.name = tmp_src audio.position = [ MONO ] }")
    lb = mk(); assert iso.wait_port("tmp_src:capture_MONO", 5)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    iso.spawn(sys.executable, os.path.join(ROOT, "tools", "watch.py"), "--worker-cmd", "false", "--status", status, "--model-src", "tmp_src:capture_MONO",
              "--dry-src", "tmp_src:capture_MONO", "--hold", "1", "--events", ev)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    has = lambda: any(carrier.DRY_PORT in l for l in iso.out("pw-link", "-l").splitlines())
    time.sleep(0.5); at_boot = has()
    lb.terminate(); lb.wait(); time.sleep(1.5); gone = not has()
    lb = mk(); iso.wait_port("tmp_src:capture_MONO", 5); t0 = time.time(); back = None
    while time.time() - t0 < 12:
        if has():
            back = time.time() - t0; break
        time.sleep(0.05)
    check("W13", at_boot and gone and back is not None and back <= 2.0, f"açılışta bağ: {at_boot} · kaynak gidince bağ yok: {gone} · kaynak dönünce bağ: {f'{back * 1000:.0f} ms' if back is not None else 'HAYIR'} (≤ 2000)")

with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    cmd = f"pw-jack {PY} {os.path.join(ROOT, 'heavy', 'worker.py')} --delay-ms 300 --block 4800 --gain 0.5 --load-delay 3 --status {status}"
    start_watch(iso, ev, cmd, status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    app = listener(iso, "gorusme-uygulamasi", os.path.join(iso.dir, "app14.wav"))
    e_l = wait_event(ev, lambda e: e["event"] == "dinleyen", 5)
    e_c = wait_event(ev, lambda e: e["event"] == "taşıyıcıda", 4)
    time.sleep(0.3)
    mx_c, st_c = mixer(iso), (json.load(open(status)) if os.path.exists(status) else {})
    n0 = len(events(ev)); t_kill = time.time()
    if st_c.get("pid"):
        os.kill(st_c["pid"], signal.SIGKILL)
    e_dry = wait_event(ev, lambda e: e["event"] == "kuru", 3, n0)
    e_c2 = wait_event(ev, lambda e: e["event"] == "taşıyıcıda", 6, n0)
    e_wet = wait_event(ev, lambda e: e["event"] == "ıslak", 10, n0)
    lat = (e_c["t"] - e_l["t"]) if (e_c and e_l) else None
    check("W14", lat is not None and lat <= 1.5 and mx_c == (0.0, 1.0) and st_c.get("wet") == 0.0 and e_dry is not None and e_dry["t"] - t_kill <= 0.3
          and e_c2 is not None and e_wet is not None and e_wet["t"] > e_c2["t"],
          f"dinleyen → taşıyıcıda {f'{lat * 1000:.0f} ms' if lat is not None else 'YOK'} (≤ 1500) · o an karıştırıcı {mx_c}, işçi ıslak {st_c.get('wet')} (0) · "
          f"yüklenirken SIGKILL → kuru {(e_dry['t'] - t_kill) * 1000 if e_dry else -1:.0f} ms (≤ 300) · yeniden taşıyıcıda: {e_c2 is not None} · sonra ıslak: {e_wet is not None}")

with Iso() as iso:
    setup(iso)
    status, ev = os.path.join(iso.dir, "heavy.json"), os.path.join(iso.dir, "ev.jsonl")
    cmd = f"pw-jack {PY} {os.path.join(ROOT, 'heavy', 'worker.py')} --delay-ms 300 --block 4800 --status {status}"
    start_watch(iso, ev, cmd, status)
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    def reported():
        """Kalite mikrofonunun çıkış portunda bildirilen (çıkış yönü) gecikme, örnek."""
        cur = None
        for l in iso.out("pw-link", "-t", "-o").splitlines():
            if not l.startswith(" "):
                cur = l.strip()
            elif cur == carrier.MAIN_OUT + ":capture_MONO" and "output latency" in l:
                return int(l.split("rate=[")[1].split()[0])
        return None
    time.sleep(0.5); r_idle = reported()
    app = listener(iso, "gorusme-uygulamasi", os.path.join(iso.dir, "app15.wav"))
    wait_event(ev, lambda e: e["event"] == "ıslak", 10); time.sleep(0.5); r_wet = reported()
    n0 = len(events(ev)); os.kill(json.load(open(status))["pid"], signal.SIGKILL)
    wait_event(ev, lambda e: e["event"] == "kuru", 3, n0); time.sleep(0.15); r_dead = reported()
    wait_event(ev, lambda e: e["event"] == "ıslak", 10, n0); time.sleep(0.5); r_wet2 = reported()
    app.terminate(); app.wait()
    wait_event(ev, lambda e: e["event"] == "işçi kapatıldı" and e.get("neden") == "dinleyen yok", 6); time.sleep(0.5); r_gone = reported()
    check("W15", (r_idle, r_wet, r_dead, r_wet2, r_gone) == (0, 14400, 0, 14400, 0), f"bildirilen gecikme (örnek): boşta {r_idle} · ıslak {r_wet} · işçi ölünce {r_dead} · yeniden ıslak {r_wet2} · dinleyen gidince {r_gone} (= 0, 14400, 0, 14400, 0)")

print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
