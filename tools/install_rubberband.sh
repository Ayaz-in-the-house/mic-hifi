#!/usr/bin/env bash
# Perde kaydırma eklentisini KÖK YETKİSİ OLMADAN kurar: Fedora deposundan sabit sürüm indirir, imzasını ve özetini doğrular,
# paket betiği çalıştırmadan açar, yalnız .so dosyasını ~/.local/lib/mic-hifi/ altına koyar. Yinelenebilir.
# Sürüm ya da özet değişirse DURUR: yeni sürümü önce incele, sonra aşağıdaki iki sabiti bilerek güncelle.
set -euo pipefail
PKG="ladspa-rubberband-plugins-4.0.0-5.fc44"
RPM_SHA256="69e06418cb7b72b7d8707789dec5692119086c832ee4d7e540f66945ff9bb902"
SO_SHA256="b7e61e16c28632fd5aa63ef0be46786d53f8b6f6feab236e29bf44cc60cd9f04"
DEST="$HOME/.local/lib/mic-hifi/ladspa-rubberband.so"
if [ -f "$DEST" ] && [ "$(sha256sum "$DEST" | cut -d' ' -f1)" = "$SO_SHA256" ]; then echo "zaten kurulu ve özet doğru: $DEST"; exit 0; fi
rpm -q rubberband-libs >/dev/null || { echo "eksik bağımlılık: rubberband-libs (sudo dnf install rubberband-libs)"; exit 1; }
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
( cd "$W" && dnf download "$PKG" >/dev/null )
RPM="$(ls "$W"/*.rpm)"
[ "$(sha256sum "$RPM" | cut -d' ' -f1)" = "$RPM_SHA256" ] || { echo "paket özeti beklenenle AYNI DEĞİL: kurulmadı"; exit 1; }
rpm -K "$RPM" | grep -q "digests signatures OK" || { echo "paket imzası doğrulanamadı: kurulmadı"; exit 1; }
( cd "$W" && rpm2cpio "$RPM" | cpio -idm --quiet ./usr/lib64/ladspa/ladspa-rubberband.so )
[ "$(sha256sum "$W/usr/lib64/ladspa/ladspa-rubberband.so" | cut -d' ' -f1)" = "$SO_SHA256" ] || { echo "eklenti özeti beklenenle AYNI DEĞİL: kurulmadı"; exit 1; }
install -D -m 0644 "$W/usr/lib64/ladspa/ladspa-rubberband.so" "$DEST"
echo "kuruldu: $DEST"
