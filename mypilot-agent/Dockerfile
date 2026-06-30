# MyPilot Agent (simulated device for M1/M2). Build context is the repo root.
#   podman build -f mypilot-agent/Dockerfile -t mypilot-agent .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY mypilot-protocol /opt/mypilot-protocol
COPY mypilot-agent/requirements.txt /app/
RUN pip install -r requirements.txt && pip install /opt/mypilot-protocol

COPY mypilot-agent/ /app/

# Default: run the simulated device. Override args via `compose run ... -- --onroad`, etc.
ENTRYPOINT ["python", "-m", "mypilot_agent"]
