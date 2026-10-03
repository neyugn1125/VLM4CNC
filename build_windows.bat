@echo off
setlocal enabledelayedexpansion

title CAD_CAM_AI_Tool - Windows Build Script

echo ========================================================
echo   CAD_CAM_AI_Tool - Script Dong Goi Windows (.exe)
echo ========================================================
echo.

:: 1. Kiem tra Python tren he thong
echo [BƯỚC 1/4] Kiem tra moi truong Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Khong tim thay Python trong PATH he thong!
    echo Vui long cai dat Python 3.10+ tu https://www.python.org/downloads/
    echo Luu y: Trong qua trinh cai dat, nho tich vao o "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

python --version
if %errorlevel% neq 0 (
    echo [ERROR] Loi khi thuc thi lenh python!
    pause
    exit /b 1
)
echo Python hop le. Tiep tuc...
echo.

:: 2. Tao va kich hoat virtual environment
echo [BƯỚC 2/4] Thiet lap moi truong ao (.venv)...
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Dang khoi tao virtual environment moi tai .venv...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Khong the tao virtual environment!
        pause
        exit /b 1
    )
    echo [INFO] Da tao virtual environment thanh cong.
) else (
    echo [INFO] Tim thay virtual environment hien huu tai .venv.
)

echo [INFO] Dang kich hoat virtual environment...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Khong the kich hoat virtual environment!
    pause
    exit /b 1
)
echo.

:: 3. Cap nhat pip va cai dat dependencies
echo [BƯỚC 3/4] Cai dat thu vien phu thuoc tu requirements.txt...
python -m pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Cai dat thu vien that bai!
    pause
    exit /b 1
)

:: Dam bao pyinstaller da duoc cai dat
pip install pyinstaller>=6.0.0
if %errorlevel% neq 0 (
    echo [ERROR] Cai dat PyInstaller that bai!
    pause
    exit /b 1
)
echo [INFO] Tat ca thu vien da san sang.
echo.

:: 4. Don dep thu muc build cu va dong goi file exe
echo [BƯỚC 4/4] Dang thuc thi dong goi PyInstaller...
if exist "build\CAD_CAM_AI_Tool" (
    echo [INFO] Don dep thu muc build cu...
    rmdir /s /q "build\CAD_CAM_AI_Tool"
)
if exist "dist\CAD_CAM_AI_Tool.exe" (
    echo [INFO] Xoa file exe cu...
    del /f /q "dist\CAD_CAM_AI_Tool.exe"
)

echo [INFO] Dang bien dich thanh file thuc thi don doc (--onefile --noconsole)...
pyinstaller --noconsole --onefile --name="CAD_CAM_AI_Tool" --add-data "core;core" --add-data "vision;vision" --add-data "ui;ui" --clean main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Qua trinh dong goi gap loi!
    pause
    exit /b 1
)

echo.
echo ========================================================
if exist "dist\CAD_CAM_AI_Tool.exe" (
    echo [HOAN TAT] File thuc thi Windows da duoc tao thanh cong!
    echo Duong dan: dist\CAD_CAM_AI_Tool.exe
    echo.
    echo Ban co the copy truc tiep file dist\CAD_CAM_AI_Tool.exe de su dung
    echo tren bat ky may Windows 10/11 64-bit nao ma khong can cai dat Python.
) else (
    echo [CANH BAO] Lenh hoan tat nhung khong tim thay file dist\CAD_CAM_AI_Tool.exe!
)
echo ========================================================
echo.
pause
