# ============================================================
# リサーチ監査モジュール
#
# 各エージェントのリサーチ活動を記録・監査・評価する。
#
# 1. エージェント別リサーチログ記録
# 2. 事業適合性チェック・スコアリング
# 3. ズレ検知・警告
# 4. リサーチ自己点検
# 5. リサーチ鮮度管理
# 6. レポートセクション生成
#
# 弊社の事業定義:
#   - 日本から海外へ中古フィギュア・おもちゃ・トレカ・ゲーム等を輸出販売
#   - 主要カテゴリ: Action Figures, Scale Figures, Trading Cards,
#     Video Games, Electronic Toys, Media & Books, Plush & Soft Toys,
#     Goods & Accessories
#   - 販売チャネル: Shopify (新規), eBay (既存)
#   - 集客チャネル: ブログ (hd-bodyscience.com), SNS (IG/FB/YT/Pinterest)
#   - 最重要方針: 価値提供ファースト（売ることを急がず価値→信頼→ファン→購入）
#   - 中古販売の特性: コンディション説明、信頼訴求、日本からの発送が差別化要素
# ============================================================

import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
from collections import defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

RESEARCH_LOG_FILE = os.path.join(SCRIPT_DIR, "research_log.json")

# 弊社事業の定義（ズレ検知に使用）
BUSINESS_PROFILE = {
    "core_categories": [
        "Action Figures", "Scale Figures", "Trading Cards",
        "Video Games", "Electronic Toys", "Media & Books",
        "Plush & Soft Toys", "Goods & Accessories",
    ],
    "core_keywords": [
        "figure", "toy", "card", "game", "manga", "anime", "pokemon",
        "dragon ball", "one piece", "naruto", "gundam", "ghibli",
        "tamagotchi", "plush", "collectible", "japanese", "japan",
        "pre-owned", "used", "vintage", "retro", "rare",
    ],
    "channels": ["shopify", "ebay", "blog", "instagram", "facebook", "youtube", "pinterest"],
    "trust_keywords": [
        "condition", "inspected", "authentic", "genuine", "shipped from japan",
        "pre-owned", "carefully", "grading", "original",
    ],
    "value_first_keywords": [
        "collector", "guide", "history", "how to", "tips", "top",
        "rare", "limited", "special", "story", "culture",
    ],
    "sales_push_keywords": [
        "buy now", "limited time", "sale", "discount", "hurry",
        "don't miss", "last chance", "order now", "free shipping",
    ],
    "new_product_keywords": [
        "brand new", "factory sealed", "unopened", "mint in box",
        "just released", "pre-order", "latest release",
    ],
}


# ============================================================
# 1. リサーチログ記録
# ============================================================

def _load_research_log():
    if not os.path.exists(RESEARCH_LOG_FILE):
        return {"entries": [], "last_updated": ""}
    try:
        with open(RESEARCH_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"entries": [], "last_updated": ""}


