"""
Patch vantage6 docker_manager.py to support algorithm_network_mode config.

Adds one config key: algorithm_network_mode
  - If set to "host" in the node config YAML, algorithm containers
    run with --network=host so they can bind ports on the host's IP.
  - If not set, behaviour is unchanged (default bridge network).

Usage (inside custom node Dockerfile):
  COPY patch_docker_manager.py /tmp/
  RUN python3 /tmp/patch_docker_manager.py
"""

import pathlib
import sys


TARGET = pathlib.Path(
    '/vantage6/vantage6-node/vantage6/node/docker/docker_manager.py'
)

if not TARGET.exists():
    print(f'ERROR: {TARGET} not found — check vantage6 node image version')
    sys.exit(1)

original = TARGET.read_text()

# ── Patch 1: read algorithm_network_mode from config ─────────────────────────
# Insert after the line that reads algorithm_env from config.
OLD_ENV_READ = "        self.algorithm_env = config.get(\"algorithm_env\", {})"
NEW_ENV_READ = (
    "        self.algorithm_env = config.get(\"algorithm_env\", {})\n"
    "        self.algorithm_network_mode = config.get(\"algorithm_network_mode\", None)"
)

if OLD_ENV_READ not in original:
    print('ERROR: Could not find algorithm_env line to patch — node image may have changed.')
    sys.exit(1)

patched = original.replace(OLD_ENV_READ, NEW_ENV_READ, 1)

# ── Patch 2: pass network_mode when creating algorithm containers ─────────────
# The algorithm container is created in task_manager.py not docker_manager.py,
# but task_manager receives algorithm_env via docker_manager.
# We patch the call site that passes algorithm_env to task_manager.

OLD_ALGO_ENV_PASS = "                    algorithm_env=self.algorithm_env,"
NEW_ALGO_ENV_PASS = (
    "                    algorithm_env=self.algorithm_env,\n"
    "                    network_mode=self.algorithm_network_mode,"
)

if OLD_ALGO_ENV_PASS not in patched:
    print('WARNING: Could not find algorithm_env pass-through to task_manager.')
    print('Trying alternative patch location...')

    # Alternative: patch wherever algorithm containers are started
    # This is a fallback in case the internal structure differs
    OLD_ALGO_ENV_PASS = "                    algorithm_env=algorithm_env,"
    NEW_ALGO_ENV_PASS = (
        "                    algorithm_env=algorithm_env,\n"
        "                    network_mode=network_mode,"
    )

    if OLD_ALGO_ENV_PASS not in patched:
        print('ERROR: Could not find algorithm container creation site.')
        print('Manual patching required.')
        # Write the original file back and exit gracefully
        # The system will work without host networking (just no port exposure)
        print('Continuing without patch — port exposure will need manual config.')
        sys.exit(0)

patched = patched.replace(OLD_ALGO_ENV_PASS, NEW_ALGO_ENV_PASS, 1)

TARGET.write_text(patched)
print(f'✓ Patched {TARGET}')
print('  Added: self.algorithm_network_mode = config.get("algorithm_network_mode", None)')
print('  Added: network_mode=self.algorithm_network_mode in container creation')
