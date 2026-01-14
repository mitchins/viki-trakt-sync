FROM python:3.11-slim

WORKDIR /app

# Install dependencies via pyproject
# (dependencies will be installed during application install)

# Copy application
COPY src/ ./src/
COPY pyproject.toml .

# Install application
RUN pip install --no-cache-dir -e .

# Volume for config persistence
VOLUME /app/config

# Environment variables
ENV CONFIG_DIR=/app/config

# Default command (can be overridden)
CMD ["viki-trakt", "sync"]
