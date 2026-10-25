#!/usr/bin/env python3
"""İki dilli panel (EN/TR) — docs/PRD-PUBLISH.md "Test noktaları — I", karar D50. Canlıya dokunmaz (kuru sunucu, MIC_DRY=1).

I1 en.json ve tr.json aynı anahtar kümesi, boş değer yok, anahtar başına aynı {yer tutucu} kümesi   neden: eksik çeviri sessizce anahtar adını gösterir
I2 index.html'de data-i18n* dışında harfli görünür metin/öznitelik yok; betikte Türkçe dize yok (yorumlar ve birimler hariç)   neden: çevrilmeyen kalıntı
I6 mod/karakter/yoğunluk/hedef/dinleme: her id iki dilde; HTML'deki id kümeleri chain ile aynı; Türkçe adlar eskisiyle aynı   neden: API sözleşmesi
I7 sunucu iletileri koda bağlı (Msg), her kod iki dilde; koda bağlanmamış Türkçe ileti dizesi yok; çalışan sunucu kod + Türkçe metni birlikte döner,
   Türkçe şablon + değişkenler = sunucunun Türkçe metni   neden: yalnız istemci çevrilirse uyarılar Türkçe kalır
I5s sayfa `/?lang=en` ile de verilir (200, sözlükler gömülü, yer tutucu kalmaz)   neden: ?lang= bağlantısı 403 alıyordu (sunucu yalnız tam "/" yolunu sayfa sayıyordu)
(I3–I5, I8 başsız tarayıcıyla, elle; sonuçlar PRD'de.)
"""
import ast, http.client, json, os, re, socket, subprocess, sys, tempfile, time
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import chain

TRL = re.compile(r"[çğıöşüÇĞİÖŞÜâÂîÎ]")
PH = re.compile(r"\{(\w+)\}")
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


