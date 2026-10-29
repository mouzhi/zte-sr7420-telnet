#!/bin/sh
# Builds a locally modified server from pinned official source. Never contacts a router.
set -eu
umask 077
if [ "$#" -ne 1 ]; then
  echo "Usage: sh scripts/build-dropbear.sh NEW_BUILD_DIRECTORY_OUTSIDE_REPOSITORY" >&2
  exit 2
fi
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
WORK=$(realpath -m -- "$1")
case "$WORK/" in "$REPO/"*) echo "Build outside the repository" >&2; exit 2;; esac
test ! -e "$WORK" || { echo "Build directory already exists; refusing to overwrite" >&2; exit 2; }
PIN=28216cd9af822732a1549b78621c2ea9a76a0fe5
mkdir -p "$WORK"
git clone --depth 1 --branch DROPBEAR_2026.94 https://github.com/mkj/dropbear.git "$WORK/source"
test "$(git -C "$WORK/source" rev-parse HEAD)" = "$PIN" || { echo "Upstream revision mismatch" >&2; exit 1; }
git -C "$WORK/source" apply --check "$REPO/patches/dropbear-2026.94-sr7420-pty.patch"
git -C "$WORK/source" apply "$REPO/patches/dropbear-2026.94-sr7420-pty.patch"
cd "$WORK/source"
cat >localoptions.h <<'OPTIONS'
#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PAM_AUTH 0
#define DROPBEAR_SVR_PUBKEY_AUTH 1
#define DROPBEAR_RSA 0
#define DROPBEAR_DSS 0
#define DROPBEAR_ECDSA 0
#define DROPBEAR_ED25519 1
OPTIONS
CC=arm-linux-gnueabi-gcc CFLAGS='-Os -ffunction-sections -fdata-sections' LDFLAGS='-Wl,--gc-sections' \
  sh ./configure --host=arm-linux-gnueabi --enable-static --disable-zlib \
  --disable-shadow --disable-syslog --disable-utmp --disable-utmpx \
  --disable-wtmp --disable-wtmpx --disable-lastlog --disable-openpty
make -j2 'PROGRAMS=dropbear dropbearkey' MULTI=1
arm-linux-gnueabi-strip dropbearmulti
mkdir "$WORK/output"
cp dropbearmulti "$WORK/output/"
cp LICENSE "$WORK/output/Dropbear-LICENSE.txt"
printf 'Modified Dropbear 2026.94 for SR7420; upstream %s\n' "$PIN" >"$WORK/output/BUILD.txt"
printf 'Local patches: private devpts; reset inherited signal mask. Password/PAM auth compiled out.\n' >>"$WORK/output/BUILD.txt"
arm-linux-gnueabi-gcc --version | sed -n '1p' >>"$WORK/output/BUILD.txt"
sha256sum "$WORK/output/dropbearmulti" >>"$WORK/output/BUILD.txt"
echo "Build complete: $WORK/output"
