FROM ghcr.io/vantage6/infrastructure/node:cotopaxi

LABEL description="Custom vantage6 node with algorithm_network_mode support for SPDZ AS nodes"

# Copy patch scripts
COPY patch_docker_manager.py /tmp/patch_docker_manager.py
COPY patch_task_manager.py   /tmp/patch_task_manager.py

# Apply patches
RUN python3 /tmp/patch_docker_manager.py && \
    python3 /tmp/patch_task_manager.py

# Clean up
RUN rm /tmp/patch_docker_manager.py /tmp/patch_task_manager.py
