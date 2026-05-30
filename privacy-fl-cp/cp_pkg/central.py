import time
from vantage6.algorithm.tools.decorators import algorithm_client
from vantage6.algorithm.client import AlgorithmClient
from vantage6.algorithm.tools.util import info

# Docker image used for the SPDZ aggregation servers
SPDZ_IMAGE = 'ghcr.io/alirezaghavamipour/privacy-fl-mpc/privacy-fl-spdz:main'
CP_IMAGE   = 'ghcr.io/alirezaghavamipour/privacy-fl-mpc/privacy-fl-cp:main'


@algorithm_client
def central(
    client: AlgorithmClient,
    cp_org_ids: list,
    as_org_ids: list,
    cp_values: list,
    num_iterations: int = 2,
):
    """
    Central FL orchestrator.

    Flow per iteration
    ------------------
    1. Send cp_local_train to each CP → each returns two additive shares.
    2. Route shares:  all 'for_as1' shares → AS-1,  all 'for_as2' → AS-2.
    3. Submit SPDZ tasks to AS-1 (Party 0) then AS-2 (Party 1).
       AS-1 listens; AS-2 connects with retry logic.
    4. Both AS nodes run the SPDZ protocol, reveal the aggregate, return it.
    5. Broadcast aggregate to CPs for the next round.

    Privacy note
    ------------
    The central orchestrator only ever handles *random shares*, never raw
    CP updates.  Neither AS node can reconstruct individual values alone.

    Parameters
    ----------
    cp_org_ids     : list of int   — organisation IDs of the CP nodes
    as_org_ids     : list of int   — [AS-1 org id, AS-2 org id]
    cp_values      : list of float — each CP's private local value
    num_iterations : int           — number of FL rounds
    """
    info('Central: Starting privacy-preserving FL with SPDZ aggregation')
    info(f'Central: CPs={cp_org_ids}, ASes={as_org_ids}, iterations={num_iterations}')

    previous_aggregate = 0.0
    all_iterations = []

    for i in range(num_iterations):
        info(f'Central: ─── Iteration {i + 1} / {num_iterations} ───')

        # ── Step 1: Local training + share splitting ──────────────────────
        info('Central: Step 1 — requesting local training from CPs')
        cp_tasks = []
        for j, org_id in enumerate(cp_org_ids):
            task = client.task.create(
                organizations=[org_id],
                name=f'cp-train-iter{i + 1}-org{org_id}',
                image=CP_IMAGE,
                input_={
                    'method': 'cp_local_train',
                    'kwargs': {
                        'local_value': cp_values[j],
                        'previous_aggregate': previous_aggregate,
                    },
                },
            )
            info(f'Central: Submitted cp_local_train to org {org_id} (task {task["id"]})')
            cp_tasks.append(task)

        # Collect share pairs from all CPs
        cp_results = []
        for task in cp_tasks:
            results = client.wait_for_results(task_id=task['id'])
            result = results[0]['result']
            # result == {'for_as1': float, 'for_as2': float}
            cp_results.append(result)
            info(f'Central: Received shares from task {task["id"]}')

        # ── Step 2: Route shares to AS nodes ─────────────────────────────
        # AS-1 gets one share from every CP, AS-2 gets the complementary share.
        # The central node sees only random numbers — not useful alone.
        as1_shares = [r['for_as1'] for r in cp_results]
        as2_shares = [r['for_as2'] for r in cp_results]
        info(f'Central: Step 2 — shares routed (AS-1: {len(as1_shares)} shares, AS-2: {len(as2_shares)} shares)')

        # ── Step 3: SPDZ aggregation ──────────────────────────────────────
        # Submit AS-1 FIRST so it starts listening before AS-2 tries to connect.
        info('Central: Step 3 — submitting SPDZ Party 0 task to AS-1')
        as1_task = client.task.create(
            organizations=[as_org_ids[0]],
            name=f'spdz-party0-iter{i + 1}',
            image=SPDZ_IMAGE,
            input_={
                'method': 'spdz_compute',
                'kwargs': {'shares': as1_shares},
            },
        )
        info(f'Central: AS-1 task id={as1_task["id"]}')

        # Small pause so AS-1's container has time to start and bind the port
        # before AS-2 makes its first connection attempt.
        # AS-2 also has a retry loop (120 s) as a safety net.
        time.sleep(10)

        info('Central: Submitting SPDZ Party 1 task to AS-2')
        as2_task = client.task.create(
            organizations=[as_org_ids[1]],
            name=f'spdz-party1-iter{i + 1}',
            image=SPDZ_IMAGE,
            input_={
                'method': 'spdz_compute',
                'kwargs': {'shares': as2_shares},
            },
        )
        info(f'Central: AS-2 task id={as2_task["id"]}')

        # ── Step 4: Collect aggregate ────────────────────────────────────
        info('Central: Waiting for both SPDZ tasks to complete...')
        as1_results = client.wait_for_results(task_id=as1_task['id'], timeout=600)
        as2_results = client.wait_for_results(task_id=as2_task['id'], timeout=600)

        aggregate_from_as1 = as1_results[0]['result']['aggregate']
        aggregate_from_as2 = as2_results[0]['result']['aggregate']

        # Both parties compute the same aggregate — sanity check
        if abs(aggregate_from_as1 - aggregate_from_as2) > 1e-6:
            info(f'Central: WARNING — AS-1 and AS-2 aggregates differ! '
                 f'({aggregate_from_as1} vs {aggregate_from_as2})')
        else:
            info(f'Central: Aggregates match ✓')

        previous_aggregate = aggregate_from_as1
        info(f'Central: Iteration {i + 1} aggregate = {previous_aggregate:.4f}')

        all_iterations.append({
            'iteration': i + 1,
            'aggregate': previous_aggregate,
        })

    info(f'Central: FL complete. Final aggregate = {previous_aggregate:.4f}')
    return {
        'iterations': all_iterations,
        'final_aggregate': previous_aggregate,
    }
