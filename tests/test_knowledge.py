"""cairnkit.knowledge: chunking, keyword search (English and Chinese), vectors, scope.

All data is a fictional company handbook. Vectors use a tiny concept embedder, so tests
never download a model.
"""

import json
import re
import sqlite3

import pytest

from cairnkit import ToolContext, make_search_tool
from cairnkit.knowledge import (
    Case,
    Chunk,
    ChunkHit,
    Document,
    KnowledgeBase,
    KnowledgeError,
    KnowledgeSearchBackend,
    Query,
    Scope,
    SQLiteStore,
    chunk_text,
    evaluate,
    make_chunks,
    rrf,
    summarise,
)
from cairnkit.knowledge.query import cjk_plan, english_plan

TRAVEL = """# Travel policy

## Booking
Book flights through the travel desk at least two weeks ahead. Economy class for trips under
six hours.

## Expenses

### Meals
Keep receipts for anything over $50. The daily allowance covers breakfast, lunch and dinner.

### Hotels
Hotels are booked by the travel desk. Mention any allergy or accessibility needs when booking.
"""

EQUIPMENT = """# Equipment
Laptops are replaced every three years. Report a lost laptop to IT within a day."""

REIMBURSE_ZH = """# 报销制度

## 餐费
餐费的报销标准是每天两百元，超过五十元需要保留发票。

## 交通
出差打车可以报销，需要在系统里填写行程。WiFi 费用按实际报销。
"""

LEAVE_ZH = """# 休假制度
年假每年十五天，需要提前一周申请。病假需要医生证明。"""


def small_chunks(doc_id: str, text: str) -> list[Chunk]:
    # tiny limits so these short fictional documents still split along their headings
    return make_chunks(doc_id, text, max_chars=60 if "#" in text and len(text) < 160 else 160)


def store_with_docs(tmp_path, **kwargs) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "kb.sqlite3", **kwargs)
    store.ensure_collection("handbook", "en")
    store.ensure_collection("handbook-zh", "zh")
    return store


def add_all(kb: KnowledgeBase) -> None:
    docs = [
        ("travel", "handbook", "Travel policy", TRAVEL, {"audience": ["staff", "managers"]}),
        ("equipment", "handbook", "Equipment", EQUIPMENT, {"audience": "managers"}),
        ("reimburse", "handbook-zh", "报销制度", REIMBURSE_ZH, {"audience": "staff"}),
        ("leave", "handbook-zh", "休假制度", LEAVE_ZH, {"audience": "staff"}),
    ]
    for doc_id, coll, title, text, meta in docs:
        kb.add(
            Document(doc_id, coll, title, text, updated_at="2026-10-01", metadata=meta),
            small_chunks(doc_id, text),
        )


@pytest.fixture
def kb(tmp_path):
    knowledge = KnowledgeBase(store_with_docs(tmp_path))
    add_all(knowledge)
    return knowledge


def ids(hits):
    return [h.chunk.id for h in hits]


def texts(hits):
    return " | ".join(h.chunk.text for h in hits)


EVERYTHING = Query("", ["handbook", "handbook-zh"])


def q(text, collections=("handbook", "handbook-zh"), **filters):
    return Query(text, list(collections), filters)


# ------------------------------------------------------------------------- chunking


def test_short_text_stays_one_chunk_and_long_text_follows_headings():
    assert chunk_text("One short note.") == [("", "One short note.")]
    pieces = chunk_text(TRAVEL, max_chars=160)
    paths = [p for p, _ in pieces]
    assert "Travel policy > Expenses > Meals" in paths
    assert all(len(t) <= 160 for _, t in pieces)
    meals = next(t for p, t in pieces if p.endswith("Meals"))
    assert meals.startswith("Keep receipts")


