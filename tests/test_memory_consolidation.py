import json

import pytest

from cairnkit import ModelAPIError, ModelResponse, ScriptedModel
from cairnkit.memory_ops import MemoryPlanError


@pytest.mark.parametrize("legacy", [False, True])
async def test_over_removal_is_rejected_before_model_reviews_a_bounded_option(legacy):
    from cairnkit.memory_consolidation import consolidate_memory
    from cairnkit.memory_ops import total_chars

    entries = [f"{i:04}:" + "x" * 17 for i in range(480)]
    operations = [
        {"action": "patch", "old_text": entries[3], "content": "latest correction"},
        {"action": "add", "content": "new"},
    ]
    bad = {"remove_ranges": [[0, 2], [4, 479]]}
    if legacy:
        bad = {"remove_indices": [i for i in range(480) if i != 3], "operations": operations}
    model = ScriptedModel(
        [ModelResponse(content=json.dumps(bad)), ModelResponse(content='{"option_id":0}')]
    )
    result = await consolidate_memory(
        model, entries, operations, 11997, target_chars=8000, render_group=lambda rows: rows[0]
    )
    assert result.plan is not None and result.attempts == 2
    assert 7600 <= total_chars(result.plan.entries) <= 8000
    assert "latest correction" in result.plan.entries and entries[3] not in result.plan.entries
    assert "new" in result.plan.entries and entries[-1] in result.plan.entries


async def test_declining_recovery_after_over_removal_keeps_original_snapshot():
    from cairnkit.memory_consolidation import consolidate_memory

    entries = [f"{i:04}:" + "x" * 17 for i in range(480)]
    model = ScriptedModel(
        [
            ModelResponse(content='{"remove_ranges":[[0,479]]}'),
            ModelResponse(content='{"option_id":null}'),
        ]
    )
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: rows[0],
    )
    assert result.plan is None and result.error == "option_declined"
    assert len(entries) == 480 and len(model.requests) == 2


@pytest.mark.parametrize("end,accepted", [(175, True), (176, False)])
async def test_deletion_tolerates_small_undershoot_but_not_beyond_five_percent(end, accepted):
    from cairnkit.memory_consolidation import consolidate_memory
    from cairnkit.memory_ops import total_chars

    entries = [f"{i:04}:" + "x" * 17 for i in range(480)]
    model = ScriptedModel(
        [
            ModelResponse(content=json.dumps({"remove_ranges": [[0, end]]})),
            ModelResponse(content='{"option_id":null}'),
        ]
    )
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: rows[0],
    )
    if accepted:
        assert total_chars(result.plan.entries) == 7603
    else:
        assert result.plan is None


async def test_large_indivisible_entry_cannot_turn_recovery_into_almost_empty_memory():
    from cairnkit.memory_consolidation import consolidate_memory

    entries = ["x" * 11998]
    model = ScriptedModel([ModelResponse(content='{"remove_ranges":[[0,0]]}')] * 3)
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: rows[0],
    )
    assert result.plan is None and result.error == "over_removal" and result.attempts == 3


async def test_lossless_host_grouping_can_shrink_far_below_target():
    from cairnkit.memory_consolidation import consolidate_memory

    entries = [f"fact-{i}:" + " " * 100 for i in range(120)]
    model = ScriptedModel(
        [
            ModelResponse(
                content=json.dumps(
                    {"groups": [list(range(i, min(i + 16, 121))) for i in range(0, 121, 16)]}
                )
            )
        ]
    )
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: ";".join(s.strip() for s in rows),
    )
    assert result.plan is not None and result.attempts == 1
    assert all(f"fact-{i}:" in ";".join(result.plan.entries) for i in range(120))
    assert "new" in ";".join(result.plan.entries) and sum(map(len, result.plan.entries)) < 2000


def reply(operations):
    return ModelResponse(content=json.dumps({"operations": operations}))


