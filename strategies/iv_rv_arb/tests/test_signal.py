import numpy as np

from iv_rv_arb.signal import expanding_zscore, target_exposure


def test_expanding_zscore_no_lookahead():
    x = np.arange(100.0)
    z1 = expanding_zscore(x, min_periods=10)
    x2 = x.copy()
    x2[50:] = -999.0                       # mutate the future
    z2 = expanding_zscore(x2, min_periods=10)
    assert np.allclose(z1[:50], z2[:50], equal_nan=True)


def test_target_exposure_band_sign_saturation():
    z = np.array([np.nan, 0.1, 1.0, -1.0, 5.0])
    w = target_exposure(z, threshold=0.5, z_cap=2.0, max_position=1.0)
    assert w[0] == 0.0      # NaN -> flat
    assert w[1] == 0.0      # inside no-trade band
    assert w[2] == 0.5      # 1.0 / 2.0
    assert w[3] == -0.5     # sign preserved
    assert w[4] == 1.0      # saturates at max_position
