# ============================================================
# 実験管理モジュール
#
# A/Bテスト・施策実験の登録・追跡・評価を行う。
# 変更対象 / 変更内容 / 測定期間 / 成功条件 / 継続・廃止・昇格
# を記録し、PDCAを回す。
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

EXPERIMENT_FILE = os.path.join(SCRIPT_DIR, "experiment_log.json")


def _load_experiments():
    if not os.path.exists(EXPERIMENT_FILE):
        return {"experiments": [], "completed": []}
    try:
        with open(EXPERIMENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"experiments": [], "completed": []}


def _save_experiments(data):
    data["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(EXPERIMENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def register_experiment(target, change, period_days, success_condition, source_agent=""):
    """新しい実験を登録する"""
    data = _load_experiments()

    exp_id = "EXP-%s-%03d" % (NOW.strftime("%y%m%d"), len(data["experiments"]) + len(data["completed"]) + 1)

    exp = {
        "id": exp_id,
        "target": target,
        "change": change,
        "start_date": NOW.strftime("%Y-%m-%d"),
        "end_date": (NOW + timedelta(days=period_days)).strftime("%Y-%m-%d"),
        "period_days": period_days,
        "success_condition": success_condition,
        "source_agent": source_agent,
        "status": "running",
        "result": None,
        "decision": None,
        "metrics_before": {},
        "metrics_after": {},
    }

    data["experiments"].append(exp)
    _save_experiments(data)
    return exp_id


def check_experiments():
    """実行中の実験を評価して findings を返す"""
    data = _load_experiments()
    findings = []

    active = []
    expiring = []
    expired = []

    for exp in data["experiments"]:
        if exp.get("status") != "running":
            continue

        end_date = exp.get("end_date", "")
        if not end_date:
            continue

        try:
            edate = datetime.strptime(end_date, "%Y-%m-%d")
            days_left = (edate - NOW.replace(tzinfo=None)).days
        except ValueError:
            days_left = 999

        if days_left < 0:
            expired.append(exp)
        elif days_left <= 2:
            expiring.append(exp)
        else:
            active.append(exp)

    # 期限切れの実験をレビュー対象に
    for exp in expired:
        exp["status"] = "review_needed"
        findings.append({
            "type": "action",
            "agent": exp.get("source_agent", "project-orchestrator"),
            "message": "Experiment %s ended: %s → review needed" % (exp["id"], exp["target"][:40]),
            "details": [
                "Change: %s" % exp["change"][:60],
                "Success condition: %s" % exp["success_condition"][:60],
                "Decision needed: continue / abolish / promote",
            ],
        })

    # もうすぐ期限の実験
    for exp in expiring:
        findings.append({
            "type": "info",
            "agent": exp.get("source_agent", "project-orchestrator"),
            "message": "Experiment %s expiring soon: %s" % (exp["id"], exp["target"][:40]),
        })

    # サマリ
    total = len(data["experiments"]) + len(data["completed"])
    details = [
        "Active: %d, Expiring soon: %d, Review needed: %d" % (len(active), len(expiring), len(expired)),
        "Completed: %d" % len(data["completed"]),
    ]

    # 過去の実験結果サマリ
    if data["completed"]:
        promoted = sum(1 for e in data["completed"] if e.get("decision") == "promote")
        abolished = sum(1 for e in data["completed"] if e.get("decision") == "abolish")
        continued = sum(1 for e in data["completed"] if e.get("decision") == "continue")
        details.append(
            "Past results: %d promoted, %d continued, %d abolished"
            % (promoted, continued, abolished)
        )

    findings.append({
        "type": "info",
        "agent": "self-learning",
        "message": "Experiments: %d total (%d active)" % (total, len(active)),
        "details": details,
    })

    _save_experiments(data)
    return findings


def auto_register_experiments(all_findings):
    """findings から実験候補を自動登録する"""
    data = _load_experiments()
    existing_targets = set(e.get("target", "") for e in data["experiments"])
    registered = 0

    for f in all_findings:
        if f.get("type") not in ("suggestion", "action"):
            continue
        msg = f.get("message", "")
        agent = f.get("agent", "")

        # 価格変更提案を実験に
        if "price" in msg.lower() and ("optimize" in msg.lower() or "adjust" in msg.lower()):
            target = "Price optimization: %s" % msg[:60]
            if target not in existing_targets:
                register_experiment(target, msg[:100], 7, "Conversion rate improvement or maintained views", agent)
                registered += 1

        # ページ改善提案を実験に
        if "page" in msg.lower() and "improve" in msg.lower():
            target = "Page improvement: %s" % msg[:60]
            if target not in existing_targets:
                register_experiment(target, msg[:100], 14, "View-to-cart rate improvement", agent)
                registered += 1

    return registered
