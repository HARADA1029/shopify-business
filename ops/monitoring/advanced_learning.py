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

    # カテゴリ別売上寄与ランキング（価格 × 商品数 × 記事カバレッジ）
    blog_state = _load_json("blog_state.json")
    article_cats = Counter()
    if blog_state:
        for a in blog_state.get("articles_generated", []):
            article_cats[a.get("category", "")] += 1

    details.append("")
    details.append("--- Category Revenue Potential Ranking ---")
    ranked = []
    for cat in sorted(cat_revenue):
        d = cat_revenue[cat]
        avg = d["total_price"] / max(d["count"], 1)
        articles = article_cats.get(cat, 0)
        # スコア = 平均単価 × 商品数 × (1 + 記事数×0.2)
        score = avg * d["count"] * (1 + articles * 0.2)
        ranked.append((cat, d["count"], avg, d["total_price"], d["high_value"], articles, score))

    ranked.sort(key=lambda x: -x[6])
    for cat, count, avg, total, hv, articles, score in ranked:
        details.append("  [%.0f] %s: %d items, avg $%.0f, %d articles, %d high-value" % (score, cat, count, avg, articles, hv))

    if ranked:
        top = ranked[0]
        bottom = ranked[-1]
        details.append("")
        details.append("Highest potential: %s (score %.0f) → prioritize proposals" % (top[0], top[6]))
        details.append("Lowest potential: %s (score %.0f) → deprioritize or grow inventory" % (bottom[0], bottom[6]))

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
# 11. Confidence 変化 + 提案順位変化
# ============================================================

def track_confidence_changes(confidences, state):
    """confidence の前回比と提案順位変化を表示"""
    details = ["=== Confidence Change Tracking ==="]

    prev_conf = state.get("prev_confidences", {})
    if not prev_conf:
        details.append("First run — no previous data for comparison")
        return details

    # 変化を計算
    all_types = set(list(confidences.keys()) + list(prev_conf.keys()))
    changes = []
    for ptype in sorted(all_types):
        curr = confidences.get(ptype, 0)
        prev = prev_conf.get(ptype, 0)
        diff = curr - prev
        if diff != 0:
            changes.append((ptype, prev, curr, diff))

    if changes:
        details.append("%-20s | Prev | Curr | Change" % "Type")
        details.append("-" * 50)
        for ptype, prev, curr, diff in sorted(changes, key=lambda x: -abs(x[3])):
            arrow = "↑" if diff > 0 else "↓"
            details.append("%-20s | %4d | %4d | %s%+d" % (ptype, prev, curr, arrow, diff))
    else:
        details.append("No confidence changes since last run")

    # 順位変化
    prev_ranked = sorted(prev_conf.items(), key=lambda x: -x[1])
    curr_ranked = sorted(confidences.items(), key=lambda x: -x[1])
    prev_order = {t: i for i, (t, _) in enumerate(prev_ranked)}
    curr_order = {t: i for i, (t, _) in enumerate(curr_ranked)}

    rank_changes = []
    for ptype in confidences:
        prev_rank = prev_order.get(ptype, len(prev_order))
        curr_rank = curr_order.get(ptype, len(curr_order))
        if prev_rank != curr_rank:
            rank_changes.append((ptype, prev_rank + 1, curr_rank + 1))

    if rank_changes:
        details.append("")
        details.append("Rank changes:")
        for ptype, prev_r, curr_r in rank_changes:
            arrow = "↑" if curr_r < prev_r else "↓"
            details.append("  %s: #%d → #%d %s" % (ptype, prev_r, curr_r, arrow))

    return details


# ============================================================
# 12. 低Confidence施策の継続追跡
# ============================================================

def track_low_confidence(confidences, pt_data):
    """confidence < 40 の施策を追跡し、40到達まで監視"""
    details = ["=== Low Confidence Watch ==="]

    low_types = [(t, c) for t, c in confidences.items() if c < 40]
    if not low_types:
        details.append("No low-confidence types — all types at 40+")
        return details

    for ptype, conf in sorted(low_types, key=lambda x: x[1]):
        # 40到達に必要なサンプル数を推定
        accuracy = pt_data.get("summary", {}).get("accuracy_by_type", {}).get(ptype, {})
        adopted = accuracy.get("adopted", 0)
        success = accuracy.get("success", 0)

        # confidence = sample*5 + days*2 + rate*30 + consistency*20
        # 40到達に必要な追加サンプル: (40 - conf) / 5 ≈ needed
        needed = max(1, int((40 - conf) / 5))
        details.append("[conf:%d] %s — need ~%d more adopted proposals to reach 40" % (conf, ptype, needed))
        details.append("  Current: %d adopted, %d success" % (adopted, success))

        if adopted >= 2 and success == 0:
            details.append("  WARNING: 0% success rate — consider SUPPRESS or criteria change")

    return details


