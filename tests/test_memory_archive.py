import pytest


def facts(n=20):
    from cairnkit.memory_archive import ArchiveFact

    return [ArchiveFact(str(i), f"fact-{i:02}-" + "x" * 12, (i, str(i)), "topic") for i in range(n)]


def summary(items, level):
    return f"{level}:{len(items)} facts"


def test_archive_preserves_keys_and_newest_details_with_headroom():
    from cairnkit.memory_archive import project_archive

    rows = facts()
    view = project_archive(
        rows, limit=140, target=110, recent_count=2, middle_count=4, summarize=summary
    )
    assert {"18", "19"} <= set(view.details)
    assert view.chars <= 110
    assert set(view.details) | {key for s in view.summaries for key in s.keys} == {
        str(i) for i in range(20)
    }
    assert len({k for s in view.summaries for k in s.keys}) == 20 - len(view.details)
    assert len(rows) == 20 and rows[0].text.startswith("fact-00")
    # A later source moves the frontier; rebuilding summaries never refreshes old facts.
    newer = project_archive(
        facts(21), limit=140, target=110, recent_count=2, middle_count=4, summarize=summary
    )
    assert "20" in newer.details and "0" not in newer.details


def test_durable_and_unknown_origins_remain_detailed():
    from cairnkit.memory_archive import ArchiveFact, project_archive

    rows = facts() + [
        ArchiveFact("job", "current occupation", (-1, "job"), "job", True),
        ArchiveFact("unknown", "unknown origin", None, "t"),
    ]
    view = project_archive(
        rows, limit=200, target=170, recent_count=2, middle_count=4, summarize=summary
    )
    assert {"job", "unknown", "18", "19"} <= set(view.details)


def test_unfit_mandatory_details_fail_without_discarding_facts():
    from cairnkit.memory_archive import project_archive
    from cairnkit.memory_ops import MemoryPlanError

    rows = facts()
    with pytest.raises(MemoryPlanError, match="mandatory"):
        project_archive(
            rows, limit=30, target=20, recent_count=2, middle_count=4, summarize=summary
        )
    assert len(rows) == 20


def test_small_inventory_needs_no_summary_and_bad_summary_is_rejected():
    from cairnkit.memory_archive import project_archive

    def forbidden(*args):
        raise AssertionError("small inventory must not summarize")

    assert (
        project_archive(
            facts(2), limit=100, target=70, recent_count=2, middle_count=4, summarize=forbidden
        ).summaries
        == ()
    )
    with pytest.raises(ValueError, match="summary"):
        project_archive(
            facts(),
            limit=140,
            target=110,
            recent_count=2,
            middle_count=4,
            summarize=lambda *args: "",
        )


@pytest.mark.parametrize("count", [301, 1021, 3000])
def test_large_projection_accounting_and_exact_partition(count):
    from cairnkit.memory_archive import ArchiveFact, project_archive
    from cairnkit.memory_ops import total_chars

    rows = [
        ArchiveFact(str(i), f"Fact {i:04} " + "x" * 10, (i, str(i)), str(i % 15))
        for i in range(count)
    ]
    view = project_archive(
        rows, limit=6000, target=4500, recent_count=100, middle_count=300, summarize=summary
    )
    by_key = {f.key: f.text for f in rows}
    assert (
        total_chars([by_key[k] for k in view.details] + [s.text for s in view.summaries])
        == view.chars
    )
    keys = list(view.details) + [k for s in view.summaries for k in s.keys]
    assert len(keys) == len(set(keys)) == count
    assert set(keys) == set(by_key)
    assert {str(i) for i in range(count - 100, count)} <= set(view.details)
    assert view.chars <= 4500
