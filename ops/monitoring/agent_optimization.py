# ============================================================
# エージェント運用最適化モジュール
#
# 1. Agent Capacity Audit（負荷・利用率・トレンド）
# 2. Work Allocation Audit（担当重複・漏れ）
# 3. Responsibility Gap Detection（未担当・曖昧担当）
# 4. Auto Rebalance Suggestions（再配分提案）
# 5. New Agent Recommendation（新規追加判断）
# 6. Agent ROI / Quality Check（成果効率）
# 7. Rebalance Safety Rules（安全制限）
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

AGENT_STATE = os.path.join(SCRIPT_DIR, "agent_optimization_state.json")

# エージェント容量定義
AGENT_CAPACITY = {
    "growth-foundation": 15,
    "store-setup": 12,
    "catalog-migration-planner": 6,
    "fulfillment-ops": 4,
    "price-auditor": 4,
    "sns-manager": 15,
    "content-strategist": 8,
    "competitive-intelligence": 5,
    "creative-quality-auditor": 8,
    "blog-analyst": 10,
    "project-orchestrator": 8,
    "self-learning": 10,
}

# 責務マッピング（どの仕事がどのエージェントの担当か）
RESPONSIBILITY_MAP = {
    "shopify_product_management": "store-setup",
    "shopify_collection_setup": "store-setup",
    "shopify_policy_pages": "store-setup",
    "shopify_theme_ui": "store-setup",
    "ebay_price_sync": "price-auditor",
    "ebay_image_sync": "catalog-migration-planner",
    "ebay_sales_analysis": "catalog-migration-planner",
    "product_migration": "catalog-migration-planner",
    "ga4_analysis": "growth-foundation",
    "search_console": "growth-foundation",
    "seo_optimization": "growth-foundation",
    "cro_audit": "growth-foundation",
    "blog_auto_post": "content-strategist",
    "blog_quality_audit": "blog-analyst",
    "blog_pdca": "blog-analyst",
    "blog_category_audit": "blog-analyst",
    "sns_auto_post": "sns-manager",
    "sns_video_post": "sns-manager",
    "sns_pdca": "sns-manager",
    "sns_engagement": "sns-manager",
    "competitor_research": "competitive-intelligence",
    "competitor_feature_gap": "competitive-intelligence",
    "content_quality_gate": "creative-quality-auditor",
    "design_comparison": "creative-quality-auditor",
    "product_page_comparison": "creative-quality-auditor",
    "proposal_tracking": "self-learning",
    "experiment_management": "self-learning",
    "safety_audit": "project-orchestrator",
    "daily_maintenance": "project-orchestrator",
    "bug_audit": "project-orchestrator",
    "newsletter_audit": "growth-foundation",
    "order_fulfillment": "fulfillment-ops",
    "inventory_sync": "fulfillment-ops",
}

# 安全制限: 自動変更禁止の責務
PROTECTED_RESPONSIBILITIES = {
    "safety_audit", "daily_maintenance", "proposal_tracking",
    "bug_audit", "experiment_management",
}


def _load_state():
    if os.path.exists(AGENT_STATE):
        try:
            with open(AGENT_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"daily_loads": [], "rebalance_history": [], "last_updated": ""}