def _save_research_log(data):
    data["last_updated"] = NOW.strftime("%Y-%m-%d")
    # 直近30日分だけ保持
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    data["entries"] = [e for e in data["entries"] if e.get("date", "") >= cutoff]
    with open(RESEARCH_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_research(agent, researched_what, categories, source, purpose, proposals, relevance_note=""):
    """エージェントのリサーチ活動を記録する"""
    log = _load_research_log()
    entry = {
        "date": NOW.strftime("%Y-%m-%d"),
        "agent": agent,
        "researched": researched_what[:200],
        "categories": categories if isinstance(categories, list) else [categories],
        "source": source,
        "purpose": purpose[:150],
        "proposals_count": proposals if isinstance(proposals, int) else len(proposals),
        "relevance": relevance_note[:150],
        "id": hashlib.md5(("%s:%s:%s" % (NOW.strftime("%Y-%m-%d"), agent, researched_what[:50])).encode()).hexdigest()[:8],
    }
    log["entries"].append(entry)
    _save_research_log(log)
    return entry["id"]


# ============================================================
# 2. 事業適合性チェック
# ============================================================

def check_business_fit(message, agent="", proposal_type=""):
    """提案の事業適合性をスコアリングする (0-10)"""
    msg_lower = message.lower()
    scores = {}

    # (a) ジャンル合致 (0-3)
    cat_match = sum(1 for cat in BUSINESS_PROFILE["core_categories"] if cat.lower() in msg_lower)
    kw_match = sum(1 for kw in BUSINESS_PROFILE["core_keywords"] if kw in msg_lower)
    if cat_match > 0:
        scores["genre_match"] = 3
    elif kw_match >= 2:
        scores["genre_match"] = 2
    elif kw_match == 1:
        scores["genre_match"] = 1
    else:
        scores["genre_match"] = 0

    # (b) 中古販売特性 (0-2)
    trust_match = sum(1 for kw in BUSINESS_PROFILE["trust_keywords"] if kw in msg_lower)
    if trust_match >= 2:
        scores["used_fit"] = 2
    elif trust_match >= 1:
        scores["used_fit"] = 1
    else:
        scores["used_fit"] = 0

    # (c) チャネル効果 (0-2)
    channel_match = sum(1 for ch in BUSINESS_PROFILE["channels"] if ch in msg_lower)
    scores["channel_fit"] = min(channel_match, 2)

    # (d) 価値提供方針 (0-2)
    value_match = sum(1 for kw in BUSINESS_PROFILE["value_first_keywords"] if kw in msg_lower)
    sales_push = sum(1 for kw in BUSINESS_PROFILE["sales_push_keywords"] if kw in msg_lower)
    if value_match >= 2 and sales_push == 0:
        scores["value_first"] = 2
    elif value_match >= 1:
        scores["value_first"] = 1
    elif sales_push > 0:
        scores["value_first"] = 0
    else:
        scores["value_first"] = 1  # ニュートラル

    # (e) ズレ懸念 (減点 0 to -1)
    new_product = sum(1 for kw in BUSINESS_PROFILE["new_product_keywords"] if kw in msg_lower)
    if new_product > 0:
        scores["deviation_penalty"] = -1
    else:
        scores["deviation_penalty"] = 0

    total = sum(scores.values())
    total = max(0, min(10, total))

    return {
        "total_score": total,
        "breakdown": scores,
        "fit_level": "high" if total >= 7 else "medium" if total >= 4 else "low",
    }


# ============================================================
# 3. ズレ検知・警告
# ============================================================

def detect_deviations(findings):
    """全 findings を走査してズレを検知する"""
    warnings = []

    for f in findings:
        msg = f.get("message", "")
        msg_lower = msg.lower()
        agent = f.get("agent", "")
        ftype = f.get("type", "")

        if ftype not in ("action", "suggestion", "medium_term"):
            continue

        issues = []

        # (1) 主要カテゴリから外れている
        has_category = any(cat.lower() in msg_lower for cat in BUSINESS_PROFILE["core_categories"])
        has_keyword = any(kw in msg_lower for kw in BUSINESS_PROFILE["core_keywords"])
        if not has_category and not has_keyword:
            issues.append("off-category: no core category/keyword match")

        # (2) 中古販売の信頼訴求を欠いている
        if ftype == "action" and "product" in msg_lower:
            has_trust = any(kw in msg_lower for kw in BUSINESS_PROFILE["trust_keywords"])
            if not has_trust:
                # 商品関連の提案なのに信頼訴求がない
                details = f.get("details", [])
                details_text = " ".join(str(d) for d in details).lower()
                if not any(kw in details_text for kw in BUSINESS_PROFILE["trust_keywords"]):
                    issues.append("missing-trust: product proposal without trust/condition language")

        # (3) 売り込みが強すぎる
        sales_push = sum(1 for kw in BUSINESS_PROFILE["sales_push_keywords"] if kw in msg_lower)
        if sales_push >= 2:
            issues.append("sales-heavy: %d sales-push keywords detected" % sales_push)

        # (4) 新品系競合のやり方をそのまま持ち込んでいる
        new_product = sum(1 for kw in BUSINESS_PROFILE["new_product_keywords"] if kw in msg_lower)
        if new_product > 0:
            issues.append("new-product-approach: using new-product language for used items")

        # (5) 価値提供より販促寄り
        value_count = sum(1 for kw in BUSINESS_PROFILE["value_first_keywords"] if kw in msg_lower)
        push_count = sum(1 for kw in BUSINESS_PROFILE["sales_push_keywords"] if kw in msg_lower)
        if push_count > value_count and push_count > 0:
            issues.append("promo-over-value: more sales language than value language")

        if issues:
            warnings.append({
                "agent": agent,
                "message": msg[:80],
                "issues": issues,
                "severity": "high" if len(issues) >= 3 else "medium" if len(issues) >= 2 else "low",
            })

    return warnings


# ============================================================
# 4. リサーチ根拠分類
# ============================================================

def classify_research_basis(message, agent=""):
    """提案の根拠を分類する"""
    msg_lower = message.lower()

    if any(kw in msg_lower for kw in ["sold", "sales", "order", "revenue", "purchased", "ebay sold"]):
        return "sales_based"
    if any(kw in msg_lower for kw in ["competitor", "solaris", "japan figure", "competitive"]):
        return "competitor_observation"
    if any(kw in msg_lower for kw in ["similar", "same type", "same category"]):
        return "similar_product"
    if any(kw in msg_lower for kw in ["character", "franchise", "related", "series"]):
        return "franchise_relation"
    if any(kw in msg_lower for kw in ["ga4", "search console", "analytics", "impressions", "clicks"]):
        return "analytics_based"
    if any(kw in msg_lower for kw in ["coverage", "gap", "missing", "under-represented"]):
        return "gap_analysis"
    return "hypothesis"


# ============================================================
# 5. リサーチ鮮度
# ============================================================

def check_research_freshness():
    """リサーチログの鮮度を確認する"""
    log = _load_research_log()
    entries = log.get("entries", [])

    today = NOW.strftime("%Y-%m-%d")
    yesterday = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")

    freshness = {
        "today": [e for e in entries if e.get("date") == today],
        "yesterday": [e for e in entries if e.get("date") == yesterday],
        "older": [e for e in entries if e.get("date", "") < yesterday],
        "stale_agents": [],
    }

    # 各エージェントの最終リサーチ日を確認
    agent_last = {}
    for e in entries:
        agent = e.get("agent", "")
        date = e.get("date", "")
        if agent not in agent_last or date > agent_last[agent]:
            agent_last[agent] = date

    expected_agents = [
        "growth-foundation", "catalog-migration-planner",
        "competitive-intelligence", "content-strategist", "sns-manager",
    ]

    for agent in expected_agents:
        last = agent_last.get(agent, "")
        if not last or last < yesterday:
            freshness["stale_agents"].append(agent)

    return freshness


# ============================================================
# 6. リサーチ自己点検（各エージェント用）
# ============================================================

def generate_self_review(agent, researched, found, fit_reason, deviation_risk, next_improvement):
    """エージェントの自己点検レコードを生成する"""
    return {
        "agent": agent,
        "date": NOW.strftime("%Y-%m-%d"),
        "researched": researched[:100],
        "found": found[:100],
        "fit_reason": fit_reason[:100],
        "deviation_risk": deviation_risk[:100],
        "next_improvement": next_improvement[:100],
    }


# ============================================================
# 7. findings からリサーチ活動を自動抽出・記録
# ============================================================

def auto_extract_research(all_findings):
    """全 findings からリサーチ活動を自動抽出して記録する"""
    # エージェントごとにどのソースで何を調べたかを推定
    agent_research = defaultdict(lambda: {
        "sources": set(),
        "categories": set(),
        "targets": [],
        "proposals": 0,
        "self_review": None,
    })

    for f in all_findings:
        agent = f.get("agent", "unknown")
        msg = f.get("message", "")
        ftype = f.get("type", "")
        details = f.get("details", [])
        msg_lower = msg.lower()

        # ソース推定
        if "ga4" in msg_lower or "analytics" in msg_lower:
            agent_research[agent]["sources"].add("GA4 Analytics")
        if "search console" in msg_lower or "impressions" in msg_lower:
            agent_research[agent]["sources"].add("Search Console")
        if "ebay" in msg_lower:
            agent_research[agent]["sources"].add("eBay API")
        if "shopify" in msg_lower and ("product" in msg_lower or "active" in msg_lower):
            agent_research[agent]["sources"].add("Shopify API")
        if "competitor" in msg_lower or "solaris" in msg_lower:
            agent_research[agent]["sources"].add("Competitor websites")
        if "wordpress" in msg_lower or "article" in msg_lower or "blog" in msg_lower:
            agent_research[agent]["sources"].add("WordPress API")
        if "sns" in msg_lower or "instagram" in msg_lower or "facebook" in msg_lower:
            agent_research[agent]["sources"].add("SNS APIs")

        # カテゴリ推定
        for cat in BUSINESS_PROFILE["core_categories"]:
            if cat.lower() in msg_lower:
                agent_research[agent]["categories"].add(cat)

        # 提案カウント
        if ftype in ("action", "suggestion"):
            agent_research[agent]["proposals"] += 1
            agent_research[agent]["targets"].append(msg[:60])

    # リサーチログに記録
    for agent, data in agent_research.items():
        if not data["sources"] and data["proposals"] == 0:
            continue
        record_research(
            agent=agent,
            researched_what=", ".join(data["targets"][:3]) if data["targets"] else "monitoring checks",
            categories=list(data["categories"]),
            source=", ".join(data["sources"]) if data["sources"] else "internal checks",
            purpose="Daily inspection and improvement proposals",
            proposals=data["proposals"],
            relevance_note="Categories: %s" % ", ".join(list(data["categories"])[:3]) if data["categories"] else "general",
        )

    return agent_research


# ============================================================
# 8. レポートセクション生成
# ============================================================

def generate_research_report(all_findings):
    """リサーチ監査レポートセクションを生成する"""
    result_findings = []

    # === A. リサーチ活動の自動抽出 ===
    agent_research = auto_extract_research(all_findings)

    # === B. エージェント別リサーチサマリ ===
    research_details = []
    research_details.append("=== Agent Research Summary ===")

    agent_order = [
        "growth-foundation", "catalog-migration-planner", "competitive-intelligence",
        "content-strategist", "sns-manager", "store-setup", "price-auditor",
        "blog-analyst", "self-learning",
    ]

    for agent in agent_order:
        data = agent_research.get(agent)
        if not data:
            continue

        sources = ", ".join(data["sources"]) if data["sources"] else "N/A"
        categories = ", ".join(data["categories"]) if data["categories"] else "general"

        research_details.append("[%s]" % agent)
        research_details.append("  Sources: %s" % sources)
        research_details.append("  Categories: %s" % categories)
        research_details.append("  Proposals: %d" % data["proposals"])

        if data["targets"]:
            research_details.append("  Topics: %s" % "; ".join(data["targets"][:2]))

    result_findings.append({
        "type": "info",
        "agent": "project-orchestrator",
        "message": "Research audit: %d agents active, %d sources used" % (
            len([a for a in agent_research.values() if a["sources"]]),
            len(set().union(*(a["sources"] for a in agent_research.values()))),
        ),
        "details": research_details,
    })

    # === C. 事業適合性チェック ===
    fit_results = []
    low_fit_count = 0

    for f in all_findings:
        if f.get("type") not in ("action", "suggestion"):
            continue

        fit = check_business_fit(f["message"], f.get("agent", ""))
        basis = classify_research_basis(f["message"], f.get("agent", ""))

        if fit["fit_level"] == "low":
            low_fit_count += 1
            fit_results.append(
                "[LOW FIT] [%s] [%s] %s (score:%d)"
                % (f.get("agent", ""), basis, f["message"][:50], fit["total_score"])
            )
        elif fit["fit_level"] == "medium":
            fit_results.append(
                "[MED FIT] [%s] [%s] %s (score:%d)"
                % (f.get("agent", ""), basis, f["message"][:50], fit["total_score"])
            )

        # 提案にスコアを付与（他モジュールで使用可能）
        f["_business_fit"] = fit["total_score"]
        f["_research_basis"] = basis

    if fit_results:
        result_findings.append({
            "type": "info" if low_fit_count == 0 else "suggestion",
            "agent": "project-orchestrator",
            "message": "Business fit check: %d low-fit proposals detected" % low_fit_count,
            "details": fit_results[:10],
        })

    # === D. ズレ検知 ===
    deviations = detect_deviations(all_findings)

    if deviations:
        dev_details = []
        high_count = sum(1 for d in deviations if d["severity"] == "high")
        med_count = sum(1 for d in deviations if d["severity"] == "medium")

        for d in deviations[:5]:
            dev_details.append(
                "[%s] [%s] %s → %s"
                % (d["severity"].upper(), d["agent"], d["message"][:40], "; ".join(d["issues"]))
            )

        severity = "critical" if high_count > 0 else "suggestion"
        result_findings.append({
            "type": severity,
            "agent": "project-orchestrator",
            "message": "Deviation check: %d warnings (%d high, %d medium)"
                % (len(deviations), high_count, med_count),
            "details": dev_details,
        })

    # === E. リサーチ鮮度 ===
    freshness = check_research_freshness()
    freshness_details = [
        "Today: %d research entries" % len(freshness["today"]),
        "Yesterday: %d entries" % len(freshness["yesterday"]),
    ]
    if freshness["stale_agents"]:
        freshness_details.append(
            "Stale agents (no research since yesterday): %s"
            % ", ".join(freshness["stale_agents"])
        )

    result_findings.append({
        "type": "info",
        "agent": "project-orchestrator",
        "message": "Research freshness: %d entries today, %d stale agents"
            % (len(freshness["today"]), len(freshness["stale_agents"])),
        "details": freshness_details,
    })

    # === F. リサーチ自己点検 ===
    self_reviews = []
    for agent in agent_order:
        data = agent_research.get(agent)
        if not data or data["proposals"] == 0:
            continue

        # 自動生成の自己点検
        categories = list(data["categories"])
        core_cats = BUSINESS_PROFILE["core_categories"]
        on_target = [c for c in categories if c in core_cats]
        off_target = [c for c in categories if c not in core_cats]

        found = "%d proposals from %s" % (data["proposals"], ", ".join(data["sources"]) if data["sources"] else "internal")
        fit_reason = "Core categories: %s" % ", ".join(on_target) if on_target else "General monitoring (no specific category)"
        deviation = "Off-category: %s" % ", ".join(off_target) if off_target else "None detected"
        improvement = "Expand to under-researched categories" if len(on_target) < 3 else "Maintain breadth"

        self_reviews.append(
            "[%s] Found: %s | Fit: %s | Risk: %s | Next: %s"
            % (agent, found[:40], fit_reason[:40], deviation[:30], improvement[:30])
        )

    if self_reviews:
        result_findings.append({
            "type": "info",
            "agent": "project-orchestrator",
            "message": "Agent self-review: %d agents reported" % len(self_reviews),
            "details": self_reviews,
        })

    return result_findings
