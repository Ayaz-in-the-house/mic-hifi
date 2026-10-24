#!/usr/bin/env python3
"""Mikrofon Konsolu sunucusu — sözleşme testleri (MIC_DRY=1: canlı grafiğe ve gerçek ayar dosyasına dokunmaz).

S1 durum okunur                 neden: panel ilk çizimde kontrolleri ve aralıkları buradan alır
S2 yabancı Host reddedilir      neden: DNS rebinding ile başka site paneli süremesin
S3 özel başlıksız POST reddi    neden: CSRF — rastgele bir web sayfası mikrofon ayarını değiştiremesin
S4 değer aralığa oturtulur      neden: sürgü dışı/bozuk değer eklentiye gitmesin (boost 999 → 36)
S5 bilinmeyen anahtar 400       neden: sessiz yutma yerine açık hata
S6 mod uygular, elle oynayınca "ozel" + taban korunur   neden: "bu modun ayarlarına dön"
S7 profil kaydet → uygula → sil; yol kaçışı reddi       neden: dosya adı istemciden geliyor
S8 durum diske yazılır ve yeniden yüklenir              neden: sunucu/servis yeniden başlayınca ayar kalmalı
S9 kapalı aşamalar eklentiye "geçiş" olarak gider       neden: anahtar gerçekten kapatmalı (oran 1 · sınır 0 · bypass)
S10 anahtarsız hiçbir API ucu çalışmaz (401): durum, ölçer, POST; ÇEREZ anahtar sayılmaz   neden: aynı makinedeki başka kullanıcı/süreç
                                                                     mikrofonu yönetemesin; çerez porta göre yalıtılmadığı için kullanılmaz
S11 sayfa sır içermez ve çerez vermez; anahtar dosyası 0600   neden: anahtar yalnız adres parçasıyla (sunucuya gitmez) taşınır
S12 başka siteden gelen GET (Sec-Fetch-Site: cross-site) çerez olsa da 403   neden: <img src=…/api/meter> ile mikrofon açtırma
S13 bozuk/negatif Content-Length 400   neden: negatif uzunluk okuyucuyu sonsuza dek bekletirdi
S15 anahtarla seviye akışı 200 döner ve veri satırı gelir; akış kapanınca sunucu yeni akış kabul eder
    neden: bu yol hiçbir testte koşmuyordu → bir düzenleme LOCK tanımını sildi, canlı panelde çubuklar sessizce öldü (2026-10-10)
S16 durum mikrofon/kesinti/deneme alanlarını taşır; deneme başlar, fazları gezer, boşa döner; sürerken ikinci deneme ve geçersiz süre reddedilir
    neden: panelin "mikrofon bağlı mı / ses kesiliyor mu" sorusuna cevabı ve kaydet-dinle akışı
S17 anahtar kapalıyken (config require_key=false): anahtarsız durum 200; AMA özel başlıksız GET 403, başka siteden 403, yabancı Host 403
    neden: "her tarayıcıda aç" tercihi başka sitelerin paneli sürmesine kapı açmamalı
S18 bilinmeyen karakter 400 · karakter uygulanınca ton değerleri = tablo, mod DEĞİŞMEZ · mod değişince karakter korunur · ton sürgüsü oynanınca karakter "ozel", mod aynı
    neden: karakter moddan bağımsız ikinci eksendir (PRD-VOICE T-V1-6)
S19 ıslık kısma/doygunluk oynanınca mod "özel"e düşmez · mod değişince doygunluk korunur · fısıltı moduna geçince ıslık kısma kapanır · megafon doygunluğu açar
    neden: ikinci eksen + fısıltı kuralı (PRD-VOICE T-V1b-6)
S20 kulakla karşılaştırma: kayıt yokken çalma reddedilir (ileti) · geçersiz süre 400 · kayıt fazı görünür · meşgulken ikinci istek reddedilir · kayıttan sonra
    karakter adıyla çalma başlar, bilinmeyen karakter 400, durdurulur · çalma canlı modu/karakteri DEĞİŞTİRMEZ
    neden: kullanıcı aynı konuşmasını farklı karakterlerle dinleyip karar verir; dinlemek ayarını bozmamalı
S21 karşılaştırma kaydı silinemezse "kayıt yok" denmez ama çalmaya da sunulmaz; kayıtçı/çalıcı `timeout` ile sarılıdır
    neden: güvenlik incelemesi (2026-10-11) — sunucu ölürse mikrofon kaydı yetim kalmasın; silme sessizce başarısız olmasın
S22 karakter yoğunluğu (hafif/orta/güçlü/çok) değerleri ölçekler ve durumda görünür; yoğunluk verilmezse seçili olan korunur; geçersiz yoğunluk 400 ·
    elle oynanan ton adla kaydedilir, uygulanır, silinir (yalnız ton anahtarları; mod değişmez); yol kaçışı ve yerleşik ad reddedilir
    neden: "daha az derin / daha derin" tek dokunuş olmalı; kendi dokunuşu adıyla saklanabilmeli
S23 teslim ölçüleri: kayıt yokken ok=false + açık ileti (S20 içinde) · kayıt varken ses yüksekliği, gerçek tepe, taban, tık/dk ve hedefler döner ·
    karakter adıyla da ölçülür · bilinmeyen karakter 400
    neden: panel sesin yayın ölçüleriyle nerede durduğunu göstermeli (PRD-QUALITY A1-T6)
S35 sayfa sürümü: durum yanıtındaki `ui` = sunulan sayfaya gömülen sürüm; sayfa dosyası değişince `ui` değişir; sayfada yer tutucu kalmaz
    neden: panel güncellenince açık sekme eski hâliyle kalıyor ve kullanıcı bilemiyor → sayfa farkı görüp "yenile" der
S34 yetenek: durum yanıtında `caps` (denoise, pitch); perde eklentisi YOKKEN `pitch_on` isteği reddedilir (ileti), durum değişmez, zincir yeniden başlamaz
    neden: eklenti yokken zinciri bozacak ayar yazılmasın (PRD-PUBLISH Y3-4)
S33 oda payı: oda kaydı varken `diag.room` = oda gürültüsü (LUFS) + her mod için eşik/pay/yeterli; kayıt yokken ya da ölçülemezken null
    neden: sessizlik eşiği odaya/halkaya bağlı; pay yetmezse seviyeleyici sessizlikte tırmanır (PRD-QUALITY "Oda payı denetimi")
S38 etiketli örnek adımları: adım listesi sessiz/aaa/ptk/fisilti/tik/metin; "tik"te en az 3 ayrı kısa ses olayı yeter (konuşma süresi aranmaz), azsa uyarı + `events`;
    "metin" 25 sn; neden: tık sayacı eşikle kalibre edilemedi (gerçek konuşmada 15 dB eşikte bile 7 sn'de 6 yanlış aday) → bilerek yapılmış olaylar gerekli
S37 uzun ses sürekliliği: "aaa" adımında en uzun kesintisiz sesli bölüm 2 sn'den kısaysa uyarı; neden: kesik kesik ortam sesi toplam süreyi doldurup geçti (2026-10-11)
S36 konuşma süresi: konuşma adımında oda sesinin 6 dB üstündeki süre adım süresinin dörtte birinden (uzun ses: %40) kısaysa uyarı + `speech_s`; neden: 2026-10-11'de
    darbe/tıkırtı iki adımı "yapıldı" gösterdi (ortalama seviye yeterliydi, konuşma yoktu)
S32 teşhis kaydı: 6 adım yönergesiyle listelenir; bilinmeyen adım 400; kayıt bitince adım "yapıldı" + seviye, dosya 0600 / dizin 0700; kayıt sürerken
    ikinci kayıt ve karşılaştırma kaydı reddedilir; "sil" dosyaları kaldırır; tam sessiz kayıt uyarı verir
    neden: onarım adımları gerçek kayıt olmadan doğrulanamıyor; kayıt kişisel veri (PRD-QUALITY "Teşhis kaydı kartı")
S31 kalite mikrofonu durumu gözcünün olay günlüğünden okunur: günlük yok → "yok"; gözcü hazır/kuru → "bosta"; işçi başlatıldı/bağlandı →
    "hazirlaniyor"; ıslak → "etkin"; kilitli → "kilitli"; gözcü kapandı → "yok"; bozuk satır yok sayılır; gecikme (carrier.QUALITY_DELAY_MS) bildirilir
    neden: ikinci mikrofonun (0,6 sn gecikmeli) çalışıp çalışmadığını kullanıcı panelden görebilmeli (PRD-VOICE L6)
S30 perdeyi kullanan karakter (Kalın, İri) seçmek ya da ondan çıkmak zinciri yeniden başlatır; perdesiz karakterler arası geçiş ve yoğunluk
    değişimi başlatmaz; perde sürgüsü elle oynanınca karakter "özel"; perde anahtarı olmayan eski kayıtlı karakter "perde kapalı" olarak yüklenir
S29 kayıt, sonradan eklenen bir mod anahtarını içermiyorsa kaydın modundan (taban) doldurulur; kayıtta olan değer ezilmez
    neden: kullanıcı Fısıltı modundayken yeni kural anahtarı (pitch_mute) varsayılan "kapalı" yüklendi → fısıltı kuralı uygulanmadı (yaşandı)
S28 perde: `pitch_on` değişince zincir yeniden başlatılır (sayaç +1), `pitch_st`/`pitch_formant` değişince başlatılmaz; mod "özel"e düşmez;
    Fısıltı'ya geçince düğüm kalır ama kuru geçer (yeniden başlatma yok, ayar korunur); kapatınca canlı parametrelerden çıkar
    neden: eklentide bypass yok ve 60 ms gecikme ekliyor → düğüm yalnız açıkken grafikte olmalı; mod değişimi mikrofonu kesmemeli
S27 çıkış yükseklik hedefi: `POST /api/loudness` yalnız tanımlı hedefi kabul eder, `loud_db` yazar, modu değiştirmez, mod değişince korunur;
    tavanın giriş kazancı = çıkış kazancı + hedef; neden: kullanıcı sayı değil hedef seçer (PRD-QUALITY A2.5)
S26 dinamik EQ (şişme, sertlik) ikinci eksendedir: açınca mod "özel"e düşmez, mod değişince korunur; Fısıltı'ya geçince sertlik kapanır
    (fısıltı 2–5 kHz'de normalden yüksek, ölçüldü), şişme kalır; üçü de kapalıyken dinamik katman devre dışı
S25 karşılaştırma kaydı, işleyicinin yeniden uygulayacağı her şey (ton, ıslık kısma, doygunluk, ÇIKIŞ KAZANCI) kapalıyken alınır;
    neden: çıkış kazancı tavanın girişine taşındı (A2.2), kayıtta açık kalırsa dinlenen ve ölçülen ses +out_db fazla çıkar (ölçüldü: +5 dB)
S24 seviyeleyiciden önce kaydedilmiş durum/profil yüklenince eski ses AYNEN korunur (seviyeleyici kapalı, eski ön kazanç ve oran);
    yeni modlar seviyeleyiciyi açar, kompresörü 3:1'e alır, ön kazancı sıfırlar · Ham modu seviyeleyiciyi kapatır
    neden: kullanıcının kayıtlı profilleri çift kazançla bozulmamalı (PRD-QUALITY A2-T6)
S14 gevşek izinli (0644) ya da sembolik bağ olan anahtar dosyası KABUL EDİLMEZ, yenisi 0600 üretilir; dizin 0700
    neden: başkasının okuyabildiği anahtar sızmış anahtardır; bağ üzerinden başka dosyaya yazdırılmamalı
"""
import http.client, json, os, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import chain
tmp = tempfile.mkdtemp()
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
QEV = os.path.join(tmp, "watch.jsonl")
env = dict(os.environ, MIC_DRY="1", XDG_CONFIG_HOME=tmp, MIC_QUALITY_EVENTS=QEV, XDG_STATE_HOME=os.path.join(tmp, "state"))
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "console", "server.py"), "--port", str(port)], env=env, stdout=subprocess.PIPE)
srv.stdout.readline()
fails = []
TOKEN = open(os.path.join(tmp, "mic-hifi", "token")).read().strip()
AUTH = True


