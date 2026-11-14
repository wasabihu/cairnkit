from cairnkit.memory import MemoryItem, render_snapshot


def test_long_item_does_not_block_shorter_lower_priority_facts():
    text, ids = render_snapshot(
        [MemoryItem("large", "x" * 100), MemoryItem("b", "Short fact")], max_chars=40
    )
    assert ids == ["b"] and "Short fact" in text and len(text) <= 40


def test_limit_counts_selected_items_after_skips_and_deduplication():
    text, ids = render_snapshot(
        [
            MemoryItem("large", "x" * 100),
            MemoryItem("a", "First"),
            MemoryItem("a", "First"),
            MemoryItem("b", "Second"),
            MemoryItem("c", "Third"),
        ],
        max_chars=80,
        max_items=2,
    )
    assert ids == ["a", "b"] and "Third" not in text and len(text) <= 80


def test_tiny_budget_does_not_return_oversized_empty_placeholder():
    text, ids = render_snapshot([], max_chars=2)
    assert len(text) <= 2 and ids == []
