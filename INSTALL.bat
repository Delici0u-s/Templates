@echo off

mkdir "%LOCALAPPDATA%\amca\bin"
cp amca_impl/snakes "%LOCALAPPDATA%\amca" -r
cp amca_impl/amca.bat "%LOCALAPPDATA%\amca\bin"
powershell -noprofile -executionpolicy bypass -file amca_impl/setpath.ps1 

mkdir "%LOCALAPPDATA%\amca\templates" 2>nul

for %%F in (./amca_impl/templates/*.json) do (
    echo Extracting "./amca_impl/templates/%%F" to "%LOCALAPPDATA%/amca/templates/"
    python amca_impl/dearchiver.py "./amca_impl/templates/%%~F" "%LOCALAPPDATA%/amca/templates/"
)