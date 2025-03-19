@echo off

mkdir "%LOCALAPPDATA%\amca\bin"
c++ amca_impl/src/find_amca.cpp -std=c++20 -Oz -O3 -s -os -o "%LOCALAPPDATA%\amca\bin\amca"
powershell -noprofile -executionpolicy bypass -file amca_impl/setpath.ps1 

mkdir "%LOCALAPPDATA%\amca\templates" 2>nul

for %%F in (./amca_impl/templates/*.json) do (
    echo Extracting "./amca_impl/templates/%%F" to "%LOCALAPPDATA%/amca/templates/"
    python amca_impl/dearchiver.py "./amca_impl/templates/%%~F" "%LOCALAPPDATA%/amca/templates/"
)