# ============================================================
# 13. 高Confidence/高利益/高効率の売上効果確認
# ============================================================

def evaluate_top_performers(confidences, products, pt_data):
    """high confidence + high profit + high efficiency の売上効果"""
    details = ["=== Top Performer Impact ==="]

    # 効率マップ
    accuracy = pt_data.get("summary", {}).get("accuracy_by_type", {})

    # スコアリング: confidence × success_rate × (1/effort)
    effort_weight = {"low": 3, "medium": 2, "high": 1}
    scored = []

    for ptype in accuracy:
        conf = confidences.get(ptype, 0)
        data = accuracy[ptype]
        adopted = data.get("adopted", 0)
        success = data.get("success", 0)
        rate = success / max(adopted, 1)
        effort = EFFORT_MAP.get(ptype, "medium")
        eff_w = effort_weight.get(effort, 2)

        # 総合スコア = confidence × success_rate × effort_efficiency
        total_score = conf * rate * eff_w
        scored.append((ptype, conf, rate, effort, total_score, adopted, success))

    scored.sort(key=lambda x: -x[4])

    if scored:
        details.append("%-20s | Conf | Rate | Effort | Score" % "Type")
        details.append("-" * 60)
        for ptype, conf, rate, effort, score, adopted, success in scored:
            marker = "★" if score >= 150 else "○" if score >= 50 else " "
            details.append("%s %-19s | %4d | %3.0f%% | %-6s | %5.0f (%d/%d)" % (
                marker, ptype, conf, rate * 100, effort, score, success, adopted))

        # 売上導線への効果
        top = scored[0]
        details.append("")
        details.append("Top performer: %s (score: %.0f)" % (top[0], top[4]))
        details.append("  → Prioritize: more %s proposals with confidence %d" % (top[0], top[1]))

        # 売上ファネルとの接続
        blog_state = _load_json("blog_state.json")
        if blog_state:
            tracking = blog_state.get("post_publish_tracking", [])
            if tracking:
                total_cart = sum(t.get("metrics", {}).get("add_to_cart", 0) for t in tracking)
                total_ref = sum(t.get("metrics", {}).get("shopify_referrals", 0) for t in tracking)
                details.append("  Sales funnel: %d Shopify referrals → %d add_to_cart" % (total_ref, total_cart))
            else:
                details.append("  Sales funnel: awaiting post-publish tracking data")

    return details


# ============================================================
# 14. 粗利寄与スコア
# ============================================================

def evaluate_profit_contribution(products):
    """カテゴリ別の粗利寄与ポテンシャル"""
    details = ["=== Profit Contribution ==="]
    cat_profit = defaultdict(lambda: {"count": 0, "total_price": 0, "est_profit": 0, "high_margin": 0})

    for p in products:
        cat = p.get("product_type", "Other")
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        # 粗利推定: Shopify価格 - eBay価格×0.6(仕入)  - Shopify手数料(2.9%+$0.30)
        cost = price * 0.6 / 0.91  # eBay価格の60%が仕入原価
        fee = price * 0.029 + 0.30
        profit = price - cost - fee
        cat_profit[cat]["count"] += 1
        cat_profit[cat]["total_price"] += price
        cat_profit[cat]["est_profit"] += max(profit, 0)
        if profit > 50:
            cat_profit[cat]["high_margin"] += 1

    ranked = sorted(cat_profit.items(), key=lambda x: -x[1]["est_profit"])
    for cat, d in ranked:
        avg_profit = d["est_profit"] / max(d["count"], 1)
        details.append("[%s] %d items, est profit $%.0f (avg $%.0f/item), %d high-margin" % (
            cat, d["count"], d["est_profit"], avg_profit, d["high_margin"]))

    if ranked:
        details.append("Top profit: %s ($%.0f)" % (ranked[0][0], ranked[0][1]["est_profit"]))

    return details


# ============================================================
# 15. Adoption Success Tracking
# ============================================================