def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json", "X-Mic-Console": "1"} if body is not None else {"X-Mic-Console": "1"}
    if AUTH:
        h["X-Mic-Key"] = TOKEN
    h.update(headers or {})
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


RAN = [0]   # gerçek koşan nokta sayısı (elle yazılan toplam eskiyordu)


def check(tp, ok, d=""):
    RAN[0] += 1
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}")
    if not ok:
        fails.append(tp)


try:
    st, d = req("GET", "/api/state")
    check("S1", st == 200 and len(d["controls"]) == len(chain.CONTROLS) and d["state"]["auto_max_db"] == 30 and d["state"]["boost_db"] == 0, f"{st}, {len(d.get('controls', []))} kontrol")
    st, _ = req("GET", "/api/state", headers={"Host": "evil.example"})
    check("S2", st == 403, str(st))
    st, _ = req("POST", "/api/state", {"patch": {"boost_db": 5}}, headers={"X-Mic-Console": "0"})
    st2, _ = req("POST", "/api/state", {"patch": {"boost_db": 5}}, headers={"Origin": "http://evil.example"})
    check("S3", st == 403 and st2 == 403, f"{st}/{st2}")
    st, d = req("POST", "/api/state", {"patch": {"boost_db": 999, "level_ratio": 7.26}})
    check("S4", st == 200 and d["state"]["boost_db"] == 36 and d["state"]["level_ratio"] == 7.5, json.dumps({k: d["state"][k] for k in ("boost_db", "level_ratio")}))
    st, _ = req("POST", "/api/state", {"patch": {"nope": 1}})
    st2, _ = req("POST", "/api/state", {"patch": {"gate_on": "yes"}})
    check("S5", st == 400 and st2 == 400, f"{st}/{st2}")
    st, d = req("POST", "/api/preset", {"id": "gece"})
    ok = d["mode"] == "gece" and d["state"]["auto_max_db"] == 36 and d["state"]["level_ratio"] == 3
    st, d = req("POST", "/api/state", {"patch": {"denoise_db": 20}})
    check("S6", ok and d["mode"] == "ozel" and d["base"] == "gece", f"mode={d['mode']} base={d['base']}")
    # S18: karakter ikinci eksendir
    st0, _ = req("POST", "/api/character", {"id": "yok-boyle"})
    st, d = req("POST", "/api/character", {"id": "radyo"})
    ok18 = st0 == 400 and st == 200 and d["character"] == "radyo" and d["mode"] == "ozel" and d["base"] == "gece" \
        and all(d["state"][k] == v for k, v in chain.CHARACTERS["radyo"].items()) and "notr" in d["characters"]
    st, d = req("POST", "/api/preset", {"id": "normal"})
    ok18 = ok18 and d["mode"] == "normal" and d["character"] == "radyo" and d["state"]["tone_low_db"] == chain.CHARACTERS["radyo"]["tone_low_db"]
    st, d = req("POST", "/api/state", {"patch": {"tone_air_db": -5}})
    ok18 = ok18 and d["character"] == "ozel" and d["mode"] == "normal"
    st, d = req("POST", "/api/character", {"id": "notr"})
    lp = chain.live_params(d["state"])
    ok18 = ok18 and d["character"] == "notr" and lp["tone:Gain 1 (G)"] == 1.0 and lp["tone:Bypass"] is False and "tone:Frequency 7 (Hz)" in lp
    # S19: ıslık kısma + doygunluk da ikinci eksende; fısıltı kuralı
    req("POST", "/api/preset", {"id": "normal"})
    st, d = req("POST", "/api/state", {"patch": {"deess_on": True, "sat_on": True, "sat_db": 9}})
    ok19 = d["mode"] == "normal" and d["character"] == "ozel" and d["state"]["deess_on"] is True
    st, d = req("POST", "/api/preset", {"id": "fisilti"})
    ok19 = ok19 and d["state"]["deess_on"] is False and d["state"]["sat_on"] is True and d["state"]["sat_db"] == 9
    st, d = req("POST", "/api/character", {"id": "megafon"})
    lp = chain.live_params(d["state"])
    ok19 = ok19 and d["character"] == "megafon" and d["mode"] == "fisilti" and lp["sat:Bypass"] is False and lp["sat:Clipping threshold (dB)"] == chain.SAT_BASE_DB - chain.CHARACTERS["megafon"]["sat_db"] and lp["dyn:Bypass"] is True
    st, d = req("POST", "/api/character", {"id": "notr"})
    # S30: perdeyi kullanan karakterler — seçmek/çıkmak yapısal, perdesizler arası geçiş canlı; eski kayıtlı karakter tanınır
    req("POST", "/api/preset", {"id": "normal"})
    st, a0 = req("POST", "/api/character", {"id": "sicak", "amount": "orta"})
    st, a1 = req("POST", "/api/character", {"id": "parlak"})
    st, a2 = req("POST", "/api/character", {"id": "kalin"})
    st, a3 = req("POST", "/api/character", {"id": "kalin", "amount": "cok"})
    st, a4 = req("POST", "/api/state", {"patch": {"pitch_st": -1}})
    st, a5 = req("POST", "/api/character", {"id": "derin", "amount": "orta"})
    old_char = {k: v for k, v in chain.scaled_character("sicak", "orta").items() if not k.startswith("pitch_")}
    cdir = os.path.join(tmp, "mic-hifi", "characters")   # sunucunun (kuru) ayar dizini
    os.makedirs(cdir, exist_ok=True)
    json.dump(old_char, open(os.path.join(cdir, "eski-sicak.json"), "w"))
    st, a6 = req("POST", "/api/character", {"id": "user:eski-sicak"})
    os.remove(os.path.join(cdir, "eski-sicak.json"))
    ok30 = a1["restarts"] == a0["restarts"] and a2["restarts"] == a1["restarts"] + 1 and a2["character"] == "kalin" and a2["state"]["pitch_on"] is True and a2["state"]["pitch_st"] == -2 \
        and a3["restarts"] == a2["restarts"] and a3["state"]["pitch_st"] == -4 and a3["amount"] == "cok" and a4["character"] == "ozel" and a4["restarts"] == a3["restarts"] \
        and a5["restarts"] == a4["restarts"] + 1 and a5["character"] == "derin" and a5["state"]["pitch_on"] is False \
        and st == 200 and a6["state"]["pitch_on"] is False and a6["state"]["tone_low_db"] == chain.CHARACTERS["sicak"]["tone_low_db"]
    check("S30", ok30, f"yeniden başlatma: Sıcak→Parlak {a1['restarts'] - a0['restarts']} · →Kalın {a2['restarts'] - a1['restarts']} · yoğunluk {a3['restarts'] - a2['restarts']} · →Derin {a5['restarts'] - a4['restarts']} (0·1·0·1) · elle perde → {a4['character']} · eski kayıtlı karakter: {a6.get('character')}")
    # S28: perde — yapısal anahtar zinciri yeniden başlatır, yarım ton canlı değişir
    req("POST", "/api/preset", {"id": "normal"})
    st, d0 = req("GET", "/api/state")
    st, d1 = req("POST", "/api/state", {"patch": {"pitch_st": -3}})                 # düğüm yokken: yapı değişmez
    st, d2 = req("POST", "/api/state", {"patch": {"pitch_on": True}})
    lp28 = chain.live_params(d2["state"])
    st, d3 = req("POST", "/api/state", {"patch": {"pitch_st": -2, "pitch_formant": False}})
    lp28b = chain.live_params(d3["state"])
    st, d4 = req("POST", "/api/preset", {"id": "fisilti"})
    lp28c = chain.live_params(d4["state"])
    st, d5 = req("POST", "/api/preset", {"id": "normal"})
    st, d6 = req("POST", "/api/state", {"patch": {"pitch_on": False}})
    ok28 = d1["restarts"] == d0["restarts"] and d2["restarts"] == d0["restarts"] + 1 and d3["restarts"] == d2["restarts"] and d4["restarts"] == d3["restarts"] and d6["restarts"] == d5["restarts"] + 1 \
        and d2["mode"] == "normal" and lp28["pitch:Semitones"] == -3.0 and lp28["pitch:Wet-Dry Mix"] == 0.0 and lp28b["pitch:Semitones"] == -2.0 and lp28b["pitch:Formant Preserving"] == 0.0 \
        and d4["state"]["pitch_on"] is True and d4["state"]["pitch_st"] == -2 and lp28c["pitch:Wet-Dry Mix"] == 1.0 and chain.live_params(d5["state"])["pitch:Wet-Dry Mix"] == 0.0 \
        and not any(k.startswith("pitch:") for k in chain.live_params(d6["state"]))
    check("S28", ok28, f"yeniden başlatma sayacı: yarım ton {d1['restarts'] - d0['restarts']} · aç {d2['restarts'] - d1['restarts']} · ayar {d3['restarts'] - d2['restarts']} · mod {d4['restarts'] - d3['restarts']} · kapat {d6['restarts'] - d5['restarts']} (0·1·0·0·1) · fısıltıda kuru: {lp28c.get('pitch:Wet-Dry Mix') == 1.0}")
    # S27: çıkış yükseklik hedefi
    req("POST", "/api/preset", {"id": "normal"})
    st_bad, _ = req("POST", "/api/loudness", {"target": "yok"})
    st, d27 = req("POST", "/api/loudness", {"target": "yayin"})
    lp27 = chain.live_params(d27["state"])
    ok27 = st_bad == 400 and st == 200 and d27["loudness"] == "yayin" and d27["mode"] == "normal" and d27["state"]["loud_db"] == 7 \
        and abs(lp27["limit:Input gain (G)"] - chain.lin(d27["state"]["out_db"] + 7)) < 1e-9
    st, d27 = req("POST", "/api/preset", {"id": "gece"})
    ok27 = ok27 and d27["state"]["loud_db"] == 7 and d27["loudness"] == "yayin"
    st, d27 = req("POST", "/api/loudness", {"target": "gorusme"})
    ok27 = ok27 and d27["state"]["loud_db"] == 0 and d27["loudness"] == "gorusme" and d27["mode"] == "gece"
    check("S27", ok27, f"yayın → loud_db 7, mod korunur, mod değişince hedef korunur, görüşme → 0 · bilinmeyen hedef {st_bad}")
    # S26: dinamik EQ anahtarları ikinci eksende; sertlik fısıltı kuralına uyar; canlı parametre adları
    req("POST", "/api/preset", {"id": "normal"})
    st, d = req("POST", "/api/state", {"patch": {"dyn_mud_on": True, "dyn_harsh_on": True, "dyn_mud_db": -30, "dyn_body_on": True, "dyn_body_db": 4}})
    lp26 = chain.live_params(d["state"])
    ok26 = d["mode"] == "normal" and lp26["dyn:Bypass"] is False and lp26["dyn:Compressor enable 1"] == 1.0 and lp26["dyn:Compressor enable 3"] == 1.0 \
        and lp26["dyn:Compressor enable 4"] == 0.0 and lp26["dyn:Compressor enable 0"] == 1.0 and abs(lp26["dyn:Makeup gain 0 (G)"] - chain.lin(4)) < 1e-9 and abs(lp26["dyn:Attack threshold 1 (G)"] - chain.lin(-30)) < 1e-9
    st, d26 = req("POST", "/api/preset", {"id": "fisilti"})
    ok26 = ok26 and d26["state"]["dyn_harsh_on"] is False and d26["state"]["dyn_body_on"] is False and d26["state"]["dyn_mud_on"] is True and d26["state"]["dyn_mud_db"] == -30
    st, d26 = req("POST", "/api/state", {"patch": {"dyn_mud_on": False}})
    ok26 = ok26 and d26["mode"] == "fisilti" and chain.live_params(d26["state"])["dyn:Bypass"] is True
    check("S26", ok26, f"mod korunur · fısıltıda sertlik ve dolgunluk kapanır, şişme kalır · üçü kapalıyken katman devre dışı: {ok26}")
    check("S19", ok19 and d["state"]["sat_on"] is False, f"mod={d['mode']} karakter={d['character']}")
    # S20: kulakla karşılaştırma
    st, d = req("GET", "/api/state"); a0 = d["audition"]
    st, dd = req("GET", "/api/delivery"); no_take = (st, dd.get("ok"), dd.get("message", ""))
    st, d = req("POST", "/api/audition", {"action": "play", "id": "radyo"}); m_no = d.get("message", "")
    st1, _ = req("POST", "/api/audition", {"action": "record", "seconds": 99})
    st, d = req("POST", "/api/audition", {"action": "record", "seconds": 4}); ph = d["audition"]["phase"]
    st, d2 = req("POST", "/api/audition", {"action": "play", "id": "radyo"}); m_busy = d2.get("message", "")
    for _ in range(40):
        st, d = req("GET", "/api/state")
        if d["audition"]["phase"] == "idle":
            break
        time.sleep(0.1)
    took = d["audition"]["take"]
    st2, _ = req("POST", "/api/audition", {"action": "play", "id": "yok-boyle"})
    st, d = req("POST", "/api/audition", {"action": "play", "id": "radyo"}); playing = d["audition"]
    mode_before = d["mode"], d["character"]
    st, d = req("POST", "/api/audition", {"action": "stop"})
    for _ in range(40):
        st, d = req("GET", "/api/state")
        if d["audition"]["phase"] == "idle":
            break
        time.sleep(0.1)
    st, d3 = req("POST", "/api/audition", {"action": "play", "id": "current"})
    ok20 = a0 == {"phase": "idle", "take": False, "id": ""} and "kayıt" in m_no.lower() and st1 == 400 and ph == "kayit" and m_busy and took is True \
        and st2 == 400 and playing["phase"] == "caliyor" and playing["id"] == "radyo" and d["audition"]["phase"] == "idle" \
        and (d["mode"], d["character"]) == mode_before and d3["audition"]["id"] == "current"
    ok20 = ok20 and no_take[0] == 200 and no_take[1] is False and "kayıt" in no_take[2].lower()
    check("S20", ok20, f"başta {a0} · kayıtsız çalma: {m_no!r} · geçersiz süre {st1} · kayıt fazı {ph} · meşgulken: {m_busy!r} · kayıt var {took} · bilinmeyen {st2} · çalarken {playing}")
    req("POST", "/api/audition", {"action": "stop"}); time.sleep(0.6)
    # S22: karakter yoğunluğu + kendi karakterlerim
    st, d = req("POST", "/api/character", {"id": "derin", "amount": "cok"})
    ok22 = d["character"] == "derin" and d["amount"] == "cok" and d["state"]["tone_low_db"] == chain.scaled_character("derin", "cok")["tone_low_db"] and d["amounts"] == ["hafif", "orta", "guclu", "cok"]
    st, d = req("POST", "/api/character", {"id": "derin", "amount": "hafif"})
    ok22 = ok22 and d["amount"] == "hafif" and d["state"]["tone_low_db"] == chain.scaled_character("derin", "hafif")["tone_low_db"]
    st, d = req("POST", "/api/character", {"id": "radyo"})                       # yoğunluk verilmezse seçili yoğunluk korunur
    ok22 = ok22 and d["character"] == "radyo" and d["amount"] == "hafif" and d["state"]["tone_low_db"] == chain.scaled_character("radyo", "hafif")["tone_low_db"]
    st_bad, _ = req("POST", "/api/character", {"id": "radyo", "amount": "asiri"})
    st, d = req("POST", "/api/state", {"patch": {"tone_air_db": -4.5}})
    ok22 = ok22 and st_bad == 400 and d["character"] == "ozel"
    st, d = req("POST", "/api/character", {"save": "gece-sesim"})
    ok22 = ok22 and st == 200 and d["character"] == "user:gece-sesim" and "gece-sesim" in d["user_characters"]
    st, d0 = req("POST", "/api/character", {"id": "notr"})
    st, d = req("POST", "/api/character", {"id": "user:gece-sesim"})
    ok22 = ok22 and d["character"] == "user:gece-sesim" and d["state"]["tone_air_db"] == -4.5 and d["mode"] == d0["mode"]
    st_p, _ = req("POST", "/api/character", {"save": "../kacis"})
    st_n, _ = req("POST", "/api/character", {"save": "notr"})                   # yerleşik adın üstüne yazılamaz
    st, d = req("POST", "/api/character", {"delete": "gece-sesim"})
    ok22 = ok22 and st_p == 400 and st_n == 400 and "gece-sesim" not in d["user_characters"] and d["character"] == "ozel"
    check("S22", ok22, f"karakter={d['character']} yoğunluk={d['amount']} geçersiz yoğunluk={st_bad} yol kaçışı={st_p} yerleşik ad={st_n}")
    req("POST", "/api/character", {"id": "notr", "amount": "orta"})
    # S23: teslim ölçüleri (kayıt üzerinden)
    st, dv = req("GET", "/api/delivery")
    ok23 = st == 200 and dv["ok"] is True and set(dv["measures"]) >= {"integrated", "true_peak", "sample_peak", "lra", "floor", "clicks_per_min", "seconds"} \
        and set(dv["targets"]) >= {"integrated", "true_peak", "floor"} and dv["id"] == "current"
    st_bad, _ = req("GET", "/api/delivery?id=yok-boyle")
    st, d2 = req("GET", "/api/delivery?id=radyo")
    ok23 = ok23 and st_bad == 400 and d2["ok"] is True and d2["id"] == "radyo"
    check("S23", ok23, f"alanlar {sorted(dv.get('measures', {}))[:4]}… · bilinmeyen karakter {st_bad} · karakterle ölçüm {d2.get('id')}")
    # S24: seviyeleyiciden önceki kayıt (auto_on anahtarı yok) yüklenince eski ses korunur; modlar seviyeleyiciyi açar
    old = os.path.join(tmp, "eski-durum.json")
    json.dump({"boost_db": 20, "level_on": True, "level_thresh_db": -24, "level_ratio": 10, "denoise_on": True, "denoise_db": 40}, open(old, "w"))
    o = chain.load_state(old)
    lp_old, lp_new = chain.live_params(o), chain.live_params({**chain.DEFAULT_STATE, **chain.PRESETS["fisilti"]})
    ok24 = o["auto_on"] is False and o["boost_db"] == 20 and o["level_ratio"] == 10 and lp_old["auto:Bypass"] is True \
        and lp_new["auto:Bypass"] is False and lp_new["level:Ratio"] == 3.0 and lp_new["level:Input gain (G)"] == 1.0 \
        and lp_new["auto:The maximum amplification gain (dB)"] == 30.0 and chain.PRESETS["ham"]["auto_on"] is False
    # S29: sonradan eklenen mod anahtarı kayıtta yoksa kaydın modundan doldurulur; kayıtta olan değer korunur
    f29 = os.path.join(tmp, "anahtarsiz.json")
    json.dump({"_mode": "ozel", "_base": "fisilti", "auto_on": True, "auto_max_db": 24, "pitch_on": True, "pitch_st": -3}, open(f29, "w"))
    s29 = chain.load_state(f29)
    json.dump({"_mode": "normal", "_base": "normal", "auto_on": True, "pitch_mute": True}, open(f29, "w"))
    s29b = chain.load_state(f29)
    check("S29", s29["pitch_mute"] is True and s29["auto_max_db"] == 24 and s29["pitch_st"] == -3 and chain.live_params(s29)["pitch:Wet-Dry Mix"] == 1.0 and s29b["pitch_mute"] is True,
          f"Fısıltı tabanlı eski kayıt: pitch_mute {s29['pitch_mute']} (kuru geçer), kayıttaki en çok kazanç {s29['auto_max_db']} korundu · kayıtta olan değer ezilmedi: {s29b['pitch_mute'] is True}")
    check("S24", ok24, f"eski kayıt: seviyeleyici kapalı={o['auto_on'] is False}, ön kazanç {o['boost_db']}, oran {o['level_ratio']} · fısıltı modu: oran {lp_new['level:Ratio']}, en çok +{lp_new['auto:The maximum amplification gain (dB)']:g} dB")
    check("S18", ok18, f"bilinmeyen={st0} karakter={d['character']} mod={d['mode']}")
    req("POST", "/api/preset", {"id": "gece"}); req("POST", "/api/state", {"patch": {"denoise_db": 20}})
    st, d = req("POST", "/api/profile", {"save": "gece-evde"})
    ok = st == 200 and "gece-evde" in d["profiles"]
    req("POST", "/api/preset", {"id": "ham"})
    st, d = req("POST", "/api/preset", {"id": "user:gece-evde"})
    ok = ok and d["state"]["denoise_db"] == 20 and d["mode"] == "user:gece-evde"
    st3, _ = req("POST", "/api/profile", {"save": "../../x"})
    st, d = req("POST", "/api/profile", {"delete": "gece-evde"})
    check("S7", ok and st3 == 400 and "gece-evde" not in d["profiles"], f"kaçış={st3}")
    saved = json.load(open(os.path.join(tmp, "mic-hifi", "state.json")))
    import chain
    check("S8", saved["denoise_db"] == 20 and chain.load_state(os.path.join(tmp, "mic-hifi", "state.json"))["denoise_db"] == 20, "state.json")
    lp = chain.live_params({**chain.DEFAULT_STATE, **chain.PRESETS["ham"]})
    check("S9", lp["level:Ratio"] == 1.0 and lp["denoise:Attenuation Limit (dB)"] == 0.0 and lp["gate:Bypass"] is True and lp["level:Input gain (G)"] == 1.0,
          f"oran={lp['level:Ratio']} sınır={lp['denoise:Attenuation Limit (dB)']} kapı-bypass={lp['gate:Bypass']}")
    AUTH = False
    page_st, page = req("GET", "/")
    codes = [req("GET", "/api/state")[0], req("GET", "/api/meter")[0], req("POST", "/api/state", {"patch": {"boost_db": 1}})[0],
             req("GET", "/api/state", headers={"Cookie": "mic_k=" + TOKEN})[0]]
    check("S10", codes == [401, 401, 401, 401], str(codes) + " (sonuncusu: çerezle bile)")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/"); r = c.getresponse(); body = r.read()
    mode = oct(os.stat(os.path.join(tmp, "mic-hifi", "token")).st_mode & 0o777)
    check("S11", page_st == 200 and r.getheader("Set-Cookie") is None and TOKEN.encode() not in body and mode == "0o600",
          f"sayfa={page_st} çerez={r.getheader('Set-Cookie')} sayfada-anahtar={TOKEN.encode() in body} izin={mode}")
    AUTH = True
    st = req("GET", "/api/meter", headers={"Sec-Fetch-Site": "cross-site"})[0]
    check("S12", st == 403, str(st))
    st = req("POST", "/api/state", {"patch": {}}, headers={"Content-Length": "-5"})[0]
    st2 = req("POST", "/api/state", {"patch": {}}, headers={"Content-Length": "abc"})[0]
    check("S13", st == 400 and st2 == 400, f"{st}/{st2}")
    ok15 = True
    for _ in range(6):   # istemci sınırı 4: her akış kapanınca yer açılmalı
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/api/meter", headers={"X-Mic-Key": TOKEN, "X-Mic-Console": "1"})
        r = c.getresponse(); line = r.fp.readline() if r.status == 200 else b""
        ok15 = ok15 and r.status == 200 and line.startswith(b'data: {"in"')
        c.close(); time.sleep(0.3)
    check("S15", ok15, f"6 ardışık akış: {'hepsi veri verdi' if ok15 else 'BAŞARISIZ'}")
    st, d = req("GET", "/api/state")
    has = all(k in d for k in ("mic", "dropouts", "trial")) and d["trial"] == "idle"
    bad = req("POST", "/api/trial", {"seconds": 99})[0]
    st, d1 = req("POST", "/api/trial", {"seconds": 5})
    st, d2 = req("POST", "/api/trial", {"seconds": 5})
    seen = {d1["trial"]}
    for _ in range(30):
        time.sleep(0.15); seen.add(req("GET", "/api/state")[1]["trial"])
    check("S16", has and bad == 400 and "zaten" in d2["message"] and {"kayit", "ham", "temiz", "idle"} <= seen, f"alanlar={has} geçersiz={bad} fazlar={sorted(seen)}")
    tmp3 = tempfile.mkdtemp(); os.makedirs(os.path.join(tmp3, "mic-hifi"))
    json.dump({"require_key": False}, open(os.path.join(tmp3, "mic-hifi", "config.json"), "w"))
    s3 = socket.socket(); s3.bind(("127.0.0.1", 0)); port3 = s3.getsockname()[1]; s3.close()
    srv3 = subprocess.Popen([sys.executable, os.path.join(ROOT, "console", "server.py"), "--port", str(port3)], env=dict(env, XDG_CONFIG_HOME=tmp3), stdout=subprocess.PIPE)
    srv3.stdout.readline()
    def r3(headers):
        c = http.client.HTTPConnection("127.0.0.1", port3, timeout=5); c.request("GET", "/api/state", headers=headers); r = c.getresponse(); r.read(); c.close(); return r.status
    codes = [r3({"X-Mic-Console": "1"}), r3({}), r3({"X-Mic-Console": "1", "Sec-Fetch-Site": "cross-site"}), r3({"X-Mic-Console": "1", "Host": "evil.example"}),
             r3({"X-Mic-Console": "1", "Origin": "http://evil.example"})]
    srv3.terminate(); srv3.wait()
    check("S17", codes == [200, 403, 403, 403, 403], str(codes))
    sys.path.insert(0, os.path.join(ROOT, "console"))
    os.environ["XDG_CONFIG_HOME"] = tmp2 = tempfile.mkdtemp()
    import importlib, chain as _c
    importlib.reload(_c)
    import server as _s
    importlib.reload(_s)
    os.makedirs(os.path.dirname(_s.TOKEN_FILE), exist_ok=True)
    open(_s.TOKEN_FILE, "w").write("A" * 43); os.chmod(_s.TOKEN_FILE, 0o644)
    t1 = _s.load_token()
    m1 = oct(os.stat(_s.TOKEN_FILE).st_mode & 0o777)
    victim = os.path.join(tmp2, "victim"); open(victim, "w").write("B" * 43); os.chmod(victim, 0o600)
    os.unlink(_s.TOKEN_FILE); os.symlink(victim, _s.TOKEN_FILE)
    t2 = _s.load_token()
    dmode = oct(os.stat(os.path.dirname(_s.TOKEN_FILE)).st_mode & 0o777)
    check("S14", t1 != "A" * 43 and m1 == "0o600" and t2 != "B" * 43 and not os.path.islink(_s.TOKEN_FILE) and open(victim).read() == "B" * 43
          and _s.load_token() == t2 and dmode == "0o700", f"gevşek→yeni:{t1 != 'A' * 43} izin={m1} bağ→yeni:{t2 != 'B' * 43} kurban sağlam:{open(victim).read() == 'B' * 43} dizin={dmode}")
    # S21: kayıt silme kapalı-başarısız + kayıtçı sunucudan bağımsız süre sınırlı
    au = _s.Audition()
    os.makedirs(au.dir, exist_ok=True)
    open(au.take, "w").write("x"); au.take_at = time.time()
    ok_a = au.wipe() is True and not os.path.exists(au.take) and au.has_take() is False
    os.makedirs(au.take)                                   # silinemeyen "dosya" (dizin) → remove OSError
    au.take_at = time.time()
    ok_b = au.wipe() is False and au.take_at != 0.0 and au.has_take() is False
    os.rmdir(au.take)
    src = open(os.path.join(ROOT, "console", "server.py"), encoding="utf-8").read()
    ok_c = src.count('"timeout", "--signal=TERM", "--kill-after=2"') == 3   # karşılaştırma kayıtçısı + çalıcı + teşhis kayıtçısı
    # S25: karşılaştırma kaydı çıkış kazancı 0 iken alınır — işleyici (ton…tavan) kazancı kendisi uygular; aksi hâlde iki kez eklenir
    check("S25", au.OFF.get("out_db") == 0 and au.OFF.get("loud_db") == 0 and au.OFF.get("pitch_st") == 0 and all(au.OFF.get(k) is False for k in ("tone_on", "deess_on", "dyn_body_on", "dyn_mud_on", "dyn_harsh_on", "sat_on")), f"kayıt sırasında geçici durum: {au.OFF}")
    check("S21", ok_a and ok_b and ok_c, f"silme başarılı→bayrak iner: {ok_a} · silinemeyince 'temiz' denmez: {ok_b} · kayıtçı ve çalıcı süre sınırlı: {ok_c}")
    # S31: kalite mikrofonu durumu
    def q(lines):
        if lines is None:
            if os.path.exists(QEV): os.remove(QEV)
        else:
            open(QEV, "w", encoding="utf-8").write("".join(l if isinstance(l, str) else json.dumps(l, ensure_ascii=False) + "\n" for l in lines))
        return req("GET", "/api/state")[1].get("quality", {})
    ev = lambda k, **kw: {"t": 1.0, "event": k, **kw}
    got = [q(None).get("state"), q([ev("gözcü hazır")]).get("state"), q([ev("gözcü hazır"), ev("dinleyen"), ev("işçi başlatıldı")]).get("state"),
           q([ev("işçi başlatıldı"), ev("işçi bağlandı")]).get("state"), q([ev("işçi bağlandı"), ev("ıslak")]).get("state"),
           q([ev("ıslak"), ev("kuru", neden="işçi öldü"), ev("işçi kapatıldı")]).get("state"), q([ev("kuru"), ev("kilitli")]).get("state"),
           q([ev("ıslak"), "{bozuk\n"]).get("state"), q([ev("ıslak"), ev("gözcü kapandı")]).get("state")]
    want = ["yok", "bosta", "hazirlaniyor", "hazirlaniyor", "etkin", "bosta", "kilitli", "etkin", "yok"]
    import carrier
    unit_ok = f"--delay-ms {carrier.QUALITY_DELAY_MS} " in open(os.path.join(ROOT, "conf", "mic-watch.service"), encoding="utf-8").read()
    check("S31", got == want and q([ev("ıslak")]).get("delay_ms") == carrier.QUALITY_DELAY_MS and unit_ok, f"durumlar {got} (= {want}) · gecikme {q([ev('ıslak')]).get('delay_ms')} ms")
    # S35: sayfa sürümü
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/"); html = c.getresponse().read().decode()
    ui = req("GET", "/api/state")[1].get("ui")
    import re as _re
    emb = (_re.search(r'const UI = "([0-9a-f]{12})"', html) or [None, None])[1]
    check("S35", bool(ui) and emb == ui and "__UI_VERSION__" not in html and "Panel güncellendi" in html, f"durumdaki ui {ui} · sayfaya gömülen {emb} · yer tutucu kaldı mı: {'__UI_VERSION__' in html}")
    # S34: yetenek — ayrı bir kuru sunucu, boş eklenti diziniyle (ana sunucuda eklentiler "var" sayılır)
    tmp2 = tempfile.mkdtemp(); s2 = socket.socket(); s2.bind(("127.0.0.1", 0)); port2 = s2.getsockname()[1]; s2.close()
    srv2 = subprocess.Popen([sys.executable, os.path.join(ROOT, "console", "server.py"), "--port", str(port2)], stdout=subprocess.PIPE,
                            env=dict(os.environ, MIC_DRY="1", XDG_CONFIG_HOME=tmp2, XDG_STATE_HOME=os.path.join(tmp2, "state"), MIC_PLUGIN_DIR=os.path.join(tmp2, "eklenti-yok")))
    srv2.stdout.readline()
    def req2(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port2, timeout=5)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", "X-Mic-Console": "1", "X-Mic-Key": open(os.path.join(tmp2, "mic-hifi", "token")).read().strip()})
        r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")
    try:
        st, c0 = req2("GET", "/api/state"); st, c1 = req2("POST", "/api/state", {"patch": {"pitch_on": True}})
    finally:
        srv2.terminate(); srv2.wait()
    main_caps = req("GET", "/api/state")[1].get("caps")
    check("S34", c0.get("caps") == {"denoise": False, "pitch": False} and c1["state"]["pitch_on"] is False and bool(c1.get("message")) and c1["restarts"] == c0["restarts"] and main_caps == {"denoise": True, "pitch": True},
          f"eklentisiz caps {c0.get('caps')} · perde açılmadı: {c1['state']['pitch_on'] is False} · ileti: {c1.get('message', '')[:50]!r} · yeniden başlatma {c1['restarts'] - c0['restarts']} (0) · ana sunucu caps {main_caps}")
    # S32: teşhis kaydı
    dg = lambda: req("GET", "/api/state")[1].get("diag", {})
    d0 = dg(); ids = [x.get("id") for x in d0.get("steps", [])]
    ok_a = ids == ["sessiz", "aaa", "ptk", "fisilti", "tik", "metin"] and all(x.get("prompt") and x.get("seconds") and x.get("done") is False for x in d0["steps"])
    ok_b = req("POST", "/api/diag", {"action": "record", "step": "yok"})[0] == 400 and req("POST", "/api/diag", {"action": "x"})[0] == 400
    st, r1 = req("POST", "/api/diag", {"action": "record", "step": "sessiz"})
    st2, r2 = req("POST", "/api/diag", {"action": "record", "step": "aaa"}); st3, r3 = req("POST", "/api/audition", {"action": "record", "seconds": 3})
    busy = bool(r2.get("message")) and bool(r3.get("message")) and r1.get("diag", {}).get("phase") == "kayit"
    for _ in range(60):
        if dg().get("phase") == "idle": break
        time.sleep(0.1)
    d1 = dg(); s1 = next((x for x in d1.get("steps", []) if x["id"] == "sessiz"), {})
    ddir = os.path.join(tmp, "state", "mic-hifi", "diag"); f1 = os.path.join(ddir, "sessiz.wav")
    ok_c = s1.get("done") is True and isinstance(s1.get("level_db"), (int, float)) and os.path.exists(f1) and (os.stat(f1).st_mode & 0o777) == 0o600 and (os.stat(ddir).st_mode & 0o777) == 0o700
    ok_f = bool(s1.get("warn"))   # kuru sunucu tam sessiz kayıt üretir → "mikrofondan ses gelmiyor" uyarısı beklenir
    st, r4 = req("POST", "/api/diag", {"action": "delete"})
    d2 = dg()
    ok_e = not os.path.exists(f1) and all(x["done"] is False for x in d2.get("steps", [{"done": True}]))
    # konuşma adımı oda sesinden ayırt edilemiyorsa uyarı (kullanıcı konuşmadan kaydetmiş): dosyalar doğrudan yazılır
    import random, struct, wave as _wave
    def put(step, db):
        rng = random.Random(7); amp = 32768 * 10 ** (db / 20) * 1.732
        with _wave.open(os.path.join(ddir, step + ".wav"), "wb") as w_:
            w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(48000)
            w_.writeframes(b"".join(struct.pack("<h", int(rng.uniform(-amp, amp))) for _ in range(144000)))   # 3 sn: oda ölçümü en az 2 sn ister
    room0 = dg().get("room", "yok")
    put("sessiz", -53); put("aaa", -52); put("ptk", -35)
    g3 = dg(); room1 = g3.get("room") or {}
    check("S33", room0 is None and isinstance(room1.get("room_lufs"), (int, float)) and set(room1.get("modes", {})) == {"normal", "fisilti", "gece"}
          and all(isinstance(v.get("margin_db"), (int, float)) and isinstance(v.get("ok"), bool) for v in room1.get("modes", {}).values()),
          f"kayıt yokken {room0!r} (None) · varken oda {room1.get('room_lufs')} LUFS · modlar {sorted(room1.get('modes', {}))}")
    d3 = {x["id"]: x for x in g3["steps"]}
    ok_g = not d3["sessiz"]["warn"] and bool(d3["aaa"]["warn"]) and not d3["ptk"]["warn"] and abs(d3["ptk"]["level_db"] + 35) <= 1
    # S36: ortalama seviye konuşmayı kanıtlamaz — oda sesi + kısa yüksek darbe (masaya vurma) konuşma adımını "yapıldı" göstermemeli
    def put_thump(step, room_db=-53, hit_db=-12, hit_s=0.4, total_s=8):
        rng = random.Random(9); n_hit = int(48000 * hit_s); n = 48000 * total_s
        with _wave.open(os.path.join(ddir, step + ".wav"), "wb") as w_:
            w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(48000)
            w_.writeframes(b"".join(struct.pack("<h", int(rng.uniform(-1, 1) * 32768 * 1.732 * 10 ** ((hit_db if 96000 <= i < 96000 + n_hit else room_db) / 20)))
                                    for i in range(n)))
    put("sessiz", -53); put_thump("ptk"); put("fisilti", -40)
    d4 = {x["id"]: x for x in dg()["steps"]}
    check("S36", "kısa" in (d4["ptk"]["warn"] or "") and d4["ptk"].get("speech_s") is not None and d4["ptk"]["speech_s"] < 1.0
          and not d4["fisilti"]["warn"] and d4["fisilti"]["speech_s"] > 2.5 and d4["sessiz"].get("speech_s") is None,
          f"darbe: uyarı {d4['ptk']['warn'][:40]!r}, konuşma {d4['ptk'].get('speech_s')} sn (< 1) · sürekli ses: uyarı yok, {d4['fisilti'].get('speech_s')} sn · oda adımında alan yok")
    # S37: "Uzun ses" SÜREKLİ olmalı — toplamı yeten ama kesik kesik ses (odadaki konuşma) geçmemeli (ölçüldü: 3,0 sn kesikli ortam sesi geçti)
    def put_bursts(step, spans, room_db=-53, hit_db=-30, total_s=6):
        rng = random.Random(11)
        with _wave.open(os.path.join(ddir, step + ".wav"), "wb") as w_:
            w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(48000)
            w_.writeframes(b"".join(struct.pack("<h", int(rng.uniform(-1, 1) * 32768 * 1.732 * 10 ** ((hit_db if any(a <= i / 48000 < b for a, b in spans) else room_db) / 20)))
                                    for i in range(48000 * total_s)))
    put("sessiz", -53); put_bursts("aaa", [(0.5, 1.1), (1.5, 2.1), (2.5, 3.1), (3.5, 4.1), (4.5, 5.1)])
    w5 = {x["id"]: x for x in dg()["steps"]}["aaa"]
    put_bursts("aaa", [(1.0, 4.0)])
    w6 = {x["id"]: x for x in dg()["steps"]}["aaa"]
    check("S37", "kesintisiz" in (w5["warn"] or "") and w5["speech_s"] >= 2.4 and not w6["warn"],
          f"kesikli 5×0,6 sn (toplam {w5['speech_s']} sn): uyarı {w5['warn'][:36]!r} · tek parça 3 sn: uyarı {w6['warn']!r}")
    # S38: etiketli örnek adımları — "tik" (bilerek yapılan ağız sesleri: kısa darbeler GEÇERLİ, konuşma süresi aranmaz) ve "metin" (25 sn, duraklamalı okuma)
    ids = [x["id"] for x in dg()["steps"]]; secs = {x["id"]: x["seconds"] for x in dg()["steps"]}
    def put_clicks(step, k, room_db=-53, total_s=8):
        rng = random.Random(13); marks = {int(48000 * (1 + j)): 1 for j in range(k)}
        with _wave.open(os.path.join(ddir, step + ".wav"), "wb") as w_:
            w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(48000)
            w_.writeframes(b"".join(struct.pack("<h", int(rng.uniform(-1, 1) * 32768 * 1.732 * 10 ** ((-25 if any(m <= i < m + 240 for m in marks) else room_db) / 20)))
                                    for i in range(48000 * total_s)))
    put("sessiz", -53); put_clicks("tik", 5); a5 = {x["id"]: x for x in dg()["steps"]}.get("tik", {})
    put_clicks("tik", 1); a1 = {x["id"]: x for x in dg()["steps"]}.get("tik", {})
    check("S38", ids == ["sessiz", "aaa", "ptk", "fisilti", "tik", "metin"] and secs.get("metin") == 25 and a5.get("done") and not a5.get("warn")
          and a5.get("events") == 5 and "en az" in (a1.get("warn") or ""),
          f"adımlar {ids} · metin {secs.get('metin')} sn · 5 darbe: olay {a5.get('events')}, uyarı {a5.get('warn')!r} · 1 darbe: uyarı {(a1.get('warn') or '')[:40]!r}")
    req("POST", "/api/diag", {"action": "delete"})
    check("S32", ok_a and ok_b and busy and ok_c and ok_f and ok_e and ok_g, f"adımlar: {ok_a} · doğrulama 400: {ok_b} · meşgulken ret: {busy} · kayıt + izinler: {ok_c} · sessiz kayıt uyarısı: {ok_f} ({s1.get('warn')}) · silme: {ok_e} · oda sesinden ayırt edilemeyen konuşma adımı uyarı verir: {ok_g}")
finally:
    srv.terminate(); srv.wait()
print(f"\n{'PASS' if not fails else 'FAIL'}: {RAN[0] - len(fails)}/{RAN[0]}")
sys.exit(1 if fails else 0)
