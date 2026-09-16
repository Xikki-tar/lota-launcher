!macro NSIS_HOOK_PREINSTALL
  strip_loop:
    StrLen $R0 $INSTDIR
    IntCmp $R0 22 strip_check strip_done strip_check
  strip_check:
    StrCpy $R1 $INSTDIR 22 -22
    StrCmp $R1 "\lota-launcher\runtime" strip_it strip_done
  strip_it:
    StrCpy $R1 $INSTDIR -22
    StrCpy $INSTDIR $R1
    Goto strip_loop
  strip_done:
  StrCpy $INSTDIR "$INSTDIR\lota-launcher\runtime"
!macroend
