# ============================================================
# 横断フィードバックモジュール
#
# 各エージェントの分析結果を横断的に評価し、
# 他エージェントに活かせるフィードバックを生成する。
#
# 入力: 日次レポートの全 findings
# 出力: エージェント間の横断フィードバック + 全体共有メモ
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SHARED_INSIGHTS_FILE = os.path.join(SCRIPT_DIR, "shared_insights.json")


def _load_insights():
    if not os.path.exists(SHARED_INSIGHTS_FILE):
        return {"insights": [], "feedbacks": [], "_last_updated": ""}
    try:
        with open(SHARED_INSIGHTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"insights": [], "feedbacks": [], "_last_updated": ""}


def _save_insights(data):
    data["_last_updated"] = NOW.strftime("%Y-%m-%d %H:%M")
    # 古い知見を30日で削除
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    data["insights"] = [i for i in data.get("insights", []) if i.get("date", "") >= cutoff]
    data["feedbacks"] = [f for f in data.get("feedbacks", []) if f.get("date", "") >= cutoff]
    with open(SHARED_INSIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_cross_feedback(all_findings):
    """全 findings を横断分析し、エージェント間フィードバックを生成する"""
    result_findings = []
    insights_data = _load_insights()
    today = NOW.strftime("%Y-%m-%d")

    new_insights = []
    new_feedbacks = []

    # findings をエージェント別に分類
    by_agent = {}
    for f in all_findings:
        agent = f.get("agent", "unknown")
        if agent not in by_agent:
            by_agent[agent] = []
        by_agent[agent].append(f)

    # === 横断フィードバック生成ルール ===

    # 1. competitive-intelligence → sns-manager
    comp_findings = by_agent.get("competitive-intelligence", [])
    for cf in comp_findings:
        msg = cf.get("message", "")
        details = cf.get("details", [])
        if "improvement ideas" in msg.lower():
            for d in details:
                if any(kw in d.lower() for kw in ["review", "newsletter", "promotion"]):
                    new_feedbacks.append({
                        "date": today,
                        "from": "competitive-intelligence",
                        "to": "sns-manager",
                        "insight": "Competitor uses: %s -> Test in SNS posts" % d[:60],
                    })
                if any(kw in d.lower() for kw in ["trust", "badge", "shipped"]):
                    new_feedbacks.append({
                        "date": today,
                        "from": "competitive-intelligence",
                        "to": "store-setup",
                        "insight": "Competitor trust element: %s -> Add to Shopify" % d[:60],
                    })

    # 2. content-strategist → catalog-migration-planner
    content_findings = by_agent.get("content-strategist", [])
    for cf in content_findings:
        msg = cf.get("message", "")
        if "article ideas" in msg.lower() and "more products than articles" in msg.lower():
            new_feedbacks.append({
                "date": today,
                "from": "content-strategist",
                "to": "catalog-migration-planner",
                "insight": "Categories need more Shopify products to match article demand",
            })

    # 3. sns-manager → content-strategist
    sns_findings = by_agent.get("sns-manager", [])
    for sf in sns_findings:
        msg = sf.get("message", "")
        if "optimization" in msg.lower():
            details = sf.get("details", [])
            for d in details:
                if "under-posted" in d.lower():
                    new_feedbacks.append({
                        "date": today,
                        "from": "sns-manager",
                        "to": "content-strategist",
                        "insight": "%s -> Write articles for these categories to create SNS content" % d[:60],
                    })

    # 4. growth-foundation → store-setup
    growth_findings = by_agent.get("growth-foundation", [])
    for gf in growth_findings:
        msg = gf.get("message", "")
        if "analytics" in msg.lower() and "need attention" in msg.lower():
            new_feedbacks.append({
                "date": today,
                "from": "growth-foundation",
                "to": "store-setup",
                "insight": "Analytics gaps affect all agents. Priority: fix tracking setup",
            })

    # 5. catalog-migration-planner → sns-manager + content-strategist
    catalog_findings = by_agent.get("catalog-migration-planner", [])
    for cf in catalog_findings:
        msg = cf.get("message", "")
        if "shopify expansion" in msg.lower():
            new_insights.append({
                "date": today,
                "source": "catalog-migration-planner",
                "insight": "New Shopify candidates available -> Use for SNS posts and articles",
                "for_agents": ["sns-manager", "content-strategist"],
            })

    # 6. 強いカテゴリ/弱いカテゴリの全体共有
    action_findings = [f for f in all_findings if f.get("type") == "action"]
    for af in action_findings:
        msg = af.get("message", "")
        if "weekly focus" in msg.lower():
            details = af.get("details", [])
            new_insights.append({
                "date": today,
                "source": "growth-foundation",
                "insight": "Weekly focus: %s" % msg,
                "for_agents": ["all"],
            })

    # 保存
    insights_data["insights"].extend(new_insights)
    insights_data["feedbacks"].extend(new_feedbacks)
    _save_insights(insights_data)

    # === レポート用 findings を生成 ===

    # 横断フィードバック
    if new_feedbacks:
        details = []
        for fb in new_feedbacks[:5]:
            details.append(
                "%s -> %s: %s" % (fb["from"], fb["to"], fb["insight"][:60])
            )
        result_findings.append({
            "type": "info", "agent": "project-orchestrator",
            "message": "Cross-agent feedback: %d items shared between agents" % len(new_feedbacks),
            "details": details,
        })

    # 全体共有メモ
    if new_insights:
        details = []
        for ins in new_insights[:3]:
            targets = ", ".join(ins["for_agents"])
            details.append("[-> %s] %s" % (targets, ins["insight"][:60]))
        result_findings.append({
            "type": "info", "agent": "project-orchestrator",
            "message": "Shared insights: %d items for cross-team reference" % len(new_insights),
            "details": details,
        })

    if not new_feedbacks and not new_insights:
        result_findings.append({
            "type": "ok", "agent": "project-orchestrator",
            "message": "Cross-agent feedback: No new cross-team insights today",
        })

    return result_findings
