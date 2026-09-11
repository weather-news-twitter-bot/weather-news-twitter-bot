@echo off
rem Entry point for Task Scheduler (WNL-Timetable-Tweet). ASCII ONLY in this file:
rem cmd reads it as cp932 and Japanese comments become garbage commands.
rem   usage: run.cmd src\tweet_local.py
rem Output goes to .local\tweet_local.log (gitignored).

setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist .local mkdir .local
"C:\Users\ryo_d\AppData\Local\Microsoft\WindowsApps\python.exe" %* >> .local\tweet_local.log 2>&1
exit /b %ERRORLEVEL%
