@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "VENV_DIR=%ROOT_DIR%\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"
set "APP_ICON=%ROOT_DIR%\assets\logo.ico"
set "LAUNCHER_VERSION_INFO=%ROOT_DIR%\packaging\windows\launcher_version_info.txt"
set "UPDATER_VERSION_INFO=%ROOT_DIR%\packaging\windows\updater_version_info.txt"

echo [1/6] Checking Python...
if not exist "%PYTHON%" (
  echo ERROR: Python not found in %VENV_DIR%.
  echo Run:
  echo   cd /d "%ROOT_DIR%"
  echo   py -m venv .venv
  echo   .venv\Scripts\python -m pip install -r requirements.txt
  exit /b 1
)

echo [2/6] Checking PyInstaller...
if not exist "%PYINSTALLER%" (
  echo ERROR: PyInstaller not found in %VENV_DIR%.
  echo Run:
  echo   .venv\Scripts\python -m pip install pyinstaller
  exit /b 1
)

echo [3/6] Checking Nuitka...
"%PYTHON%" -c "import nuitka" 2>nul
if errorlevel 1 (
  echo ERROR: Nuitka not found in %VENV_DIR%.
  echo Run:
  echo   .venv\Scripts\python -m pip install nuitka
  exit /b 1
)

echo [4/6] Checking assets and version files...
if not exist "%APP_ICON%" (
  echo ERROR: App icon not found: %APP_ICON%
  exit /b 1
)
if not exist "%LAUNCHER_VERSION_INFO%" (
  echo ERROR: Launcher version info not found: %LAUNCHER_VERSION_INFO%
  exit /b 1
)
if not exist "%UPDATER_VERSION_INFO%" (
  echo ERROR: Updater version info not found: %UPDATER_VERSION_INFO%
  exit /b 1
)

echo [5/6] Cleaning previous build artifacts...
cd /d "%ROOT_DIR%"
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q *.spec 2>nul

echo [6/6] Building binaries...
echo.

echo --- launcher (PyInstaller) ---
"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name Lota-launcher ^
  --icon "%APP_ICON%" ^
  --version-file "%LAUNCHER_VERSION_INFO%" ^
  --add-data "assets;assets" ^
  launcher.py
if errorlevel 1 exit /b %errorlevel%

echo --- updater (PyInstaller) ---
"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name updater ^
  --icon "%APP_ICON%" ^
  --version-file "%UPDATER_VERSION_INFO%" ^
  --add-data "assets;assets" ^
  updater.py
if errorlevel 1 exit /b %errorlevel%

echo --- installer (Nuitka, may take several minutes on first run) ---
"%PYTHON%" -m nuitka ^
  --onefile ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico="%APP_ICON%" ^
  --enable-plugin=pyside6 ^
  --include-data-dir=assets=assets ^
  --windows-company-name=LOTATeam ^
  --windows-product-name=LotaLauncher ^
  --windows-product-version=0.0.1 ^
  --windows-file-version=0.0.1.0 ^
  "--windows-file-description=LOTA Installer" ^
  --output-filename=installer.exe ^
  --output-dir=dist ^
  --assume-yes-for-downloads ^
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
