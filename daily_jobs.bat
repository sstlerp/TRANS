@echo off
REM TRANS ERP - daily checks: renewal statuses and reminders, maintenance due,
REM tyre tread / warranty alerts, unmatched-bank reminder.
REM Schedule once a day with Windows Task Scheduler - Action: this file, Start in: this folder.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.jobs daily >> logs\jobs.log 2>&1
