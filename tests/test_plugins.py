#!/usr/bin/env python3
"""Eklenti kilidi ve yetenek yoklaması (plugins.lock.json, tools/plugins.py) — docs/PRD-PUBLISH.md Y3. Canlıya dokunmaz (geçici eklenti dizini).

Y3-1 kilit: DeepFilterNet + rubberband için ad + sha256; kurulum betiğindeki özet kilitle aynı        neden: iki yerde duran özet ayrışır
Y3-2 check: doğru → 0 · değişmiş ikili → 1 (adıyla) · okunamayan → 2 · isteğe bağlı yok → 0 · zorunlu yok → 1   neden: üç sonuçlu kapı
Y3-3 ön başlatma: uyuşmazlıkta çıkış 78; birimde RestartPreventExitStatus=78                         neden: doğrulanmamış ikili ses yoluna girmesin
"""
import hashlib, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


lockp = os.path.join(ROOT, "plugins.lock.json")
lock = json.load(open(lockp, encoding="utf-8")) if os.path.exists(lockp) else {}
P = lock.get("plugins", {})
sh = open(os.path.join(ROOT, "tools", "install_rubberband.sh"), encoding="utf-8").read()
so_in_script = (re.search(r'^SO_SHA256="([0-9a-f]{64})"', sh, flags=re.M) or [None, ""])[1]
ok1 = all(re.fullmatch(r"[0-9a-f]{64}", P.get(k, {}).get("sha256", "")) and P[k].get("file") for k in ("deepfilter", "rubberband")) \
    and P.get("rubberband", {}).get("sha256") == so_in_script and P.get("deepfilter", {}).get("required") is True and P.get("rubberband", {}).get("required") is False
check("Y3-1", ok1, f"kilitte: {sorted(P)} · betikteki rubberband özeti kilitle aynı: {P.get('rubberband', {}).get('sha256') == so_in_script}")
tool = [sys.executable, os.path.join(ROOT, "tools", "plugins.py")]
with tempfile.TemporaryDirectory() as d:
    def setup(df=b"df-ikili", rb=b"rb-ikili"):
        lk = {"plugins": {"deepfilter": {"file": "libdeep_filter_ladspa.so", "sha256": hashlib.sha256(b"df-ikili").hexdigest(), "required": True},
                          "rubberband": {"file": "ladspa-rubberband.so", "sha256": hashlib.sha256(b"rb-ikili").hexdigest(), "required": False}}}
        json.dump(lk, open(os.path.join(d, "lock.json"), "w"))
        for n, c in (("libdeep_filter_ladspa.so", df), ("ladspa-rubberband.so", rb)):
            p = os.path.join(d, n)
            if os.path.exists(p): os.chmod(p, 0o600); os.remove(p)
            if c is not None: open(p, "wb").write(c)
    env = dict(os.environ, MIC_PLUGIN_DIR=d, MIC_PLUGIN_LOCK=os.path.join(d, "lock.json"))
    run = lambda *a: subprocess.run(tool + list(a), env=env, capture_output=True, text=True)
    setup(); r_ok = run("check")
    setup(df=b"df-ikilI"); r_bad = run("check")
    setup(rb=None); r_opt = run("check")
    setup(df=None); r_req = run("check")
    setup(); os.chmod(os.path.join(d, "libdeep_filter_ladspa.so"), 0); r_unread = run("check"); os.chmod(os.path.join(d, "libdeep_filter_ladspa.so"), 0o600)
    check("Y3-2", (r_ok.returncode, r_bad.returncode, r_opt.returncode, r_req.returncode, r_unread.returncode) == (0, 1, 0, 1, 2) and "deepfilter" in r_bad.stdout + r_bad.stderr and "yok" in r_opt.stdout,
          f"doğru → {r_ok.returncode} (0) · değişmiş → {r_bad.returncode} (1) · isteğe bağlı yok → {r_opt.returncode} (0) · zorunlu yok → {r_req.returncode} (1) · okunamayan → {r_unread.returncode} (2)")
    setup(df=b"df-ikilI")
    pr = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "prio.py"), "--plugin-gate"], env=env, capture_output=True, text=True)
    setup(); pr_ok = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "prio.py"), "--plugin-gate"], env=env, capture_output=True, text=True)
unit = open(os.path.join(ROOT, "conf", "mic-clean.service"), encoding="utf-8").read()
check("Y3-3", pr.returncode == 78 and pr_ok.returncode == 0 and "RestartPreventExitStatus=78" in unit and "prio.py --plugin-gate" in unit,
      f"uyuşmazlıkta çıkış {pr.returncode} (78) · doğruyken {pr_ok.returncode} (0) · birimde yeniden deneme engeli: {'RestartPreventExitStatus=78' in unit} · birim kapıyı çağırıyor: {'prio.py --plugin-gate' in unit}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