async def test_fitting_batch_needs_no_model_call():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    result = await consolidate_memory(model, [], [{"action": "add", "content": "A"}], 20)
    assert result.plan.entries == ["A"] and result.attempts == 0 and not model.requests


async def test_full_memory_consolidates_atomically_without_mutating_input():
    from cairnkit.memory_consolidation import consolidate_memory

    entries = ["Likes morning appointments."]
    model = ScriptedModel(
        [
            reply(
                [
                    {"action": "patch", "old_text": entries[0], "content": "Likes mornings."},
                    {"action": "add", "content": "Uses notes."},
                ]
            )
        ]
    )
    result = await consolidate_memory(
        model, entries, [{"action": "add", "content": "Uses notes."}], 30
    )
    assert result.plan.entries == ["Likes mornings.", "Uses notes."]
    assert entries == ["Likes morning appointments."] and result.attempts == 1
    feedback = json.loads(model.requests[0]["messages"][-1]["content"])
    assert feedback["current_entries"] == entries and feedback["limit"] == 30


async def test_bad_match_feedback_can_be_repaired_in_next_attempt():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            reply([{"action": "remove", "old_text": "missing"}]),
            reply([{"action": "remove", "old_text": "old"}, {"action": "add", "content": "new"}]),
        ]
    )
    result = await consolidate_memory(model, ["old"], [{"action": "add", "content": "new"}], 3)
    assert result.plan.entries == ["new"] and result.attempts == 2
    assert json.loads(model.requests[1]["messages"][-1]["content"])["failure_class"] == "no_match"
    assert [m["role"] for m in model.requests[1]["messages"]] == [
        "system",
        "user",
        "user",
    ]


async def test_three_failed_attempts_leave_original_memory_unchanged():
    from cairnkit.memory_consolidation import consolidate_memory

    operations = [{"action": "add", "content": "new"}]
    model = ScriptedModel([reply(operations)] * 3)
    entries = ["old"]
    result = await consolidate_memory(model, entries, operations, 3)
    assert result.plan is None and result.attempts == 3 and result.error == "over_limit"
    assert entries == ["old"] and len(model.requests) == 3


async def test_host_rejection_is_feedback_not_a_write():
    from cairnkit.memory_consolidation import consolidate_memory

    def validate(plan):
        if "new" not in plan.entries:
            raise MemoryPlanError("Must retain the new fact", "ungrounded")

    model = ScriptedModel(
        [
            reply([{"action": "remove", "old_text": "old"}]),
            reply([{"action": "remove", "old_text": "old"}, {"action": "add", "content": "new"}]),
        ]
    )
    result = await consolidate_memory(
        model, ["old"], [{"action": "add", "content": "new"}], 3, validate=validate
    )
    assert result.plan.entries == ["new"] and result.attempts == 2


async def test_invalid_initial_operation_does_not_trigger_consolidation():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    with pytest.raises(MemoryPlanError):
        await consolidate_memory(model, ["old"], [{"action": "remove", "old_text": "missing"}], 3)
    assert not model.requests


@pytest.mark.parametrize("content", ["not JSON", '{"operations": []}', '{"operations": [42]}'])
async def test_malformed_model_output_has_bounded_attempts(content):
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content=content)] * 3)
    result = await consolidate_memory(model, ["old"], [{"action": "add", "content": "new"}], 3)
    assert result.plan is None and result.attempts == 3


async def test_transport_errors_are_not_retried():
    from cairnkit.memory_consolidation import consolidate_memory

    class Failing:
        calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            raise ModelAPIError(503, "unavailable")

    model = Failing()
    with pytest.raises(ModelAPIError):
        await consolidate_memory(model, ["old"], [{"action": "add", "content": "new"}], 3)
    assert model.calls == 1


