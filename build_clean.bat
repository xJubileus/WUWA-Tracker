@echo off
echo OPTIONAL: rebuilds PyInstaller from source so the program gets its own, unique bootloader.
echo This usually lowers antivirus false positives a lot, but needs a C compiler:
echo install "Visual Studio Build Tools" with the "Desktop development with C++" workload first.
echo.
pause
py -m pip install --upgrade pip wheel
py -m pip uninstall -y pyinstaller
py -m pip install --no-binary pyinstaller --no-cache-dir pyinstaller
if errorlevel 1 (
  echo Building PyInstaller from source failed - usually the C compiler is missing.
  pause
  exit /b 1
)
call build.bat
