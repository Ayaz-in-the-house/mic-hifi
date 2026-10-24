#!/usr/bin/env python3
"""tools/prio.py — zincir bekçisi karar mantığı (PRD-QUALITY A0.5). Saf işlev; canlıya dokunmaz.

P1 ham mikrofon VAR, temiz kaynak YOK, servis ≥ 6 sn'dir ayakta, son onarım ≥ 20 sn önce → ONAR
P2 ikisi de var → dokunma
P3 ham mikrofon yok → dokunma (takılı değilken yeniden başlatmak döngüdür)
P4 servis yeni başladı (< 6 sn) → bekle (düğümler birkaç saniyede oluşur)
P5 son onarım < 20 sn önce → bekle (yeniden başlatma fırtınası olmasın)
P6 servis çalışmıyor (kullanıcı durdurmuş) → dokunma
P7 onarım bütçesi: son 10 dakikada 3 onarım yapıldıysa dördüncüsü yapılmaz; eski denemeler sayılmaz
P8 profil koruması: etkin profilde analog giriş yoksa ve analog girişli bir profil varsa onu ister (çıkışı da koruyanı yeğler);
   analog giriş zaten etkinse, analog profil yoksa ya da kart yoksa dokunmaz
   neden: zincir yeniden başlarken kart profili dijital girişe kayıyor (E29, iki kez yeniden üretildi) → ham kaynak yok → zincir hedefsiz
P9 kart adı ham kaynak adından türetilir
A09-T5 son başlatma: temiz kaynak görününce varsayılan girişi geri yazar — yalnız kullanıcının SEÇİLİ varsayılanı oysa ve geçerli olan o değilse
   neden: oturum yöneticisi geri yazıyor ama saniyeler sonra (ölçüldü: 6 sn'de hâlâ ham); kullanıcı başka mikrofon seçtiyse dokunulmamalı
A09 ön başlatma: profil kaymışsa geri yazar ve ham kaynak görünene dek SINIRLI bekler; kaynak varsa hiç beklemez
   neden: bekçinin onarımı da bir yeniden başlatma olduğu için kaymayı yeniden tetikleyip bütçeyi tüketti (olay 2026-10-11) → zincir hedefi görmeden başlamamalı
neden: zincir, hedef mikrofon yokken başlarsa sanal mikrofonu hiç oluşturmuyor ve mikrofon gelince de toparlanmıyor
(yalıtılmış örnekte yeniden üretildi 2026-10-11; lessons/errors.md E30). Çalışırken çıkar-tak sorunsuz.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import chain, prio

R, C = chain.RAW_SOURCE, chain.CLEAN_SOURCE
cases = [("P1", ({R}, 30.0, 999.0, True), True), ("P2", ({R, C}, 30.0, 999.0, True), False), ("P3", (set(), 30.0, 999.0, True), False),
         ("P4", ({R}, 3.0, 999.0, True), False), ("P5", ({R}, 30.0, 8.0, True), False), ("P6", ({R}, 0.0, 999.0, False), False)]
fails = 0
for name, args, want in cases:
    got = prio.needs_repair(*args)
    print(f"{'PASS' if got == want else 'FAIL'}  {name}  needs_repair → {got} (beklenen {want})")
    fails += got != want
b = [prio.budget_ok([], 1000.0), prio.budget_ok([900.0, 950.0], 1000.0), prio.budget_ok([900.0, 950.0, 990.0], 1000.0), prio.budget_ok([100.0, 200.0, 300.0], 1000.0)]
ok = b == [True, True, False, True]
print(f"{'PASS' if ok else 'FAIL'}  P7  onarım bütçesi (10 dk'da en çok 3): {b} (beklenen [True, True, False, True])")
fails += not ok
cases.append(("P7", None, None))
A, D = "output:analog-stereo+input:analog-stereo", "output:analog-stereo+input:iec958-stereo"
pf = [prio.wanted_profile(D, [A, D, "input:analog-stereo"]), prio.wanted_profile(A, [A, D]), prio.wanted_profile("input:analog-stereo", [A, D]),
      prio.wanted_profile(D, [D, "input:analog-stereo"]), prio.wanted_profile(D, [D]), prio.wanted_profile(None, [A])]
ok = pf == [A, None, None, "input:analog-stereo", None, None]
print(f"{'PASS' if ok else 'FAIL'}  P8  profil koruması: {pf}")
fails += not ok
cases.append(("P8", None, None))
ok = prio.card_of("alsa_input.usb-Acme_Mic_1-00.analog-stereo") == "alsa_card.usb-Acme_Mic_1-00" and prio.card_of(R).startswith("alsa_card.")
print(f"{'PASS' if ok else 'FAIL'}  P9  kart adı ham kaynak adından türetilir: {prio.card_of(R)}")
fails += not ok
cases.append(("P9", None, None))
# A0.9: ön başlatma (PRD-QUALITY "A0.9")
calls = {"n": 0, "set": []}


def probe_factory(arrive_at, profile="output:analog-stereo+input:iec958-stereo"):
    def probe():
        calls["n"] += 1
        fixed = bool(calls["set"])
        return ("output:analog-stereo+input:analog-stereo" if fixed else profile, ["output:analog-stereo+input:analog-stereo", "output:analog-stereo+input:iec958-stereo"],
                (arrive_at is not None and calls["n"] >= arrive_at and (fixed or "input:analog-stereo" in profile)))
    return probe


extra = []
calls.update(n=0, set=[])
r = prio.prestart(probe_factory(3), calls["set"].append, sleep=lambda s: None, settle=0, timeout=10, step=0.5)
extra.append(("A09-T2a", r["ready"] and calls["set"] == ["output:analog-stereo+input:analog-stereo"] and calls["n"] <= 6, f"profil kaymış, kaynak 3. yoklamada: {r}, profil yazımı {calls['set']}"))
calls.update(n=0, set=[])
r = prio.prestart(probe_factory(None), calls["set"].append, sleep=lambda s: None, settle=0, timeout=3, step=0.5)
extra.append(("A09-T2b", not r["ready"] and r["waited"] <= 3.5 and calls["n"] <= 9, f"kaynak hiç gelmiyor: {r} (sınırlı bekleme)"))
calls.update(n=0, set=[])
r = prio.prestart(probe_factory(1, "output:analog-stereo+input:analog-stereo"), calls["set"].append, sleep=lambda s: None, settle=0, timeout=10, step=0.5)
extra.append(("A09-T1", r["ready"] and calls["set"] == [] and r["waited"] == 0, f"profil doğru, kaynak var: {r}, profil yazımı {calls['set']} (= yok)"))
# A09-T5: son başlatma — varsayılan girişi yalnız kullanıcının seçimi buysa geri yazar
WP = "Settings\n └─ Default Configured Devices:\n         0. Audio/Sink    effect_input.bta_console\n         1. Audio/Source  %s\n"
did = []
r = prio.poststart(lambda: f"{R}\n{C}", lambda: R, lambda: "baska_mikrofon", did.append, sleep=lambda s: None, timeout=1.0, hijacked=True)
extra.append(("A09-T5 profil kayması düzeltildiyse (seçim kaydı ezilmiş olsa da)", did == [C] and r["restored"], f"{r} · yazılan {did}"))
for tag, conf_src, cur, srcs, want_set in (("seçili = temiz, geçerli = ham", C, R, [R, C], True), ("seçili = temiz, geçerli = temiz", C, C, [R, C], False),
                                           ("kullanıcı başka mikrofon seçmiş", "baska_mikrofon", R, [R, C], False), ("temiz kaynak hiç gelmiyor", C, R, [R], False)):
    did = []
    r = prio.poststart(lambda: "\n".join(srcs), lambda: cur, lambda: prio.configured_default_source(WP % conf_src), did.append, sleep=lambda s: None, timeout=1.0)
    extra.append((f"A09-T5 {tag}", (did == [C]) == want_set and r["restored"] == want_set, f"{r} · yazılan {did}"))
for name, ok, d in extra:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {d}")
    fails += not ok
cases = cases + extra
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(cases) - fails}/{len(cases)}")
sys.exit(1 if fails else 0)
