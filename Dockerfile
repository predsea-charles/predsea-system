# Unified Dockerfile for PredSea Web API and Daily Orchestrator Job
FROM python:3.11-slim

# Install system dependencies required for scientific Python packages (cartopy, netCDF4, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgeos-dev \
    libproj-dev \
    proj-bin \
    libnetcdf-dev \
    libhdf5-dev \
    libeccodes-tools \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Google Cloud SDK (gcloud CLI)
RUN curl -sSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz > /tmp/google-cloud-sdk.tar.gz \
    && tar -xzf /tmp/google-cloud-sdk.tar.gz -C /root \
    && /root/google-cloud-sdk/install.sh --quiet \
    && rm /tmp/google-cloud-sdk.tar.gz \
    && ln -sf /usr/local/bin/python3 /usr/bin/python3 \
    && ln -sf /usr/local/bin/python /usr/bin/python
ENV PATH="/root/google-cloud-sdk/bin:${PATH}"





# Set up environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/humanintheloop

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download Cartopy offline shapefiles to prevent dynamic runtime network dependencies
RUN mkdir -p /app/assets/cartopy_data && \
    cartopy_feature_download physical --output /app/assets/cartopy_data

# Copy application source code
COPY . .

# Ensure simulation/inputs directory exists and populate with the static reference bathymetry grids
RUN mkdir -p /app/simulation/inputs && \
    cp /app/assets/static_grids/balearic_bathymetry_*.nc /app/simulation/inputs/

# Set default ports and run arguments
EXPOSE 8080

# Default container command: launch the FastAPI web application
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080", "--app-dir", "humanintheloop"]
