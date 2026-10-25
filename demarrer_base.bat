@echo off
rem Démarre l'instance PostgreSQL du projet (port 5435) après un redémarrage du PC.
rem Double-cliquer sur ce fichier, ou le lancer depuis un terminal.
set "PGBIN=C:\Program Files\PostgreSQL\15\bin"
set "DONNEES=%~dp0data\pgdata"
"%PGBIN%\pg_ctl.exe" status -D "%DONNEES%" >nul 2>&1
if %errorlevel%==0 (
    echo La base du projet est deja demarree.
) else (
    "%PGBIN%\pg_ctl.exe" start -D "%DONNEES%" -l "%~dp0data\postgresql.log" -w
)
pause
