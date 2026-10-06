# BVI Charter Guide

Offline, installable web app (PWA) for a December 2026 Moorings bareboat charter out of Road Town, Tortola.
Works on iPhone, iPad and Android with no signal once installed.

## Install on a phone
1. Open https://rwfloberg.github.io/Photo23D/bvi/ in Safari (iPhone/iPad) or Chrome (Android).
2. Share → **Add to Home Screen**.
3. Open it once from the home screen while on Wi-Fi. After that it works offline.

## Share with the group
More → Share has a QR code, a **Send the app** button, and install steps.

To give everyone the same trip details (boat name, Moorings phone numbers, ferry times, notes):
fill in More → Settings, then More → Share → **Send trip details**. Each person installs the app,
opens it from the home screen, and pastes the message into **Got a trip code?**.
Flights and appearance stay private to each phone. Trip details are never on the website itself;
they only travel inside the code. Checklist ticks and day notes stay on each phone.

## Updating
Edit `index.html`, then bump `VERSION` in `sw.js` (e.g. `bvi-guide-v2`) so installed copies pick up the change
the next time they open with a connection.

## Credits
Coastlines: geoBoundaries (CC BY 4.0) and Natural Earth (public domain). Font: Barlow Condensed (SIL OFL, see `fonts/OFL.txt`).
The chart is schematic and not for navigation.
