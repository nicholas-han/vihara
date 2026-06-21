from iv_rv_arb.implied import DiscreteReplicationIV, build_chain


def test_discrete_replication_recovers_flat_vol():
    vol = 0.5
    chain = build_chain(forward=100.0, T=30 / 365, vol=vol, n_strikes=81, width=0.8)
    iv = DiscreteReplicationIV().implied_variance(chain)
    assert abs(iv - vol**2) / vol**2 < 0.05
