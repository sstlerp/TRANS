@echo off
REM TRANS ERP - fetch / update the toll plaza master from the internet (toll ID, name, place, state).
REM Default source: the first active TOLL_PLAZA_MASTER integration (OpenStreetMap, free).
REM Examples:  toll_plazas_sync.bat                      (all of India)
REM            toll_plazas_sync.bat --states TN,KA,KL    (only these states)
REM            toll_plazas_sync.bat --source TOLL-DATAGOV --dry-run
REM Schedule weekly with Windows Task Scheduler - Action: this file, Start in: this folder.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m app.jobs toll-plazas %* >> logs\jobs.log 2>&1
