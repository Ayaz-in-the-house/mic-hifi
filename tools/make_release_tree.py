#!/usr/bin/env python3
"""Temiz yayın ağacı üretir: HEAD'deki izlenen dosyalardan yalnız release.manifest'teki yolları <hedef> dizinine çıkarır ve denetim kapısını
O AĞAÇTA koşar. docs/PRD-PUBLISH.md Y4. Commit ATMAZ, hiçbir yere göndermez (yazar kimliği ve push kullanıcı kararıdır).

    python3 tools/make_release_tree.py <hedef dizin>      çıkış 0 = ağaç hazır ve temiz · 1 = denetim bulgusu (hedef SİLİNİR) · 2 = üretilemedi
"""
import io, os, shutil, subprocess, sys, tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = (".wav", ".flac", ".ogg", ".mp3", ".so", ".onnx", ".npz", ".npy", ".pt", ".pth", ".bin", ".safetensors")


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr); return 2
    dst = os.path.abspath(sys.argv[1])
    if os.path.exists(dst):
        print(f"hedef zaten var, üstüne yazılmaz: {dst}", file=sys.stderr); return 2
    specs = [l.strip() for l in open(os.path.join(ROOT, "release.manifest"), encoding="utf-8") if l.strip() and not l.startswith("#")]
    ls = subprocess.run(["git", "ls-files", "--"] + specs, cwd=ROOT, capture_output=True, text=True)
    files = [f for f in ls.stdout.split("\n") if f]
    if ls.returncode != 0 or not files:
        print(f"gönderilecek dosya listesi alınamadı (git çıkış {ls.returncode})", file=sys.stderr); return 2
    ar = subprocess.run(["git", "archive", "--format=tar", "HEAD", "--"] + files, cwd=ROOT, capture_output=True)   # HEAD: çalışma ağacındaki commit edilmemiş değişiklik GİRMEZ
    if ar.returncode != 0:
        print("git archive başarısız: " + ar.stderr.decode(errors="replace")[-200:], file=sys.stderr); return 2
    os.makedirs(dst)
    try:
        with tarfile.open(fileobj=io.BytesIO(ar.stdout)) as t:
            t.extractall(dst, filter="data")
        out = [os.path.relpath(os.path.join(dp, f), dst) for dp, _dn, fs in os.walk(dst) for f in fs]
        binf = [f for f in out if f.lower().endswith(BINARY)]
        # İçerik taraması adları ve bağ hedeflerini görmez: yol adları ayrıca taranır; sembolik bağ ve olağan dışı dosya ağaçta kabul edilmez.
        sys.path.insert(0, os.path.join(ROOT, "tools")); import oss_audit
        odd = [f for f in out if os.path.islink(os.path.join(dst, f)) or not os.path.isfile(os.path.join(dst, f))]
        odd += [d_ for dp, dn, _fs in os.walk(dst) for d_ in (os.path.relpath(os.path.join(dp, x), dst) for x in dn) if os.path.islink(os.path.join(dst, d_))]
        named = [f"{f}: {n}: {m}" for f in out for n, m in oss_audit.scan_text(f)]
        audit = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oss_audit.py")] + [os.path.join(dst, f) for f in out], capture_output=True, text=True)
        if audit.returncode != 0 or binf or odd or named:
            sys.stdout.write(audit.stdout); sys.stderr.write(audit.stderr)
            if binf:
                print("ikili/ses/ağırlık dosyası: " + ", ".join(binf))
            if odd:
                print("sembolik bağ ya da olağan dışı dosya: " + ", ".join(odd))
            for n_ in named:
                print("dosya ADINDA kişisel veri: " + n_)
            shutil.rmtree(dst)
            print("YAYIN AĞACI ÜRETİLMEDİ: denetim geçmedi; hedef silindi.", file=sys.stderr)
            return 1 if audit.returncode in (0, 1) else 2
    except Exception as e:
        shutil.rmtree(dst, ignore_errors=True)
        print(f"üretilemedi: {e}", file=sys.stderr); return 2
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"yayın ağacı hazır: {dst} · {len(out)} dosya · kaynak commit {head} · denetim temiz")
    print("sonraki adımlar (kullanıcı): cd <hedef> && git init && git add -A && git commit  (yazar kimliğini sen seç) → push senin kararın")
    return 0


if __name__ == "__main__":
    sys.exit(main())
