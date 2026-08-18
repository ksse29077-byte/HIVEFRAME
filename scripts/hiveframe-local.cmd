@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0hiveframe-local.ps1" %*
set "HIVEFRAME_EXIT=%ERRORLEVEL%"
if not "%HIVEFRAME_EXIT%"=="0" pause
exit /b %HIVEFRAME_EXIT%
