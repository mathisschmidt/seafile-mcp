FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

RUN useradd --create-home --uid 1000 mcp \
    && mkdir /data && chown mcp:mcp /data
USER mcp

# Serves over HTTP by default; set MCP_TRANSPORT=stdio for stdio clients
EXPOSE 8000
ENTRYPOINT ["seafile-mcp"]
