!macro NSIS_HOOK_POSTINSTALL
  Delete "$DESKTOP\Lota Launcher.lnk"
  CreateShortCut "$DESKTOP\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"

  Delete "$SMPROGRAMS\Lota Launcher.lnk"
  CreateShortCut "$SMPROGRAMS\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"
!macroend
