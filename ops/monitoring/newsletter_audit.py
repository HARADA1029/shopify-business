# ============================================================
# Newsletter 監査・PDCA モジュール
#
# Newsletter 導入の計画→実行→分析→改善を定期実行で回す。
#
# 1. 導入状態監査（設置有無/フォーム品質/表示位置）
# 2. 競合リサーチ（他社のNewsletter運用を参考）
# 3. 登録数・開封率・クリック率の追跡
# 4. 配信内容のPDCA（テーマ/頻度/CTA/trust文言）
# 5. Retention効果の測定（再訪率/リピート購入）
# 6. 改善提案の生成
#
# 担当:
#   growth-foundation: 数値分析・効果測定
#   store-setup: Shopify設定・フォーム設置
#   content-strategist: 配信内容企画
#   competitive-intelligence: 競合リサーチ
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

NEWSLETTER_STATE = os.path.join(SCRIPT_DIR, "newsletter_state.json")


def _load_state():
    if not os.path.exists(NEWSLETTER_STATE):
        return {
            "status": "not_implemented",
            "setup": {},
            "subscribers": 0,
            "campaigns": [],
            "competitor_research": [],
            "pdca_history": [],
            "last_updated": "",
        }
    try:
        with open(NEWSLETTER_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"status": "not_implemented", "setup": {}, "subscribers": 0, "campaigns": [], "competitor_research": [], "pdca_history": [], "last_updated": ""}


