# ============================================================
# エージェント自己学習サマリモジュール
#
# 日次レポートの全 findings を集約し、
# 各エージェントの「本日の再確認結果 / 問題点 / 改善案」を
# 1つのセクションにまとめて出力する。
#
# 各エージェントの実際の情報収集・分析は各モジュールで実施済み。
# このモジュールはそれを「見える化」する役割。
# ============================================================

import json
import os
from collections import defaultdict


AGENT_DESCRIPTIONS = {
    "growth-foundation": "SEO / GA4 / SC / 外部導線",
    "store-setup": "Shopify 設定 / UI / Collection",
    "catalog-migration-planner": "商品データ / eBay連携",
    "fulfillment-ops": "注文 / 在庫",
    "price-auditor": "価格監査",
    "sns-manager": "SNS投稿 / 動画 / 最適化",
    "content-strategist": "記事企画 / 内部リンク / WP",
    "competitive-intelligence": "競合分析 / バズ調査",
    "project-orchestrator": "統括 / タスク追跡",
}


def generate_learning_summary(all_findings):
    """全 findings をエージェント別に集約してサマリを生成する"""
    result_findings = []

    # エージェント別に分類
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

    # サマリを生成
    details = []
    for agent in [
        "growth-foundation", "store-setup", "catalog-migration-planner",
        "fulfillment-ops", "price-auditor", "sns-manager",
        "content-strategist", "competitive-intelligence", "project-orchestrator",
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

    return result_findings
