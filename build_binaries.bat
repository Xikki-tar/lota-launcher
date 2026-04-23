@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "VENV_DIR=%ROOT_DIR%\.venv"
set "PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"
set "APP_ICON=%ROOT_DIR%\assets\logo.ico"
set "LAUNCHER_VERSION_INFO=%ROOT_DIR%\packaging\windows\launcher_version_info.txt"
set "UPDATER_VERSION_INFO=%ROOT_DIR%\packaging\windows\updater_version_info.txt"
set "INSTALLER_VERSION_INFO=%ROOT_DIR%\packaging\windows\installer_version_info.txt"

if not exist "%PYINSTALLER%" (
  echo PyInstaller not found in %VENV_DIR%.
  echo Run:
  echo   cd /d "%ROOT_DIR%"
  echo   py -m venv .venv
  echo   .venv\Scripts\python -m pip install -r requirements.txt
  echo   .venv\Scripts\python -m pip install pyinstaller
  exit /b 1
)

if not exist "%APP_ICON%" (
  echo App icon not found: %APP_ICON%
  exit /b 1
)

if not exist "%LAUNCHER_VERSION_INFO%" (
  echo Launcher version info not found: %LAUNCHER_VERSION_INFO%
  exit /b 1
)

if not exist "%UPDATER_VERSION_INFO%" (
  echo Updater version info not found: %UPDATER_VERSION_INFO%
  exit /b 1
)

if not exist "%INSTALLER_VERSION_INFO%" (
  echo Installer version info not found: %INSTALLER_VERSION_INFO%
  exit /b 1
)

cd /d "%ROOT_DIR%"

echo Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q *.spec 2>nul

echo Building launcher...
"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name launcher ^
  --icon "%APP_ICON%" ^
  --version-file "%LAUNCHER_VERSION_INFO%" ^
  --add-data "assets;assets" ^
  launcher.py
if errorlevel 1 exit /b %errorlevel%

echo Building updater...
"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name updater ^
  --icon "%APP_ICON%" ^
  --version-file "%UPDATER_VERSION_INFO%" ^
  updater.py
if errorlevel 1 exit /b %errorlevel%

echo Building installer...
"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name installer ^
  --icon "%APP_ICON%" ^
  --version-file "%INSTALLER_VERSION_INFO%" ^
  --add-data "assets;assets" ^
  installer.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete. Files:
dir /b "%ROOT_DIR%\dist"
echo.
echo Run installer with:
echo   set LOTA_API_BASES=https://ru.lota.work,https://eu.lota.work
echo   "%ROOT_DIR%\dist\installer.exe"

endlocal