async def test_target_leaves_headroom_then_successive_adds_need_no_model():
    from cairnkit.memory_consolidation import consolidate_memory
    from cairnkit.memory_ops import total_chars

    model = ScriptedModel(
        [reply([{"action": "remove", "old_text": "x" * 9}, {"action": "add", "content": "new"}])]
    )
    result = await consolidate_memory(
        model, ["a" * 9, "x" * 9], [{"action": "add", "content": "new"}], 24, target_chars=16
    )
    assert result.target_met and total_chars(result.plan.entries) <= 16
    for fact in ["b", "c"]:
        result = await consolidate_memory(
            model, result.plan.entries, [{"action": "add", "content": fact}], 24, target_chars=16
        )
        assert result.attempts == 0
    assert len(model.requests) == 1
    assert not result.target_met  # ordinary writes may use the reserved headroom


async def test_soft_target_falls_back_to_best_valid_plan_after_three_proposals():
    from cairnkit.memory_consolidation import consolidate_memory

    batch = [{"action": "remove", "old_text": "old"}, {"action": "add", "content": "new fact"}]
    model = ScriptedModel([reply(batch), ModelResponse(content="bad json"), reply(batch)])
    result = await consolidate_memory(
        model, ["old"], [{"action": "add", "content": "new fact"}], 9, target_chars=5
    )
    assert result.plan.entries == ["new fact"] and not result.target_met and result.attempts == 3
    feedback = json.loads(model.requests[1]["messages"][-1]["content"])
    assert feedback["failure_class"] == "target_not_met" and "current_entries" not in feedback


async def test_index_removals_reduce_proposal_size_and_cannot_empty_store():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            ModelResponse(content=json.dumps({"remove_indices": [0]})),
            ModelResponse(
                content=json.dumps(
                    {"remove_indices": [0], "operations": [{"action": "add", "content": "new"}]}
                )
            ),
        ]
    )
    result = await consolidate_memory(model, ["old"], [{"action": "add", "content": "new"}], 3)
    assert result.plan.entries == ["new"] and result.attempts == 2
    assert (
        json.loads(model.requests[1]["messages"][-1]["content"])["failure_class"] == "would_empty"
    )


@pytest.mark.parametrize("target", [0, -1, 11])
async def test_invalid_target_rejected_before_model(target):
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    with pytest.raises(ValueError):
        await consolidate_memory(
            model, [], [{"action": "add", "content": "a"}], 10, target_chars=target
        )
    assert not model.requests


async def test_selection_merges_by_stable_ids_with_pending_already_included():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content='{"groups":[[0,1,2]],"remove_ranges":[]}')])
    result = await consolidate_memory(
        model,
        ["A long", "B long"],
        [{"action": "add", "content": "C long"}],
        18,
        target_chars=8,
        render_group=lambda rows: "+".join(r[0] for r in rows),
    )
    assert result.plan.entries == ["A+B+C"] and result.target_met
    assert [(c.action, c.before, c.after) for c in result.plan.changes] == [
        ("remove", "A long", None),
        ("remove", "B long", None),
        ("add", None, "A+B+C"),
    ]
    data = json.loads(model.requests[0]["messages"][-1]["content"])
    assert data["entry_count"] == 3 and data["protected_ids"] == [2]
    assert data["selection_entries"][2]["id"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"groups": [[True]]},
        {"groups": [[0, 0]]},
        {"groups": [[0], [0]]},
        {"remove_ranges": [[0, 9999999]]},
        {"remove_ranges": [[1, 0]]},
        {"remove_ranges": [[2, 2]]},
        {"groups": [[0]], "remove_ranges": [[0, 0]]},
        {"remove_ranges": [[0, 1], [1, 1]]},
        {"groups": [[-1]]},
    ],
)
async def test_selection_invalid_ids_overlap_and_pending_deletion_fail_closed(bad):
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content=json.dumps(bad))] * 3)
    result = await consolidate_memory(
        model,
        ["old A", "old B"],
        [{"action": "add", "content": "new"}],
        14,
        render_group=lambda rows: "|".join(rows),
    )
    assert result.plan is None and result.attempts == 3


