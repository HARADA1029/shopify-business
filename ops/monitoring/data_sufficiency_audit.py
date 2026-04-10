# ============================================================
# データ充足監査モジュール
#
# 分析に必要なデータが十分に揃っているかを毎回チェックし、
# 不足があれば原因・影響・対処を明示する。
#
# 1. 分析データ充足サマリ（6領域）
# 2. データ不足監査（原因・影響・対処・担当）
# 3. データ件数表示
# 4. 最終更新日時
# 5. 優先不足データ Top 3
# ============================================================

import json
import os
import glob
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")

# 充足レベル定義
SUFFICIENT = "sufficient"
PARTIAL = "partial"
INSUFFICIENT = "insufficient"


def _load_json(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _file_mtime(filepath):
    """ファイルの最終更新日時をJST文字列で返す"""
    if not os.path.exists(filepath):
        return None
    ts = os.path.getmtime(filepath)
    dt = datetime.fromtimestamp(ts, tz=JST)
    return dt.strftime("%Y-%m-%d %H:%M")


def _days_since(date_str):
    """日付文字列から経過日数を返す"""
    if not date_str:
        return 999
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (NOW.replace(tzinfo=None) - dt).days
    except ValueError:
        return 999


# ============================================================
# 各領域のデータ充足チェック
# ============================================================

def _check_shopify_products(all_findings):
    """Shopify 商品分析データの充足度"""
    product_count = 0
    for f in all_findings:
        msg = f.get("message", "")
        if "Active:" in msg:
            try:
                product_count = int(msg.split("Active:")[1].split("/")[0].strip().split()[0])
            except (ValueError, IndexError):
                pass

    issues = []
    if product_count == 0:
        level = INSUFFICIENT
        issues.append({
            "data": "Shopify product list",
            "reason": "API returned 0 products or connection failed",
            "temporary": True,
            "impact": "Cannot run product PDCA, page audit, or category analysis",
            "fix": "Check SHOPIFY_STORE env and .shopify_token.json validity",
            "agent": "store-setup",
        })
    elif product_count < 10:
        level = PARTIAL
        issues.append({
            "data": "Shopify active product count",
            "reason": "Only %d active products (limited analysis scope)" % product_count,
            "temporary": False,
            "impact": "Category analysis and competitive comparison have small sample",
            "fix": "Activate more draft products or import from eBay",
            "agent": "catalog-migration-planner",
        })
    else:
        level = SUFFICIENT

    return {"level": level, "count": product_count, "issues": issues}


def _check_adoption_tracking():
    """eBay→Shopify 採用商品事後分析データ"""
    data = _load_json("adoption_tracking.json")
    issues = []

    if not data or not data.get("adopted_products"):
        level = INSUFFICIENT
        issues.append({
            "data": "Adoption tracking entries",
            "reason": "No adopted products tracked yet",
            "temporary": False,
            "impact": "Cannot evaluate which eBay→Shopify migrations succeeded",
            "fix": "Track newly activated products via product_pdca.py",
            "agent": "catalog-migration-planner",
        })
        return {"level": level, "count": 0, "issues": issues}

    adopted = data.get("adopted_products", [])
    total = len(adopted)
    with_views = sum(1 for p in adopted if p.get("views", 0) > 0)
    with_result = sum(1 for p in adopted if p.get("status") not in ("monitoring", None))

    if with_views == 0:
        level = PARTIAL
        issues.append({
            "data": "GA4 view data for adopted products",
            "reason": "Tracking %d products but 0 have view data" % total,
            "temporary": True,
            "impact": "Cannot distinguish weak vs popular products",
            "fix": "GA4 e-commerce events need time to accumulate data",
            "agent": "growth-foundation",
        })
    elif with_result < total * 0.5:
        level = PARTIAL
    else:
        level = SUFFICIENT

    return {"level": level, "count": total, "with_views": with_views, "with_result": with_result, "issues": issues}


def _check_sns_data():
    """SNS 投稿分析データ"""
    data = _load_json("sns_posted.json")
    issues = []

    if not data:
        level = INSUFFICIENT
        issues.append({
            "data": "SNS posting history",
            "reason": "sns_posted.json not found or empty",
            "temporary": True,
            "impact": "Cannot analyze SNS performance or optimize posting",
            "fix": "Run SNS auto-post workflows (GitHub Actions)",
            "agent": "sns-manager",
        })
        return {"level": level, "count": 0, "with_engagement": 0, "issues": issues}

    history = data.get("history", [])
    total = len(history)

    # 過去7日
    week_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= week_ago]

    # エンゲージメント付き
    with_engagement = sum(
        1 for h in history
        if h.get("engagement") and sum(h["engagement"].values()) > 0
    )

    if total == 0:
        level = INSUFFICIENT
        issues.append({
            "data": "SNS post history", "reason": "No posts recorded",
            "temporary": True, "impact": "No PDCA possible",
            "fix": "Execute SNS auto-post scripts", "agent": "sns-manager",
        })
    elif len(recent) == 0:
        level = PARTIAL
        issues.append({
            "data": "Recent SNS posts (7 days)", "reason": "No posts in last 7 days",
            "temporary": True, "impact": "SNS optimization using stale data",
            "fix": "Check GitHub Actions workflow execution", "agent": "sns-manager",
        })
    elif with_engagement == 0:
        level = PARTIAL
        issues.append({
            "data": "SNS engagement metrics",
            "reason": "%d posts but 0 have engagement data" % total,
            "temporary": True,
            "impact": "Cannot determine best-performing post types",
            "fix": "Instagram Insights token or wait 2+ days for data collection",
            "agent": "sns-manager",
        })
    else:
        level = SUFFICIENT

    return {"level": level, "count": total, "recent_7d": len(recent), "with_engagement": with_engagement, "issues": issues}


