@echo off
REM 牛马 Niuma — One command to rule them all
cd /d "%~dp0"

REM 首次运行自动装依赖（Python + Node.js 双方面检查）
set NEED_INSTALL=0
python -m pytest --version >nul 2>&1
if errorlevel 1 set NEED_INSTALL=1
if not exist "node_modules\" set NEED_INSTALL=1

if %NEED_INSTALL%==1 (
    echo   安装依赖... ^| Installing dependencies...
    pip install -r requirements.txt -q 2>nul
    call npm install --silent 2>nul
    echo   [OK] 就绪 ^| Ready.
    echo.
)

python cli.py %*
