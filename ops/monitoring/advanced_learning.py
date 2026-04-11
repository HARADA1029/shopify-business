# ============================================================
# 高度学習モジュール
#
# 1. Confidence score（信頼度）
# 2. 売上/粗利寄与スコア
# 3. 学習結果の有効期限
# 4. テンプレート/プロンプト version 管理
# 5. Agent別当たり率
# 6. 実装コスト評価
# 7. Franchise/Character 学習
# 8. 不採用理由の学習
# 9. Workflow health score
# 10. Category/Franchise 成功率ランキング
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

LEARNING_STATE = os.path.join(SCRIPT_DIR, "advanced_learning_state.json")

# テンプレートバージョン管理
CURRENT_VERSIONS = {
    "guide_template": "v2.0",       # guide優先化 (2026-04-10)
    "single_review_template": "v2.0", # guide要素移植 (2026-04-10)
    "cta_template": "v3.0",         # trust 3点 + ミニCTA (2026-04-10)
    "trust_copy": "v2.0",           # ship+inspect+condition (2026-04-10)
    "gemini_prompt": "v3.0",        # 構成アウトライン + 1200w必須 (2026-04-10)
}

# 実装コスト定義
EFFORT_MAP = {
    "page_improvement": "low",
    "article_theme": "medium",
    "category_gap": "low",
    "sns_post": "low",
    "internal_link": "low",
    "sales_based": "medium",
    "similar_product": "medium",
    "related_character": "high",
}


