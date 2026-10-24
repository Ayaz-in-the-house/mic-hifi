#!/usr/bin/env python3
"""Yayın denetim kapısı (tools/oss_audit.py) — docs/PRD-PUBLISH.md Y1.

Y1-1 LICENSE özgün Apache-2.0 metni (sha256)                                   neden: elle yazılmış lisans geçersiz olabilir
Y1-2 NOTICE üçüncü tarafları lisansıyla sayar; RE-USE/Seed-VC "depoda değil"    neden: yanlış lisans beyanı yayın engeli
Y1-3 ekilmiş kişisel veri örneklerinin hepsi yakalanır; izinli örnekler yakalanmaz   neden: kapı kör olmasın, gürültü yapmasın
Y1-6 kapı KAPALI-başarısız: metin olarak çözülemeyen dosyadaki veri de yakalanır · okunamayan/olmayan dosya → çıkış 2 · taranacak dosya yoksa → çıkış 2
     neden: atlanan dosya "temiz" sayılırsa kapı sessizce kör olur (güvenlik incelemesi bulgusu)
Y1-7 sınama dosyası istisnası ADA değil İÇERİĞE bağlı: başka bir ağaçta `tests/test_release.py` adlı ama farklı içerikli dosya TARANIR
     neden: ad eşleşmesiyle istisna, kapıdan kaçış yoludur (güvenlik incelemesi bulgusu)
Y1-5 izlenen ikili/ses/ağırlık dosyası yok                                      neden: ses ve ağırlık depoya girmez
"""
import hashlib, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


lic = os.path.join(ROOT, "LICENSE")
h = hashlib.sha256(open(lic, "rb").read()).hexdigest() if os.path.exists(lic) else "yok"
check("Y1-1", h == "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30", f"LICENSE sha256 {h[:16]}…")
nt = open(os.path.join(ROOT, "NOTICE"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "NOTICE")) else ""
need = ["PipeWire", "MIT", "LSP", "LGPL-3.0-or-later", "DeepFilterNet", "Rubber Band", "GPL-2.0-or-later", "MossFormer2", "Apache-2.0", "LADSPA", "RE-USE", "Seed-VC"]
miss = [w for w in need if w not in nt]
check("Y1-2", not miss, f"NOTICE'te eksik: {miss or 'yok'}")
try:
    import oss_audit
    PLANT = {"bt-iki-nokta": "kulaklık AA:BB:CC:DD:EE:0F adresinde", "bt-alt-çizgi": "bluez_output.AA_BB_CC_DD_EE_0F.1", "ev-dizini": "yol /home/birisi/projects/x",
             "e-posta": "yazar kisi@ornek-alan.org", "tailscale": "sunucu 100.101.102.103 üzerinde", "özel-ip": "yönlendirici 192.168.1.20",
             "usb-seri": "alsa_input.usb-Marka_model_000000010000-00.analog-stereo", "makine-adı": "makine " + oss_audit.HOST + " üzerinde"}
    ALLOW = ["Co-Authored-By: x <noreply@anthropic.com>", "user@example.com", "00:00:00:00:00:00", "sürüm 1.2.3.4 değil", "http://127.0.0.1:8767/"]
    got = {k: bool(oss_audit.scan_text(v)) for k, v in PLANT.items()}
    noise = [a for a in ALLOW if oss_audit.scan_text(a)]
    check("Y1-3", all(got.values()) and not noise, f"yakalanan: {got} · yanlış alarm: {noise or 'yok'}")
except ImportError as e:
    check("Y1-3", False, f"araç yok: {e}")
bins = [f for f in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        if f.lower().endswith((".wav", ".flac", ".ogg", ".mp3", ".so", ".onnx", ".npz", ".npy", ".pt", ".pth", ".bin", ".safetensors"))]
check("Y1-5", not bins, f"izlenen ikili/ses/ağırlık: {bins or 'yok'}")
with tempfile.TemporaryDirectory() as d:
    binf = os.path.join(d, "ikili.dat"); open(binf, "wb").write(b"\xff\xfe\x00 yol /home/birisi/gizli \xff\n")
    ok_txt = os.path.join(d, "temiz.txt"); open(ok_txt, "w").write("merhaba\n")
    locked = os.path.join(d, "kilitli.txt"); open(locked, "w").write("/home/birisi\n"); os.chmod(locked, 0)
    tool = [sys.executable, os.path.join(ROOT, "tools", "oss_audit.py")]
    r_bin = subprocess.run(tool + [binf], capture_output=True, text=True)
    r_missing = subprocess.run(tool + [os.path.join(d, "yok.txt")], capture_output=True, text=True)
    r_locked = subprocess.run(tool + [locked], capture_output=True, text=True)
    r_clean = subprocess.run(tool + [ok_txt], capture_output=True, text=True)
    r_nogit = subprocess.run(tool, capture_output=True, text=True, env=dict(os.environ, GIT_DIR=os.path.join(d, "yok-git")))
    os.chmod(locked, 0o600)
    check("Y1-6", r_bin.returncode == 1 and "ev dizini" in r_bin.stdout and r_missing.returncode == 2 and r_locked.returncode == 2 and r_clean.returncode == 0 and r_nogit.returncode == 2,
          f"çözülemeyen dosya → {r_bin.returncode} (1) · olmayan → {r_missing.returncode} (2) · okunamayan → {r_locked.returncode} (2) · temiz → {r_clean.returncode} (0) · git yok → {r_nogit.returncode} (2)")
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "tests")); fake = os.path.join(d, "tests", "test_release.py"); open(fake, "w").write("# /home/birisi/gizli\n")
    import shutil
    same = os.path.join(d, "kopya", "tests"); os.makedirs(same); shutil.copy(os.path.join(ROOT, "tests", "test_oss_audit.py"), os.path.join(same, "test_oss_audit.py"))
    tool = [sys.executable, os.path.join(ROOT, "tools", "oss_audit.py")]
    r_fake = subprocess.run(tool + [fake], capture_output=True, text=True); r_same = subprocess.run(tool + [os.path.join(same, "test_oss_audit.py")], capture_output=True, text=True)
    check("Y1-7", r_fake.returncode == 1 and r_same.returncode == 0, f"aynı adlı farklı dosya → {r_fake.returncode} (1: tarandı) · birebir kopya → {r_same.returncode} (0: istisna)")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