async def test_large_selection_range_compact_output_and_continuous_headroom():
    from cairnkit.memory_consolidation import consolidate_memory
    from cairnkit.memory_ops import total_chars

    entries = [f"{i:04}:" + "x" * 17 for i in range(480)]  # 11997 including delimiters
    model = ScriptedModel([ModelResponse(content='{"remove_ranges":[[0,160]]}')])
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: "|".join(rows),
    )
    assert result.target_met and total_chars(result.plan.entries) == 7978
    assert entries[160] not in result.plan.entries and entries[161] in result.plan.entries
    for i in range(20):
        result = await consolidate_memory(
            model,
            result.plan.entries,
            [{"action": "add", "content": f"new-{i}"}],
            12000,
            target_chars=8000,
            render_group=lambda rows: "|".join(rows),
        )
        assert result.attempts == 0
    assert len(model.requests) == 1


async def test_rejected_long_output_not_replayed_and_length_never_commits():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            ModelResponse(content='{"remove_ranges":[[0,0]]}', finish_reason="length"),
            ModelResponse(content="invalid-" * 10000),
            ModelResponse(content='{"option_id":0}', finish_reason="stop"),
        ]
    )
    result = await consolidate_memory(
        model,
        ["old"],
        [{"action": "add", "content": "new"}],
        3,
        render_group=lambda rows: "|".join(rows),
    )
    assert result.plan.entries == ["new"] and result.attempts == 3
    for request in model.requests[1:]:
        assert all(m["role"] != "assistant" for m in request["messages"])
        assert len(json.dumps(request["messages"])) < 6000
        feedback = json.loads(request["messages"][-1]["content"])
        assert "removal_options" in feedback
    assert "selection_entries" not in json.loads(model.requests[1]["messages"][-1]["content"])


@pytest.mark.parametrize("overlap", [False, True])
async def test_full_singleton_list_recovers_with_a_calculated_removal_option(overlap):
    from cairnkit.memory_consolidation import consolidate_memory
    from cairnkit.memory_ops import total_chars

    entries = [f"{i:04}-" + "x" * (12 + i % 5) for i in range(20)]
    operations = [
        {"action": "patch", "old_text": entries[3], "content": "latest correction"},
        {"action": "add", "content": "new fact"},
    ]
    bad = {"groups": [[i] for i in range(21)]}
    if overlap:
        bad["remove_ranges"] = [[0, 14]]
    model = ScriptedModel(
        [
            ModelResponse(content=json.dumps(bad)),
            ModelResponse(content='{"option_id":0}'),
            ModelResponse(content=json.dumps(bad)),
        ]
    )
    result = await consolidate_memory(
        model, entries, operations, 440, target_chars=300, render_group=lambda rows: rows[0]
    )
    assert result.plan is not None and result.target_met and result.attempts == 2
    after = result.plan.entries
    assert 277 <= total_chars(after) <= 300
    assert "latest correction" in after and "new fact" in after and entries[3] not in after
    assert entries[-1] in after and entries[0] not in after
    assert set(after) <= {*entries, "latest correction", "new fact"}
    data = json.loads(model.requests[1]["messages"][1]["content"])
    assert "selection_entries" not in data
    assert data["removal_options"][0]["result_chars"] == total_chars(after)


@pytest.mark.parametrize("bad_id", [-1, True, 999])
async def test_recovery_option_never_applies_without_valid_model_selection(bad_id):
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            ModelResponse(content='{"groups":[[0],[1],[2]]}'),
            ModelResponse(content=json.dumps({"option_id": bad_id})),
            ModelResponse(content='{"option_id":0,"remove_ranges":[[2,2]]}'),
        ]
    )
    entries = ["a" * 9, "b" * 9]
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        24,
        target_chars=15,
        render_group=lambda rows: rows[0],
    )
    assert result.plan is None and entries == ["a" * 9, "b" * 9]
    data = json.loads(model.requests[1]["messages"][1]["content"])
    assert data["removal_options"][0]["result_chars"] == 15


