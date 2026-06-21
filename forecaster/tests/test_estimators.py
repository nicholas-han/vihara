import numpy as np

from forecaster.realized import (
    garman_klass,
    realized_kernel,
    realized_variance,
    realized_variance_grid,
)


def test_realized_variance_grid_recovers_known():
    n_days, n_intra, r = 10, 50, 0.001
    row = np.concatenate([[0.0], np.cumsum(np.full(n_intra - 1, r))])
    grid = np.exp(np.tile(row, (n_days, 1)))
    rv = realized_variance_grid(grid, annualization=365.0)
    expected = (n_intra - 1) * r**2 * 365.0
    assert np.allclose(rv, expected, rtol=1e-10)


def test_realized_kernel_same_order_as_rv_for_iid():
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 500)))
    rk = realized_kernel(prices, annualization=1.0)
    rv = realized_variance(prices, annualization=1.0)
    assert rk > 0 and abs(rk - rv) < 5 * rv


def test_garman_klass_nonnegative():
    o = np.array([100.0, 101.0])
    h = np.array([102.0, 103.0])
    low = np.array([99.0, 100.0])
    c = np.array([101.0, 102.0])
    assert np.all(garman_klass(o, h, low, c) >= 0)