def test_long_paragraphs_split_by_sentence_including_chinese():
    text = "# 规定\n" + "。".join(["这是一句很长的规定说明" * 3] * 12) + "。"
    pieces = chunk_text(text, max_chars=100)
    assert len(pieces) > 2 and all(len(t) <= 100 for _, t in pieces)
    assert all(not t.startswith(" ") for _, t in pieces)


# ------------------------------------------------------------------------- query plans


def test_query_plans_quote_words_and_use_prefixes_or_trigrams():
    assert english_plan('allergic cart" OR x')[0].match == '"allergic"* "cart" "or"'
    first, fallback = cjk_plan("餐费报销标准")
    assert first.match == '"餐费报销标准"'
    assert '"餐费报"' in fallback.match and '"销标准"' in fallback.match
    assert cjk_plan("年假 病假")[0].like_all == ("年假", "病假")
    assert english_plan("  ") == []


# ------------------------------------------------------------------------- English


def test_english_exact_word_forms_and_heading_context(kb):
    assert "receipts" in texts(kb.search(q("receipts over $50")))
    # porter stems allergy / allergic differently; the prefix query finds both
    assert "allergy" in texts(kb.search(q("allergic")))
    # the chunk text never says "meal expenses": its heading path does
    assert kb.search(q("meal expenses"))[0].chunk.heading_path.endswith("Meals")


def test_all_words_first_then_any_word(kb):
    hits = kb.search(q("laptop zebra"))
    assert hits and hits[0].document.id == "equipment"
    assert kb.search(q("zebra")) == []


# ------------------------------------------------------------------------- Chinese


def test_chinese_phrase_short_words_and_near_phrases(kb):
    zh = ["handbook-zh"]
    assert "两百元" in texts(kb.search(q("报销标准", zh)))
    assert kb.search(q("年假", zh))[0].document.id == "leave"  # two characters: LIKE
    assert kb.search(q("病假 证明", zh))[0].document.id == "leave"
    # the text says 餐费的报销标准; the trigram fallback still finds it first
    assert kb.search(q("餐费报销标准", zh))[0].chunk.heading_path.endswith("餐费")
    assert kb.search(q("wifi", zh))[0].document.id == "reimburse"  # English inside Chinese
    assert kb.search(q("游泳池", zh)) == []


def test_mixed_language_collections_merge(kb):
    found = {h.document.id for h in kb.search(q("laptop 年假"))}
    assert {"equipment", "leave"} <= found


# ------------------------------------------------------------------------- scope


def test_filters_collections_and_allowed_hide_documents_everywhere(kb):
    staff = Scope(["handbook", "handbook-zh"], {"audience": "staff"})
    backend = KnowledgeSearchBackend(kb, lambda ctx: staff)
    ctx = ToolContext()
    assert backend.search("laptop", ctx, 10) == []
    assert backend.read("equipment", ctx, 10) is None
    assert backend.around("equipment", "equipment#0", ctx, 2) is None
    assert "equipment" not in [h.doc_id for h in backend.browse(ctx, 10)]
    assert [h.doc_id for h in backend.search("receipts", ctx, 10)] == ["travel"]

    no_zh = KnowledgeSearchBackend(
        kb,
        lambda ctx: Scope(["handbook", "handbook-zh"]),
        allowed=lambda doc, ctx: doc.collection != "handbook-zh",
    )
    assert no_zh.search("年假", ctx, 10) == []
    assert kb.search(Query("receipts", [])) == []  # no collection: nothing, never everything


def test_unknown_collection_and_language_mismatch(tmp_path):
    store = store_with_docs(tmp_path)
    with pytest.raises(KnowledgeError):
        store.ensure_collection("handbook", "zh")
    with pytest.raises(KnowledgeError):
        store.upsert(Document("x", "nowhere", "X", "text"))


# ------------------------------------------------------------------------- writing


