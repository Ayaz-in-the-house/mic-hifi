#!/usr/bin/env python3
"""Ağır iş kilidi (tools/heavy_guard.py) — docs/PRD-QUALITY.md "A0.8 teşhisi". Canlıya dokunmaz (ayrı kilit dosyası).

H1 iki korumalı süreç aynı anda başlar → çalışma aralıkları örtüşmez; ikincisi "sırada bekliyor" yazar   neden: paralel ağır iş canlı mikrofonu keser (ölçüldü)
H2 korumalı süreç nice 19                                                                              neden: canlı zincire öncelik
H3 kilidi tutan süreç SIGKILL alır → bekleyen ≤ 2 sn'de devam eder                                      neden: ölü süreç kilidi tutmamalı
H5 mikrofonu gerçek bir uygulama dinlerken korumalı iş başlamaz ("mikrofon kullanımda"), dinleyen gidince devam eder   neden: kullanıcının görüşmesi kesilmesin
H6 bekleme süresi dolarsa çıkış kodu 3, iş koşmaz                                                                    neden: sonsuz bekleme yok
H7 yalnız ölçer ya da kalite mikrofonunun iç bağı dinliyorsa beklemeden başlar                                        neden: gösterge gerçek kullanım değil
H4 korumalı sürecin başlattığı korumalı alt süreç beklemez                                             neden: testler aracı alt süreç olarak çağırır
"""
import os, signal, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = tempfile.mkdtemp(prefix="hg-")
open(os.path.join(d, "bos-graf.txt"), "w").close()
env = dict(os.environ, MIC_HEAVY_LOCK=os.path.join(d, "lock"), PYTHONPATH=os.path.join(ROOT, "tools"),
           MIC_HEAVY_PWLINK=os.path.join(d, "bos-graf.txt"))   # H1–H4 canlı grafiğe bağlı olmasın (panel açıkken düşüyordu: E63)
env.pop("MIC_HEAVY_HELD", None)
fails, ran = [], []


def check(tp, ok, msg=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {msg}", flush=True)
    if not ok: fails.append(tp)


JOB = "import heavy_guard, os, sys, time\nheavy_guard.guard('sinama')\nprint('B', time.time(), os.nice(0), flush=True)\ntime.sleep(float(sys.argv[1]))\nprint('E', time.time(), flush=True)\n"
NEST = ("import heavy_guard, subprocess, sys, time\nheavy_guard.guard('dis')\nt = time.time()\n"
        "subprocess.run([sys.executable, '-c', \"import heavy_guard; heavy_guard.guard('ic')\"], timeout=10)\nprint('N', time.time() - t, flush=True)\n")
run = lambda code, *a: subprocess.Popen([sys.executable, "-c", code, *a], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def spans(p):
    out, err = p.communicate(timeout=20)
    v = {l.split()[0]: l.split()[1:] for l in out.splitlines() if l[:1] in "BEN"}
    return v, err

try:
    a = run(JOB, "1.5"); time.sleep(0.3); b = run(JOB, "0.3")
    va, _ = spans(a); vb, eb = spans(b)
    ok = "B" in va and "B" in vb and float(vb["B"][0]) >= float(va["E"][0])
    check("H1", ok and "sırada bekliyor" in eb, f"ikincinin başlangıcı − birincinin bitişi {float(vb['B'][0]) - float(va['E'][0]) if ok or ('B' in vb and 'E' in va) else float('nan'):+.2f} sn (≥ 0) · bekleme iletisi: {'sırada bekliyor' in eb}")
    check("H2", va.get("B", [0, "?"])[1] == "19", f"nice {va.get('B', [0, '?'])[1]} (19)")
    a = run(JOB, "30"); time.sleep(0.5); b = run(JOB, "0.1"); time.sleep(0.5)
    t0 = time.time(); a.send_signal(signal.SIGKILL); a.wait()
    vb, _ = spans(b)
    check("H3", "B" in vb and float(vb["B"][0]) - t0 <= 2.0, f"tutan öldükten {float(vb['B'][0]) - t0 if 'B' in vb else float('nan'):.2f} sn sonra devam (≤ 2)")
    vn, en = spans(run(NEST))
    check("H4", "N" in vn and float(vn["N"][0]) <= 3.0, f"iç içe korumalı alt süreç {float(vn['N'][0]) if 'N' in vn else float('nan'):.2f} sn'de bitti (≤ 3) {en.strip()[-80:] if 'N' not in vn else ''}")
    # H5–H7: dinleyen denetimi (pw-link çıktısı dosyadan taklit edilir)
    fake = os.path.join(d, "links.txt"); env2 = dict(env, MIC_HEAVY_PWLINK=fake, MIC_HEAVY_POLL="0.2")
    BUSY = "effect_output.mic_clean:capture_MONO\n  |-> GNOME Settings:input_MONO\n  |-> effect_input.mic_main:input_AUX0\n  |-> Chromium:input_MONO\n"
    FREE = "effect_output.mic_clean:capture_MONO\n  |-> GNOME Settings:input_MONO\n  |-> mic-console-meter:input_MONO\n  |-> effect_input.mic_main:input_AUX0\neffect_output.mic_main:capture_MONO\n  |-> pavucontrol:input_MONO\n"
    run2 = lambda e, code, *a: subprocess.Popen([sys.executable, "-c", code, *a], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    open(fake, "w").write(FREE); t0 = time.time(); v7, e7 = spans(run2(env2, JOB, "0.1"))
    check("H7", "B" in v7 and float(v7["B"][0]) - t0 <= 1.5 and "kullanımda" not in e7, f"ölçer + iç bağ varken başlama {float(v7['B'][0]) - t0 if 'B' in v7 else float('nan'):.2f} sn (≤ 1,5), bekleme iletisi yok: {'kullanımda' not in e7}")
    open(fake, "w").write(BUSY); p5 = run2(env2, JOB, "0.1"); time.sleep(1.2); started_early = p5.poll() is not None
    t_free = time.time(); open(fake, "w").write(FREE); v5, e5 = spans(p5)
    check("H5", not started_early and "B" in v5 and float(v5["B"][0]) >= t_free and "mikrofon kullanımda" in e5 and "Chromium" in e5,
          f"dinleyen varken başlamadı: {not started_early} · dinleyen gidince {float(v5['B'][0]) - t_free if 'B' in v5 else float('nan'):.2f} sn sonra başladı · ileti dinleyeni adıyla yazdı: {'Chromium' in e5}")
    open(fake, "w").write(BUSY); p6 = run2(dict(env2, MIC_HEAVY_WAIT="1"), JOB, "0.1"); out6, err6 = p6.communicate(timeout=10)
    check("H6", p6.returncode == 3 and "B " not in out6, f"çıkış kodu {p6.returncode} (3) · iş koşmadı: {'B ' not in out6}")
finally:
    import shutil; shutil.rmtree(d, ignore_errors=True)
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
