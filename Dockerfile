FROM node:22-bookworm-slim AS codex
RUN npm install -g @openai/codex@0.159.2

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
COPY web_server.py storage.py database.py engine.py codex_backend.py server_codex.py tasks.py ./
COPY web ./web
RUN useradd --create-home tradescout && mkdir /app/data && chown tradescout:tradescout /app/data
USER tradescout
ENV PORT=8000
ENV TRADESCOUT_CODEX_MODE=server
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn web_server:app --host 0.0.0.0 --port ${PORT}"]
