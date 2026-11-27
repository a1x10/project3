; Установщик Stella Assistant (собирается нативным makensis без wine).
; makensis -DSRC=dist/win-unpacked -DOUT=dist/Stella-Setup.exe -DVERSION=1.0.0 build/installer.nsi
Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APPNAME "Stella Assistant"
!define EXENAME "Stella Assistant.exe"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\StellaAssistant"

Name "${APPNAME}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\Stella Assistant"
InstallDirRegKey HKCU "Software\StellaAssistant" "InstallDir"
RequestExecutionLevel user
BrandingText "Stella Assistant ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "Установщик Stella Assistant"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Stella Team"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Установка Stella Assistant"
!define MUI_WELCOMEPAGE_TEXT "Живой 3D-ассистент: Стелла и Марк. Говорит голосом, управляет компьютером, выходит в реальный мир через телефон и ест ненужные файлы.$\r$\n$\r$\nНажми «Далее», чтобы продолжить."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXENAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить Stella Assistant"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"

Function .onInit
  ; закрываем запущенную копию, чтобы файлы можно было заменить
  nsExec::Exec 'taskkill /IM "${EXENAME}" /F'
FunctionEnd

Section "Stella Assistant" SecMain
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\resources"
  File /r "${SRC}\*.*"
  File "/oname=stella.ico" "${ICON}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\Stella Assistant"
  CreateShortCut "$SMPROGRAMS\Stella Assistant\Stella Assistant.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\stella.ico" 0
  CreateShortCut "$SMPROGRAMS\Stella Assistant\Удалить Stella Assistant.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\Stella.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\stella.ico" 0

  WriteRegStr HKCU "Software\StellaAssistant" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "Stella Team"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\stella.ico"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${REGKEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /IM "${EXENAME}" /F'
  Delete "$DESKTOP\Stella.lnk"
  RMDir /r "$SMPROGRAMS\Stella Assistant"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\StellaAssistant"
  ; данные пользователя (аккаунты, чаты, желудок) остаются в %APPDATA%\stella-assistant
SectionEnd