def _load_json(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_json(filename, data):
    with open(os.path.join(SCRIPT_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_state():
    if os.path.exists(LEARNING_STATE):
        try:
            with open(LEARNING_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"version_performance": {}, "agent_scores": {}, "franchise_learning": {}, "rejection_reasons": {}, "last_updated": ""}


def _save_state(state):
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(LEARNING_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _days_since(date_str):
    if not date_str:
        return 999
    try:
        return (NOW.replace(tzinfo=None) - datetime.strptime(date_str[:10], "%Y-%m-%d")).days
    except ValueError:
        return 999


# ============================================================
# 1. Confidence Score
# ============================================================

def calculate_confidence(samples, days_observed, success_rate, consistency):
    """信頼度を0-100で算出"""
    # サンプル数 (0-30)
    sample_score = min(samples * 5, 30)
    # 観測日数 (0-20)
    day_score = min(days_observed * 2, 20)
    # 成功率一貫性 (0-30)
    rate_score = success_rate * 30
    # 一貫性 (0-20)
    consistency_score = consistency * 20

    return min(round(sample_score + day_score + rate_score + consistency_score), 100)


def evaluate_confidence(pt_data):
    """全提案タイプの信頼度を評価"""
    details = ["=== Confidence Score by Type ==="]
    accuracy = pt_data.get("summary", {}).get("accuracy_by_type", {})
    confidences = {}

    for ptype, data in sorted(accuracy.items()):
        proposed = data.get("proposed", 0)
        adopted = data.get("adopted", 0)
        success = data.get("success", 0)
        if proposed == 0:
            continue

        success_rate = success / max(adopted, 1)
        # 観測日数を推定（proposalの日付範囲）
        proposals = pt_data.get("proposals", [])
        type_proposals = [p for p in proposals if p.get("type") == ptype]
        dates = [p.get("date", "") for p in type_proposals if p.get("date")]
        days_observed = (_days_since(min(dates)) if dates else 0) if dates else 0
        # 一貫性（直近3件の成功率）
        recent = type_proposals[-3:]
        recent_success = sum(1 for p in recent if p.get("result") == "success")
        consistency = recent_success / max(len(recent), 1)

        conf = calculate_confidence(adopted, days_observed, success_rate, consistency)
        confidences[ptype] = conf

        level = "HIGH" if conf >= 70 else "MED" if conf >= 40 else "LOW"
        details.append("[%s] %s: confidence %d (samples:%d days:%d rate:%.0f%% consistency:%.0f%%)" % (
            level, ptype, conf, adopted, days_observed, success_rate * 100, consistency * 100))

    return details, confidences


# ============================================================
# 2. 売上/粗利寄与スコア
# ============================================================

def evaluate_revenue_contribution(products):
    """カテゴリ/価格帯別の売上寄与ポテンシャル"""
    details = ["=== Revenue Contribution Potential ==="]

    cat_revenue = defaultdict(lambda: {"count": 0, "total_price": 0, "high_value": 0})
    for p in products:
        cat = p.get("product_type", "Other")
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        cat_revenue[cat]["count"] += 1
        cat_revenue[cat]["total_price"] += price
        if price >= 300:
            cat_revenue[cat]["high_value"] += 1

    for cat in sorted(cat_revenue, key=lambda c: -cat_revenue[c]["total_price"]):
        d = cat_revenue[cat]
        avg = d["total_price"] / max(d["count"], 1)
        details.append("[%s] %d items, avg $%.0f, total $%.0f, high-value: %d" % (
            cat, d["count"], avg, d["total_price"], d["high_value"]))

    # 利益重視の提案優先度
    details.append("")
    details.append("Priority: Focus proposals on categories with high avg price + sufficient inventory")

    return details


# ============================================================
# 3. 学習結果の有効期限
# ============================================================

def apply_learning_decay(pt_data):
    """古い学習結果の重みを減衰"""
    details = []
    proposals = pt_data.get("proposals", [])

    fresh = 0    # 7日以内
    aging = 0    # 8-14日
    stale = 0    # 15-30日
    expired = 0  # 30日超

    for p in proposals:
        days = _days_since(p.get("date", ""))
        if days <= 7:
            fresh += 1
        elif days <= 14:
            aging += 1
        elif days <= 30:
            stale += 1
        else:
            expired += 1

    details.append("=== Learning Freshness ===")
    details.append("Fresh (≤7d): %d | Aging (8-14d): %d | Stale (15-30d): %d | Expired (>30d): %d" % (
        fresh, aging, stale, expired))

    if stale + expired > fresh:
        details.append("WARNING: More stale/expired than fresh — learning may be based on outdated data")

    return details


# ============================================================
# 4. Template/Prompt Version 管理
# ============================================================

def track_version_performance(pt_data):
    """各バージョンの成果を追跡"""
    details = ["=== Template Version Performance ==="]
    for name, version in CURRENT_VERSIONS.items():
        details.append("[%s] Current: %s" % (name, version))

    return details


# ============================================================
# 5. Agent別当たり率
# ============================================================

def evaluate_agent_quality(pt_data, all_findings):
    """エージェント別の提案精度を評価"""
    details = ["=== Agent Quality Ranking ==="]
    proposals = pt_data.get("proposals", [])

    agent_stats = defaultdict(lambda: {"proposed": 0, "adopted": 0, "success": 0, "deviation": 0})

    for p in proposals:
        agent = p.get("agent", "unknown")
        agent_stats[agent]["proposed"] += 1
        if p.get("status") == "adopted":
            agent_stats[agent]["adopted"] += 1
        if p.get("result") == "success":
            agent_stats[agent]["success"] += 1

    # deviation count from findings
    for f in all_findings:
        if f.get("_deviation_action") in ("hold", "block", "suppress"):
            agent_stats[f.get("agent", "unknown")]["deviation"] += 1

    ranked = sorted(agent_stats.items(), key=lambda x: x[1]["success"] / max(x[1]["proposed"], 1), reverse=True)

    for agent, s in ranked:
        success_rate = s["success"] / max(s["adopted"], 1) * 100
        dev_rate = s["deviation"] / max(s["proposed"], 1) * 100
        fit_rate = 100 - dev_rate
        details.append("[%s] proposed:%d adopted:%d success:%.0f%% fit:%.0f%% dev:%d" % (
            agent, s["proposed"], s["adopted"], success_rate, fit_rate, s["deviation"]))

    return details


# ============================================================
# 6. 実装コスト評価
# ============================================================

def evaluate_effort(pt_data):
    """提案タイプ別の実装コストと成果の効率"""
    details = ["=== Effort vs Impact ==="]
    accuracy = pt_data.get("summary", {}).get("accuracy_by_type", {})

    for ptype in sorted(accuracy):
        data = accuracy[ptype]
        effort = EFFORT_MAP.get(ptype, "medium")
        success = data.get("success", 0)
        adopted = data.get("adopted", 0)
        rate = success / max(adopted, 1) * 100

        efficiency = "HIGH" if effort == "low" and rate >= 60 else "MED" if rate >= 40 else "LOW"
        details.append("[%s] %s: effort=%s success=%.0f%% → efficiency=%s" % (
            efficiency, ptype, effort, rate, efficiency))

    return details


# ============================================================
# 7. Franchise/Character 学習
# ============================================================

def evaluate_franchise_performance(products, pt_data):
    """フランチャイズ別の成果を評価"""
    details = ["=== Franchise Success Ranking ==="]

    franchise_map = {
        "pokemon": ["pokemon", "pikachu", "charizard", "eevee", "mewtwo", "lugia", "appletun"],
        "vocaloid": ["miku", "hatsune", "vocaloid"],
        "beyblade": ["beyblade", "bey"],
        "tamagotchi": ["tamagotchi"],
        "final_fantasy": ["final fantasy", "ff7", "ff"],
        "jojo": ["jojo", "bizarre adventure", "jolyne"],
        "evangelion": ["evangelion", "eva", "misato"],
        "one_piece": ["one piece", "luffy"],
        "ghibli": ["ghibli", "spirited", "totoro"],
    }

    franchise_stats = {}
    for p in products:
        title = p["title"].lower()
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        for franchise, keywords in franchise_map.items():
            if any(kw in title for kw in keywords):
                if franchise not in franchise_stats:
                    franchise_stats[franchise] = {"count": 0, "total_price": 0}
                franchise_stats[franchise]["count"] += 1
                franchise_stats[franchise]["total_price"] += price
                break

    for f in sorted(franchise_stats, key=lambda x: -franchise_stats[x]["total_price"]):
        s = franchise_stats[f]
        avg = s["total_price"] / max(s["count"], 1)
        details.append("[%s] %d products, avg $%.0f, total $%.0f" % (f, s["count"], avg, s["total_price"]))

    return details


# ============================================================
# 8. 不採用理由の学習
# ============================================================

def analyze_rejection_reasons(pt_data):
    """不採用/hold/suppress/blockの理由を集計"""
    details = ["=== Rejection Reason Summary ==="]
    proposals = pt_data.get("proposals", [])

    reasons = Counter()
    for p in proposals:
        status = p.get("status", "")
        if status in ("expired", "rejected"):
            reasons["expired_no_action"] += 1
        elif p.get("_deviation_action") == "block":
            reasons["blocked_high_deviation"] += 1
        elif p.get("_deviation_action") == "hold":
            reasons["held_deviation"] += 1
        elif p.get("_deviation_action") == "suppress":
            reasons["suppressed_low_fit"] += 1
        elif p.get("result") in ("no_reaction", "failed"):
            reasons["failed_no_impact"] += 1

    if reasons:
        for reason, count in reasons.most_common():
            details.append("[%d] %s" % (count, reason))
        details.append("")
        top = reasons.most_common(1)[0]
        details.append("Top rejection: %s (%d) → reduce similar proposals" % (top[0], top[1]))
    else:
        details.append("No rejections recorded yet")

    return details


# ============================================================
# 9. Workflow Health Score
# ============================================================

def evaluate_workflow_health():
    """ワークフロー全体の健全性スコア"""
    details = ["=== Workflow Health Score ==="]
    scores = {}

    # Token freshness
    tokens = {
        "Shopify": ".shopify_token.json",
        "Instagram": ".instagram_token.json",
        "Pinterest": ".pinterest_token.json",
        "eBay": ".ebay_token.json",
    }
    token_ok = 0
    is_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    for name, f in tokens.items():
        if os.path.exists(os.path.join(PROJECT_ROOT, f)) or is_ci:
            token_ok += 1
    scores["token_freshness"] = round(token_ok / max(len(tokens), 1) * 100)

    # State file freshness
    state_files = ["shared_state.json", "proposal_tracking.json", "blog_state.json", "sns_posted.json"]
    fresh = 0
    for sf in state_files:
        data = _load_json(sf)
        if data:
            updated = data.get("last_updated", data.get("_last_updated", ""))
            if _days_since(updated) <= 2:
                fresh += 1
    scores["state_freshness"] = round(fresh / max(len(state_files), 1) * 100)

    # Overall
    overall = round(sum(scores.values()) / max(len(scores), 1))
    level = "HEALTHY" if overall >= 80 else "CAUTION" if overall >= 50 else "UNHEALTHY"

    details.append("Overall: %d%% (%s)" % (overall, level))
    for k, v in sorted(scores.items()):
        details.append("  %s: %d%%" % (k, v))

    return details, overall


# ============================================================
# 10. Category/Franchise 成功率ランキング
# ============================================================

def rank_categories(pt_data):
    """カテゴリ別成功率ランキング"""
    details = ["=== Category Success Ranking ==="]

    cat_keywords = {
        "Trading Cards": ["card", "tcg", "pokemon card"],
        "Action Figures": ["figure", "figuarts", "beyblade"],
        "Scale Figures": ["scale", "nendoroid", "statue"],
        "Electronic Toys": ["tamagotchi", "electronic", "digivice"],
        "Video Games": ["game", "playstation", "nintendo"],
        "Media & Books": ["manga", "book", "dvd", "cd"],
        "Plush & Soft Toys": ["plush", "stuffed", "doll"],
        "Goods & Accessories": ["goods", "jacket", "poster", "watch"],
    }

    cat_stats = defaultdict(lambda: {"proposed": 0, "success": 0})
    for p in pt_data.get("proposals", []):
        msg = p.get("message", "").lower()
        for cat, kws in cat_keywords.items():
            if any(kw in msg for kw in kws):
                cat_stats[cat]["proposed"] += 1
                if p.get("result") == "success":
                    cat_stats[cat]["success"] += 1
                break

    ranked = sorted(cat_stats.items(), key=lambda x: x[1]["success"] / max(x[1]["proposed"], 1), reverse=True)
    for cat, s in ranked:
        rate = s["success"] / max(s["proposed"], 1) * 100
        details.append("[%.0f%%] %s: %d proposed, %d success" % (rate, cat, s["proposed"], s["success"]))

    return details


# ============================================================
# メインエントリポイント
# ============================================================

def run_advanced_learning(products, all_findings):
    """高度学習分析を実行"""
    result = []
    state = _load_state()
    pt_data = _load_json("proposal_tracking.json") or {"proposals": [], "summary": {}}

    all_details = []

    # 1. Confidence
    conf_details, confidences = evaluate_confidence(pt_data)
    all_details.extend(conf_details)

    # 2. Revenue contribution
    all_details.extend(evaluate_revenue_contribution(products))

    # 3. Learning freshness
    all_details.extend(apply_learning_decay(pt_data))

    # 4. Version tracking
    all_details.extend(track_version_performance(pt_data))

    # 5. Agent quality
    all_details.extend(evaluate_agent_quality(pt_data, all_findings))

    # 6. Effort vs impact
    all_details.extend(evaluate_effort(pt_data))

    # 7. Franchise
    all_details.extend(evaluate_franchise_performance(products, pt_data))

    # 8. Rejection reasons
    all_details.extend(analyze_rejection_reasons(pt_data))

    # 9. Workflow health
    wf_details, wf_score = evaluate_workflow_health()
    all_details.extend(wf_details)

    # 10. Category ranking
    all_details.extend(rank_categories(pt_data))

    result.append({
        "type": "info",
        "agent": "self-learning",
        "message": "Advanced learning: %d types tracked, workflow %d%%, %d proposals" % (
            len(confidences), wf_score, len(pt_data.get("proposals", []))),
        "details": all_details,
    })

    # State保存
    state["confidences"] = confidences
    state["workflow_health"] = wf_score
    state["versions"] = CURRENT_VERSIONS
    _save_state(state)

    return result