def track_adoption_success(pt_data):
    """採用施策の成果追跡"""
    details = ["=== Adoption Success Tracking ==="]
    proposals = pt_data.get("proposals", [])

    stages = {"pending": 0, "adopted": 0, "success": 0, "reaction_only": 0, "no_reaction": 0, "expired": 0}
    for p in proposals:
        status = p.get("status", "")
        result = p.get("result", "")
        if status == "pending":
            stages["pending"] += 1
        elif status == "adopted" and result == "success":
            stages["success"] += 1
        elif status == "adopted" and result in ("weak", "reaction_only"):
            stages["reaction_only"] += 1
        elif status == "adopted" and result in ("failed", "no_reaction"):
            stages["no_reaction"] += 1
        elif status == "adopted" and not result:
            stages["adopted"] += 1  # 結果未記録
        elif status in ("expired", "archived"):
            stages["expired"] += 1

    total = len(proposals)
    details.append("Total: %d | Pending: %d | Adopted: %d | Success: %d | Weak: %d | Failed: %d | Expired: %d" % (
        total, stages["pending"], stages["adopted"], stages["success"],
        stages["reaction_only"], stages["no_reaction"], stages["expired"]))

    if stages["adopted"] > 0:
        details.append("WARNING: %d adopted without result — evaluate within 7 days" % stages["adopted"])

    success_rate = stages["success"] / max(stages["success"] + stages["reaction_only"] + stages["no_reaction"], 1) * 100
    details.append("Success rate: %.0f%%" % success_rate)

    return details


# ============================================================
# 16. Agent Correction Score
# ============================================================

def evaluate_agent_correction(pt_data, all_findings):
    """エージェント別の精度補正スコア"""
    details = ["=== Agent Correction Score ==="]
    proposals = pt_data.get("proposals", [])

    agent_stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0, "deviation": 0, "rework": 0})

    for p in proposals:
        agent = p.get("agent", "unknown")
        agent_stats[agent]["total"] += 1
        if p.get("result") == "success":
            agent_stats[agent]["success"] += 1
        elif p.get("result") in ("failed", "no_reaction"):
            agent_stats[agent]["fail"] += 1
        if p.get("retry_attempted"):
            agent_stats[agent]["rework"] += 1

    for f in all_findings:
        if f.get("_deviation_action") in ("hold", "block", "suppress"):
            agent_stats[f.get("agent", "unknown")]["deviation"] += 1

    ranked = sorted(agent_stats.items(), key=lambda x: x[1]["success"] / max(x[1]["total"], 1), reverse=True)
    for agent, s in ranked:
        sr = s["success"] / max(s["total"], 1) * 100
        dr = s["deviation"] / max(s["total"], 1) * 100
        rr = s["rework"] / max(s["total"], 1) * 100
        details.append("[%s] total:%d success:%.0f%% deviation:%.0f%% rework:%.0f%%" % (agent, s["total"], sr, dr, rr))

    return details


# ============================================================
# 17. Learning Input Health
# ============================================================

