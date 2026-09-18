!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $R0 HKCU "Software\lota-launcher" "InstallRoot"
  StrCmp $R0 "" do_append
  StrCmp $INSTDIR "$R0\lota-launcher\runtime" already_suffixed do_append
  do_append:
    StrCpy $INSTDIR "$INSTDIR\lota-launcher\runtime"
  already_suffixed:

  StrLen $R0 $INSTDIR
  IntCmp $R0 200 path_ok path_ok path_too_long
  path_too_long:
    StrCpy $INSTDIR "$LOCALAPPDATA\lota-launcher\runtime"
  path_ok:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  StrCpy $R1 $INSTDIR -22
  WriteRegStr HKCU "Software\lota-launcher" "InstallRoot" "$R1"

  Delete "$DESKTOP\Lota Launcher.lnk"
  CreateShortCut "$DESKTOP\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"

  Delete "$SMPROGRAMS\Lota Launcher.lnk"
  CreateShortCut "$SMPROGRAMS\Lota Launcher.lnk" "$INSTDIR\lota-launcher.exe"
!macroend
