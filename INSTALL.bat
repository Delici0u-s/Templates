@echo off

mkdir "%LOCALAPPDATA%\amca\bin"
cp amca_impl/snakes "%LOCALAPPDATA%\amca" -r
gcc  amca_impl/amca_runner.c -o "%LOCALAPPDATA%\amca\bin\amca"
powershell -noprofile -executionpolicy bypass -file amca_impl/setpath.ps1 

mkdir "%LOCALAPPDATA%\amca\templates" 2>nul

for /D %%F in (./amca_impl/blueprints/*) do (
    echo installing template: %%F
    cp ./amca_impl/blueprints/%%F "%LOCALAPPDATA%\amca\templates" -r
)