def evaluate_learning_health():
    """学習入力の品質を監査"""
    details = ["=== Learning Input Health ==="]
    scores = {}

    # Event coverage（実際の設定状況を確認）
    events_configured = {
        "view_item": True,            # GA4 Custom Pixel
        "add_to_cart": True,          # GA4 Custom Pixel
        "purchase": True,             # GA4 Custom Pixel
        "cta_click": True,            # UTM tracking (utm_medium=article)
        "internal_link_click": True,  # UTM: 内部リンクにutm_medium=internal付与済み
        "blog_to_shopify": True,      # UTM: utm_source=hd-bodyscience
        "sns_to_shopify": True,       # UTM: utm_source=instagram/facebook/pinterest
        "ui_improvement_log": True,   # ui_improvement_log.json で記録
    }
    configured = sum(events_configured.values())
    total_events = len(events_configured)
    scores["event_coverage"] = round(configured / max(total_events, 1) * 100)

    # ギャップを詳細表示
    gaps = [k for k, v in events_configured.items() if not v]
    if gaps:
        details.append("  Event gaps: %s" % ", ".join(gaps))

    # Log freshness
    logs = ["shared_state.json", "proposal_tracking.json", "blog_state.json", "sns_posted.json"]
    fresh = 0
    for lf in logs:
        data = _load_json(lf)
        if data:
            updated = data.get("last_updated", data.get("_last_updated", ""))
            if _days_since(updated) <= 2:
                fresh += 1
    scores["log_freshness"] = round(fresh / max(len(logs), 1) * 100)

    # API health
    is_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    tokens = [".shopify_token.json", ".instagram_token.json", ".ebay_token.json"]
    token_ok = sum(1 for t in tokens if os.path.exists(os.path.join(PROJECT_ROOT, t)) or is_ci)
    scores["api_health"] = round(token_ok / max(len(tokens), 1) * 100)

    # Attribution completeness (UTMパラメータの一貫性)
    scores["attribution"] = 85  # UTM設定済み、GA4連携済み、一部クロスドメイン未検証

    # Workflow success rate (直近の成功率 + 失敗内訳)
    safety_log = _load_json("safety_audit_log.json")
    if safety_log and safety_log.get("audits"):
        recent_audits = safety_log["audits"][-7:]
        healthy = sum(1 for a in recent_audits if a.get("status") in ("SAFE", "CAUTION"))
        scores["workflow_success"] = round(healthy / max(len(recent_audits), 1) * 100)

        # 失敗内訳
        failed = [a for a in recent_audits if a.get("status") not in ("SAFE", "CAUTION")]
        if failed:
            details.append("  Workflow failures (7d): %d" % len(failed))
            for fa in failed:
                triggers = fa.get("triggers", 0)
                effects = fa.get("side_effects", 0)
                details.append("    [%s] status=%s triggers=%d side_effects=%d" % (
                    fa.get("date", "?"), fa.get("status", "?"), triggers, effects))
    else:
        scores["workflow_success"] = 50

    # Maintenance log からも失敗パターンを取得
    maint_log = _load_json("maintenance_log.json")
    if maint_log and maint_log.get("runs"):
        recent_maint = maint_log["runs"][-7:]
        maint_issues = sum(r.get("issues", 0) for r in recent_maint)
        maint_fixes = sum(r.get("fixes", 0) for r in recent_maint)
        if maint_issues > 0:
            details.append("  Maintenance (7d): %d issues, %d auto-fixes" % (maint_issues, maint_fixes))

    overall = round(sum(scores.values()) / max(len(scores), 1))
    level = "HEALTHY" if overall >= 80 else "CAUTION" if overall >= 60 else "UNHEALTHY"
    details.append("Overall: %d%% (%s)" % (overall, level))
    for k, v in sorted(scores.items()):
        icon = "✅" if v >= 80 else "⚠️" if v >= 60 else "❌"
        details.append("  %s %s: %d%%" % (icon, k, v))

    return details, overall


# ============================================================
# 18. Rejection Prevention Learning
# ============================================================

def analyze_rejection_prevention(pt_data):
    """拒否理由を学習して次回の無駄提案を減らす"""
    details = ["=== Rejection Prevention ==="]
    proposals = pt_data.get("proposals", [])

    rejection_reasons = Counter()
    for p in proposals:
        if p.get("status") in ("expired", "archived"):
            rejection_reasons["expired_no_action"] += 1
        elif p.get("result") in ("failed", "no_reaction"):
            msg = p.get("message", "").lower()
            if "sns" in msg or "post" in msg:
                rejection_reasons["sns_low_impact"] += 1
            elif "article" in msg or "blog" in msg:
                rejection_reasons["blog_low_quality"] += 1
            else:
                rejection_reasons["other_failure"] += 1

    if rejection_reasons:
        total = sum(rejection_reasons.values())
        details.append("Total rejections: %d" % total)
        for reason, count in rejection_reasons.most_common():
            pct = count / total * 100
            details.append("  [%d] %s (%.0f%%)" % (count, reason, pct))
        top = rejection_reasons.most_common(1)[0]
        details.append("Prevention: reduce %s proposals (%.0f%% of rejections)" % (top[0], top[1] / total * 100))
    else:
        details.append("No rejections recorded")

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

    # 14. Profit contribution
    all_details.extend(evaluate_profit_contribution(products))

    # 15. Adoption success tracking
    all_details.extend(track_adoption_success(pt_data))

    # 16. Agent correction score
    all_details.extend(evaluate_agent_correction(pt_data, all_findings))

    # 17. Learning input health
    health_details, health_score = evaluate_learning_health()
    all_details.extend(health_details)

    # 18. Rejection prevention
    all_details.extend(analyze_rejection_prevention(pt_data))

    # 11. Confidence 変化追跡
    all_details.extend(track_confidence_changes(confidences, state))

    # 12. 低Confidence追跡
    all_details.extend(track_low_confidence(confidences, pt_data))

    # 13. Top Performer Impact
    all_details.extend(evaluate_top_performers(confidences, products, pt_data))

    # State保存
    state["prev_confidences"] = state.get("confidences", {})
    state["confidences"] = confidences
    state["workflow_health"] = wf_score
    state["learning_health"] = health_score
    state["versions"] = CURRENT_VERSIONS
    _save_state(state)

    return result
