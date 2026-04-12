# ============================================================
# エージェント負荷監視モジュール
#
# 各エージェントのタスク数・提案数・保留数を計測し、
# 過負荷になる前にアラートを出す。
# ============================================================

import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 各エージェントの設計上のタスク上限
AGENT_CAPACITY = {
    "growth-foundation": {"max_tasks": 15, "description": "SEO / GA4 / SC / 外部導線"},
    "store-setup": {"max_tasks": 12, "description": "Shopify設定 / UI / Collection"},
    "catalog-migration-planner": {"max_tasks": 6, "description": "商品データ / eBay連携"},
    "fulfillment-ops": {"max_tasks": 4, "description": "注文 / 在庫"},
    "price-auditor": {"max_tasks": 4, "description": "価格監査"},
    "sns-manager": {"max_tasks": 15, "description": "SNS投稿 / 動画 / 最適化 / PDCA"},
    "content-strategist": {"max_tasks": 8, "description": "記事企画 / 内部リンク / WP"},
    "competitive-intelligence": {"max_tasks": 5, "description": "競合調査 / 市場リサーチ"},
    "creative-quality-auditor": {"max_tasks": 8, "description": "投稿前品質比較 / 比較スコア管理"},
    "blog-analyst": {"max_tasks": 10, "description": "ブログ分析 / PDCA / 内部リンク"},
    "project-orchestrator": {"max_tasks": 8, "description": "統括 / タスク追跡"},
}


def check_agent_load(all_findings):
    """全 findings からエージェントの負荷を計測しアラートを生成する"""
    result_findings = []

    # エージェント別の findings 数を集計
    agent_counts = Counter()
    agent_issues = Counter()
    agent_actions = Counter()

    for f in all_findings:
        agent = f.get("agent", "unknown")
        agent_counts[agent] += 1
        ftype = f.get("type", "")
        if ftype in ("critical", "suggestion"):
            agent_issues[agent] += 1
        elif ftype == "action":
            agent_actions[agent] += 1

    # 未実装タスクの負荷も加算
    tasks_file = os.path.join(SCRIPT_DIR, "pending_tasks.json")
    pending_by_agent = Counter()
    if os.path.exists(tasks_file):
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                tasks = json.load(f)
            for t in tasks.get("tasks", []):
                if t.get("status") in ("pending", "in_progress"):
                    cat = t.get("category", "").lower()
                    if "sns" in cat:
                        pending_by_agent["sns-manager"] += 1
                    elif "shopify" in cat:
                        pending_by_agent["store-setup"] += 1
                    elif "analytics" in cat or "api" in cat:
                        pending_by_agent["growth-foundation"] += 1
                    else:
                        pending_by_agent["project-orchestrator"] += 1
        except (json.JSONDecodeError, IOError):
            pass

    # 負荷判定
    details = []
    alerts = []

    for agent, config in AGENT_CAPACITY.items():
        max_tasks = config["max_tasks"]
        desc = config["description"]
        current = agent_counts.get(agent, 0)
        pending = pending_by_agent.get(agent, 0)
        total_load = current + pending

        # 負荷率
        load_ratio = total_load / max_tasks if max_tasks > 0 else 0

        if load_ratio > 1.0:
            status = "OVERLOADED"
            alerts.append({
                "agent": agent,
                "status": status,
                "load": total_load,
                "max": max_tasks,
                "ratio": load_ratio,
            })
        elif load_ratio > 0.75:
            status = "WARNING"
            alerts.append({
                "agent": agent,
                "status": status,
                "load": total_load,
                "max": max_tasks,
                "ratio": load_ratio,
            })
        else:
            status = "OK"

        icon = {"OK": "OK", "WARNING": "!!", "OVERLOADED": "XX"}.get(status, "??")
        details.append(
            "[%s] %s (%s): %d/%d tasks (%.0f%%)" % (icon, agent, desc, total_load, max_tasks, load_ratio * 100)
        )

    # アラート
    if alerts:
        overloaded = [a for a in alerts if a["status"] == "OVERLOADED"]
        warnings = [a for a in alerts if a["status"] == "WARNING"]

        if overloaded:
            alert_details = []
            for a in overloaded:
                alert_details.append(
                    "%s: %d/%d tasks (%.0f%%) -> Consider splitting or adding agent" % (
                        a["agent"], a["load"], a["max"], a["ratio"] * 100,
                    )
                )
            result_findings.append({
                "type": "critical", "agent": "project-orchestrator",
                "message": "Agent overload alert: %d agents exceeded capacity" % len(overloaded),
                "details": alert_details,
            })

        if warnings:
            warn_details = []
            for a in warnings:
                warn_details.append(
                    "%s: %d/%d tasks (%.0f%%) -> Monitor closely" % (
                        a["agent"], a["load"], a["max"], a["ratio"] * 100,
                    )
                )
            result_findings.append({
                "type": "suggestion", "agent": "project-orchestrator",
                "message": "Agent load warning: %d agents approaching capacity" % len(warnings),
                "details": warn_details,
            })

    # 前回の負荷データと比較
    load_history_file = os.path.join(SCRIPT_DIR, "agent_load_history.json")
    prev_loads = {}
    if os.path.exists(load_history_file):
        try:
            with open(load_history_file, "r", encoding="utf-8") as f:
                prev_loads = json.load(f).get("loads", {})
        except (json.JSONDecodeError, IOError):
            pass

    # 負荷変化を検出
    changes = []
    current_loads = {}
    for agent in AGENT_CAPACITY:
        current = agent_counts.get(agent, 0) + pending_by_agent.get(agent, 0)
        current_loads[agent] = current
        prev = prev_loads.get(agent, current)
        diff = current - prev
        if diff > 2:
            changes.append("%s: +%d (increased)" % (agent, diff))
        elif diff < -2:
            changes.append("%s: %d (decreased)" % (agent, diff))

    if changes:
        details.append("")
        details.append("Changes from last check:")
        details.extend(["  %s" % c for c in changes])

    # 現在の負荷を保存
    try:
        with open(load_history_file, "w", encoding="utf-8") as f:
            json.dump({"loads": current_loads, "date": NOW.strftime("%Y-%m-%d")}, f)
    except IOError:
        pass

    # 全体サマリ
    result_findings.append({
        "type": "info", "agent": "project-orchestrator",
        "message": "Agent load check: %d agents monitored, %d alerts" % (len(AGENT_CAPACITY), len(alerts)),
        "details": details,
    })

    return result_findings
