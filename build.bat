@echo off
rem Extra PyInstaller options. Empty = the known good setup.
rem Experiment for fewer antivirus hits: change the next line to  set "EXTRA=--debug noarchive"
set "EXTRA="

echo Installing requirements...
py -m pip install --upgrade pywebview
py -m pip show pyinstaller >nul 2>&1
if errorlevel 1 py -m pip install pyinstaller
echo.
echo Building the program...
py -m PyInstaller --noconfirm --clean --onedir --windowed --name "WUWA Tracker" --icon wuwa.ico --version-file version.txt --exclude-module tkinter %EXTRA% --add-data "wuwa.ico;." wuwa_app.py
if errorlevel 1 goto fail

if not exist Output mkdir Output
powershell -NoProfile -Command "Compress-Archive -Path 'dist\WUWA Tracker\*' -DestinationPath 'Output\WUWA-Tracker-Portable.zip' -Force"
echo.
call :find
if not defined ISCC (
  echo Inno Setup not found, trying to install it with winget...
  winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
  call :find
)
if not defined ISCC goto noinno
"%ISCC%" installer.iss
if errorlevel 1 goto fail
echo.
echo DONE!
echo   Installer: Output\WUWA-Tracker-Setup.exe
echo   Portable : Output\WUWA-Tracker-Portable.zip
echo.
echo SHA256 of the installer, use it for false positive reports:
certutil -hashfile "Output\WUWA-Tracker-Setup.exe" SHA256
pause
exit /b 0

:noinno
echo.
echo Inno Setup could not be installed automatically.
echo Install it from https://jrsoftware.org/isdl.php and run build.bat again.
echo The portable version is ready in: Output\WUWA-Tracker-Portable.zip
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
