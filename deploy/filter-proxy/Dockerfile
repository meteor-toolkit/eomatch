FROM python:3.11-slim
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx
COPY main.py /app/main.py
WORKDIR /app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
