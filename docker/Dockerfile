# =============================================================================
# Multi-stage Dockerfile for Azure ML CI/CD Pipeline
# =============================================================================
# Production-optimized image with security best practices.
# Author: Gabriel Demetrios Lafis
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Production
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS production

LABEL maintainer="Gabriel Demetrios Lafis"
LABEL description="Azure ML CI/CD Pipeline"
LABEL org.opencontainers.image.source="https://github.com/galafis/azure-ml-cicd-pipeline"

# Security: run as non-root user
RUN groupadd -r mlpipeline && \
    useradd -r -g mlpipeline -d /app -s /sbin/nologin mlpipeline

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Set up application
WORKDIR /app

COPY src/ ./src/
COPY config/ ./config/

# Create necessary directories
RUN mkdir -p logs evaluation_artifacts promotion_audit && \
    chown -R mlpipeline:mlpipeline /app

# Switch to non-root user
USER mlpipeline

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import src; print('healthy')" || exit 1

# Use tini for proper signal handling
ENTRYPOINT ["tini", "--"]

# Default command
CMD ["python", "-m", "src"]
