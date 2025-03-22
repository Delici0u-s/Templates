@echo off

mkdir "%LOCALAPPDATA%\amca\bin"
cp amca_impl/snakes "%LOCALAPPDATA%\amca" -r
cp amca_impl/amca.bat "%LOCALAPPDATA%\amca\bin"
powershell -noprofile -executionpolicy bypass -file amca_impl/setpath.ps1 

mkdir "%LOCALAPPDATA%\amca\templates" 2>nul

for /D %%F in (./amca_impl/blueprints/*) do (
    echo installing template: %%F
    cp ./amca_impl/blueprints/%%F "%LOCALAPPDATA%\amca\templates" -r
)