def _check_price_sync():
    """価格同期分析データ"""
    data = _load_json("price_sync_log.json")
    issues = []

    if not data:
        level = INSUFFICIENT
        issues.append({
            "data": "Price sync log",
            "reason": "price_sync_log.json not found",
            "temporary": False,
            "impact": "Cannot track price change history or sync accuracy",
            "fix": "Run price_sync with valid eBay credentials",
            "agent": "price-auditor",
        })
        return {"level": level, "count": 0, "issues": issues}

    changes = data.get("changes", [])
    total = len(changes)

    if total == 0:
        level = PARTIAL
        issues.append({
            "data": "Price sync change records",
            "reason": "Log exists but 0 changes recorded",
            "temporary": True,
            "impact": "Cannot evaluate price sync effectiveness",
            "fix": "Verify eBay API credentials and SKU mapping (EB-xxxxx)",
            "agent": "price-auditor",
        })
    else:
        level = SUFFICIENT

    return {"level": level, "count": total, "issues": issues}


def _check_competitive_data():
    """競合比較データ"""
    data = _load_json("competitive_cache.json")
    comparison = _load_json("product_comparison_cache.json")
    issues = []

    has_competitive = data is not None
    has_comparison = comparison is not None

    if not has_competitive and not has_comparison:
        level = INSUFFICIENT
        issues.append({
            "data": "Competitor site data",
            "reason": "No competitive analysis cache found",
            "temporary": True,
            "impact": "Cannot track competitor changes or feature gaps",
            "fix": "Run competitive_analysis.py (requires network access to competitor sites)",
            "agent": "competitive-intelligence",
        })
    elif not has_comparison:
        level = PARTIAL
        issues.append({
            "data": "Product page comparison cache",
            "reason": "No product-level competitor comparison yet",
            "temporary": False,
            "impact": "Cannot track page improvement progress over time",
            "fix": "Will auto-populate after first product_pdca run with products",
            "agent": "competitive-intelligence",
        })
    else:
        level = SUFFICIENT
        # 鮮度チェック
        comp_date = comparison.get("date", "") if comparison else ""
        if _days_since(comp_date) > 7:
            level = PARTIAL
            issues.append({
                "data": "Competitor comparison freshness",
                "reason": "Last comparison %d days ago" % _days_since(comp_date),
                "temporary": True,
                "impact": "Improvement tracking based on stale baseline",
                "fix": "Runs automatically in daily inspection",
                "agent": "competitive-intelligence",
            })

    pages_compared = 1 if has_comparison else 0
    return {"level": level, "pages_compared": pages_compared, "issues": issues}


