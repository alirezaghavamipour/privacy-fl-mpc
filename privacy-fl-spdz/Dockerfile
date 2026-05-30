FROM python:3.12-slim

LABEL org.opencontainers.image.description="SPDZ aggregation party: secure sum via asyncio+mTLS direct TCP"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir vantage6-algorithm-tools

COPY spdz_pkg/ ./spdz_pkg/
COPY setup.py .
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ARG PKG_NAME="spdz_pkg"
ENV PKG_NAME=${PKG_NAME}

CMD python -c "from vantage6.algorithm.tools.wrap import wrap_algorithm; wrap_algorithm()"
