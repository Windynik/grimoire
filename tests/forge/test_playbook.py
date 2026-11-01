import re

from backend.forge.playbook import PLAYSTYLES, load_playbook


def test_formats_loaded():
    pb = load_playbook()
    assert set(pb.formats) == {"commander", "brawl", "standardbrawl", "standard", "pioneer",
                               "modern", "legacy", "vintage", "pauper", "casual"}
    assert pb.formats["commander"].deck_size == 100 and pb.formats["commander"].singleton
    assert pb.formats["pauper"].legality_key == "pauper"
    assert pb.formats["casual"].legality_key is None


def test_copies_allowed():
    pb = load_playbook()
    assert pb.formats["vintage"].copies_allowed("restricted") == 1
    assert pb.formats["modern"].copies_allowed("legal") == 4
    assert pb.formats["commander"].copies_allowed("legal") == 1


def test_quotas_scale_with_size():
    pb = load_playbook()
    assert pb.quotas(pb.formats["commander"], "midrange")["ramp"] == 10
    assert pb.quotas(pb.formats["modern"], "aggro")["creatures"] == 18
    casual80 = pb.formats["casual"].scaled(80, 4)
    assert pb.quotas(casual80, "midrange")["ramp"] == 8  # 100-class scaled by 0.8


def test_casual_scaled_clamps():
    c = load_playbook().formats["casual"].scaled(10, 9)
    assert c.deck_size == 40 and c.max_copies == 4


def test_curve_targets_sum_to_one():
    pb = load_playbook()
    for style in PLAYSTYLES:
        assert abs(sum(pb.curve_target(pb.formats["modern"], style).values()) - 1.0) < 1e-6


def test_regexes_compile():
    pb = load_playbook()
    for patterns in pb.roles.values():
        for p in patterns:
            re.compile(p)
    for hook in pb.hooks.values():
        for key in ("gives", "wants", "wants_scaling"):
            for p in hook[key]:
                re.compile(p)