def _save_state(state):
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    state["daily_loads"] = state.get("daily_loads", [])[-14:]  # 14日分
    with open(AGENT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _load_json(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ============================================================
# 1. Agent Capacity Audit
# ============================================================

def audit_capacity(all_findings):
    """各エージェントの負荷を監査"""
    details = ["=== Agent Capacity Audit ==="]
    state = _load_state()

    # 現在の負荷を計測
    agent_load = Counter(f.get("agent", "unknown") for f in all_findings)
    today_record = {"date": NOW.strftime("%Y-%m-%d"), "loads": dict(agent_load)}
    state["daily_loads"].append(today_record)

    overloaded = []
    underused = []

    details.append("%-25s | Load | Cap | Util%% | Trend" % "Agent")
    details.append("-" * 65)

    for agent, cap in sorted(AGENT_CAPACITY.items()):
        load = agent_load.get(agent, 0)
        util = load / max(cap, 1) * 100

        # 7日平均
        recent = state.get("daily_loads", [])[-7:]
        avg_7d = sum(d.get("loads", {}).get(agent, 0) for d in recent) / max(len(recent), 1)

        # 3日トレンド
        recent_3 = state.get("daily_loads", [])[-3:]
        if len(recent_3) >= 2:
            first = recent_3[0].get("loads", {}).get(agent, 0)
            last = recent_3[-1].get("loads", {}).get(agent, 0)
            trend = "↑" if last > first else "↓" if last < first else "→"
        else:
            trend = "→"

        warn = ""
        if util > 100:
            warn = " OVERLOAD"
            overloaded.append((agent, load, cap, util))
        elif util < 30 and load > 0:
            underused.append((agent, load, cap, util))

        details.append("%-25s | %4d | %3d | %4.0f%% | %s%.0f%s" % (
            agent, load, cap, util, trend, avg_7d, warn))

    _save_state(state)
    return details, overloaded, underused


# ============================================================
# 2. Work Allocation Audit
# ============================================================

def audit_allocation():
    """担当の重複・漏れを検出"""
    details = ["=== Work Allocation Audit ==="]

    # 逆引き: agent → responsibilities
    agent_tasks = defaultdict(list)
    for task, agent in RESPONSIBILITY_MAP.items():
        agent_tasks[agent].append(task)

    # 集中度チェック
    for agent, tasks in sorted(agent_tasks.items(), key=lambda x: -len(x[1])):
        if len(tasks) > 5:
            details.append("[HEAVY] %s: %d responsibilities" % (agent, len(tasks)))
        else:
            details.append("[OK] %s: %d responsibilities" % (agent, len(tasks)))

    return details


# ============================================================
# 3. Responsibility Gap Detection
# ============================================================

def detect_gaps(all_findings):
    """未担当・曖昧担当を検出"""
    details = ["=== Responsibility Gaps ==="]

    known_agents = set(AGENT_CAPACITY.keys())
    finding_agents = set(f.get("agent", "") for f in all_findings)
    unknown = finding_agents - known_agents - {"", "unknown"}

    if unknown:
        details.append("Unknown agents in findings: %s" % ", ".join(unknown))

    # 担当のない仕事カテゴリを検出
    covered_areas = set(RESPONSIBILITY_MAP.keys())
    potential_gaps = [
        "x_twitter_management",
        "tiktok_management",
        "email_marketing",
        "customer_support_automation",
    ]

    gaps = [g for g in potential_gaps if g not in covered_areas]
    if gaps:
        details.append("Uncovered areas: %s" % ", ".join(gaps))
    else:
        details.append("No responsibility gaps detected")

    return details


# ============================================================
# 4. Auto Rebalance Suggestions
# ============================================================

def suggest_rebalance(overloaded, underused):
    """過負荷・未活用に基づく再配分提案"""
    details = ["=== Rebalance Suggestions ==="]

    if not overloaded and not underused:
        details.append("All agents within normal range — no rebalance needed")
        return details

    for agent, load, cap, util in overloaded:
        details.append("[OVERLOAD] %s: %d/%d (%.0f%%)" % (agent, load, cap, util))
        # 移管候補を探す
        tasks = [t for t, a in RESPONSIBILITY_MAP.items() if a == agent and t not in PROTECTED_RESPONSIBILITIES]
        if tasks and underused:
            target = underused[0]
            details.append("  Suggest: move '%s' → %s (currently %.0f%% utilized)" % (
                tasks[-1], target[0], target[3]))

    for agent, load, cap, util in underused:
        details.append("[UNDERUSED] %s: %d/%d (%.0f%%)" % (agent, load, cap, util))

    return details


# ============================================================
# 5. New Agent Recommendation
# ============================================================

def recommend_new_agent(overloaded, state):
    """新規エージェント追加の判断"""
    details = ["=== New Agent Recommendation ==="]

    if not overloaded:
        details.append("No new agent needed — all within capacity")
        return details

    # 2日以上の過負荷継続をチェック
    for agent, load, cap, util in overloaded:
        recent = state.get("daily_loads", [])[-3:]
        overload_days = sum(1 for d in recent if d.get("loads", {}).get(agent, 0) > cap)

        if overload_days >= 2:
            details.append("[RECOMMEND] %s overloaded %d/3 days — consider splitting responsibilities" % (agent, overload_days))
        else:
            details.append("[MONITOR] %s overloaded today only — watch for pattern" % agent)

    return details


# ============================================================
# 6. Agent ROI / Quality
# ============================================================

def evaluate_agent_roi(all_findings):
    """エージェント別のROI評価"""
    details = ["=== Agent ROI Summary ==="]

    pt = _load_json("proposal_tracking.json")
    if not pt:
        details.append("No proposal data for ROI evaluation")
        return details

    agent_stats = defaultdict(lambda: {"total": 0, "success": 0, "deviation": 0})
    for p in pt.get("proposals", []):
        agent = p.get("agent", "unknown")
        agent_stats[agent]["total"] += 1
        if p.get("result") == "success":
            agent_stats[agent]["success"] += 1

    for f in all_findings:
        if f.get("_deviation_action") in ("hold", "block", "suppress"):
            agent_stats[f.get("agent", "unknown")]["deviation"] += 1

    ranked = sorted(agent_stats.items(), key=lambda x: x[1]["success"] / max(x[1]["total"], 1), reverse=True)

    for agent, s in ranked:
        load = sum(1 for f in all_findings if f.get("agent") == agent)
        cap = AGENT_CAPACITY.get(agent, 10)
        sr = s["success"] / max(s["total"], 1) * 100
        efficiency = "HIGH" if sr >= 70 and load <= cap else "MEDIUM" if sr >= 40 else "LOW"
        details.append("[%s] %s: success:%.0f%% load:%d/%d proposals:%d" % (
            efficiency, agent, sr, load, cap, s["total"]))

    return details


# ============================================================
# メインエントリポイント
# ============================================================

def run_agent_optimization(all_findings):
    """エージェント運用最適化を実行"""
    result = []
    state = _load_state()

    all_details = []

    # 1. Capacity
    cap_details, overloaded, underused = audit_capacity(all_findings)
    all_details.extend(cap_details)

    # 2. Allocation
    all_details.extend(audit_allocation())

    # 3. Gaps
    all_details.extend(detect_gaps(all_findings))

    # 4. Rebalance
    all_details.extend(suggest_rebalance(overloaded, underused))

    # 5. New agent
    all_details.extend(recommend_new_agent(overloaded, state))

    # 6. ROI
    all_details.extend(evaluate_agent_roi(all_findings))

    severity = "suggestion" if overloaded else "info"
    result.append({
        "type": severity,
        "agent": "project-orchestrator",
        "message": "Agent optimization: %d overloaded, %d underused, %d agents total" % (
            len(overloaded), len(underused), len(AGENT_CAPACITY)),
        "details": all_details,
    })

    return result
