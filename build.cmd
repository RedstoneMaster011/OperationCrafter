@echo off
setlocal EnableExtensions

rem Build the Windows application from this repository, regardless of drive/path.
for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"
if "%~1"=="" (
    set "DIST_DIR=%SOURCE_DIR%\dist"
) else (
    set "DIST_DIR=%~f1"
)

if defined PYTHON_BIN (
    set "PYTHON_COMMAND=%PYTHON_BIN%"
) else if exist "%SOURCE_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_COMMAND=%SOURCE_DIR%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_COMMAND=py"
)

set "WORK_DIR=%TEMP%\OperationCrafter-PyInstaller-%RANDOM%-%RANDOM%"
mkdir "%WORK_DIR%" >nul 2>&1
mkdir "%DIST_DIR%" >nul 2>&1

"%PYTHON_COMMAND%" -m PyInstaller "%SOURCE_DIR%\main.py" ^
    --name "OperationCrafter-Windows" ^
    --exclude PyQt5 --exclude PySide6 ^
    --onefile --windowed --noconfirm ^
    --distpath "%DIST_DIR%" ^
    --workpath "%WORK_DIR%\work" ^
    --specpath "%WORK_DIR%" ^
    --add-data "%SOURCE_DIR%\icon-blue.png;." ^
    --icon "%SOURCE_DIR%\icon-blue.ico" ^
    --add-data "%SOURCE_DIR%\app;app" ^
    --paths "%SOURCE_DIR%" ^
    --collect-all PyQt6 ^
    --hidden-import glob ^
    --hidden-import json ^
    --hidden-import shutil

if errorlevel 1 (
    echo Packaging failed. Temporary files were left at "%WORK_DIR%" for inspection.
    exit /b 1
)

if exist "%SOURCE_DIR%\qemu" xcopy "%SOURCE_DIR%\qemu\*" "%DIST_DIR%\qemu\" /E /I /Y >nul
if exist "%SOURCE_DIR%\nasm" xcopy "%SOURCE_DIR%\nasm\*" "%DIST_DIR%\nasm\" /E /I /Y >nul
if exist "%SOURCE_DIR%\plugins" xcopy "%SOURCE_DIR%\plugins\*" "%DIST_DIR%\plugins\" /E /I /Y >nul
if exist "%SOURCE_DIR%\LICENCE" copy /Y "%SOURCE_DIR%\LICENCE" "%DIST_DIR%\LICENCE" >nul
if not exist "%DIST_DIR%\OperationProjects" mkdir "%DIST_DIR%\OperationProjects"

rmdir /S /Q "%WORK_DIR%"
echo Packaging complete: "%DIST_DIR%"
exit /b 0
