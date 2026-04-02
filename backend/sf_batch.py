"""Shared SOQL batch utility — eliminates duplicated chunked-query patterns.

Provides sequential and parallel helpers to run SOQL queries with IN-clause
batching.  Every caller that previously had a `for i in range(0, len(ids), N)`
loop should use one of these instead.
"""

import logging
from sf_client import sf_query_all, sf_parallel

log = logging.getLogger(__name__)


def batch_soql_query(
    template: str,
    ids: list,
    chunk_size: int = 200,
) -> list:
    """Run a SOQL query with IN-clause batching in sequential chunks.

    Parameters
    ----------
    template : str
        SOQL string containing an ``{id_list}`` placeholder that will be
        replaced with a comma-separated, single-quoted list of IDs.
        Example: ``"SELECT Id FROM SA WHERE Id IN ('{id_list}')"``
    ids : list
        The full list of IDs (or any string keys) to query.
    chunk_size : int
        How many IDs per SOQL call (default 200).

    Returns
    -------
    list
        Combined result rows from all chunks.
    """
    if not ids:
        return []

    results: list = []
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        id_list = "','".join(chunk)
        rows = sf_query_all(template.format(id_list=id_list))
        results.extend(rows)
    return results


def batch_soql_parallel(
    template: str,
    ids: list,
    chunk_size: int = 200,
) -> list:
    """Like :func:`batch_soql_query` but runs chunks in parallel via
    ``sf_parallel``.

    Best for large ID lists where each chunk is independent and the SF
    rate-limiter can handle the concurrency.
    """
    if not ids:
        return []

    chunks = [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]

    if len(chunks) == 1:
        # No benefit from parallelism — just run directly
        id_list = "','".join(chunks[0])
        return sf_query_all(template.format(id_list=id_list))

    fns = {}
    for idx, chunk in enumerate(chunks):
        id_list = "','".join(chunk)
        query = template.format(id_list=id_list)
        # Default-arg capture to avoid late-binding closure bug
        fns[f"chunk_{idx}"] = (lambda q=query: sf_query_all(q))

    results_map = sf_parallel(**fns)
    # Combine in chunk order
    combined: list = []
    for idx in range(len(chunks)):
        combined.extend(results_map[f"chunk_{idx}"])
    return combined
