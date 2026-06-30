# MyPilot API. Build context is the repo root (so the shared protocol package is available).
#   podman build -f mypilot-stack/api/Dockerfile -t mypilot-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Shared protocol package (Ed25519 signing + message schemas).
COPY mypilot-protocol /opt/mypilot-protocol

# Python deps (cached separately from app source).
COPY mypilot-stack/api/requirements.txt mypilot-stack/api/requirements-dev.txt /app/
RUN pip install -r requirements-dev.txt && pip install /opt/mypilot-protocol

# Application source.
COPY mypilot-stack/api/ /app/
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
