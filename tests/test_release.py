#!/usr/bin/env python3
"""Temiz yayın ağacı (tools/make_release_tree.py) — docs/PRD-PUBLISH.md Y4. Kaynak depoya ve canlıya dokunmaz.

Y4-1 ağaçta yalnız bildirimdeki yollar; docs/, .claude/, AGENTS.md, tools/experiments/, .git yok   neden: çalışma günlüğü yayımlanmaz
Y4-2 ağaçta denetim 0 bulgu; ikili/ses/ağırlık yok                                              neden: ağaç tek başına temiz olmalı
Y4-3 gönderilen dosyaya kişisel veri ekilirse çıkış 1 ve hedef dizin bırakılmaz                  neden: kirli ağaç ortada kalmasın
Y4-4 ağaç boş bir ev dizininde kendi testlerini koşar                                           neden: bu depoya/makineye bağlı olmamalı
Y5-1 README/CHANGELOG/SECURITY/CONTRIBUTING yayın ağacında                                       neden: v1 şartı
Y5-2 README'de adı geçen her dosya yolu ağaçta var                                             neden: belgede olmayan komut kullanıcıyı çıkmaza sokar
Y5-3 README bölümleri: gereksinimler · kurulum · sınırlar · lisans · İngilizce özet            neden: okuyan neyi alıp almadığını bilmeli
Y4-6 kişisel veri DOSYA ADINDA ya da sembolik bağ ağaçta ise araç çıkış 1 verir, hedef bırakılmaz; araçta ortam değişkeniyle dosya ekleme kancası YOK
     neden: içerik taraması adları ve bağ hedeflerini görmez; sınama kancası üretim aracında arka kapıdır (güvenlik incelemesi bulguları)
Y4-5 kaynak depoda `git status` temiz kalır                                                     neden: dışa aktarım kaynağı değiştirmez
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "make_release_tree.py")
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


dirty0 = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "yayin")
    r = subprocess.run([sys.executable, TOOL, out], capture_output=True, text=True)
    files = sorted(os.path.relpath(os.path.join(dp, f), out) for dp, _dn, fs in os.walk(out) for f in fs) if os.path.isdir(out) else []
    bad = [f for f in files if f.startswith(("docs/", ".claude/", ".git/", "tools/experiments/")) or f in ("AGENTS.md", "CLAUDE.md")]
    need = ["LICENSE", "NOTICE", "plugins.lock.json", "bin/mic", "tools/chain.py", "console/server.py", "console/index.html", "conf/mic-clean.service", "heavy/worker.py", "tests/test_console_server.py"]
    check("Y4-1", r.returncode == 0 and files and not bad and all(n in files for n in need), f"çıkış {r.returncode} · {len(files)} dosya · gönderilmemesi gereken: {bad or 'yok'} · eksik: {[n for n in need if n not in files] or 'yok'}")
    a = subprocess.run([sys.executable, os.path.join(out, "tools", "oss_audit.py")] + [os.path.join(out, f) for f in files], capture_output=True, text=True) if files else None
    binf = [f for f in files if f.lower().endswith((".wav", ".flac", ".so", ".onnx", ".npz", ".npy", ".pt", ".pth", ".bin", ".safetensors"))]
    check("Y4-2", a is not None and a.returncode == 0 and not binf, f"denetim çıkışı {a.returncode if a else '—'} (0) {a.stdout.strip()[-80:] if a else ''} · ikili: {binf or 'yok'}")
    import re
    docs = ["README.md", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md"]
    check("Y5-1", all(f in files for f in docs), f"eksik: {[f for f in docs if f not in files] or 'yok'}")
    rd = open(os.path.join(out, "README.md"), encoding="utf-8").read() if "README.md" in files else ""
    paths = sorted(set(re.findall(r"(?<![\w/.~-])((?:bin|tools|tests|conf|console|heavy)/[A-Za-z0-9_./-]+\.[a-z]+|bin/mic)\b", rd)))
    missing = [p for p in paths if p not in files]
    check("Y5-2", bool(paths) and not missing, f"README'de {len(paths)} dosya yolu · ağaçta olmayan: {missing or 'yok'}")
    heads = [h for h in ("## Gereksinimler", "## Kurulum", "## Sınırlar", "## Lisans", "## English summary") if h not in rd]
    check("Y5-3", not heads and "kulakla" in rd.lower() and "PipeWire" in rd, f"eksik bölüm: {heads or 'yok'}")
    # Y4-4: boş ev dizininde ağacın kendi testleri
    home = os.path.join(d, "ev"); os.makedirs(home)
    env = {k: v for k, v in os.environ.items() if k not in ("MIC_SOURCE", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "MIC_PLUGIN_DIR")}
    import site
    env.update(HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"), XDG_STATE_HOME=os.path.join(home, ".local", "state"),
               PYTHONUSERBASE=site.getuserbase())   # ev dizini boş ama Python bağımlılıkları (numpy/scipy: requirements.txt) görünür kalsın
    res = {}
    for t in ("test_console_server.py", "test_device.py", "test_install.py", "test_plugins.py", "test_heavy_guard.py", "test_measure.py"):
        if os.path.exists(os.path.join(out, "tests", t)):
            rr = subprocess.run([sys.executable, os.path.join(out, "tests", t)], env=env, capture_output=True, text=True, cwd=out)
            res[t] = (rr.stdout.strip().splitlines() or ["çıktı yok"])[-1]
    check("Y4-4", len(res) == 6 and all(v.startswith("PASS:") for v in res.values()), " · ".join(f"{k[5:-3]} {v}" for k, v in res.items()))
    # Y4-3 / Y4-6: ekim, deponun GEÇİCİ bir kopyasında yapılır (araçta sınama kancası yok; kaynak depoya dokunulmaz)
    def clone_with(mutate, msg):
        c = os.path.join(d, "kopya-" + msg); subprocess.run(["git", "clone", "-q", "--no-hardlinks", ROOT, c], check=True, capture_output=True)
        mutate(c)
        subprocess.run(["git", "-C", c, "add", "-A"], check=True)
        subprocess.run(["git", "-C", c, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", msg], check=True)
        o = os.path.join(d, "yayin-" + msg)
        rr = subprocess.run([sys.executable, os.path.join(c, "tools", "make_release_tree.py"), o], capture_output=True, text=True)
        return rr.returncode, os.path.exists(o)
    r_content = clone_with(lambda c: open(os.path.join(c, "tools", "ekili.py"), "w").write("# yol /home/birisi/gizli\n"), "icerik")
    check("Y4-3", r_content == (1, False), f"içerikte ekili veri → (çıkış, hedef kaldı mı) {r_content} (= (1, False))")
    r_name = clone_with(lambda c: open(os.path.join(c, "tools", "not-02_00_00_00_00_01.txt"), "w").write("temiz içerik\n"), "ad")
    r_link = clone_with(lambda c: os.symlink("/home/birisi/gizli", os.path.join(c, "tools", "bag")), "bag")
    hook = "MIC_RELEASE_EXTRA" in open(TOOL, encoding="utf-8").read()
    check("Y4-6", r_name == (1, False) and r_link[0] in (1, 2) and r_link[1] is False and not hook,
          f"dosya adında veri → {r_name} (= (1, False)) · sembolik bağ → {r_link} (çıkış 1 ya da 2: çıkarma aşamasında reddedilir; hedef kalmaz) · araçta ekleme kancası: {hook}")
dirty1 = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
check("Y4-5", dirty0 == dirty1, f"kaynak depo durumu değişmedi: {dirty0 == dirty1}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
