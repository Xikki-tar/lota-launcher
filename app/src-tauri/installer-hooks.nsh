!macro LOTA_STOP_PROCESSES
  nsExec::Exec `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$dir = [IO.Path]::GetFullPath('$INSTDIR').TrimEnd('\') + '\'; Get-Process -Name lota-launcher,backend,updater -ErrorAction SilentlyContinue | Where-Object { $$_.Path -and $$_.Path.StartsWith($$dir, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"`
  Pop $0
  Sleep 1000
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro LOTA_STOP_PROCESSES
!macroend

!macro NSIS_HOOK_POSTINSTALL
  Delete "$DESKTOP\Lota Launcher.lnk"
  CreateShortCut "$DESKTOP\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"

  Delete "$SMPROGRAMS\Lota Launcher.lnk"
  CreateShortCut "$SMPROGRAMS\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro LOTA_STOP_PROCESSES
!macroend
