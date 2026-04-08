# ============================================================
# 未実装タスク追跡モジュール
#
# 過去に提案した改善案の実装状況を追跡し、
# 日次レポートに「未実装タスク一覧」を出力する。
#
# タスクの状態: pending / in_progress / on_hold / completed
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TASKS_FILE = os.path.join(SCRIPT_DIR, "pending_tasks.json")


def _load_tasks():
    if not os.path.exists(TASKS_FILE):
        return _initialize_tasks()
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _initialize_tasks()


def _save_tasks(tasks):
    tasks["_last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)


def _initialize_tasks():
    """既知の未実装タスクを初期化する"""
    tasks = {
        "_last_updated": NOW.strftime("%Y-%m-%d"),
        "tasks": [
            {
                "id": "T001",
                "name": "Pinterest API 連携",
                "category": "SNS",
                "priority": "high",
                "status": "on_hold",
                "proposed_date": "2026-04-06",
                "reason": "自動投稿と分析基盤のため必須。サポート返信待ち",
            },
            {
                "id": "T002",
                "name": "Trading Cards Draft 3件の Active 化",
                "category": "Shopify",
                "priority": "high",
                "status": "pending",
                "proposed_date": "2026-04-06",
                "reason": "今週の重点カテゴリの受け皿不足を解消",
            },
            {
                "id": "T003",
                "name": "TikTok API 連携（DNS認証待ち）",
                "category": "SNS",
                "priority": "high",
                "status": "on_hold",
                "proposed_date": "2026-04-07",
                "reason": "動画自動投稿チャネル拡大。DNS伝播待ち",
            },
            {
                "id": "T004",
                "name": "GA4 e-commerce イベント設定",
                "category": "Analytics",
                "priority": "high",
                "status": "pending",
                "proposed_date": "2026-04-07",
                "reason": "view_item/add_to_cart/purchase の計測でCVR改善",
            },
            {
                "id": "T005",
                "name": "Collection SEO 残り2件（ホームページ, Sale）",
                "category": "Shopify",
                "priority": "medium",
                "status": "pending",
                "proposed_date": "2026-04-05",
                "reason": "カテゴリページの検索流入改善",
            },
            {
                "id": "T006",
                "name": "Shipping / Refund policy ページ公開",
                "category": "Shopify",
                "priority": "medium",
                "status": "pending",
                "proposed_date": "2026-04-07",
                "reason": "信頼訴求と購入率改善",
            },
            {
                "id": "T007",
                "name": "Shopify デザイン改善（配色を明るく）",
                "category": "Shopify",
                "priority": "medium",
                "status": "pending",
                "proposed_date": "2026-04-06",
                "reason": "競合比較で暗い印象。CVR改善",
            },
            {
                "id": "T008",
                "name": "Shopify レビュー機能導入（Judge.me等）",
                "category": "Shopify",
                "priority": "medium",
                "status": "pending",
                "proposed_date": "2026-04-06",
                "reason": "競合の大半が導入。信頼性向上",
            },
            {
                "id": "T009",
                "name": "Instagram bio 手動更新",
                "category": "SNS",
                "priority": "low",
                "status": "pending",
                "proposed_date": "2026-04-06",
                "reason": "API制限で手動のみ。現在のbioでも機能している",
            },
            {
                "id": "T010",
                "name": "Draft 8件の Product Type Other 整理",
                "category": "Shopify",
                "priority": "low",
                "status": "pending",
                "proposed_date": "2026-04-05",
                "reason": "Active化するタイミングで個別整理",
            },
        ],
    }
    _save_tasks(tasks)
    return tasks


def auto_update_status(tasks):
    """自動的にタスク状態を更新する（ファイル存在チェック等）"""
    project_root = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

    for task in tasks.get("tasks", []):
        if task["status"] == "completed":
            continue

        # Pinterest API: トークンファイルの存在で判定
        if task["id"] == "T001":
            if os.path.exists(os.path.join(project_root, ".pinterest_token.json")):
                task["status"] = "completed"

        # TikTok API: トークンファイルの存在で判定
        if task["id"] == "T003":
            if os.path.exists(os.path.join(project_root, ".tiktok_token.json")):
                task["status"] = "completed"

        # Instagram bio: API では検出困難なのでそのまま

    return tasks


def generate_task_report():
    """未実装タスク一覧をレポート用の findings として返す"""
    findings = []
    tasks = _load_tasks()
    tasks = auto_update_status(tasks)
    _save_tasks(tasks)

    task_list = tasks.get("tasks", [])

    # 未完了タスクを優先度順にソート
    priority_order = {"high": 0, "medium": 1, "low": 2}
    pending = [
        t for t in task_list
        if t["status"] in ("pending", "in_progress", "on_hold")
    ]
    pending.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    if pending:
        details = []
        for t in pending:
            priority_label = {"high": "高", "medium": "中", "low": "低"}.get(t["priority"], "?")
            status_label = {"pending": "未着手", "in_progress": "進行中", "on_hold": "保留"}.get(t["status"], "?")
            details.append(
                "[%s] %s (%s, %s since %s)" % (
                    priority_label, t["name"], status_label, t["category"], t["proposed_date"],
                )
            )

        findings.append({
            "type": "info", "agent": "project-orchestrator",
            "message": "Pending tasks: %d items (%d high priority)" % (
                len(pending),
                sum(1 for t in pending if t["priority"] == "high"),
            ),
            "details": details,
        })

    # 実施済みタスク（直近7日以内に完了したものを表示）
    completed = [t for t in task_list if t["status"] == "completed"]
    recent_completed = [
        t for t in completed
        if t.get("completed_date", "") >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    ]

    if recent_completed:
        details = []
        for t in sorted(recent_completed, key=lambda x: x.get("completed_date", ""), reverse=True)[:5]:
            details.append(
                "[実施済み] %s (%s, %s完了)" % (t["name"][:50], t["category"], t.get("completed_date", "?"))
            )
        findings.append({
            "type": "ok", "agent": "project-orchestrator",
            "message": "Recently completed: %d tasks in last 7 days (total: %d completed)" % (len(recent_completed), len(completed)),
            "details": details,
        })
    elif completed:
        findings.append({
            "type": "ok", "agent": "project-orchestrator",
            "message": "Completed tasks: %d items (no new completions this week)" % len(completed),
        })

    return findings