def test_upsert_replaces_chunks_and_delete_removes_everything(kb):
    kb.add(
        Document(
            "equipment",
            "handbook",
            "Equipment",
            "Tablets only now.",
            version=2,
            metadata={"audience": "managers"},
        )
    )
    assert kb.search(q("laptops")) == [] or kb.search(q("laptops"))[0].document.id != "equipment"
    hit = kb.search(q("tablets"))[0]
    assert hit.document.version == 2 and hit.document.updated_at
    kb.remove("equipment")
    assert kb.store.get("equipment") is None and kb.search(q("tablets")) == []


def test_shared_connection_keeps_the_hosts_row_factory(tmp_path):
    conn = sqlite3.connect(tmp_path / "app.sqlite3")
    conn.row_factory = lambda cursor, row: ("host", row)
    store = SQLiteStore(conn, prefix="kb_")
    store.ensure_collection("handbook")
    kb = KnowledgeBase(store)
    kb.add(Document("travel", "handbook", "Travel policy", TRAVEL))
    assert kb.search(q("receipts", ["handbook"]))
    assert conn.execute("SELECT 1").fetchone() == ("host", (1,))
    assert (
        conn.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'kb_%'").fetchone()[1][0]
        > 0
    )


# ------------------------------------------------------------------------- vectors

CONCEPTS = {
    0: ("meal", "meals", "food", "lunch", "dinner", "breakfast", "餐", "吃饭"),
    1: ("expense", "expenses", "receipt", "receipts", "reimburse", "costs", "报销", "发票", "钱"),
    2: ("laptop", "laptops", "computer", "电脑"),
    3: ("leave", "vacation", "holiday", "休假", "年假", "假期"),
}


class ConceptEmbedder:
    """Counts concept words: a stand-in for a real model's notion of similar meaning."""

    name = "concepts-v1"

    def _vec(self, text: str) -> list[float]:
        words = set(re.findall(r"\w+", text.lower()))
        vec = [0.0] * 5
        for index, terms in CONCEPTS.items():
            vec[index] = float(sum(t in words or (len(t) <= 2 and t in text) for t in terms))
        return vec

    def embed_documents(self, texts):
        return [[*self._vec(t)[:4], 0.05] for t in texts]  # never a zero vector

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture(params=["python", "auto"])
def vkb(tmp_path, request):
    knowledge = KnowledgeBase(store_with_docs(tmp_path, vectors=request.param), ConceptEmbedder())
    add_all(knowledge)
    return knowledge


def test_vectors_find_other_words_for_the_same_thing(vkb):
    assert vkb.store.lexical(q("food costs", ["handbook"])) == []
    hits = vkb.search(q("food costs", ["handbook"]))
    assert hits and hits[0].chunk.heading_path.endswith("Meals")
    assert vkb.search(q("吃饭的钱", ["handbook-zh"]))[0].chunk.heading_path.endswith("餐费")
    assert vkb.search(q("computer"))[0].document.id == "equipment"


def test_hybrid_keeps_keyword_hits_and_drops_weak_vectors(vkb):
    assert vkb.search(q("Economy class"))[0].chunk.heading_path.endswith("Booking")
    assert vkb.search(q("zebra")) == []


def test_python_and_sqlite_vec_rank_the_same(tmp_path):
    pytest.importorskip("sqlite_vec")
    results = []
    for engine in ("python", "sqlite-vec"):
        store = SQLiteStore(tmp_path / f"{engine}.sqlite3", vectors=engine)
        store.ensure_collection("handbook")
        store.ensure_collection("handbook-zh", "zh")
        kb = KnowledgeBase(store, ConceptEmbedder(), mode="vector", min_similarity=0.1)
        add_all(kb)
        assert store.vector_engine == engine
        results.append([ids(kb.search(q(t))) for t in ("food costs", "computer", "假期")])
    assert results[0] == results[1]


def test_reindex_embeds_what_was_added_before_the_embedder(tmp_path):
    store = store_with_docs(tmp_path)
    add_all(KnowledgeBase(store))
    kb = KnowledgeBase(store, ConceptEmbedder())
    assert kb.search(q("food costs", ["handbook"])) == []
    assert kb.reindex() == len(store.missing_vectors("other-model", limit=1000))
    assert kb.search(q("food costs", ["handbook"]))


