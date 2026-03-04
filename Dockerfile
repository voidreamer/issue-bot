FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY issue_bot/ ./issue_bot/
RUN mkdir -p /app/data
EXPOSE 8321
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8321"]
