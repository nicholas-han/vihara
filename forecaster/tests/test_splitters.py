import numpy as np

from forecaster.timeseries import HARForecaster
from forecaster.validation import purged_walk_forward, walk_forward_predict


def test_purge_gap_train_before_test_no_overlap():
    horizon = 3
    for tr, te in purged_walk_forward(100, n_splits=4, horizon=horizon, min_train=20):
        assert tr.max() < te.min()
        assert te.min() - tr.max() >= horizon          # purge gap respected
        assert len(np.intersect1d(tr, te)) == 0


def test_walk_forward_predict_initial_block_is_nan():
    rng = np.random.default_rng(2)
    X = rng.uniform(0.01, 0.1, (300, 3))
    y = 0.01 + X @ np.array([0.4, 0.3, 0.3])
    preds = walk_forward_predict(HARForecaster, X, y, n_splits=5, horizon=1)
    assert np.isnan(preds[0])
    assert np.isfinite(preds[-1])
