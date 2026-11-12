"""Search a small fictional handbook (English and Chinese) and measure how well it works.

    uv run python examples/knowledge.py            # keyword search only, offline
    uv run python examples/knowledge.py --vectors  # + local embeddings (cairnkit[vectors];
                                                   #   downloads a ~220 MB model once)

Prints the retrieval report per kind of question: exact words, other word forms, short
Chinese words, near phrases, other words for the same thing, and questions about things
the handbook does not cover (those should find nothing).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from cairnkit import ToolContext
from cairnkit.knowledge import (
    Case,
    Document,
    KnowledgeBase,
    KnowledgeSearchBackend,
    Scope,
    SQLiteStore,
    evaluate,
    make_chunks,
    report,
)

HANDBOOK_EN = {
    "travel": (
        "Travel policy",
        """# Travel policy
## Booking
Book flights through the travel desk at least two weeks ahead. Economy class for trips
under six hours; premium economy above that.
## Meals
Keep receipts for anything over $50. The daily allowance covers breakfast, lunch and dinner.
## Hotels
Mention any allergy or accessibility needs when the travel desk books your hotel.""",
    ),
    "equipment": (
        "Equipment",
        """# Equipment
## Laptops
Laptops are replaced every three years. Report a lost or stolen laptop to IT within a day.
## Phones
Company phones are for work calls; personal use is fine within reason.""",
    ),
    "leave": (
        "Time off",
        """# Time off
## Annual leave
Everyone gets 25 days of annual leave. Ask your manager two weeks ahead.
## Sick days
Tell your manager before 9am. From the fourth day you need a doctor's note.""",
    ),
}

HANDBOOK_ZH = {
    "baoxiao": (
        "报销制度",
        """# 报销制度
## 餐费
出差期间餐费的报销标准是每天两百元，超过五十元的单笔消费需要保留发票。
## 交通
出差打车可以报销，需要在系统里填写行程和事由。机票请通过行政部统一预订。
## 提交时间
每月五号之前提交上个月的报销单，逾期顺延到下个月处理。""",
    ),
    "xiujia": (
        "休假制度",
        """# 休假制度
## 年假
入职满一年的员工每年有十五天年假，需要提前一周在系统里申请。
## 病假
病假需要当天早上九点前告知直属上级，连续三天以上需要医院证明。
## 婚假
员工结婚可以享受十天婚假，需要提供结婚证复印件。""",
    ),
    "shebei": (
        "设备管理",
        """# 设备管理
## 笔记本电脑
公司配发的笔记本电脑每三年更换一次，丢失或损坏需要在一天内报告信息部。
## 门禁卡
门禁卡遗失请到前台补办，补办费用五十元。""",
    ),
}


def chunk_ids(kb: KnowledgeBase, doc_id: str, heading: str) -> str:
    return next(c.id for c in kb.store.chunks(doc_id) if c.heading_path.endswith(heading))


def build(kb: KnowledgeBase) -> None:
    for collection, docs in (("handbook", HANDBOOK_EN), ("handbook-zh", HANDBOOK_ZH)):
        for doc_id, (title, text) in docs.items():
            # small chunks so these short documents still split along their headings
            kb.add(
                Document(doc_id, collection, title, text), make_chunks(doc_id, text, max_chars=60)
            )


def cases(kb: KnowledgeBase) -> list[Case]:
    def c(query: str, doc: str, heading: str | None, kind: str) -> Case:
        return Case(query, doc, chunk_ids(kb, doc, heading) if heading else None, kind)

    return [
        c("receipts over $50", "travel", "Meals", "exact"),
        c("lost laptop", "equipment", "Laptops", "exact"),
        c("doctor's note", "leave", "Sick days", "exact"),
        c("报销标准", "baoxiao", "餐费", "exact"),
        c("门禁卡", "shebei", "门禁卡", "exact"),
        c("booked flights", "travel", "Booking", "morph"),
        c("allergic", "travel", "Hotels", "morph"),
        c("年假", "xiujia", "年假", "short"),
        c("婚假", "xiujia", "婚假", "short"),
        c("餐费报销标准", "baoxiao", "餐费", "near"),
        c("报销单提交", "baoxiao", "提交时间", "near"),
        c("food costs", "travel", "Meals", "synonym"),
        c("vacation days", "leave", "Annual leave", "synonym"),
        c("computer broken", "equipment", "Laptops", "synonym"),
        c("吃饭的钱怎么报", "baoxiao", "餐费", "synonym"),
        c("结婚放假", "xiujia", "婚假", "synonym"),
        c("电脑坏了", "shebei", "笔记本电脑", "synonym"),
    ]


ABSENT = ["parking permit", "gym membership", "dress code", "停车位", "健身房", "年终奖"]


def main(argv: list[str]) -> int:
    embedder = None
    if "--vectors" in argv:
        from cairnkit.knowledge import FastEmbed

        embedder = FastEmbed()
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(Path(tmp) / "handbook.sqlite3")
        store.ensure_collection("handbook", "en")
        store.ensure_collection("handbook-zh", "zh")
        kb = KnowledgeBase(store, embedder)
        build(kb)
        backend = KnowledgeSearchBackend(kb, lambda ctx: Scope(["handbook", "handbook-zh"]))
        ctx = ToolContext()
        print(f"mode: {kb.mode}, vectors: {store.vector_engine}")
        results = evaluate(backend, ctx, cases(kb))
        print(report(results))
        for r in results:
            if not r["full"]:
                print(f"  missed ({r['kind']}): {r['query']}")
        noise = [q for q in ABSENT if backend.search(q, ctx, 3)]
        print(f"absent topics with hits: {len(noise)}/{len(ABSENT)} {noise}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
