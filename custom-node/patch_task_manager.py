"""
Patch vantage6 task_manager.py to accept and use a network_mode parameter
for the algorithm container.

The algorithm container is normally started with `network=<named network>`.
When algorithm_network_mode is set (e.g. "host"), we instead start it with
`network_mode=<mode>` and drop the named network (docker-py rejects both).
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

# ── Patch 1: add network_mode at the END of run() signature ────────────────
# It must come after the last non-default parameter (databases_to_use),
# otherwise Python raises "non-default argument follows default argument".
OLD_SIG = (
    "        algorithm_env: dict,\n"
    "        databases_to_use: list[dict],\n"
    "    ) -> list[dict] | None:"
)
NEW_SIG = (
    "        algorithm_env: dict,\n"
    "        databases_to_use: list[dict],\n"
    "        network_mode: str | None = None,\n"
    "    ) -> list[dict] | None:"
)
if "network_mode: str | None = None," not in original and OLD_SIG in original:
    original = original.replace(OLD_SIG, NEW_SIG, 1)
    print('✓ Patched run() signature')
else:
    print('• run() signature already patched or pattern missing')

# ── Patch 2: store network_mode as instance variable ───────────────────────
OLD_STORE = "        self.environment_variables = self._setup_environment_vars("
NEW_STORE = (
    "        self.network_mode = network_mode\n"
    "        self.environment_variables = self._setup_environment_vars("
)
if "self.network_mode = network_mode" not in original and OLD_STORE in original:
    original = original.replace(OLD_STORE, NEW_STORE, 1)
    print('✓ Patched network_mode storage')
else:
    print('• network_mode storage already patched or pattern missing')

# ── Patch 3: wire network_mode into the algorithm containers.run() call ─────
# Original line:    network=container_network,
# Replacement: keep named network only when no explicit mode is requested,
# and add network_mode (None by default → unchanged behaviour).
OLD_NET = "                network=container_network,"
NEW_NET = (
    "                network=(None if self.network_mode else container_network),\n"
    "                network_mode=self.network_mode,"
)
if "network_mode=self.network_mode," not in original and OLD_NET in original:
    original = original.replace(OLD_NET, NEW_NET, 1)
    print('✓ Patched algorithm containers.run() with network_mode')
elif "network_mode=self.network_mode," in original:
    print('• containers.run() already patched')
else:
    print('ERROR: could not find "network=container_network," to patch')
    sys.exit(1)

TARGET.write_text(original)
print(f'✓ Written to {TARGET}')
