@echo off
cd /d "%~dp0"
docker compose exec agent python -m agent.bedrock_check
pause
