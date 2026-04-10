# ============================================================
# 状態整合性監査モジュール
#
# implementation_ledger.json（単一台帳）を基に、
# レポート内の判定とタスク状態の乖離を検出・修正する。
#
# 1. 実装済みなのに未対応扱いされている項目を検出
# 2. 改善提案から完了済みタスクを除外
# 3. 判定根拠を記録
# 4. レポートに整合性監査セクションを追加
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

LEDGER_FILE = os.path.join(SCRIPT_DIR, "implementation_ledger.json")

# 完了済みとみなすステータス
COMPLETED_STATUSES = {"completed", "completed_improvement_phase", "rejected"}
# 提案から除外すべきステータス
EXCLUDE_FROM_PROPOSALS = {"completed", "completed_improvement_phase", "rejected", "monitoring"}


def _load_ledger():
    if not os.path.exists(LEDGER_FILE):
        return {"tasks": {}}
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"tasks": {}}


def get_task_status(task_key):
    """台帳からタスク状態を取得"""
    ledger = _load_ledger()
    task = ledger.get("tasks", {}).get(task_key)
    if task:
        return task.get("status", "unknown")
    return "unknown"


def is_completed(task_key):
    """タスクが完了済みかどうか"""
    return get_task_status(task_key) in COMPLETED_STATUSES


def should_exclude_from_proposals(task_key):
    """タスクを改善提案から除外すべきか"""
    return get_task_status(task_key) in EXCLUDE_FROM_PROPOSALS


def filter_findings_by_ledger(all_findings):
    """findings から完了済みタスクに関する誤検知を除去・修正する"""
    ledger = _load_ledger()
    tasks = ledger.get("tasks", {})

    # 台帳のタスク名からキーワードマッピング
    completed_keywords = {}
    for key, task in tasks.items():
        if task.get("status") in COMPLETED_STATUSES:
            name = task.get("name", "").lower()
            completed_keywords[key] = {
                "name": name,
                "status": task["status"],
                "keywords": name.split(),
            }

    filtered = []
    corrected = []
    for f in all_findings:
        msg = f.get("message", "").lower()
        ftype = f.get("type", "")

        # suggestion/action の中に完了済みタスクへの言及があるか
        is_false_positive = False

        if ftype in ("suggestion", "action", "critical"):
            for key, info in completed_keywords.items():
                # キーワード一致チェック（2語以上一致で関連と判定）
                match_count = sum(1 for kw in info["keywords"] if len(kw) > 3 and kw in msg)
                if match_count >= 2:
                    # 完了済みタスクなのに問題として報告されている
                    if any(neg in msg for neg in ["not configured", "not set", "missing", "not found",
                                                   "not connected", "not available", "failed", "not yet"]):
                        is_false_positive = True
                        corrected.append({
                            "original_message": f.get("message", "")[:80],
                            "task_key": key,
                            "task_status": info["status"],
                            "action": "suppressed (false positive)",
                        })
                        break

            # rejected タスクの再提案を除外
            if not is_false_positive:
                for key, task in tasks.items():
                    if task.get("status") == "rejected":
                        name = task.get("name", "").lower()
                        reject_keywords = [kw for kw in name.split() if len(kw) > 3]
                        if sum(1 for kw in reject_keywords if kw in msg) >= 2:
                            is_false_positive = True
                            corrected.append({
                                "original_message": f.get("message", "")[:80],
                                "task_key": key,
                                "task_status": "rejected",
                                "action": "suppressed (rejected task)",
                            })
                            break

        if not is_false_positive:
            filtered.append(f)

    return filtered, corrected


def generate_consistency_audit(all_findings):
    """状態整合性監査レポートを生成"""
    result_findings = []
    ledger = _load_ledger()
    tasks = ledger.get("tasks", {})

    # === 1. 台帳サマリ ===
    status_counts = {}
    for task in tasks.values():
        s = task.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    summary_details = ["=== Implementation Ledger Summary ==="]
    for s, count in sorted(status_counts.items()):
        label = ledger.get("status_definitions", {}).get(s, s)
        summary_details.append("%s: %d items — %s" % (s, count, label))

    # === 2. 今日更新されたタスク ===
    today = NOW.strftime("%Y-%m-%d")
    today_updated = [
        (k, t) for k, t in tasks.items()
        if t.get("updated_date") == today
    ]
    if today_updated:
        summary_details.append("")
        summary_details.append("--- Updated today ---")
        for key, task in today_updated:
            summary_details.append("[%s] %s: %s" % (task["status"], task["name"], task.get("verification_detail", "")[:60]))

    # === 3. 判定根拠サマリ ===
    summary_details.append("")
    summary_details.append("--- Verification basis ---")
    verification_types = {}
    for task in tasks.values():
        v = task.get("verification", "unknown")
        verification_types[v] = verification_types.get(v, 0) + 1
    for v, count in sorted(verification_types.items()):
        summary_details.append("%s: %d tasks" % (v, count))

    # === 4. 乖離検出 ===
    # findings 内で完了済みタスクが問題として報告されているか
    _, corrected = filter_findings_by_ledger(all_findings)

    if corrected:
        summary_details.append("")
        summary_details.append("--- False positives detected and suppressed ---")
        for c in corrected:
            summary_details.append(
                "[%s] %s -> %s (task: %s)"
                % (c["task_status"], c["original_message"][:50], c["action"], c["task_key"])
            )

    # === 5. 再発監視 ===
    monitoring = [(k, t) for k, t in tasks.items() if t.get("status") == "monitoring"]
    if monitoring:
        summary_details.append("")
        summary_details.append("--- Under recurrence monitoring ---")
        for key, task in monitoring:
            summary_details.append("[monitoring] %s: %s" % (task["name"], task.get("notes", "")))

    result_findings.append({
        "type": "info",
        "agent": "project-orchestrator",
        "message": "State consistency: %d tasks tracked, %d false positives suppressed" % (
            len(tasks), len(corrected)),
        "details": summary_details,
    })

    return result_findings
