# WUWA Tracker

A small Windows checklist app for **Wuthering Waves**: daily, weekly and monthly tasks that reset automatically
with the game's server reset (04:00 UTC+1 server time), a Waveplate counter, banner countdowns, reminders and an
optional see-through "always on top" overlay.

Unofficial fan-made tool. Not affiliated with Kuro Games.

## Install

Download `WUWA-Tracker-Setup.exe` from the [Releases](../../releases) page and run it.
Requires Windows 10/11 with the Microsoft WebView2 Runtime (preinstalled on most systems).

## Privacy

WUWA Tracker works offline. It does not collect, send or share any personal data.
Your progress and task list are stored locally in `%APPDATA%\WuWaTracker`.
The only network request is an optional update check against the public GitHub releases API
(it can be switched off in the settings).

## Build from source

Needs Python 3.12+ and (optionally) Inno Setup. Run `build.bat`.
The installer is also built automatically by GitHub Actions (`.github/workflows/build.yml`).

## Code signing policy

- Only binaries built by the GitHub Actions workflow in this repository are submitted for signing.
- Roles: Author / Reviewer / Approver: **xJubileus**

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Jubileus.
