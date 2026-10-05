@echo off
echo === WUWA Tracker: build WITHOUT PyInstaller (embedded Python) ===
echo This version has no custom .exe at all: it ships the official, signed Python and our plain script.
echo.
for /f %%v in ('py -c "import sys;print(sys.version.split()[0])"') do set "PYV=%%v"
echo Python version: %PYV%
set "ST=build_emb\stage"
if exist build_emb rmdir /s /q build_emb
mkdir "%ST%\python" "%ST%\lib" "%ST%\app"

echo Downloading embeddable Python %PYV% ...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PYV%/python-%PYV%-embed-amd64.zip' -OutFile 'build_emb\python.zip'"
if errorlevel 1 goto fail
powershell -NoProfile -Command "Expand-Archive -Path 'build_emb\python.zip' -DestinationPath '%ST%\python' -Force"
if errorlevel 1 goto fail

echo Installing packages...
py -m pip install --upgrade --target "%ST%\lib" pywebview
if errorlevel 1 goto fail

for %%F in ("%ST%\python\python*._pth") do set "PTH=%%F" & set "PB=%%~nF"
powershell -NoProfile -Command "Set-Content -Path '%PTH%' -Value @('%PB%.zip','.','..\lib','..\app','import site')"
copy /y wuwa_app.py "%ST%\app\" >nul
copy /y wuwa.ico "%ST%\app\" >nul

if not exist Output mkdir Output
call :find
if not defined ISCC (
  echo Inno Setup not found, trying to install it with winget...
  winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
  call :find
)
if not defined ISCC goto noinno
"%ISCC%" installer_embedded.iss
if errorlevel 1 goto fail
echo.
echo DONE! Installer: Output\WUWA-Tracker-Embedded-Setup.exe
echo Test without installing: build_emb\stage\python\pythonw.exe build_emb\stage\app\wuwa_app.py
echo.
certutil -hashfile "Output\WUWA-Tracker-Embedded-Setup.exe" SHA256
pause
exit /b 0

:noinno
echo Inno Setup could not be installed automatically. Install it from https://jrsoftware.org/isdl.php and run this file again.
pause
exit /b 0

:fail
echo.
echo Something went wrong. Please copy the messages above and send them over.
pause
exit /b 1

:find
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%P set "ISCC=%%~P"
exit /b 0
