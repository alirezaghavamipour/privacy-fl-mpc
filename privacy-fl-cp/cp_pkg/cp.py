import numpy as np
from vantage6.algorithm.tools.util import info


def cp_local_train(local_value: float, previous_aggregate: float):
    """
    Simulate local training on a CP node.

    In a real FL system this would train a local model on private data.
    Here we compute:  local_update = local_value + previous_aggregate

    The update is immediately split into two additive shares so that
    neither the central orchestrator nor any single AS sees the raw value.

    Returns
    -------
    dict with keys:
      for_as1 : float  — random share  (goes to AS-1)
      for_as2 : float  — complement    (goes to AS-2)
    """
    local_update = local_value + previous_aggregate
    info(f'CP: local_value={local_value}, previous_aggregate={previous_aggregate:.4f}')
    info(f'CP: local_update={local_update:.4f}')

    # Additive secret splitting
    # share_a is uniformly random; share_b = update - share_a
    # share_a + share_b == local_update  (exact in floats for these magnitudes)
    share_a = float(np.random.uniform(-1e6, 1e6))
    share_b = local_update - share_a

    info('CP: update split into additive shares — raw value never leaves this node')

    return {
        'for_as1': share_a,
        'for_as2': share_b,
    }
