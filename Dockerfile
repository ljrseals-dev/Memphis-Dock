FROM --platform=$TARGETPLATFORM python:3.12-slim

ARG TARGETARCH
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY dockcore ./dockcore
COPY brutegenius ./brutegenius
COPY console ./console
COPY edge ./edge
COPY mcp_server ./mcp_server
COPY sdk ./sdk

RUN pip install --no-cache-dir .

ENV APP=console
EXPOSE 8080 8090

CMD ["sh", "-c", "uvicorn ${APP}.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
