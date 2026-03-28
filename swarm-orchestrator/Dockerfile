FROM python:3.12-slim

# System dependencies required by matrix-nio[e2e] and PyNaCl
RUN apt-get update && apt-get install -y --no-install-recommends \
    libolm-dev \
    libsodium-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata first for layer caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

# Copy source
COPY src/ src/

# Install the package itself (editable not needed in production)
RUN pip install --no-cache-dir --no-deps -e .

# Persistent volumes:
#   /data              — NaCl keys, matrix-nio store
#   /etc/orchestrator  — config.toml and topology.toml
VOLUME ["/data", "/etc/orchestrator"]

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "-m", "orchestrator.main"]
