# BVI Charter Guide

Offline, installable web app (PWA) for a December 2026 Moorings bareboat charter out of Road Town, Tortola.
Works on iPhone, iPad and Android with no signal once installed.

## Install on a phone
1. Open https://rwfloberg.github.io/Photo23D/bvi/ in Safari (iPhone/iPad) or Chrome (Android).
2. Share → **Add to Home Screen**.
3. Open it once from the home screen while on Wi-Fi. After that it works offline.

Trip details, checklist ticks and notes are stored only on each phone (Settings tab).

## Updating
Edit `index.html`, then bump `VERSION` in `sw.js` (e.g. `bvi-guide-v2`) so installed copies pick up the change
the next time they open with a connection.

## Credits
Coastlines: geoBoundaries (CC BY 4.0) and Natural Earth (public domain). Font: Barlow Condensed (SIL OFL, see `fonts/OFL.txt`).
The chart is schematic and not for navigation.
