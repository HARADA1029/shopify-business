# ============================================================
# エージェント自己学習サマリモジュール（強化版）
#
# 1. エージェント別活動サマリ
# 2. 提案精度評価（タイプ別成功率）
# 3. 前回比 / 7日比の変化検出
# 4. 実験進捗
# 5. 「何を学習して、次回どう変えたか」の可視化
# ============================================================

import json
import os
import glob
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")


AGENT_DESCRIPTIONS = {
    "growth-foundation": "SEO / GA4 / SC / 外部導線",
    "store-setup": "Shopify 設定 / UI / Collection",
    "catalog-migration-planner": "商品データ / eBay連携",
    "fulfillment-ops": "注文 / 在庫",
    "price-auditor": "価格監査",
    "sns-manager": "SNS投稿 / 動画 / 最適化",
    "content-strategist": "記事企画 / 内部リンク / WP",
    "competitive-intelligence": "競合調査 / 市場リサーチ",
    "creative-quality-auditor": "投稿前品質比較 / 比較スコア管理",
    "project-orchestrator": "統括 / タスク追跡",
    "blog-analyst": "ブログ分析 / 記事PDCA",
    "self-learning": "自己学習 / 提案精度",
}


def _load_past_report(days_ago):
    """N日前のレポートJSONを読み込む"""
    target_date = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    path = os.path.join(REPORTS_DIR, "report_%s.json" % target_date)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _count_by_type(findings):
    """findingsをtype別にカウント"""
    counts = defaultdict(int)
    for f in findings:
        counts[f.get("type", "unknown")] += 1
    return dict(counts)


def _extract_metrics(findings):
    """findingsから主要KPIを抽出"""
    metrics = {
        "active_products": 0,
        "critical_count": 0,
        "suggestion_count": 0,
        "action_count": 0,
    }
    for f in findings:
        msg = f.get("message", "")
        if "Active:" in msg:
            # "Active: 48 / Draft: 8" のようなメッセージからパース
            try:
                active = int(msg.split("Active:")[1].split("/")[0].strip().split()[0])
                metrics["active_products"] = active
            except (ValueError, IndexError):
                pass
        metrics[f.get("type", "unknown") + "_count"] = metrics.get(f.get("type", "unknown") + "_count", 0) + 1

    metrics["critical_count"] = sum(1 for f in findings if f.get("type") == "critical")
    metrics["suggestion_count"] = sum(1 for f in findings if f.get("type") == "suggestion")
    metrics["action_count"] = sum(1 for f in findings if f.get("type") == "action")
    return metrics


def generate_comparison_section(today_findings):
    """前回比 / 7日比の変化を検出"""
    findings = []

    today_metrics = _extract_metrics(today_findings)
    today_counts = _count_by_type(today_findings)

    comparisons = []

    # 前日比
    yesterday = _load_past_report(1)
    if yesterday:
        y_findings = yesterday.get("findings", [])
        y_metrics = _extract_metrics(y_findings)
        y_counts = _count_by_type(y_findings)

        diffs = []
        if today_metrics["active_products"] != y_metrics["active_products"]:
            diff = today_metrics["active_products"] - y_metrics["active_products"]
            diffs.append("Active products: %d → %d (%+d)" % (y_metrics["active_products"], today_metrics["active_products"], diff))
        if today_metrics["critical_count"] != y_metrics["critical_count"]:
            diff = today_metrics["critical_count"] - y_metrics["critical_count"]
            diffs.append("Critical issues: %d → %d (%+d)" % (y_metrics["critical_count"], today_metrics["critical_count"], diff))
        if today_metrics["suggestion_count"] != y_metrics["suggestion_count"]:
            diff = today_metrics["suggestion_count"] - y_metrics["suggestion_count"]
            diffs.append("Suggestions: %d → %d (%+d)" % (y_metrics["suggestion_count"], today_metrics["suggestion_count"], diff))

        if diffs:
            comparisons.append("vs Yesterday:")
            comparisons.extend(["  %s" % d for d in diffs])
        else:
            comparisons.append("vs Yesterday: No significant changes")

    # 7日前比
    week_ago = _load_past_report(7)
    if week_ago:
        w_findings = week_ago.get("findings", [])
        w_metrics = _extract_metrics(w_findings)

        diffs = []
        if today_metrics["active_products"] != w_metrics["active_products"]:
            diff = today_metrics["active_products"] - w_metrics["active_products"]
            diffs.append("Active products: %d → %d (%+d)" % (w_metrics["active_products"], today_metrics["active_products"], diff))
        if today_metrics["critical_count"] != w_metrics["critical_count"]:
            diff = today_metrics["critical_count"] - w_metrics["critical_count"]
            diffs.append("Critical issues: %d → %d (%+d)" % (w_metrics["critical_count"], today_metrics["critical_count"], diff))

        if diffs:
            comparisons.append("vs 7 days ago:")
            comparisons.extend(["  %s" % d for d in diffs])
        else:
            comparisons.append("vs 7 days ago: No significant changes")

    if comparisons:
        findings.append({
            "type": "info",
            "agent": "self-learning",
            "message": "Period comparison: changes detected",
            "details": comparisons,
        })

    return findings


