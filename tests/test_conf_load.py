#!/usr/bin/env python3
"""Üretilen zincir conf'unun GERÇEK PipeWire'da yüklendiğinin kanıtı — yalıtılmış örnekte; canlı grafiğe dokunmaz.

L1 conf yalıtılmış örnekte yüklenir: iki düğüm (effect_input/effect_output.mic_clean) oluşur, süreç yaşar, günlükte eklenti/port hatası yok
   neden: çevrimdışı konak (ladspa_host) port adını kabul etse de filter-chain reddedebilir; canlıda öğrenmek = kullanıcının mikrofonu düşer
L2 her canlı parametre (chain.live_params) grafikten geri okunur ve durumla aynıdır
   neden: panelin canlıda değiştirdiği port adları conf'takiyle birebir olmalı (ad değişince sessizce etkisiz kalır)
L3 canlı değişim: ıslık kısma eşiği pw-cli ile yazılır, geri okunur
   neden: sürgü yeniden başlatma istemeden çalışmalı
L5 perde düğümü (kullanıcı dizinindeki rubberband eklentisi) yüklenir ve yarım ton canlı yazılır   neden: yapısal düğüm canlıdan önce gerçek PipeWire'da sınanmalı
L4 dinleyen yokken (düğüm askıda) yazılan parametre, dinleyen gelince uygulanmış olur
   neden: kullanıcı ayarı kimse dinlemezken değiştirir; ölçüldü: askıdayken geri okuma ESKİ değeri gösterir, kayıp yoktur
"""
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here); sys.path.insert(0, os.path.join(here, "..", "tools"))
import chain, gen_conf
from iso import Iso

fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


def props(iso):
    """effect_input.mic_clean Props → {"düğüm:Port": değer} (pw-dump iki Props girdisi döndürür; birleştirilir)."""
    out = {}
    for o in json.loads(iso.out("pw-dump", timeout=10) or "[]"):
        if (o.get("info") or {}).get("props", {}).get("node.name") == "effect_input.mic_clean":
            for pr in o["info"].get("params", {}).get("Props", []):
                p = pr.get("params") or []
                out.update(dict(zip(p[::2], p[1::2])))
    return out


state = {**chain.DEFAULT_STATE, **chain.PRESETS["normal"], "deess_on": True, "dyn_mud_on": True, "dyn_harsh_on": True, "dyn_body_on": True, "sat_on": True, "tone_on": True, "pitch_on": True, "pitch_st": -3}
with Iso() as iso:
    conf = os.path.join(iso.dir, "c.conf")
    open(conf, "w").write(gen_conf.render(dict(state)).replace(chain.RAW_SOURCE, "fake_mic"))
    log = os.path.join(iso.dir, "chain.log")
    p = iso.spawn("pipewire", "-c", conf, stdout=open(log, "w"), stderr=open(log, "a"))
    for _ in range(80):
        names = iso.out("pw-cli", "ls", "Node")
        if "effect_input.mic_clean" in names and "effect_output.mic_clean" in names:
            break
        time.sleep(0.25)
    time.sleep(1)
    names = iso.out("pw-cli", "ls", "Node")
    txt = open(log).read()
    bad = [l for l in txt.splitlines() if any(k in l.lower() for k in ("unknown control", "can't", "failed", "error", "no such"))]
    check("L1", "effect_input.mic_clean" in names and "effect_output.mic_clean" in names and p.poll() is None and not bad,
          f"düğümler {'var' if 'effect_output.mic_clean' in names else 'YOK'} · süreç {'yaşıyor' if p.poll() is None else 'ÖLDÜ'} · hata satırı {len(bad)}{': ' + bad[0][-160:] if bad else ''}")
    got, want = props(iso), chain.live_params(state)
    diff = {k: (v, got.get(k)) for k, v in want.items() if k not in got or abs(float(got[k]) - float(v)) > 1e-4 * max(1.0, abs(float(v)))}
    check("L2", bool(got) and not diff, f"{len(want) - len(diff)}/{len(want)} canlı parametre grafikte = durum{' · fark: ' + str(dict(list(diff.items())[:3])) if diff else ''}")
    key, new = "dyn:Attack threshold 4 (G)", round(chain.lin(-30), 6)
    ratio = 'level:Ratio'
    iso.run("pw-cli", "set-param", "effect_input.mic_clean", "Props", '{ params = [ "%s" 5.0 ] }' % ratio)   # düğüm ASKIDA iken yazılır
    time.sleep(0.5)
    stale = props(iso).get(ratio)
    iso.record("effect_output.mic_clean", os.path.join(iso.dir, "r.wav"))   # dinleyen gelir → düğüm çalışır
    for _ in range(40):                                                     # kayıt akışının bağlanması değişken sürer: duruma bak, süreye güvenme
        if iso.state("effect_input.mic_clean") == "running":
            break
        time.sleep(0.25)
    running = iso.state("effect_input.mic_clean") == "running"
    time.sleep(0.5)
    woke = props(iso).get(ratio)
    check("L4", running and woke is not None and abs(float(woke) - 5.0) < 1e-4,
          f"askıdayken yazılan değer: geri okuma {stale} (askıda eski görünebilir) → düğüm {'çalışıyor' if running else 'ÇALIŞMADI'}, değer {woke}")
    iso.run("pw-cli", "set-param", "effect_input.mic_clean", "Props", '{ params = [ "%s" %s ] }' % (key, new))
    time.sleep(0.5)
    back = props(iso).get(key)
    check("L3", back is not None and abs(float(back) - new) < 1e-4, f"ıslık kısma eşiği canlı yazıldı: {new} → geri okunan {back}")
    key5 = "pitch:Semitones"
    iso.run("pw-cli", "set-param", "effect_input.mic_clean", "Props", '{ params = [ "%s" 2.0 ] }' % key5)
    time.sleep(0.5)
    back5 = props(iso).get(key5)
    check("L5", "pitch" in [n[0] for n in chain.nodes(state)] and back5 is not None and abs(float(back5) - 2.0) < 1e-4, f"perde düğümü yüklü; yarım ton canlı yazıldı: 2.0 → geri okunan {back5}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