async def test_recovery_option_still_requires_host_validation():
    from cairnkit.memory_consolidation import consolidate_memory

    def validate(plan):
        if "keep this" not in plan.entries:
            raise MemoryPlanError("Host policy protects this fact", "ungrounded")

    model = ScriptedModel(
        [
            ModelResponse(content='{"groups":[[0],[1],[2]]}'),
            ModelResponse(content='{"option_id":0}'),
            ModelResponse(content='{"option_id":0}'),
        ]
    )
    entries = ["keep this", "b" * 9]
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        24,
        target_chars=15,
        render_group=lambda rows: rows[0],
        validate=validate,
    )
    assert result.plan is None and result.error == "ungrounded"
    assert entries == ["keep this", "b" * 9]


async def test_model_can_decline_the_calculated_removal_option():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            ModelResponse(content='{"groups":[[0],[1],[2]]}'),
            ModelResponse(content='{"option_id":null}'),
            ModelResponse(content='{"option_id":0}'),
        ]
    )
    result = await consolidate_memory(
        model,
        ["a" * 9, "b" * 9],
        [{"action": "add", "content": "new"}],
        24,
        target_chars=15,
        render_group=lambda rows: rows[0],
    )
    assert result.plan is None and result.attempts == 2


async def test_soft_target_feedback_reports_valid_size_without_committing_proposal():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel(
        [
            ModelResponse(content='{"remove_ranges":[[0,0]]}'),
            ModelResponse(content='{"remove_ranges":[[0,1]]}'),
            ModelResponse(content='{"remove_ranges":[[0,1]]}'),
        ]
    )
    result = await consolidate_memory(
        model,
        ["A" * 9, "B" * 9],
        [{"action": "add", "content": "new"}],
        24,
        target_chars=12,
        render_group=lambda rows: "|".join(rows),
    )
    feedback = json.loads(model.requests[1]["messages"][-1]["content"])
    assert feedback["candidate_chars"] == 15
    assert feedback["additional_chars_to_free"] == 3
    assert feedback["previous_selection"] == {"remove_ranges": [[0, 0]]}
    assert feedback["snapshot_unchanged"] is True
    # Deleting the second old entry would overshoot badly: retain the earlier
    # safe candidate even though it is slightly above the soft target.
    assert result.plan.entries == ["B" * 9, "new"]
    assert not result.target_met and result.attempts == 3


async def test_lossless_prepass_fits_without_model_even_above_soft_target():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    result = await consolidate_memory(
        model,
        ["alpha verbose"],
        [{"action": "add", "content": "beta verbose"}],
        20,
        target_chars=5,
        compact_entries=lambda rows: [s.replace(" verbose", "") for s in rows],
    )
    assert result.plan.entries == ["alpha", "beta"]
    assert result.attempts == 0 and not model.requests and not result.target_met
    assert result.precompacted


async def test_lossless_prepass_that_still_overflows_does_not_commit_partial_edits():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content="bad")] * 3)
    entries = ["old verbose"]
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new verbose"}],
        5,
        compact_entries=lambda rows: [s.replace(" verbose", "") for s in rows],
    )
    assert result.plan is None and entries == ["old verbose"] and result.attempts == 3


async def test_lossless_callback_cannot_bypass_host_validation():
    from cairnkit.memory_consolidation import consolidate_memory

    def validate(plan):
        if "old" not in plan.entries or "new" not in plan.entries:
            raise MemoryPlanError("lost fact", "ungrounded")

    with pytest.raises(MemoryPlanError, match="lost fact"):
        await consolidate_memory(
            ScriptedModel([]),
            ["old"],
            [{"action": "add", "content": "new"}],
            5,
            compact_entries=lambda rows: ["new"],
            validate=validate,
        )


