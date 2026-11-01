import random

from fof.facts.evidence import bh, prior_strength, score


def test_small_sample_is_pulled_back_big_sample_keeps_its_rate():
    p_small, _, z_small = score(10, 20, 0.40, m=200)      # 50% on 20 tries
    p_big, _, z_big = score(500, 1000, 0.40, m=200)       # 50% on 1000 tries
    assert 0.40 < p_small < 0.42 and z_small < 1
    assert p_big > 0.48 and z_big > 4


def test_pure_noise_gives_a_strong_prior_and_no_discoveries():
    random.seed(1)
    n, p0 = [40] * 300, [0.4] * 300
    k = [sum(random.random() < 0.4 for _ in range(40)) for _ in n]
    m = prior_strength(k, n, p0)
    assert m > 200                                         # spread is all binomial noise
    zs = [score(ki, ni, 0.4, m)[2] for ki, ni in zip(k, n)]
    from fof.facts.evidence import two_sided_p
    assert not any(bh([two_sided_p(z) for z in zs]))


def test_bh_keeps_real_effects():
    assert bh([0.0001, 0.0002, 0.5, 0.9]) == [True, True, False, False]
    assert bh([]) == []
