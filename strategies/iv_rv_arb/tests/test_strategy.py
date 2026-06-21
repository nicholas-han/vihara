import numpy as np

from iv_rv_arb.config import IvRvConfig
from iv_rv_arb.data import synthetic_dataset
from iv_rv_arb.strategy import build_inputs


def test_carry_prefix_invariant_no_lookahead():
    """carry[i] = sum(premium[:i]) so holding i->i+1 earns exactly premium[i].

    Locks the alignment that keeps the future-laden premium out of the decision
    path: the mark increment realises a bar later, never at the decision bar.
    """
    ds = synthetic_dataset(n_days=300, horizon=1, seed=3)
    inp = build_inputs(ds, IvRvConfig())
    carry, premium = inp["carry"], inp["premium"]
    assert carry[0] == 0.0
    assert np.allclose(np.diff(carry), premium[:-1])  # terminal premium intentionally unrealised


def test_build_inputs_shapes_aligned():
    ds = synthetic_dataset(n_days=300, horizon=1, seed=3)
    inp = build_inputs(ds, IvRvConfig())
    m = len(inp["times"])
    for key in ("X", "y", "implied", "premium", "carry"):
        assert len(inp[key]) == m