async def test_prepass_accepts_duplicate_input_entries_without_repeated_remove():
    from cairnkit.memory_consolidation import consolidate_memory

    result = await consolidate_memory(
        ScriptedModel([]),
        ["old verbose", "old verbose"],
        [{"action": "add", "content": "new verbose"}],
        10,
        compact_entries=lambda rows: [s.replace(" verbose", "") for s in rows],
    )
    assert result.plan.entries == ["old", "new"] and result.attempts == 0


async def test_host_protected_entry_cannot_be_selected_for_removal():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content='{"remove_ranges":[[0,0]]}')] * 3)
    result = await consolidate_memory(
        model,
        ["durable fact", "old detail"],
        [{"action": "add", "content": "new"}],
        25,
        target_chars=20,
        render_group=lambda rows: ";".join(rows),
        protected_entry=lambda text: text == "durable fact",
    )
    assert result.plan is None
    payload = json.loads(model.requests[0]["messages"][1]["content"])
    assert payload["protected_ids"] == [0, 2]


async def test_proven_lower_bound_skips_model_without_mutating_snapshot():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    entries = ["required-old"]
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "required-new"}],
        20,
        target_chars=15,
        minimum_chars=lambda pending: 27,
    )
    assert result.plan is None and result.error == "capacity_unreachable"
    assert result.attempts == 0 and not model.requests and entries == ["required-old"]


async def test_truncated_selection_switches_to_short_option_protocol():
    from cairnkit.memory_consolidation import consolidate_memory

    entries = [f"{i:04}:" + "x" * 17 for i in range(480)]
    model = ScriptedModel(
        [
            ModelResponse(content='{"groups":[[0,1', finish_reason="length"),
            ModelResponse(content='{"option_id":0}'),
        ]
    )
    result = await consolidate_memory(
        model,
        entries,
        [{"action": "add", "content": "new"}],
        12000,
        target_chars=8000,
        render_group=lambda rows: rows[0],
    )
    assert result.plan is not None and result.attempts == 2
    assert "removal_options" in json.loads(model.requests[1]["messages"][1]["content"])


async def test_truncated_selection_without_safe_option_stops_after_one_call():
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([ModelResponse(content='{"groups":[[0', finish_reason="length")] * 3)
    result = await consolidate_memory(
        model,
        ["protected-old"],
        [{"action": "add", "content": "new"}],
        15,
        target_chars=10,
        render_group=lambda r: r[0],
        protected_entry=lambda t: True,
    )
    assert result.plan is None and result.error == "truncated"
    assert result.attempts == 1 and len(model.requests) == 1


def test_selection_rejects_large_id_enumerations():
    from cairnkit.memory_selection import prepare, select_plan

    entries = [str(i) for i in range(40)]
    ops = [{"action": "add", "content": "pending"}]
    working, protected = prepare(entries, ops)
    with pytest.raises(ValueError, match="bounded"):
        select_plan(
            entries,
            ops,
            working,
            protected,
            {"groups": [list(range(17))]},
            1000,
            lambda rows: ",".join(rows),
        )
    with pytest.raises(ValueError, match="bounded"):
        select_plan(
            entries,
            ops,
            working,
            protected,
            {"groups": [[i] for i in range(17)]},
            1000,
            lambda rows: rows[0],
        )


@pytest.mark.parametrize("bound", [-1, True, 1000])
async def test_invalid_host_bound_fails_without_model_call(bound):
    from cairnkit.memory_consolidation import consolidate_memory

    model = ScriptedModel([])
    with pytest.raises(ValueError, match="lower bound"):
        await consolidate_memory(
            model,
            ["old"],
            [{"action": "add", "content": "new"}],
            3,
            minimum_chars=lambda rows: bound,
        )
    assert model.requests == []
