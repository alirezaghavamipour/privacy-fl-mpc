"""
Patch vantage6 task_manager.py to accept and use network_mode parameter.

This is the second part of the patch: task_manager.py actually calls
docker_client.containers.run() for algorithm containers.
We add the network_mode argument to that call.
"""

import pathlib
import sys

TARGET = pathlib.Path(
    '/vantage6/vantage6-node/vantage6/node/docker/task_manager.py'
)

if not TARGET.exists():
    print(f'ERROR: {TARGET} not found')
    sys.exit(1)

original = TARGET.read_text()

# ── Patch: add network_mode to __init__ signature ────────────────────────────
OLD_INIT_SIG = "        algorithm_env: dict,"
NEW_INIT_SIG = "        algorithm_env: dict,\n        network_mode: str = None,"

if OLD_INIT_SIG not in original:
    print('WARNING: Could not patch __init__ signature — may already be patched or changed.')
else:
    original = original.replace(OLD_INIT_SIG, NEW_INIT_SIG, 1)
    print('✓ Patched __init__ signature')

# ── Patch: store network_mode as instance variable ───────────────────────────
OLD_STORE = "        self.environment_variables = self._setup_environment_vars("
NEW_STORE = (
    "        self.network_mode = network_mode\n"
    "        self.environment_variables = self._setup_environment_vars("
)

if OLD_STORE not in original:
    print('WARNING: Could not patch network_mode storage.')
else:
    original = original.replace(OLD_STORE, NEW_STORE, 1)
    print('✓ Patched network_mode storage')

# ── Patch: pass network_mode to docker run ───────────────────────────────────
# Find the containers.run() call and add network_mode
OLD_RUN = "            auto_remove=not keep,"
NEW_RUN = "            auto_remove=not keep,\n            network_mode=self.network_mode,"

if OLD_RUN not in original:
    print('WARNING: Could not find auto_remove line in containers.run()')
    print('Trying alternative...')
    OLD_RUN = "            tty=True,"
    NEW_RUN = "            tty=True,\n            network_mode=self.network_mode,"
    if OLD_RUN not in original:
        print('ERROR: Could not patch containers.run() call.')
        sys.exit(0)

original = original.replace(OLD_RUN, NEW_RUN, 1)
print('✓ Patched containers.run() with network_mode')

TARGET.write_text(original)
print(f'✓ Written to {TARGET}')
