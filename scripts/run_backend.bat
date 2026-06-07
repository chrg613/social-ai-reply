@echo off
cd /d C:\Users\ravi7\OneDrive\Documents\GitHub\social-ai-reply
call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> backend.out.log 2>> backend.err.log
