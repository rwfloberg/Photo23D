# BVI Charter Guide

Offline, installable web app (PWA) for a December 2026 Moorings bareboat charter out of Road Town, Tortola.
Works on iPhone, iPad and Android with no signal once installed.

## Install on a phone
1. Open https://rwfloberg.github.io/Photo23D/bvi/ in Safari (iPhone/iPad) or Chrome (Android).
2. Share → **Add to Home Screen**.
3. Open it once from the home screen while on Wi-Fi. After that it works offline.

## Share with the group
More → Share has a QR code, a **Send the app** button, and install steps.

To give everyone the same trip details (boat names, Moorings phone numbers, ferry times, notes, plan changes):
fill in More → Settings, then More → Share → **Send trip details**. Each person installs the app,
opens it from the home screen, and pastes the message into **Got a trip code?**.
Flights and appearance stay private to each phone. Trip details are never on the website itself;
they only travel inside the code. Checklist ticks and day notes stay on each phone.

## Updating
Edit `index.html` and change the `BUILD` date near the top of its script (it is shown under More → About so the
group can check they all have the same guide). Installed copies check for a new page every time they open with a
connection and show an "Update now" bar when one is ready.

Only bump `VERSION` in `sw.js` when `sw.js` itself or its list of files changes.

## What is stored where
- The website holds the guide only. No names, bookings or phone-specific details are in the code.
- Each phone keeps its own settings, checklist ticks, day notes, fuel calculator inputs and daily log.
- The trip code carries dates, boat names, Moorings numbers, ferry times, notes and any plan changes.
  Flights, "which boat is this phone on" and appearance never leave the phone.

## Credits
Coastlines: geoBoundaries (CC BY 4.0) and Natural Earth (public domain). Font: Barlow Condensed (SIL OFL, see `fonts/OFL.txt`).
The chart is schematic and not for navigation.