def _check_learning_data():
    """research_log / proposal_tracking / experiments"""
    research = _load_json("research_log.json")
    proposals = _load_json("proposal_tracking.json")
    experiments = _load_json("experiment_log.json")
    issues = []

    research_count = len(research.get("entries", [])) if research else 0
    proposal_count = len(proposals.get("proposals", [])) if proposals else 0
    experiment_count = len(experiments.get("experiments", [])) if experiments else 0

    total = research_count + proposal_count + experiment_count

    if total == 0:
        level = INSUFFICIENT
        issues.append({
            "data": "Learning system data (research/proposals/experiments)",
            "reason": "All learning stores are empty",
            "temporary": False,
            "impact": "Self-learning loop cannot function",
            "fix": "Run daily_inspection.py to auto-populate",
            "agent": "self-learning",
        })
    elif proposal_count < 5 or experiment_count == 0:
        level = PARTIAL
        if proposal_count < 5:
            issues.append({
                "data": "Proposal tracking history",
                "reason": "Only %d proposals tracked (need 5+ for accuracy analysis)" % proposal_count,
                "temporary": False,
                "impact": "Proposal accuracy by type cannot be reliably calculated",
                "fix": "Continue daily runs to accumulate proposals",
                "agent": "self-learning",
            })
        if experiment_count == 0:
            issues.append({
                "data": "Active experiments",
                "reason": "No experiments registered",
                "temporary": False,
                "impact": "No A/B testing or controlled improvement tracking",
                "fix": "Register experiments via experiment_manager.py",
                "agent": "self-learning",
            })
    else:
        level = SUFFICIENT

    return {
        "level": level,
        "research_count": research_count,
        "proposal_count": proposal_count,
        "experiment_count": experiment_count,
        "issues": issues,
    }


# ============================================================
# 最終更新日時チェック
# ============================================================

def _get_last_updated_times():
    """主要データの最終取得日時"""
    times = {}

    # GA4 レポート
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "report_*.json")), reverse=True)
    if report_files:
        times["daily_report"] = _file_mtime(report_files[0])

    # 各データファイル
    file_map = {
        "eBay sales cache": "ebay_sales_cache.json",
        "Shopify product analysis": "adoption_tracking.json",
        "Price sync log": "price_sync_log.json",
        "Competitive analysis": "competitive_cache.json",
        "SNS posted log": "sns_posted.json",
        "Research log": "research_log.json",
        "Proposal tracking": "proposal_tracking.json",
        "Experiment log": "experiment_log.json",
        "SNS weights": "sns_weights.json",
        "Shared state": "shared_state.json",
    }

    for label, filename in file_map.items():
        path = os.path.join(SCRIPT_DIR, filename)
        mtime = _file_mtime(path)
        if mtime:
            times[label] = mtime
        else:
            times[label] = "not found"

    # トークンファイル（API接続状態）
    token_map = {
        "Pinterest API": ".pinterest_token.json",
        "Instagram API": ".instagram_token.json",
        "eBay API": ".ebay_token.json",
        "Shopify API": ".shopify_token.json",
    }
    for label, filename in token_map.items():
        path = os.path.join(PROJECT_ROOT, filename)
        mtime = _file_mtime(path)
        if mtime:
            times[label] = mtime
        else:
            times[label] = "no token"

    return times


# ============================================================
# メイン: レポートセクション生成
# ============================================================

