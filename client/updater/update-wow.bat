@echo off
REM Double-click me. Runs update-wow.ps1 next to this file.
REM -ExecutionPolicy Bypass is scoped to THIS process only -- it does not change any machine or
REM user policy, which is what makes it safe to hand to a friend.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-wow.ps1" %*
if errorlevel 1 pause