def _save_state(state):
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(NEWSLETTER_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. 導入状態監査
# ============================================================

def audit_newsletter_setup():
    """Newsletter の設置状況を監査"""
    findings = []
    state = _load_state()

    checks = []
    issues = []

    # Shopify のNewsletter設定を確認
    shopify_token_file = os.path.join(PROJECT_ROOT, ".shopify_token.json")
    has_shopify = os.path.exists(shopify_token_file)

    if state["status"] == "not_implemented":
        issues.append("[NOT IMPLEMENTED] Newsletter signup form not yet added to Shopify")
        issues.append("  Recommended: Shopify built-in customer form or Klaviyo/Mailchimp integration")
        issues.append("  Priority locations: Footer, Homepage popup (delayed), Blog sidebar")
        issues.append("  Value proposition: 'Get notified about new arrivals from Japan'")
    elif state["status"] == "implemented":
        checks.append("Newsletter form: Active")
        checks.append("Subscribers: %d" % state.get("subscribers", 0))
        if state.get("subscribers", 0) < 10:
            issues.append("[LOW] Only %d subscribers — improve form visibility" % state.get("subscribers", 0))
    elif state["status"] == "planned":
        checks.append("Newsletter: Planned (not yet live)")

    # 設置推奨位置
    recommended_placements = [
        {"location": "Footer", "priority": "high", "reason": "Always visible, low friction"},
        {"location": "Homepage banner", "priority": "high", "reason": "First-time visitor capture"},
        {"location": "Blog article end", "priority": "medium", "reason": "Engaged readers most likely to subscribe"},
        {"location": "Product page", "priority": "low", "reason": "After purchase intent, email for follow-up"},
        {"location": "Exit intent popup", "priority": "medium", "reason": "Capture leaving visitors"},
    ]

    if state["status"] != "implemented":
        issues.append("")
        issues.append("--- Recommended Setup ---")
        for p in recommended_placements:
            issues.append("  [%s] %s — %s" % (p["priority"].upper(), p["location"], p["reason"]))

    # 配信内容テンプレート提案
    content_ideas = [
        "New Arrivals: Weekly digest of newly listed Japanese collectibles",
        "Collector Spotlight: Featured rare item with condition details",
        "Category Guide: Monthly deep-dive (Tamagotchi, Pokemon, etc.)",
        "Price Drop Alert: Items with reduced prices",
        "Blog Digest: Latest collector guides and articles",
    ]

    if state["status"] != "implemented":
        issues.append("")
        issues.append("--- Suggested Email Content ---")
        for idea in content_ideas:
            issues.append("  - %s" % idea)

    severity = "action" if state["status"] == "not_implemented" else "info"
    findings.append({
        "type": severity,
        "agent": "store-setup",
        "message": "Newsletter audit: %s (%d subscribers)" % (state["status"], state.get("subscribers", 0)),
        "details": checks + (["--- Issues ---"] + issues if issues else []),
    })

    return findings


# ============================================================
# 2. 競合リサーチ
# ============================================================

def research_competitor_newsletters():
    """競合のNewsletter運用を調査"""
    findings = []
    state = _load_state()

    competitors = [
        {"name": "Solaris Japan", "url": "https://solarisjapan.com", "expected": ["newsletter", "subscribe", "email"]},
        {"name": "Japan Figure", "url": "https://www.japan-figure.com", "expected": ["newsletter", "subscribe", "email", "signup"]},
        {"name": "AmiAmi", "url": "https://www.amiami.com", "expected": ["newsletter", "subscribe", "mail"]},
    ]

    insights = []
    for comp in competitors:
        try:
            resp = requests.get(comp["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200:
                html = resp.text.lower()
                features = {
                    "has_newsletter": any(kw in html for kw in comp["expected"]),
                    "has_popup": "popup" in html or "modal" in html,
                    "has_footer_form": ("footer" in html and any(kw in html for kw in ["email", "subscribe"])),
                    "has_incentive": any(kw in html for kw in ["discount", "coupon", "% off", "free shipping"]),
                }

                active = [k.replace("has_", "") for k, v in features.items() if v]
                insights.append({
                    "name": comp["name"],
                    "features": active,
                    "has_newsletter": features["has_newsletter"],
                })
        except Exception:
            pass

    if insights:
        details = ["=== Competitor Newsletter Research ==="]
        for i in insights:
            details.append("[%s] %s: %s" % (
                "YES" if i["has_newsletter"] else "NO",
                i["name"],
                ", ".join(i["features"]) if i["features"] else "none detected",
            ))

        # 学習ポイント
        with_newsletter = sum(1 for i in insights if i["has_newsletter"])
        with_incentive = sum(1 for i in insights if "incentive" in i.get("features", []))
        details.append("")
        details.append("--- Learnings ---")
        details.append("%d/%d competitors have newsletters" % (with_newsletter, len(insights)))
        if with_incentive > 0:
            details.append("Note: %d use signup incentives (discount/coupon) — consider for our store" % with_incentive)
        else:
            details.append("No signup incentives detected — value-first approach (new arrivals notification) is viable")

        # 弊社向け推奨
        details.append("")
        details.append("--- Recommendation for HD Toys Store Japan ---")
        details.append("Approach: Value-first (not discount-based)")
        details.append("Hook: 'Get notified when rare Japanese collectibles arrive'")
        details.append("Frequency: Weekly (not daily — avoid unsubscribes)")
        details.append("Content: New arrivals + collector guides + rare finds")
        details.append("Trust: Include 'inspected & shipped from Japan' in every email")

        findings.append({
            "type": "info",
            "agent": "competitive-intelligence",
            "message": "Competitor newsletters: %d/%d have newsletters" % (with_newsletter, len(insights)),
            "details": details,
        })

        # state に保存
        state["competitor_research"].append({
            "date": NOW.strftime("%Y-%m-%d"),
            "competitors_checked": len(insights),
            "with_newsletter": with_newsletter,
        })
        state["competitor_research"] = state["competitor_research"][-10:]
        _save_state(state)

    return findings


# ============================================================
# 3. 配信PDCA（実装後）
# ============================================================

def analyze_campaign_performance():
    """配信実績を分析"""
    findings = []
    state = _load_state()
    campaigns = state.get("campaigns", [])

    if not campaigns:
        return findings

    # 直近5件のキャンペーン分析
    recent = campaigns[-5:]
    details = ["=== Newsletter Campaign Performance ==="]

    total_sent = sum(c.get("sent", 0) for c in recent)
    total_opens = sum(c.get("opens", 0) for c in recent)
    total_clicks = sum(c.get("clicks", 0) for c in recent)
    total_shopify = sum(c.get("shopify_visits", 0) for c in recent)

    open_rate = total_opens / max(total_sent, 1) * 100
    click_rate = total_clicks / max(total_opens, 1) * 100
    visit_rate = total_shopify / max(total_clicks, 1) * 100

    details.append("Recent %d campaigns:" % len(recent))
    details.append("  Sent: %d → Opens: %d (%.1f%%) → Clicks: %d (%.1f%%) → Shopify: %d (%.1f%%)" % (
        total_sent, total_opens, open_rate, total_clicks, click_rate, total_shopify, visit_rate))

    # タイプ別比較
    type_stats = {}
    for c in recent:
        ctype = c.get("type", "general")
        if ctype not in type_stats:
            type_stats[ctype] = {"sent": 0, "opens": 0, "clicks": 0}
        type_stats[ctype]["sent"] += c.get("sent", 0)
        type_stats[ctype]["opens"] += c.get("opens", 0)
        type_stats[ctype]["clicks"] += c.get("clicks", 0)

    if len(type_stats) > 1:
        details.append("--- By Type ---")
        for ctype, s in sorted(type_stats.items()):
            or_ = s["opens"] / max(s["sent"], 1) * 100
            details.append("  [%s] open:%.1f%%, click:%.1f%%" % (ctype, or_, s["clicks"] / max(s["opens"], 1) * 100))

    findings.append({
        "type": "info",
        "agent": "growth-foundation",
        "message": "Newsletter PDCA: %.1f%% open, %.1f%% click (%d campaigns)" % (open_rate, click_rate, len(recent)),
        "details": details,
    })

    return findings


# ============================================================
# 4. Retention 効果測定
# ============================================================

def measure_retention_effect():
    """Newsletter の再訪・リピート効果を測定"""
    findings = []
    state = _load_state()

    if state["status"] != "implemented" or state.get("subscribers", 0) == 0:
        return findings

    details = ["=== Newsletter Retention Effect ==="]
    details.append("Subscribers: %d" % state.get("subscribers", 0))

    # 再訪率・リピート購入はGA4データが必要（将来対応）
    details.append("Metrics to track:")
    details.append("  - Return visit rate from email (UTM: utm_source=newsletter)")
    details.append("  - Repeat purchase rate from subscribers")
    details.append("  - Unsubscribe rate per campaign")
    details.append("  - Revenue attributed to newsletter")

    findings.append({
        "type": "info",
        "agent": "growth-foundation",
        "message": "Newsletter retention: %d subscribers, tracking pending" % state.get("subscribers", 0),
        "details": details,
    })

    return findings


# ============================================================
# 5. 改善提案
# ============================================================

def generate_newsletter_improvements():
    """Newsletter の改善提案を生成"""
    findings = []
    state = _load_state()

    if state["status"] == "not_implemented":
        findings.append({
            "type": "action",
            "agent": "store-setup",
            "message": "Newsletter: Implementation needed — high retention opportunity",
            "details": [
                "Step 1: Add email signup form to Shopify footer",
                "Step 2: Create welcome email with store introduction + trust message",
                "Step 3: Set up weekly 'New Arrivals from Japan' automated email",
                "Step 4: Add signup CTA to blog articles",
                "Step 5: Track with UTM: utm_source=newsletter&utm_medium=email",
                "",
                "Value proposition: 'Be the first to know when rare Japanese collectibles arrive'",
                "Trust message: 'Every item inspected & shipped from Japan'",
                "Frequency: Weekly (every Monday)",
            ],
        })

    # PDCAログに記録
    state["pdca_history"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "status": state["status"],
        "subscribers": state.get("subscribers", 0),
        "action": "audit_completed",
    })
    state["pdca_history"] = state["pdca_history"][-30:]
    _save_state(state)

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_newsletter_audit():
    """Newsletter 監査フルスイートを実行"""
    result = []

    # 1. 導入状態監査
    result.extend(audit_newsletter_setup())

    # 2. 競合リサーチ
    result.extend(research_competitor_newsletters())

    # 3. 配信PDCA（実装後のみ）
    result.extend(analyze_campaign_performance())

    # 4. Retention効果
    result.extend(measure_retention_effect())

    # 5. 改善提案
    result.extend(generate_newsletter_improvements())

    return result
