"""Page-level macro recall, query hit rate, and reciprocal rank."""


def query_metrics(relevant, retrieved):
    truth = {(r["document"],r["page"]) for r in relevant}
    if not truth:
        raise ValueError("Recall is undefined for a no-answer query")
    pages = list(dict.fromkeys((r["document"],r["page"]) for r in retrieved))
    result = {}
    for k in (1,3,5):
        hits = len(set(pages[:k]) & truth)
        result[f"recall@{k}"] = hits / len(truth)
        result[f"hit@{k}"] = float(hits > 0)
    result["mrr@5"] = next((1/rank for rank,page in enumerate(pages[:5],1) if page in truth),0.)
    return result


def aggregate(items):
    if not items:
        raise ValueError("Cannot score an empty evaluation split")
    return {key:sum(row[key] for row in items)/len(items) for key in items[0]}
