FROM python:3.12-slim
WORKDIR /app
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY web_server.py storage.py engine.py ./
COPY web ./web
RUN useradd --create-home tradescout && mkdir /app/data && chown tradescout:tradescout /app/data
USER tradescout
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn web_server:app --host 0.0.0.0 --port ${PORT}"]
