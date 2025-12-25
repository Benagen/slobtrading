FROM python:3.9-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY slob/ slob/
COPY scripts/ scripts/

# Create directories
RUN mkdir -p /app/data /app/logs

# Health check
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import sqlite3; sqlite3.connect('/app/data/slob_state.db').execute('SELECT 1')" || exit 1

# Default command (can be overridden)
CMD ["python", "scripts/run_paper_trading.py", "--account", "${IB_ACCOUNT}", "--gateway", "--duration", "168"]
