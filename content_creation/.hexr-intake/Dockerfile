# Hexr Agent Container - Development Build
FROM python:3.11-slim

# Set build metadata
LABEL maintainer="Hexr SDK"
LABEL version="0.1.0"
LABEL description="Hexr AI Agent Container"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl ca-certificates gcc python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set up Python environment
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
COPY hexr_sdk*.whl /tmp/

# Install Python dependencies + hexr-sdk (baked into image layer)
# SDK extras: [observability]
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir /tmp/hexr_sdk*.whl \
    && pip install --no-cache-dir opentelemetry-api>=1.21.0 opentelemetry-sdk>=1.21.0 opentelemetry-propagator-b3>=1.21.0 opentelemetry-exporter-otlp-proto-grpc>=1.21.0 \
    && pip install --no-cache-dir --upgrade "opentelemetry-proto>=1.41.0,<2.0.0" "opentelemetry-exporter-otlp-proto-http>=1.41.0,<2.0.0" "opentelemetry-exporter-otlp-proto-grpc>=1.41.0,<2.0.0" "protobuf>=6.31.1,<7.0.0"

# Copy application code (hexr-sdk installed from PyPI)
COPY claims_intake_a2a.py /app/claims_intake_a2a.py

# ENTERPRISE: Copy PID mapper for sidecar container
COPY enterprise_pid_mapper.py /app/enterprise_pid_mapper.py

# ENTERPRISE: Copy manifests for PID mapper agent discovery and CD templates
COPY manifests/ /app/manifests/

# Set environment variables for Hexr SDK
ENV HEXR_TENANT="pivot-demo"
ENV HEXR_FRAMEWORK="bespoke"
ENV HEXR_TARGET="production"

# Hexr Runtime integration paths (enterprise PID mapping enabled)
ENV HEXR_SPIFFE_SOCKET_PATH="/run/spire/sockets/agent.sock"
ENV SPIRE_SOCKET_PATH="/tmp/spire-agent/public/api.sock"
ENV HEXR_CREDENTIAL_INJECTOR_URL="http://localhost:15001"
ENV HEXR_PROCESS_CONTEXT_DIR="/tmp/hexr-context"
ENV HEXR_ENTERPRISE_PID_MAPPING="enabled"
ENV HEXR_ENHANCED_ATTESTOR_ENABLED="true"

# Create required directories for enterprise PID mapping
RUN mkdir -p /run/spire/sockets /tmp/hexr-context /host/proc /tmp/spire-agent/public

# Security: Run as non-root user
RUN groupadd -r hexr && useradd -r -g hexr hexr
RUN chown -R hexr:hexr /app /tmp/hexr-context


# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import hexr; print('healthy')" || exit 1

# Switch to non-root user
USER hexr

# Expose port for health checks
EXPOSE 8000

# HEXR ARCHITECTURE: Multi-stage Docker build compatible entry point
# Direct agent execution (not AgentCore main.py pattern)
ENTRYPOINT ["python"]
CMD ["/app/claims_intake_a2a.py"]