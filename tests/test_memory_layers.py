import pytest


def test_rank_counts_original_facts_and_keeps_recent_details():
    from cairnkit.memory_layers import LayeredFact, layer_facts

    facts = [LayeredFact(str(i) * 20, (i, str(i)), "topic") for i in range(6)]
    policy = layer_facts(facts, recent_count=2, middle_count=4)
    assert [policy.level(str(i) * 20) for i in range(6)] == [
        "distant",
        "distant",
        "middle",
        "middle",
        "recent",
        "recent",
    ]
    assert policy.protected("5" * 20) and not policy.protected("0" * 20)
    result = policy.compact(lambda texts, level: level + ":" + ",".join(t[0] for t in texts))
    assert "4" * 20 in result and "5" * 20 in result
    assert "distant:0,1" in result and "middle:2,3" in result


def test_unknown_origins_and_durable_facts_cannot_be_deleted():
    from cairnkit.memory_layers import LayeredFact, layer_facts

    policy = layer_facts(
        [
            LayeredFact("old", (0, "a"), "t", protected=True),
            LayeredFact("unknown", None, "t"),
            LayeredFact("new", (1, "b"), "t"),
        ],
        recent_count=1,
        middle_count=2,
    )
    assert all(policy.protected(x) for x in ["old", "unknown", "new"])
    assert policy.level("unknown") == "recent"


def test_layers_stable_when_input_order_or_storage_grouping_changes():
    from cairnkit.memory_layers import LayeredFact, layer_facts

    facts = [LayeredFact(str(i), (i, str(i)), str(i % 2)) for i in range(7)]
    first = layer_facts(facts, recent_count=2, middle_count=4)
    second = layer_facts(list(reversed(facts)), recent_count=2, middle_count=4)
    assert {f.text: first.level(f.text) for f in facts} == {
        f.text: second.level(f.text) for f in facts
    }
    # Correction receives its own newer source order; its old peers do not.
    changed = layer_facts(
        [*facts[1:], LayeredFact("corrected", (8, "c"), "0", protected=True)],
        recent_count=2,
        middle_count=4,
    )
    assert changed.level("corrected") == "recent" and changed.level("1") == "distant"


@pytest.mark.parametrize("recent,middle", [(0, 3), (3, 2), (-1, 3)])
def test_bad_layer_limits_rejected(recent, middle):
    from cairnkit.memory_layers import layer_facts

    with pytest.raises(ValueError):
        layer_facts([], recent_count=recent, middle_count=middle)
