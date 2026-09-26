#!/usr/bin/env bash
# Construit « SP500 Analyzer.app » et une image disque .dmg. À exécuter sur macOS.
# Prérequis : pip install ".[app,llm]" pyinstaller
set -euo pipefail
cd "$(dirname "$0")/../.."

APP="SP500 Analyzer"
BUILD=build/macos
ARCH=$(uname -m)
rm -rf "$BUILD" "dist/$APP" "dist/$APP.app"
mkdir -p "$BUILD/icon.iconset" dist

echo "==> Icône"
python3 packaging/macos/make_icon.py "$BUILD/icon.png"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$BUILD/icon.png" --out "$BUILD/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$BUILD/icon.png" --out "$BUILD/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/SP500Analyzer.icns"

echo "==> Application"
APP_ICON="$PWD/$BUILD/SP500Analyzer.icns" pyinstaller --noconfirm --clean \
  --distpath dist --workpath "$BUILD/work" packaging/macos/SP500Analyzer.spec

echo "==> Signature ad hoc (non notariée)"
codesign --force --deep --sign - "dist/$APP.app"
codesign --verify --deep --strict "dist/$APP.app"

echo "==> Test de fumée de l'application empaquetée"
"dist/$APP.app/Contents/MacOS/$APP" --self-test

echo "==> Image disque"
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "dist/$APP.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/SP500-Analyzer-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "$APP" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "Terminé : $DMG"
