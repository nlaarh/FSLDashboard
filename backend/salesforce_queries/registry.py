"""Named Salesforce query registry for diagnostics and tests."""

from salesforce_queries import data_quality

_NAMED_QUERIES = {
    "data-quality-total": {
        "description": "28-day Data Quality ServiceAppointment count query",
        "builder": lambda *, since: data_quality.data_quality_soql(since)["total"],
    },
}


def list_named_queries() -> list[dict[str, str]]:
    return [
        {"name": name, "description": item["description"]}
        for name, item in sorted(_NAMED_QUERIES.items())
    ]


def get_named_query(name: str, **kwargs) -> str:
    item = _NAMED_QUERIES.get(name)
    if not item:
        raise KeyError(name)
    return item["builder"](**kwargs)
