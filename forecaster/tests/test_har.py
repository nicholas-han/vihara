import numpy as np

from forecaster.timeseries import HARForecaster, make_har_dataset


def test_har_recovers_linear_in_level():
    rng = np.random.default_rng(1)
    X = rng.uniform(0.01, 0.1, size=(500, 3))
    beta = np.array([0.5, 0.3, 0.2])
    y = 0.001 + X @ beta
    pred = HARForecaster(log_space=False).fit(X, y).predict(X)
    assert np.allclose(pred, y, atol=1e-8)


def test_make_har_dataset_alignment_no_lookahead():
    rv = np.arange(1.0, 51.0)
    X, y, idx = make_har_dataset(rv, horizon=1, lags=(1, 5, 22))
    assert idx[0] == 21               # first valid decision day = max_lag - 1
    assert y[0] == 23.0               # forward target rv[t+1] = rv[22]
    assert np.isclose(X[0, 0], 22.0)  # lag-1 feature = rv[t] = rv[21]