def generate_data_sufficiency_report(all_findings):
    """データ充足監査レポートを生成する"""
    result_findings = []

    # === 各領域チェック ===
    shopify = _check_shopify_products(all_findings)
    adoption = _check_adoption_tracking()
    sns = _check_sns_data()
    price = _check_price_sync()
    competitive = _check_competitive_data()
    learning = _check_learning_data()

    checks = {
        "Shopify product analysis": shopify,
        "eBay->Shopify adoption tracking": adoption,
        "SNS posting analysis": sns,
        "Price sync analysis": price,
        "Competitive comparison": competitive,
        "Learning system (research/proposals/experiments)": learning,
    }

    # === 1. 充足サマリ ===
    level_icon = {SUFFICIENT: "✅", PARTIAL: "⚠️", INSUFFICIENT: "❌"}
    level_label = {SUFFICIENT: "充足", PARTIAL: "一部不足", INSUFFICIENT: "不足"}

    summary_details = ["=== Data Sufficiency Summary ==="]
    insufficient_count = 0
    partial_count = 0

    for label, check in checks.items():
        level = check["level"]
        icon = level_icon[level]
        jp = level_label[level]
        summary_details.append("%s %s: %s" % (icon, label, jp))
        if level == INSUFFICIENT:
            insufficient_count += 1
        elif level == PARTIAL:
            partial_count += 1

    # === 2. データ件数表示 ===
    summary_details.append("")
    summary_details.append("=== Data Counts ===")
    summary_details.append("Shopify active products: %d" % shopify.get("count", 0))
    summary_details.append("Adoption tracked products: %d (views:%d, evaluated:%d)" % (
        adoption.get("count", 0), adoption.get("with_views", 0), adoption.get("with_result", 0)))
    summary_details.append("SNS posts total: %d (recent 7d:%d, with engagement:%d)" % (
        sns.get("count", 0), sns.get("recent_7d", 0), sns.get("with_engagement", 0)))
    summary_details.append("Price sync changes: %d" % price.get("count", 0))
    summary_details.append("Competitor pages compared: %d" % competitive.get("pages_compared", 0))
    summary_details.append("Research log: %d, Proposals: %d, Experiments: %d" % (
        learning.get("research_count", 0), learning.get("proposal_count", 0), learning.get("experiment_count", 0)))

    # === 3. 最終更新日時 ===
    times = _get_last_updated_times()
    summary_details.append("")
    summary_details.append("=== Last Updated ===")
    for label, mtime in sorted(times.items()):
        summary_details.append("%s: %s" % (label, mtime))

    result_findings.append({
        "type": "info" if insufficient_count == 0 else "suggestion",
        "agent": "project-orchestrator",
        "message": "Data sufficiency: %d sufficient, %d partial, %d insufficient" % (
            len(checks) - insufficient_count - partial_count, partial_count, insufficient_count),
        "details": summary_details,
    })

    # === 4. データ不足監査 ===
    all_issues = []
    for label, check in checks.items():
        for issue in check.get("issues", []):
            issue["area"] = label
            all_issues.append(issue)

    if all_issues:
        issue_details = ["=== Data Gap Audit (%d issues) ===" % len(all_issues)]
        for issue in all_issues:
            temp = "temporary" if issue.get("temporary") else "persistent"
            issue_details.append("[%s] [%s] %s" % (issue["agent"], temp, issue["data"]))
            issue_details.append("  Reason: %s" % issue["reason"])
            issue_details.append("  Impact: %s" % issue["impact"])
            issue_details.append("  Fix: %s" % issue["fix"])

        result_findings.append({
            "type": "suggestion" if insufficient_count > 0 else "info",
            "agent": "project-orchestrator",
            "message": "Data gaps: %d issues found (%d areas affected)" % (
                len(all_issues), sum(1 for c in checks.values() if c.get("issues"))),
            "details": issue_details,
        })

    # === 5. 優先不足データ Top 3 ===
    # 優先度: insufficient > partial, persistent > temporary
    priority_issues = sorted(
        all_issues,
        key=lambda x: (
            0 if any(c["level"] == INSUFFICIENT for c in checks.values() if x in c.get("issues", [])) else 1,
            0 if not x.get("temporary") else 1,
        ),
    )[:3]

    if priority_issues:
        top3_details = []
        for i, issue in enumerate(priority_issues, 1):
            top3_details.append(
                "#%d [%s] %s → %s" % (i, issue["agent"], issue["data"], issue["fix"])
            )

        result_findings.append({
            "type": "action" if insufficient_count > 0 else "info",
            "agent": "project-orchestrator",
            "message": "Priority data gaps (top 3 to fix before next run)",
            "details": top3_details,
        })

    return result_findings
