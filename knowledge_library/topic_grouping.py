"""Conservative topic grouping; independent of search ranking and model inference."""
from collections import Counter, defaultdict
import base64

import numpy as np

STATE_VERSION = 1
MAX_DOCUMENTS = 4096  # Bound quadratic pairwise distance/linkage allocations.
DISTANCE_THRESHOLD = 0.55


class TopicCapacityError(ValueError):
    pass


def _unit(value, dimensions=None):
    try:
        vector = np.asarray(value, dtype=np.float32)
        if vector.ndim != 1 or (dimensions is not None and len(vector) != dimensions):
            return None
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(vector).all() or not np.isfinite(norm) or norm < 1e-6:
            return None
        return vector / norm
    except (TypeError, ValueError, OverflowError):
        return None


def fit_topics(documents, vectors):
    """Fit groups with bounded worst-pair distance; singletons deliberately abstain.

    Input ordering cannot select the naming examples. Representatives are ordered
    by center proximity, with stable document IDs breaking ties.
    """
    from sklearn.cluster import AgglomerativeClustering

    candidates = []
    for doc in sorted(documents, key=lambda d: d['id']):
        vector = _unit(vectors.get(doc['id']))
        if vector is not None:
            candidates.append((doc, vector))
    dimensions = Counter(len(v) for _, v in candidates).most_common(1)
    dims = dimensions[0][0] if dimensions else 0
    copies = defaultdict(list)
    originals = {}
    for doc, vector in candidates:
        if len(vector) != dims:
            continue
        identity = doc.get('sha256') or doc['id']
        copies[identity].append(doc['id'])
        originals.setdefault(identity, (doc, vector))
    if len(originals) > MAX_DOCUMENTS:
        raise TopicCapacityError(f'Topic rebuild supports up to {MAX_DOCUMENTS:,} distinct embedded files; existing topics were kept.')

    entries = list(originals.items())
    mean = np.zeros(dims, dtype=np.float32)
    cutoff = 0.15
    state = dict(version=STATE_VERSION, dimensions=dims, mean=mean.tolist(), distance_threshold=cutoff, groups=[])
    if len(entries) < 2:
        return state
    X = np.array([item[1][1] for item in entries], dtype=np.float32)
    # Mean subtraction is unstable for tiny libraries and for identical vectors.
    if len(entries) >= 8:
        proposed_mean = X.mean(axis=0)
        if np.linalg.norm(X - proposed_mean, axis=1).max() > 1e-6:
            mean = proposed_mean
            cutoff = DISTANCE_THRESHOLD
    transformed = X - mean
    norms = np.linalg.norm(transformed, axis=1)
    usable = np.flatnonzero(norms > 1e-6)
    state.update(mean=mean.tolist(), distance_threshold=cutoff)
    if len(usable) < 2:
        return state
    Y = transformed[usable] / norms[usable, None]
    distances = np.clip(1 - Y @ Y.T, 0, 2)
    np.fill_diagonal(distances, 0)
    labels = AgglomerativeClustering(n_clusters=None, metric='precomputed', linkage='complete', distance_threshold=cutoff).fit_predict(distances)
    for label in sorted(set(labels)):
        positions = np.flatnonzero(labels == label)
        if len(positions) < 2:
            continue
        centroid = _unit(Y[positions].mean(axis=0))
        if centroid is None:
            continue
        scores = Y[positions] @ centroid
        order = sorted(range(len(positions)), key=lambda j: (-float(scores[j]), entries[usable[positions[j]]][1][0]['id']))
        identities = [entries[usable[positions[j]]][0] for j in order]
        state['groups'].append(dict(
            document_ids=[doc_id for identity in identities for doc_id in copies[identity]],
            source_hashes=identities, centroid=centroid.tolist(),
            min_similarity=float(min(scores)),
            member_vectors=base64.b64encode(Y[positions].astype('<f4').tobytes()).decode('ascii'),
        ))
    state['groups'].sort(key=lambda g: min(g['document_ids']))
    return state


def match_topic(state, vector, source_hash=None):
    """Return a single unambiguous accepted topic, or None for uncertain input."""
    try:
        if not isinstance(state, dict) or state.get('version') != STATE_VERSION:
            return None
        dims = state['dimensions']
        v = _unit(vector, dims)
        mean = np.asarray(state['mean'], dtype=np.float32)
        if v is None or mean.shape != v.shape or not np.isfinite(mean).all():
            return None
        transformed = _unit(v - mean, dims)
        if transformed is None:
            return None
        groups = state['groups']
        cutoff = float(state['distance_threshold'])
        if not 0 < cutoff < 2:
            return None
        known = {g['name'] for g in groups if source_hash and source_hash in g['source_hashes']}
        if len(known) == 1:
            return next(iter(known))
        if len(known) > 1:
            return None
        accepted = []
        for group in groups:
            center = _unit(group['centroid'], dims)
            minimum = float(group['min_similarity'])
            if center is None or not np.isfinite(minimum) or not -1 <= minimum <= 1:
                return None
            score = float(transformed @ center)
            if score >= max(0.65, minimum) - 1e-6:
                count = len(group['source_hashes'])
                encoded = group['member_vectors']
                expected_bytes = count * dims * 4
                if count < 2 or count > MAX_DOCUMENTS or len(encoded) > 4*((expected_bytes+2)//3):
                    return None
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) != expected_bytes:
                    return None
                members = np.frombuffer(raw, dtype='<f4').reshape(count, dims)
                if not np.isfinite(members).all():
                    return None
                if np.min(members @ transformed) >= 1-cutoff-1e-6:
                    accepted.append((score, group['name']))
        by_name = {}
        for score, name in accepted:
            by_name[name] = max(score, by_name.get(name, -1))
        accepted = sorted(((score, name) for name, score in by_name.items()), reverse=True)
        if accepted and (len(accepted) == 1 or accepted[0][0] - accepted[1][0] >= 0.05):
            return accepted[0][1]
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None