def load(lang):
    try:
        return json.load(open(os.path.join(ROOT, "console", "i18n", lang + ".json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


EN, TR = load("en"), load("tr")
HTML = open(os.path.join(ROOT, "console", "index.html"), encoding="utf-8").read()

# ── I1 ──
only_en, only_tr = sorted(set(EN) - set(TR)), sorted(set(TR) - set(EN))
empty = [k for d in (EN, TR) for k, v in d.items() if not isinstance(v, str) or not v.strip()]
ph_diff = [k for k in set(EN) & set(TR) if set(PH.findall(EN[k])) != set(PH.findall(TR[k]))]
# biçimli değer yalnız "_html" anahtarında ve yalnız <b>…</b>; başka hiçbir değerde etiket yok (panel innerHTML kullanmaz, <b> düğümü kurar)
tags = [k for d in (EN, TR) for k, v in d.items() if isinstance(v, str) and re.search(r"<(?!/?b>)[a-zA-Z/!]", v) or (isinstance(v, str) and "<b>" in v and not k.endswith("_html"))]
check("I1", bool(EN) and not only_en and not only_tr and not empty and not ph_diff and not tags,
      f"{len(EN)} anahtar · yalnız en: {only_en[:5] or 'yok'} · yalnız tr: {only_tr[:5] or 'yok'} · boş: {empty[:5] or 'yok'} · yer tutucu farkı: {ph_diff[:5] or 'yok'} · izinsiz etiket: {tags[:5] or 'yok'}")


# ── I2 ──
UNITS = re.compile(r"\b(?:dB|dBFS|dBTP|LUFS|LU|Hz|kHz|ms)\b")
ATTRS = {"title": "data-i18n-title", "aria-label": "data-i18n-aria", "placeholder": "data-i18n-ph", "alt": "data-i18n-alt"}
VOID = {"meta", "link", "input", "br", "img", "hr"}


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.bad, self.keys, self.in_script = [], [], set(), False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k in ("data-i18n", "data-i18n-html", "data-i18n-title", "data-i18n-aria", "data-i18n-ph", "data-i18n-alt"):
            if a.get(k):
                self.keys.add(a[k])
        for at, marker in ATTRS.items():
            v = a.get(at)
            if v and re.search(r"[^\W\d_]", UNITS.sub("", v)) and not a.get(marker):
                self.bad.append(f"<{tag} {at}={v[:30]!r}>")
        if tag in VOID:
            return
        self.stack.append((tag, bool(a.get("data-i18n")), bool(a.get("data-i18n-html"))))
        self.in_script = tag in ("script", "style")

    def handle_endtag(self, tag):
        while self.stack:
            t = self.stack.pop()[0]
            if t == tag:
                break
        self.in_script = False

    def handle_data(self, data):
        if self.in_script or not self.stack or self.stack[-1][0] in ("script", "style"):
            return
        txt = UNITS.sub("", data).strip()
        if re.search(r"[^\W\d_]", txt) and not self.stack[-1][1] and not any(h for _t, _m, h in self.stack):
            self.bad.append(repr(data.strip()[:40]))


sc = Scan(); sc.feed(HTML)
script = "\n".join(re.findall(r"<script>(.*?)</script>", HTML, re.S))
code = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
code = "\n".join(re.sub(r"(^|[^:\"'\\])//.*$", r"\1", ln) for ln in code.splitlines())
lits = re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`((?:[^`\\]|\\.)*)`', code)
lits = [x for t in lits for x in t if x]
TRWORDS = re.compile(r"\b(?:Profil\w*|Mikrofon\w*|mikrofon\w*|Tamam|Kaydet\w*|Kaydedil\w*|kalite|zincir|hedef|dk|sn|Panel a\w*|Olmad\w*|Hazırlan|Ham mikrofon)\b")
js_bad = [x for x in lits if TRL.search(x) or TRWORDS.search(x)]
missing_keys = sorted(k for k in sc.keys if k not in EN)
check("I2", not sc.bad and not js_bad and not missing_keys,
      f"etiketsiz metin/öznitelik: {sc.bad[:6] or 'yok'} · betikte Türkçe dize: {js_bad[:6] or 'yok'} · sözlükte olmayan anahtar: {missing_keys[:6] or 'yok'}")

# ── I6 ──
ids = lambda attr: set(re.findall(attr + r'="([a-z]+)"', HTML))
want_tr = {"mode.normal": "Normal", "mode.fisilti": "Fısıltı", "mode.gece": "Gece", "mode.ham": "Ham",
           "char.notr": "Nötr", "char.sicak": "Sıcak", "char.parlak": "Parlak", "char.radyo": "Radyo", "char.derin": "Derin", "char.yakin": "Yakın",
           "char.kalin": "Kalın", "char.iri": "İri", "char.telefon": "Telefon", "char.megafon": "Megafon",
           "amt.hafif": "Hafif", "amt.orta": "Orta", "amt.guclu": "Güçlü", "amt.cok": "En güçlü"}
need = [f"mode.{m}" for m in chain.PRESETS] + [f"mode.{m}.desc" for m in chain.PRESETS] + [f"char.{c}" for c in chain.CHARACTERS] + \
       [f"char.{c}.desc" for c in chain.CHARACTERS] + [f"amt.{a}" for a in chain.AMOUNTS] + [f"loud.{t}" for t in chain.LOUD_TARGETS] + [f"mon.{m}" for m in ("off", "temiz", "ham")]
miss6 = [k for k in need if not (EN.get(k) and TR.get(k))]
idok = ids("data-mode") == set(chain.PRESETS) and ids("data-char") == set(chain.CHARACTERS) and ids("data-loud") == set(chain.LOUD_TARGETS) \
    and ids("data-amt") == set(chain.AMOUNTS) and ids("data-id") == set(chain.CHARACTERS) | {"off", "current"} and ids("data-mon") == {"off", "temiz", "ham"}
trdiff = [k for k, v in want_tr.items() if TR.get(k) != v]
same_en = [k for k in want_tr if k in EN and EN[k] == TR.get(k) and k not in ("mode.normal",)]
check("I6", not miss6 and idok and not trdiff and not same_en,
      f"{len(need)} ad/açıklama · eksik: {miss6[:6] or 'yok'} · id kümeleri chain ile aynı: {idok} · değişen Türkçe ad: {trdiff or 'yok'} · çevrilmemiş EN ad: {same_en or 'yok'}")

# ── I7 (durağan): sunucu kaynağı ──
src = open(os.path.join(ROOT, "console", "server.py"), encoding="utf-8").read()
tree = ast.parse(src)
parent = {}
for n in ast.walk(tree):
    for c in ast.iter_child_nodes(n):
        parent[c] = n
codes, call_vars = {}, {}
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Msg" and n.args and isinstance(n.args[0], ast.Constant):
        codes.setdefault(n.args[0].value, set()).update(k.arg for k in n.keywords)
docs = {id(b.body[0].value) for b in ast.walk(tree) if isinstance(b, (ast.FunctionDef, ast.ClassDef, ast.Module)) and b.body
        and isinstance(b.body[0], ast.Expr) and isinstance(b.body[0].value, ast.Constant)}
ALLOW_FN = {"quality_line", "_run", "main"}          # gözcü olay adları (iç veri), `mic ab` çıktısını ayrıştırma, sunucu günlüğü
ALLOW_ASSIGN = {"SENTENCE", "STEPS"}                 # teşhis adımları: istemci id'den çevirir (diag.<id>.title/.prompt)


def context_ok(n):
    p = n
    while p in parent:
        p = parent[p]
        if isinstance(p, ast.Call) and getattr(p.func, "id", None) == "Msg":
            return True
        if isinstance(p, ast.FunctionDef) and p.name in ALLOW_FN:
            return True
        if isinstance(p, ast.Assign) and any(getattr(t, "id", None) in ALLOW_ASSIGN for t in p.targets):
            return True
    return False


loose = [n.value[:40] for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and TRL.search(n.value)
         and id(n) not in docs and not context_ok(n)]
err_dicts = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "error" for k in n.keys)
             and not any(isinstance(p, ast.FunctionDef) and p.name == "_err" for p in [parent.get(n), parent.get(parent.get(n)), parent.get(parent.get(parent.get(n)))])]
nokey = sorted(c for c in codes if not (EN.get("srv." + c) and TR.get("srv." + c)))
badvars = sorted(c for c, v in codes.items() if c not in nokey and not set(PH.findall(EN["srv." + c])) <= v)
steps_ok = all(EN.get(f"diag.{s[0]}.{f}") and TR.get(f"diag.{s[0]}.{f}") for s in [(x,) for x in ("sessiz", "aaa", "ptk", "fisilti", "tik", "metin")] for f in ("title", "prompt"))

# ── I7 (çalışan kuru sunucu) ──
tmp = tempfile.mkdtemp()
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, MIC_DRY="1", XDG_CONFIG_HOME=tmp, XDG_STATE_HOME=os.path.join(tmp, "state"), MIC_QUALITY_EVENTS=os.path.join(tmp, "q.jsonl"))
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "console", "server.py"), "--port", str(port)], env=env, stdout=subprocess.PIPE)
srv.stdout.readline()
TOKEN = open(os.path.join(tmp, "mic-hifi", "token")).read().strip()


def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json", "X-Mic-Console": "1", "X-Mic-Key": TOKEN}
    h.update(headers or {})
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    r = c.getresponse(); raw = r.read(); c.close()
    return r.status, json.loads(raw or b"{}")


def tr_render(code, vars_):
    t = TR.get("srv." + code, "")
    return PH.sub(lambda m: str(vars_.get(m.group(1), m.group(0))), t)


seen = []
try:
    st, d = req("POST", "/api/audition", {"action": "play", "id": "radyo"}); seen.append(("message", d))           # kayıt yok
    st, d = req("GET", "/api/delivery"); seen.append(("message", d))
    req("POST", "/api/trial", {"seconds": 5}); st, d = req("POST", "/api/trial", {"seconds": 5}); seen.append(("message", d))   # deneme zaten sürüyor
    st, d = req("POST", "/api/profile", {"save": "deneme-1"}); seen.append(("message", d))
    st, d = req("POST", "/api/profile", {"delete": "deneme-1"}); seen.append(("message", d))
    st, e1 = req("POST", "/api/profile", {"save": "Kötü Ad"}); seen.append(("error", e1))
    st, e2 = req("GET", "/api/yok"); seen.append(("error", e2))
    st, e3 = req("GET", "/api/state", headers={"X-Mic-Key": "x" * 40}); seen.append(("error", e3))
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request("GET", "/?lang=en"); r = c.getresponse(); page = r.read().decode(); c.close()
    page_ok = (r.status, r.getheader("Content-Type", "")[:9]) == (200, "text/html") and "/*__I18N__*/" not in page and '"en": {"app.title": "Mic Console"' in page
    time.sleep(2.0)
    req("POST", "/api/diag", {"action": "record", "step": "sessiz"}); time.sleep(1.2)
    st, d = req("GET", "/api/state")
    steps = d.get("diag", {}).get("steps", [])
finally:
    srv.terminate(); srv.wait()
rt_bad = []
for kind, d in seen:
    text, c, v = (d.get("message"), d.get("message_code"), d.get("message_vars", {})) if kind == "message" else (d.get("error"), d.get("code"), d.get("vars", {}))
    if not c or not EN.get("srv." + c) or tr_render(c, v) != text:
        rt_bad.append(f"{kind}:{c}:{(text or '')[:30]}")
warned = [x for x in steps if x.get("warn")]
for x in warned:
    if not x.get("warn_code") or not EN.get("srv." + x["warn_code"]) or tr_render(x["warn_code"], x.get("warn_vars", {})) != x["warn"]:
        rt_bad.append(f"warn:{x.get('warn_code')}")
check("I7", codes and not nokey and not badvars and not loose and not err_dicts and steps_ok and not rt_bad and warned,
      f"{len(codes)} kod · sözlükte eksik: {nokey[:5] or 'yok'} · EN şablonda tanımsız değişken: {badvars[:5] or 'yok'} · koda bağlanmamış Türkçe dize: {loose[:4] or 'yok'} · "
      f"_err dışında hata sözlüğü: {err_dicts[:4] or 'yok'} · teşhis adımları iki dilde: {steps_ok} · çalışan sunucu ({len(seen) + len(warned)} ileti) uyumsuz: {rt_bad[:4] or 'yok'}")

check("I5s", page_ok, f"/?lang=en → {r.status} {r.getheader('Content-Type')} · sözlük gömülü: {'Mic Console' in page}")

print(f"\n{len(ran) - len(fails)}/{len(ran)} PASS" + (f" · FAIL: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
