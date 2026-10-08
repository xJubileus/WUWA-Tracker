# WUWA Tracker

Small checklist application for Windows targeting Wuthering Waves, which helps you stay synchronized with the server reset schedule, that happens at 04:00 UTC+1. Includes the Waveplate counter, banner timers, useful tips, and even transparent "Always On Top" layer.

Fan-made software not connected to Kuro Games.

## Installation
Obtain WUWA-Tracker-Setup.exe from Releases page and launch it. Windows 10 or 11 and Microsoft WebView2 runtime are required (comes pre-installed on most systems).

## Privacy
Offline-only application without access to any personal information. Saves all your progress and to-do list in %APPDATA%\WuWaTracker folder locally. One exception from no communication may be update checker to GitHub public API about releases (disposable option, can be disabled in Settings).

## Building from sources
Needs Python 3.12+ and, maybe, Inno Setup. Launch build.bat. The installer is also made by GitHub Actions automatically (using .github/workflows/build.yml file).

## Code signing policy
Only the binaries, produced using the GitHub Actions process from this repo, are going to be signed.

Roles: Author / Reviewer / Approver: xJubileus

## License
MIT License. More info in LICENSE file. Copyright (c) 2026 Jubileus.