def generate_learning_summary(all_findings):
    """全 findings をエージェント別に集約してサマリを生成する（強化版）"""
    result_findings = []

    # === 1. エージェント別活動サマリ ===
    by_agent = defaultdict(lambda: {"issues": [], "actions": [], "ok": []})

    for f in all_findings:
        agent = f.get("agent", "unknown")
        ftype = f.get("type", "")
        msg = f.get("message", "")

        if ftype in ("critical", "suggestion"):
            by_agent[agent]["issues"].append(msg[:70])
        elif ftype == "action":
            by_agent[agent]["actions"].append(msg[:70])
        elif ftype == "ok":
            by_agent[agent]["ok"].append(msg[:70])

    details = []
    for agent in [
        "growth-foundation", "store-setup", "catalog-migration-planner",
        "fulfillment-ops", "price-auditor", "sns-manager",
        "content-strategist", "competitive-intelligence", "project-orchestrator",
        "blog-analyst", "self-learning",
    ]:
        data = by_agent.get(agent)
        if not data:
            continue

        desc = AGENT_DESCRIPTIONS.get(agent, "")
        issues = len(data["issues"])
        actions = len(data["actions"])
        ok_count = len(data["ok"])

        if issues > 0:
            status = "%d issues, %d actions" % (issues, actions)
        elif actions > 0:
            status = "%d actions, all OK" % actions
        else:
            status = "OK (%d checks passed)" % ok_count

        line = "%s (%s): %s" % (agent, desc, status)
        details.append(line)

    result_findings.append({
        "type": "info", "agent": "project-orchestrator",
        "message": "Agent learning summary: %d agents active" % len(details),
        "details": details,
    })

    # === 2. 前回比 / 7日比 ===
    result_findings.extend(generate_comparison_section(all_findings))

    # === 3. 学習変化の可視化 ===
    # proposal_tracking.json から学習履歴を読む
    tracking_path = os.path.join(SCRIPT_DIR, "proposal_tracking.json")
    if os.path.exists(tracking_path):
        try:
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)
            summary = tracking.get("summary", {})
            total = summary.get("total", 0)
            adopted = summary.get("adopted", 0)
            success = summary.get("success", 0)

            learning_details = [
                "Total proposals tracked: %d" % total,
                "Adopted: %d, Success: %d, Pending: %d" % (adopted, success, summary.get("pending", 0)),
            ]

            # タイプ別精度
            accuracy = summary.get("accuracy_by_type", {})
            for ptype, data in sorted(accuracy.items()):
                if data.get("proposed", 0) > 0:
                    learning_details.append(
                        "  [%s] proposed:%d adopted:%d success:%d"
                        % (ptype, data["proposed"], data.get("adopted", 0), data.get("success", 0))
                    )

            # 重みづけ変化の提案
            if total > 10:
                best_type = max(
                    ((k, v.get("success", 0) / max(v.get("adopted", 1), 1))
                     for k, v in accuracy.items() if v.get("adopted", 0) > 0),
                    key=lambda x: x[1],
                    default=None,
                )
                worst_type = min(
                    ((k, v.get("success", 0) / max(v.get("adopted", 1), 1))
                     for k, v in accuracy.items() if v.get("adopted", 0) > 0),
                    key=lambda x: x[1],
                    default=None,
                )
                if best_type and worst_type and best_type[0] != worst_type[0]:
                    learning_details.append(
                        "Weight adjustment: increase %s (%.0f%% success), decrease %s (%.0f%% success)"
                        % (best_type[0], best_type[1] * 100, worst_type[0], worst_type[1] * 100)
                    )

            result_findings.append({
                "type": "info",
                "agent": "self-learning",
                "message": "Learning history: %d proposals tracked, %d adopted, %d successful" % (total, adopted, success),
                "details": learning_details,
            })
        except (json.JSONDecodeError, IOError):
            pass

    # === 4. 実験進捗 ===
    exp_path = os.path.join(SCRIPT_DIR, "experiment_log.json")
    if os.path.exists(exp_path):
        try:
            with open(exp_path, "r", encoding="utf-8") as f:
                exp_data = json.load(f)
            active_exps = [e for e in exp_data.get("experiments", []) if e.get("status") == "running"]
            completed_exps = exp_data.get("completed", [])
            if active_exps or completed_exps:
                exp_details = ["Active experiments: %d" % len(active_exps)]
                for e in active_exps[:3]:
                    exp_details.append("  [%s] %s (ends %s)" % (e["id"], e["target"][:40], e.get("end_date", "?")))
                if completed_exps:
                    promoted = sum(1 for e in completed_exps if e.get("decision") == "promote")
                    exp_details.append("Completed: %d (%d promoted)" % (len(completed_exps), promoted))
                result_findings.append({
                    "type": "info",
                    "agent": "self-learning",
                    "message": "Experiments: %d active, %d completed" % (len(active_exps), len(completed_exps)),
                    "details": exp_details,
                })
        except (json.JSONDecodeError, IOError):
            pass

    return result_findings
