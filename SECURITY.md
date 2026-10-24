# Güvenlik

- Panel yalnız `127.0.0.1` üzerinde dinler; istekler kişisel bir anahtar ve özel bir başlık ister. Paneli ağa açma.
- Ses kayıtları yalnız bu bilgisayarda, yalnız kullanıcının okuyabildiği dizinlerde tutulur; hiçbir yere gönderilmez.
- Kullanıcı dizinine kurulan ikili eklentilerin özeti `plugins.lock.json` ile karşılaştırılır; uyuşmayan eklenti ses yoluna yüklenmez (`python3 tools/plugins.py check`).
- Bir açık bulduysan lütfen herkese açık bir kayıt açmadan önce depo sahibine özel olarak bildir (depo sayfasındaki güvenlik bildirimi yolu).

Security issues: please report privately to the repository owner before opening a public issue.
