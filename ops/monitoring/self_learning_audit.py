# ============================================================
# 自己学習機能監査モジュール
#
# 自己学習機能自体を毎回の定期実行で点検し、
# 不足する設定・API・ログ・追跡・精度評価を検出して
# 改善提案としてレポートに上げる。
#
# 「自己学習機能がある」ではなく
# 「自己学習に必要なデータ・ログ・API・履歴・結果反映が十分か」
# を毎回判定する。
#
# 担当:
#   project-orchestrator: 統括
#   growth-foundation: 分析データ取得監査
#   competitive-intelligence: 参考事例リサーチ
#   store-setup: Shopify/WP 反映ログ監査
#   sns-manager: SNS分析データ監査
#   catalog-migration-planner: 商品追加後追跡監査
#   price-auditor: 価格同期履歴監査
#   blog-analyst: ブログPDCA学習ログ監査
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


def _load_json(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _token_exists(filename):
    return os.path.exists(os.path.join(PROJECT_ROOT, filename))


def _days_since(date_str):
    if not date_str:
        return 999
    try:
        return (NOW.replace(tzinfo=None) - datetime.strptime(date_str[:10], "%Y-%m-%d")).days
    except ValueError:
        return 999


# ============================================================
# 1. 自己学習機能 構成監査
# ============================================================

def _audit_learning_components():
    """自己学習の各コンポーネントが正常動作しているか点検"""
    checks = []  # (name, status, detail, agent)
    issues = []  # 改善提案用

    # --- proposal_tracking ---
    pt = _load_json("proposal_tracking.json")
    if pt:
        proposals = pt.get("proposals", [])
        total = len(proposals)
        adopted = sum(1 for p in proposals if p.get("status") == "adopted")
        with_result = sum(1 for p in proposals if p.get("result"))
        with_next = sum(1 for p in proposals if p.get("next_action"))

        if total >= 5 and with_result >= 3:
            checks.append(("proposal_tracking", "ok", "%d proposals, %d with results" % (total, with_result), "self-learning"))
        elif total > 0:
            checks.append(("proposal_tracking", "partial", "%d proposals, %d with results (need more)" % (total, with_result), "self-learning"))
            if with_result < adopted:
                issues.append({
                    "component": "proposal_tracking", "issue": "Adopted proposals missing result records",
                    "detail": "%d adopted but only %d have result evaluation" % (adopted, with_result),
                    "impact": "Cannot calculate proposal accuracy by type",
                    "fix": "Run evaluate_proposals() with product/article data after 7 days",
                    "priority": "high", "agent": "self-learning",
                })
            if with_next < with_result:
                issues.append({
                    "component": "proposal_tracking", "issue": "Results missing next_action reflection",
                    "detail": "%d results but only %d have next_action" % (with_result, with_next),
                    "impact": "Learning loop incomplete: results not feeding into next proposals",
                    "fix": "Add next_action when evaluating results",
                    "priority": "medium", "agent": "self-learning",
                })
        else:
            checks.append(("proposal_tracking", "missing", "File exists but empty", "self-learning"))
            issues.append({
                "component": "proposal_tracking", "issue": "No proposals tracked",
                "detail": "proposal_tracking.json has 0 entries",
                "impact": "Entire proposal accuracy system non-functional",
                "fix": "Run daily_inspection to auto-generate proposals",
                "priority": "critical", "agent": "self-learning",
            })

        # 精度評価チェック
        accuracy = pt.get("summary", {}).get("accuracy_by_type", {})
        types_with_data = sum(1 for v in accuracy.values() if v.get("proposed", 0) > 0)
        if types_with_data < 3:
            issues.append({
                "component": "proposal_tracking", "issue": "Accuracy evaluation covers too few types",
                "detail": "Only %d proposal types have data (need 3+)" % types_with_data,
                "impact": "Cannot compare proposal type effectiveness",
                "fix": "Continue daily runs to accumulate diverse proposals",
                "priority": "medium", "agent": "self-learning",
            })
    else:
        checks.append(("proposal_tracking", "missing", "File not found", "self-learning"))
        issues.append({
            "component": "proposal_tracking", "issue": "proposal_tracking.json missing",
            "detail": "Core learning file does not exist",
            "impact": "No proposal tracking, accuracy, or learning possible",
            "fix": "File auto-created on next daily_inspection run",
            "priority": "critical", "agent": "self-learning",
        })

    # --- experiments ---
    exp = _load_json("experiment_log.json")
    if exp:
        active = [e for e in exp.get("experiments", []) if e.get("status") == "running"]
        completed = exp.get("completed", [])
        with_decision = sum(1 for e in completed if e.get("decision"))

        if active or completed:
            checks.append(("experiments", "ok", "%d active, %d completed" % (len(active), len(completed)), "self-learning"))
        else:
            checks.append(("experiments", "partial", "File exists but no experiments", "self-learning"))
            issues.append({
                "component": "experiments", "issue": "No experiments registered",
                "detail": "A/B testing system has no active or completed experiments",
                "impact": "Cannot validate improvements with controlled tests",
                "fix": "Register experiments for recent changes (trust block, Trading Cards, Pinterest)",
                "priority": "high", "agent": "self-learning",
            })

        if completed and with_decision < len(completed):
            issues.append({
                "component": "experiments", "issue": "Completed experiments without decision",
                "detail": "%d completed but only %d have continue/abolish/promote decision" % (len(completed), with_decision),
                "impact": "Experiment results not being acted on",
                "fix": "Review completed experiments and record decisions",
                "priority": "medium", "agent": "self-learning",
            })
    else:
        checks.append(("experiments", "missing", "File not found", "self-learning"))
        issues.append({
            "component": "experiments", "issue": "experiment_log.json missing",
            "detail": "Experiment tracking file does not exist",
            "impact": "No A/B testing capability",
            "fix": "File auto-created on next daily_inspection run",
            "priority": "high", "agent": "self-learning",
        })

    # --- research_log ---
    rl = _load_json("research_log.json")
    if rl:
        entries = rl.get("entries", [])
        today = NOW.strftime("%Y-%m-%d")
        today_entries = sum(1 for e in entries if e.get("date") == today)
        unique_agents = len(set(e.get("agent", "") for e in entries))

        if today_entries >= 3 and unique_agents >= 3:
            checks.append(("research_log", "ok", "%d entries today, %d agents" % (today_entries, unique_agents), "self-learning"))
        elif entries:
            checks.append(("research_log", "partial", "%d total entries, %d today" % (len(entries), today_entries), "self-learning"))
            if unique_agents < 3:
                issues.append({
                    "component": "research_log", "issue": "Too few agents logging research",
                    "detail": "Only %d agents have research entries (need 3+)" % unique_agents,
                    "impact": "Cannot verify all agents are actively researching",
                    "fix": "Ensure all agents log research via auto_extract_research()",
                    "priority": "medium", "agent": "project-orchestrator",
                })
        else:
            checks.append(("research_log", "partial", "File exists but empty", "self-learning"))
    else:
        checks.append(("research_log", "missing", "File not found", "self-learning"))

    # --- shared_state ---
    ss = _load_json("shared_state.json")
    if ss:
        has_focus = bool(ss.get("weekly_focus", {}).get("category"))
        has_weights = bool(ss.get("scoring_weights"))
        has_learning = bool(ss.get("adoption_learning"))
        has_philosophy = bool(ss.get("philosophy"))

        missing_keys = []
        if not has_focus:
            missing_keys.append("weekly_focus")
        if not has_weights:
            missing_keys.append("scoring_weights")
        if not has_learning:
            missing_keys.append("adoption_learning")

        if not missing_keys:
            checks.append(("shared_state", "ok", "All required keys present", "self-learning"))
        else:
            checks.append(("shared_state", "partial", "Missing: %s" % ", ".join(missing_keys), "self-learning"))
            issues.append({
                "component": "shared_state", "issue": "Missing shared state keys",
                "detail": "Keys not found: %s" % ", ".join(missing_keys),
                "impact": "Agent coordination and scoring may use defaults",
                "fix": "Will auto-populate through weekly_focus and adoption_learning updates",
                "priority": "medium", "agent": "project-orchestrator",
            })
    else:
        checks.append(("shared_state", "missing", "File not found", "self-learning"))

    # --- cross-agent feedback ---
    # Cross-agent feedback はレポート内の findings として生成されるため
    # 過去レポートで確認
    reports_dir = os.path.join(SCRIPT_DIR, "reports")
    yesterday = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_report = os.path.join(reports_dir, "report_%s.json" % yesterday)
    if os.path.exists(yesterday_report):
        try:
            with open(yesterday_report, "r", encoding="utf-8") as f:
                prev = json.load(f)
            has_cross = any("Cross-agent" in f.get("message", "") for f in prev.get("findings", []))
            if has_cross:
                checks.append(("cross_agent_feedback", "ok", "Present in yesterday's report", "project-orchestrator"))
            else:
                checks.append(("cross_agent_feedback", "partial", "Not found in yesterday's report", "project-orchestrator"))
        except (json.JSONDecodeError, IOError):
            checks.append(("cross_agent_feedback", "unknown", "Could not read yesterday's report", "project-orchestrator"))
    else:
        checks.append(("cross_agent_feedback", "unknown", "No previous report to check", "project-orchestrator"))

    return checks, issues


# ============================================================
# 2. API・接続設定 監査
# ============================================================

def _audit_api_connections():
    """自己学習に必要なAPI接続の状態と粒度を点検"""
    apis = []

    # GA4 Data API
    gcp_key = os.path.join(PROJECT_ROOT, ".gcp_service_account.json")
    ga4_prop = os.environ.get("GA4_PROPERTY_ID", "")
    if os.path.exists(gcp_key) or os.environ.get("GCP_KEY_FILE"):
        apis.append({
            "name": "GA4 Data API", "status": "connected",
            "granularity": "Page views, sessions, events (e-commerce via custom pixel)",
            "missing_granularity": "Per-product conversion funnel (view→cart→purchase) needs data accumulation",
            "priority": "high", "agent": "growth-foundation",
        })
    else:
        apis.append({
            "name": "GA4 Data API", "status": "credentials_missing",
            "granularity": "None", "missing_granularity": "All GA4 analysis",
            "priority": "critical", "agent": "growth-foundation",
        })

    # Search Console API
    if os.path.exists(gcp_key) or os.environ.get("GCP_KEY_FILE"):
        apis.append({
            "name": "Search Console API", "status": "connected",
            "granularity": "Queries, pages, impressions, clicks, CTR, position",
            "missing_granularity": "Click-through to purchase tracking (requires GA4 cross-reference)",
            "priority": "high", "agent": "growth-foundation",
        })
    else:
        apis.append({
            "name": "Search Console API", "status": "credentials_missing",
            "granularity": "None", "missing_granularity": "All SEO analysis",
            "priority": "critical", "agent": "growth-foundation",
        })

    # WordPress API
    wp_user = os.environ.get("WP_USER", "") or os.environ.get("WP_APP_PASSWORD", "")
    apis.append({
        "name": "WordPress REST API", "status": "connected" if wp_user else "not_configured",
        "granularity": "Posts, pages, categories (CRUD)" if wp_user else "None",
        "missing_granularity": "Article pageview data (needs GA4 cross-reference), CTA click tracking",
        "priority": "medium", "agent": "content-strategist",
    })

    # Shopify API
    shopify_token = _token_exists(".shopify_token.json")
    apis.append({
        "name": "Shopify Admin API", "status": "connected" if shopify_token else "token_missing",
        "granularity": "Products, orders, themes, collections, policies" if shopify_token else "None",
        "missing_granularity": "Real-time inventory sync events, customer journey data",
        "priority": "critical" if not shopify_token else "low", "agent": "store-setup",
    })

    # eBay API
    ebay_token = _token_exists(".ebay_token.json")
    ebay_app = os.environ.get("EBAY_APP_ID", "")
    apis.append({
        "name": "eBay API", "status": "connected" if (ebay_token or ebay_app) else "not_configured",
        "granularity": "Sales orders, item prices, active listings" if (ebay_token or ebay_app) else "None",
        "missing_granularity": "Per-item view count (not available via API), listing quality score",
        "priority": "high" if not (ebay_token or ebay_app) else "low", "agent": "catalog-migration-planner",
    })

    # Pinterest API
    pinterest_token = _token_exists(".pinterest_token.json")
    apis.append({
        "name": "Pinterest API", "status": "trial_access" if pinterest_token else "not_connected",
        "granularity": "Boards, pins (read/write via trial)" if pinterest_token else "None",
        "missing_granularity": "Pin analytics (impressions/clicks/saves) requires Standard access",
        "priority": "high" if not pinterest_token else "medium", "agent": "sns-manager",
    })

    # Instagram Insights
    ig_token = _token_exists(".instagram_token.json")
    apis.append({
        "name": "Instagram Graph API", "status": "connected" if ig_token else "token_missing",
        "granularity": "Post publishing, basic insights" if ig_token else "None",
        "missing_granularity": "Detailed insights (reach, profile visits, website clicks) need extended permissions",
        "priority": "high" if not ig_token else "medium", "agent": "sns-manager",
    })

    # YouTube Data API
    yt_token = _token_exists(".youtube_token.json")
    apis.append({
        "name": "YouTube Data API", "status": "connected" if yt_token else "token_missing",
        "granularity": "Video upload, basic metadata" if yt_token else "None",
        "missing_granularity": "YouTube Analytics (views, watch time, CTR) needs separate API scope",
        "priority": "low", "agent": "sns-manager",
    })

    return apis


# ============================================================
# 3. 学習イベント・ログ 監査
# ============================================================

def _audit_learning_events():
    """自己学習に必要なイベント・ログの記録状況を点検"""
    events = []

    # 商品ページ閲覧 (GA4 view_item)
    events.append({
        "event": "Product page view (view_item)",
        "status": "configured", "source": "GA4 Custom Pixel",
        "learning_use": "Product popularity ranking, adoption success evaluation",
        "gap": "Data accumulation needed (configured 2026-04-08)",
    })

    # add_to_cart
    events.append({
        "event": "Add to cart (add_to_cart)",
        "status": "configured", "source": "GA4 Custom Pixel",
        "learning_use": "Conversion funnel analysis, page quality evaluation",
        "gap": "Data accumulation needed",
    })

    # purchase
    events.append({
        "event": "Purchase (purchase)",
        "status": "configured", "source": "GA4 Custom Pixel",
        "learning_use": "Revenue tracking, proposal success validation",
        "gap": "No purchases yet (new store)",
    })

    # CTA click
    events.append({
        "event": "CTA click tracking",
        "status": "partial", "source": "UTM parameters on blog/SNS links",
        "learning_use": "Channel attribution, content effectiveness",
        "gap": "No dedicated CTA click event in GA4; tracking via UTM only",
    })

    # Internal link click
    events.append({
        "event": "Internal link click",
        "status": "not_tracked", "source": "N/A",
        "learning_use": "Content navigation optimization, article quality evaluation",
        "gap": "Need GA4 event or link click tracking on hd-bodyscience.com",
    })

    # Blog → Shopify referral
    events.append({
        "event": "Blog to Shopify referral",
        "status": "partial", "source": "UTM parameters (utm_source=hd-bodyscience)",
        "learning_use": "Blog ROI, article-to-sale attribution",
        "gap": "UTM set but cross-domain tracking not verified",
    })

    # SNS → profile / Shopify
    events.append({
        "event": "SNS to Shopify referral",
        "status": "partial", "source": "UTM parameters per platform",
        "learning_use": "SNS channel ROI, best platform identification",
        "gap": "Profile visit tracking requires Instagram Insights extended permissions",
    })

    # eBay→Shopify price sync result
    price_log = _load_json("price_sync_log.json")
    events.append({
        "event": "Price sync execution log",
        "status": "configured" if price_log else "empty",
        "source": "price_sync_log.json",
        "learning_use": "Price optimization accuracy, margin analysis",
        "gap": "No sync changes recorded yet" if not price_log or not price_log.get("changes") else "OK",
    })

    # Adoption post-analysis
    adoption = _load_json("adoption_tracking.json")
    events.append({
        "event": "Adoption post-analysis",
        "status": "configured" if adoption else "empty",
        "source": "adoption_tracking.json",
        "learning_use": "eBay→Shopify migration success rate, category learning",
        "gap": "GA4 view data not yet flowing into adoption records" if adoption and not any(p.get("views", 0) > 0 for p in adoption.get("adopted_products", [])) else "OK",
    })

    # Competitive comparison history
    comp = _load_json("product_comparison_cache.json")
    events.append({
        "event": "Competitive comparison history",
        "status": "configured" if comp else "empty",
        "source": "product_comparison_cache.json",
        "learning_use": "Page improvement tracking, feature gap closure",
        "gap": "Only latest comparison stored; need history for trend" if comp else "No comparison data yet",
    })

    # UI/UX improvement history
    events.append({
        "event": "UI/UX improvement history",
        "status": "not_tracked", "source": "N/A",
        "learning_use": "Before/after comparison of UI changes",
        "gap": "No dedicated UI change log; improvements tracked only in proposal_tracking",
    })

    # Blog article performance
    blog_state = _load_json("blog_state.json")
    events.append({
        "event": "Blog article PDCA log",
        "status": "configured" if blog_state else "empty",
        "source": "blog_state.json",
        "learning_use": "Article quality improvement, CTA effectiveness",
        "gap": "blog_state.json empty or missing" if not blog_state else "OK",
    })

    return events


# ============================================================
# 4. 学習精度 監査
# ============================================================

def _audit_learning_accuracy():
    """提案タイプ別の精度を評価し、改善が必要な領域を特定"""
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return [], [{"type": "all", "issue": "No proposal data for accuracy evaluation"}]

    accuracy = pt.get("summary", {}).get("accuracy_by_type", {})
    results = []
    improvements = []

    for ptype, data in sorted(accuracy.items()):
        proposed = data.get("proposed", 0)
        adopted = data.get("adopted", 0)
        success = data.get("success", 0)

        if proposed == 0:
            continue

        adopt_rate = adopted / proposed if proposed > 0 else 0
        success_rate = success / adopted if adopted > 0 else 0

        status = "high" if success_rate >= 0.7 else "medium" if success_rate >= 0.4 else "low"
        results.append({
            "type": ptype, "proposed": proposed, "adopted": adopted, "success": success,
            "adopt_rate": adopt_rate, "success_rate": success_rate, "status": status,
        })

        if status == "low" and adopted >= 2:
            improvements.append({
                "type": ptype,
                "issue": "Low success rate (%.0f%%)" % (success_rate * 100),
                "suggestion": "Review %s proposals: refine criteria or reduce weight" % ptype,
            })

    # 精度データが不足しているタイプ
    expected_types = ["sales_based", "similar_product", "related_character", "category_gap",
                      "article_theme", "sns_post", "page_improvement"]
    tracked_types = set(accuracy.keys())
    missing_types = [t for t in expected_types if t not in tracked_types]
    if missing_types:
        improvements.append({
            "type": "coverage",
            "issue": "No accuracy data for: %s" % ", ".join(missing_types),
            "suggestion": "These proposal types need more data to evaluate effectiveness",
        })

    return results, improvements


# ============================================================
# 5. レポート生成
# ============================================================

def generate_self_learning_audit(all_findings):
    """自己学習機能監査レポートを生成する"""
    result_findings = []

    # === A. 構成監査 ===
    checks, component_issues = _audit_learning_components()

    ok_count = sum(1 for c in checks if c[1] == "ok")
    partial_count = sum(1 for c in checks if c[1] == "partial")
    missing_count = sum(1 for c in checks if c[1] == "missing")

    component_details = ["=== Self-Learning Component Status ==="]
    icon_map = {"ok": "✅", "partial": "⚠️", "missing": "❌", "unknown": "❓"}
    for name, status, detail, agent in checks:
        component_details.append("%s %s: %s" % (icon_map.get(status, "❓"), name, detail))

    result_findings.append({
        "type": "info" if missing_count == 0 else "suggestion",
        "agent": "project-orchestrator",
        "message": "Self-learning audit: %d ok, %d partial, %d missing" % (ok_count, partial_count, missing_count),
        "details": component_details,
    })

    # === B. API接続監査 ===
    apis = _audit_api_connections()

    api_details = ["=== API Connection Audit ==="]
    for api in apis:
        status_icon = {"connected": "✅", "trial_access": "🔶", "credentials_missing": "❌",
                       "token_missing": "❌", "not_configured": "❌", "not_connected": "❌"}.get(api["status"], "❓")
        api_details.append("%s %s [%s]" % (status_icon, api["name"], api["status"]))
        if api.get("missing_granularity") and api["status"] in ("connected", "trial_access"):
            api_details.append("  Missing: %s" % api["missing_granularity"])

    not_connected = sum(1 for a in apis if a["status"] not in ("connected", "trial_access"))
    result_findings.append({
        "type": "info" if not_connected == 0 else "suggestion",
        "agent": "growth-foundation",
        "message": "API audit: %d connected, %d need attention" % (len(apis) - not_connected, not_connected),
        "details": api_details,
    })

    # === C. 学習ログ監査 ===
    pt = _load_json("proposal_tracking.json")
    exp = _load_json("experiment_log.json")
    rl = _load_json("research_log.json")

    log_details = ["=== Learning Log Counts ==="]
    log_details.append("proposal_tracking: %d entries" % (len(pt.get("proposals", [])) if pt else 0))
    log_details.append("experiments: %d active, %d completed" % (
        len([e for e in (exp or {}).get("experiments", []) if e.get("status") == "running"]),
        len((exp or {}).get("completed", [])),
    ))
    log_details.append("research_log: %d entries" % (len((rl or {}).get("entries", []))))

    # 今回追加された件数（今日の日付）
    today = NOW.strftime("%Y-%m-%d")
    today_proposals = sum(1 for p in (pt or {}).get("proposals", []) if p.get("date") == today)
    today_research = sum(1 for e in (rl or {}).get("entries", []) if e.get("date") == today)
    log_details.append("Added today: proposals=%d, research=%d" % (today_proposals, today_research))

    # Stale チェック
    stale = []
    if pt and _days_since(pt.get("summary", {}).get("last_updated", "")) > 2:
        stale.append("proposal_tracking (last: %s)" % pt.get("summary", {}).get("last_updated", "?"))
    if exp and _days_since(exp.get("last_updated", "")) > 2:
        stale.append("experiments (last: %s)" % exp.get("last_updated", "?"))
    if rl and _days_since(rl.get("last_updated", "")) > 2:
        stale.append("research_log (last: %s)" % rl.get("last_updated", "?"))
    if stale:
        log_details.append("Stale logs: %s" % ", ".join(stale))

    result_findings.append({
        "type": "info",
        "agent": "self-learning",
        "message": "Learning logs: %d proposals, %d experiments, %d research entries" % (
            len((pt or {}).get("proposals", [])),
            len((exp or {}).get("experiments", [])),
            len((rl or {}).get("entries", [])),
        ),
        "details": log_details,
    })

    # === D. 学習精度監査 ===
    accuracy_results, accuracy_improvements = _audit_learning_accuracy()

    if accuracy_results:
        acc_details = ["=== Proposal Accuracy by Type ==="]
        for r in accuracy_results:
            icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(r["status"], "⚪")
            acc_details.append(
                "%s %s: proposed=%d adopted=%d success=%d (%.0f%%)"
                % (icon, r["type"], r["proposed"], r["adopted"], r["success"], r["success_rate"] * 100)
            )
        if accuracy_improvements:
            acc_details.append("--- Improvements needed ---")
            for imp in accuracy_improvements:
                acc_details.append("[%s] %s → %s" % (imp["type"], imp["issue"], imp["suggestion"]))

        result_findings.append({
            "type": "info",
            "agent": "self-learning",
            "message": "Learning accuracy: %d types tracked, %d need improvement" % (
                len(accuracy_results), len(accuracy_improvements)),
            "details": acc_details,
        })

    # === E. イベント・ログ監査 ===
    events = _audit_learning_events()
    gap_events = [e for e in events if e.get("gap") and e["gap"] != "OK"]

    if gap_events:
        event_details = ["=== Learning Event Gaps ==="]
        for e in gap_events:
            status_icon = {"configured": "🔶", "partial": "⚠️", "not_tracked": "❌", "empty": "❌"}.get(e["status"], "❓")
            event_details.append("%s %s [%s]" % (status_icon, e["event"], e["status"]))
            event_details.append("  Gap: %s" % e["gap"])
            event_details.append("  Learning use: %s" % e["learning_use"])

        result_findings.append({
            "type": "suggestion",
            "agent": "growth-foundation",
            "message": "Learning event gaps: %d events need attention" % len(gap_events),
            "details": event_details,
        })

    # === F. 改善提案（自己学習機能自体の改善） ===
    all_issues = component_issues[:]

    # API不足からの改善提案
    for api in apis:
        if api["status"] not in ("connected", "trial_access"):
            all_issues.append({
                "component": "api_%s" % api["name"].lower().replace(" ", "_"),
                "issue": "%s: %s" % (api["name"], api["status"]),
                "detail": api.get("missing_granularity", "All data from this API"),
                "impact": "Cannot collect %s data for learning" % api["name"],
                "fix": "Set up credentials/token for %s" % api["name"],
                "priority": api["priority"], "agent": api["agent"],
            })

    # イベント不足からの改善提案
    for e in events:
        if e["status"] in ("not_tracked", "empty"):
            all_issues.append({
                "component": "event_%s" % e["event"][:30].lower().replace(" ", "_"),
                "issue": "%s: %s" % (e["event"], e["status"]),
                "detail": e["gap"],
                "impact": "Cannot use for: %s" % e["learning_use"],
                "fix": "Configure %s tracking" % e["event"],
                "priority": "medium", "agent": "growth-foundation",
            })

    if all_issues:
        # 優先度でソート
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        all_issues.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

        improvement_details = ["=== Self-Learning Improvement Proposals ==="]
        for issue in all_issues[:8]:
            improvement_details.append(
                "[%s] [%s] %s" % (issue.get("priority", "?").upper(), issue["agent"], issue["issue"])
            )
            improvement_details.append("  Impact: %s" % issue.get("impact", ""))
            improvement_details.append("  Fix: %s" % issue.get("fix", ""))

        result_findings.append({
            "type": "action",
            "agent": "project-orchestrator",
            "message": "Self-learning improvements: %d items (%d critical/high)" % (
                len(all_issues),
                sum(1 for i in all_issues if i.get("priority") in ("critical", "high")),
            ),
            "details": improvement_details,
        })

    return result_findings
