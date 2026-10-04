WUWA Tracker - build instructions

1. Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH" in the installer).
2. Keep all files of this folder together.
3. Double-click build.bat and wait a few minutes.
   - It builds the program and, if Inno Setup is available (it tries to install it with winget), also a real installer.
4. Give your friends this file: Output\WUWA-Tracker-Setup.exe
   (it installs the app per user, adds Start menu and optional desktop shortcut, and has an uninstaller)

Your data lives in %APPDATA%\WuWaTracker (progress.json, tasks.json, error.log).
The program also works without installing: dist\WUWA Tracker\WUWA Tracker.exe
Window: frameless with its own title bar. Always on top = see-through overlay; hover it with a free cursor to use it. Start with Windows is an option in the installer.

ANTIVIRUS FALSE POSITIVES
Unsigned Python-based programs are often flagged by heuristic/ML scanners. This is a false positive.
What helps, in order of effect:
 1. Code signing certificate (OV/EV, or the free SignPath Foundation program if the source is public).
 2. build_clean.bat (own PyInstaller bootloader; needs Visual Studio Build Tools).
 3. Submit the installer as a false positive to the vendors that flag it (Microsoft, Avast/AVG, Avira, ...).

Finding what triggers the scanners: upload these three to virustotal.com and compare
 - dist\WUWA Tracker\WUWA Tracker.exe (the bare program)
 - Output\WUWA-Tracker-Portable.zip
 - Output\WUWA-Tracker-Setup.exe
Submit the FINAL files as false positives (every rebuild changes the hash).

TWO WAYS TO BUILD
 build.bat           PyInstaller version  -> Output\WUWA-Tracker-Setup.exe
 build_embedded.bat  embedded Python (no custom .exe, usually far fewer antivirus hits) -> Output\WUWA-Tracker-Embedded-Setup.exe

GITHUB + SIGNING
Upload the contents of this folder to a public GitHub repository (LICENSE and .github/workflows/build.yml are included).
The workflow builds the installer in the cloud. Apply to the SignPath Foundation (signpath.org) for free code signing,
then enable the commented signing step in .github/workflows/build.yml.
