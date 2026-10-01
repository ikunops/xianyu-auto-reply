@echo off
chcp 65001 >nul
call "%~dp0..\scripts\stop_service_by_port.bat" "Backend-Web服务" "8778"
exit /b %errorlevel%
