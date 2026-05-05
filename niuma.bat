@echo off
REM 牛马 Niuma — One command to rule them all
cd /d "%~dp0"

REM 首次运行自动装依赖
if not exist "node_modules\" (
    echo   首次运行，安装依赖... | First run, installing dependencies...
    pip install -r requirements.txt -q 2>nul
    call npm install --silent 2>nul
    echo   [OK] 就绪 | Ready.
    echo.
)

python cli.py %*
