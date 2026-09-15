"""Generate the suppliers dimension table."""

import numpy as np
import pandas as pd

from src import config
from src.data_generation.utils import get_faker, get_rng, CATEGORY_NAMES

_REGIONS = ["North America", "Europe", "Asia", "South America"]


def generate_suppliers(n: int = config.N_SUPPLIERS) -> pd.DataFrame:
    """Return the suppliers dimension table.

    Reliability design decision
    ----------------------------
    base_reliability_score is drawn from a Beta(8, 2) distribution rather
    than a uniform distribution. Beta(8, 2) is heavily skewed toward the
    high end (mean ~0.8) with a long left tail — this mirrors real
    supplier networks, where most suppliers are dependable and a minority
    are chronically unreliable. A uniform distribution would make "bad"
    suppliers just as common as "good" ones, which isn't how procurement
    risk is actually distributed, and would make the Phase 5 "which
    suppliers are unreliable?" analysis trivial (everything looks equally
    random) instead of a genuine pattern to uncover.

    Lead time is correlated with reliability: less-reliable suppliers also
    tend to quote longer/more variable lead times, which matches the
    real-world pattern that weak logistics discipline shows up as both
    "slow" and "inconsistent" at once.

    primary_category (schema addition beyond Phase 1's original design)
    ----------------------------------------------------------------------
    The original architecture (docs/architecture.md) didn't give suppliers
    a category. We add `primary_category` here because it lets products be
    assigned to suppliers who plausibly sell that kind of product (an
    electronics supplier is unlikely to also ship groceries), instead of a
    random pairing that would make no business sense. This addition is
    documented in docs/architecture.md and docs/data_dictionary.md.
    """
    fake = get_faker()
    rng = get_rng("suppliers")

    reliability = rng.beta(8, 2, size=n)
    base_lead_time = rng.integers(3, 21, size=n)
    lead_time_penalty = ((1 - reliability) * 10).astype(int)
    avg_lead_time_days = base_lead_time + lead_time_penalty

    suppliers = pd.DataFrame({
        "supplier_id": np.arange(1, n + 1),
        "name": [fake.company() for _ in range(n)],
        "region": rng.choice(_REGIONS, size=n),
        "primary_category": rng.choice(CATEGORY_NAMES, size=n),
        "base_reliability_score": reliability.round(3),
        "avg_lead_time_days": avg_lead_time_days,
    })
    return suppliers