def test_rrf_rewards_agreement_and_records_where_hits_came_from():
    doc = Document("d", "handbook", "D")

    def hit(x, via):
        return ChunkHit(Chunk(x, "d", 0, "", x), doc, 1.0, "", (via,))

    fused = rrf(
        [[hit("a", "lexical"), hit("b", "lexical")], [hit("b", "vector"), hit("c", "vector")]]
    )
    assert [h.chunk.id for h in fused] == ["b", "a", "c"]
    assert fused[0].via == ("lexical", "vector")


# ------------------------------------------------------------------------- agent tool


def test_tool_expands_around_the_matching_chunk_with_headings(kb):
    tool = make_search_tool(KnowledgeSearchBackend(kb, lambda ctx: Scope(["handbook"])))
    out = json.loads(tool.handler({"query": "receipts"}, ToolContext()))
    top = out["top"]
    assert top["doc_id"] == "travel" and top["around_id"] == out["hits"][0]["item_id"]
    assert any(i["text"].startswith("[Travel policy > Expenses > Meals]") for i in top["items"])


def test_timeline_prefers_the_newest_matching_entry(tmp_path):
    store = SQLiteStore(tmp_path / "t.sqlite3")
    store.ensure_collection("notes")
    kb = KnowledgeBase(store)
    entries = [
        ("2026-01-05", "Prefers afternoon meetings, meeting after two, meeting slots please."),
        ("2026-03-01", "Asked about the range."),
        ("2026-06-20", "Now wants an early meeting."),
    ]
    kb.add(
        Document("p1", "notes", "Pat"),
        [
            Chunk(f"p1#{i}", "p1", i, "", t, when=w, author="sam")
            for i, (w, t) in enumerate(entries)
        ],
    )
    backend = KnowledgeSearchBackend(kb, lambda ctx: Scope(["notes"]), timeline=True)
    assert backend.search("meeting", ToolContext(), 3)[0].item_id == "p1#2"
    assert [i.item_id for i in backend.read("p1", ToolContext(), 2)] == ["p1#2", "p1#1"]


def test_evaluate_reports_per_kind(kb):
    backend = KnowledgeSearchBackend(kb, lambda ctx: Scope(["handbook", "handbook-zh"]))
    meals = next(c.id for c in kb.store.chunks("travel") if c.heading_path.endswith("Meals"))
    results = evaluate(
        backend,
        ToolContext(),
        [
            Case("receipts", "travel", meals, "exact"),
            Case("年假", "leave", kind="zh"),
            Case("food costs", "travel", meals, "synonym"),
        ],
    )
    summary = summarise(results)
    assert summary["exact"]["full"] == 1.0 and summary["zh"]["found"] == 1.0
    assert summary["synonym"]["found"] == 0.0  # keyword search alone cannot do this
    assert summary["all"]["n"] == 3


def test_timeline_vector_hits_never_displace_an_older_keyword_match(tmp_path):
    store = SQLiteStore(tmp_path / "t.sqlite3")
    store.ensure_collection("notes")
    kb = KnowledgeBase(store, ConceptEmbedder())
    entries = [
        ("2026-01-05", "Brings a laptop to every meeting."),
        ("2026-06-20", "Asked for a new computer."),  # newer, similar meaning, other words
    ]
    kb.add(
        Document("p1", "notes", "Pat"),
        [Chunk(f"p1#{i}", "p1", i, "", t, when=w) for i, (w, t) in enumerate(entries)],
    )
    backend = KnowledgeSearchBackend(kb, lambda ctx: Scope(["notes"]), timeline=True)
    assert backend.search("laptop", ToolContext(), 3)[0].item_id == "p1#0"
    assert backend.search("computer", ToolContext(), 3)[0].item_id == "p1#1"
