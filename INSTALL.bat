@echo off
SETLOCAL ENABLEEXTENSIONS

REM === 1. Define variables ===
set "AMCA_DIR=%LOCALAPPDATA%\amca"
set "BIN_DIR=%AMCA_DIR%\bin"
set "SNAKES_SRC=%~dp0amca_impl\snakes"
set "BLUEPRINTS_SRC=%~dp0amca_impl\blueprints"
set "TEMPLATES_DIR=%AMCA_DIR%\templates"

REM === 2. Create directories if missing ===
if not exist "%BIN_DIR%" (
  echo Creating %BIN_DIR%
  mkdir "%BIN_DIR%"
)
if not exist "%TEMPLATES_DIR%" (
  echo Creating %TEMPLATES_DIR%
  mkdir "%TEMPLATES_DIR%"
)

REM === 3. Copy Python scripts ===
echo Copying AMCA Python core...
robocopy "%SNAKES_SRC%" "%AMCA_DIR%\snakes" /E /Z /NFL /NDL >nul

REM === 4. Compile the C “runner” ===
echo.
echo Checking for a C compiler...
where gcc >nul 2>nul
if %ERRORLEVEL%==0 (
  echo Found GCC — compiling with gcc
  gcc "%~dp0amca_impl\amca_runner.c" -o "%BIN_DIR%\amca.exe"
) else (
  where cl >nul 2>nul
  if %ERRORLEVEL%==0 (
    echo Found MSVC — compiling with cl
    cl /nologo /EHsc "%~dp0amca_impl\amca_runner.c" /Fe"%BIN_DIR%\amca.exe"
  ) else (
    echo ERROR: No C compiler found (need gcc or cl) >&2
    exit /b 1
  )
)

REM === 5. Install all blueprints ===
echo.
echo Installing templates...
for /D %%F in ("%BLUEPRINTS_SRC%\*") do (
  echo   - %%~nxF
  robocopy "%%F" "%TEMPLATES_DIR%\%%~nxF" /E /Z /NFL /NDL >nul
)

REM === 6. Add to user PATH ===
echo.
echo Updating user PATH to include AMCA…
powershell -noprofile -executionpolicy bypass -file amca_impl/setpath.ps1 

echo.
echo === AMCA installation complete! ===
echo Please close and re‑open your terminal sessions for PATH changes to take effect.
ENDLOCAL
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul 2>&1
if %errorlevel%==0 (
    pause
)
