# ============================================================
# バグ・異常監査モジュール
#
# 定期実行の全自動化処理を統合的に監査し、
# 異常を検出・分類・再発監視する。
#
# 監査対象:
# 1. API / 接続異常
# 2. 自動化処理異常
# 3. データ異常
# 4. 品質異常
# 5. エージェント運用異常
#
# 出力:
# - 異常サマリ（新規/継続/解消）
# - 異常一覧（内容/種別/影響/原因/担当/優先度/状態）
# - 再発監視（連続日数/改善有無）
# - 品質異常カウント
# ============================================================

import json
import os
import re
import glob
from datetime import datetime, timezone, timedelta
from collections import defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")

BUG_LOG_FILE = os.path.join(SCRIPT_DIR, "bug_audit_log.json")


def _load_bug_log():
    if not os.path.exists(BUG_LOG_FILE):
        return {"issues": [], "resolved": [], "last_run": ""}
    try:
        with open(BUG_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"issues": [], "resolved": [], "last_run": ""}


def _save_bug_log(log):
    log["last_run"] = NOW.strftime("%Y-%m-%d")
    # 解消済みは30日保持
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    log["resolved"] = [r for r in log["resolved"] if r.get("resolved_date", "") >= cutoff]
    with open(BUG_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


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


def _make_issue(category, name, detail, impact, cause, agent, priority):
    """異常レコードを生成"""
    return {
        "category": category,
        "name": name,
        "detail": detail[:200],
        "impact": impact[:150],
        "cause": cause[:150],
        "agent": agent,
        "priority": priority,
        "key": "%s:%s" % (category, name),
        "detected_date": NOW.strftime("%Y-%m-%d"),
    }


# ============================================================
# 1. API / 接続異常
# ============================================================

def _audit_api(all_findings):
    """API接続・認証・権限の異常を検出"""
    issues = []

    # トークンファイルチェック
    tokens = {
        "Shopify": (".shopify_token.json", "store-setup", "critical", "SHOPIFY_ACCESS_TOKEN"),
        "eBay": (".ebay_token.json", "price-auditor", "high", "EBAY_APP_ID"),
        "Instagram": (".instagram_token.json", "sns-manager", "medium", "INSTAGRAM_ACCESS_TOKEN"),
        "Pinterest": (".pinterest_token.json", "sns-manager", "medium", "PINTEREST_APP_ID"),
        "YouTube": (".youtube_token.json", "sns-manager", "low", "YOUTUBE_CLIENT_ID"),
        "TikTok": (".tiktok_token.json", "sns-manager", "low", "TIKTOK_CLIENT_KEY"),
    }

    is_ci = bool(os.environ.get("GITHUB_ACTIONS"))

    for name, (filename, agent, priority, env_var) in tokens.items():
        has_file = _token_exists(filename)
        has_env = bool(os.environ.get(env_var))
        # GitHub Actions ではsecretsから環境変数で供給されるのでファイル不要
        if not has_file and not has_env and not is_ci:
            issues.append(_make_issue(
                "api", "%s token missing" % name,
                "%s not found (local)" % filename,
                "%s API calls will fail" % name,
                "Token file not created or deleted",
                agent, priority,
            ))
        elif not has_file and not has_env and is_ci:
            # CI環境ではsecretが設定されていない場合のみ警告
            issues.append(_make_issue(
                "api", "%s credentials not in secrets" % name,
                "Neither %s file nor %s env var found in CI" % (filename, env_var),
                "%s API calls will fail in GitHub Actions" % name,
                "Add %s to repository secrets" % env_var,
                agent, "medium",  # CIでは medium に下げる（secretsの設定漏れ）
            ))

    # GCP credentials
    gcp_file = os.environ.get("GCP_KEY_FILE", "")
    gcp_path = os.path.join(PROJECT_ROOT, gcp_file) if gcp_file else os.path.join(PROJECT_ROOT, ".gcp_service_account.json")
    if not os.path.exists(gcp_path):
        # GitHub Actionsでは動的生成されるので、ローカルのみチェック
        if not os.environ.get("GITHUB_ACTIONS"):
            issues.append(_make_issue(
                "api", "GCP credentials missing",
                "GCP service account key not found",
                "GA4 and Search Console API calls will fail",
                "File not present locally (OK in GitHub Actions)",
                "growth-foundation", "medium",
            ))

    # findings内のAPI関連エラーを検出
    for f in all_findings:
        msg = f.get("message", "").lower()
        if any(kw in msg for kw in ["failed [auth]", "token not available", "credentials not available", "401", "403"]):
            agent = f.get("agent", "project-orchestrator")
            issues.append(_make_issue(
                "api", "API error in findings",
                f.get("message", "")[:100],
                "Related analysis or sync skipped",
                "Authentication or permission issue",
                agent, "high",
            ))

    return issues


# ============================================================
# 2. 自動化処理異常
# ============================================================

def _audit_automation(all_findings):
    """自動化処理の失敗を検出"""
    issues = []

    # findings 内の失敗を検出
    error_keywords = ["failed", "error", "not available", "skip", "rejected", "timeout"]

    for f in all_findings:
        msg = f.get("message", "").lower()
        ftype = f.get("type", "")

        # critical/suggestion の中にエラー系がある場合
        if ftype in ("critical", "suggestion") and any(kw in msg for kw in error_keywords):
            agent = f.get("agent", "project-orchestrator")
            priority = "critical" if ftype == "critical" else "high"

            # 種別を特定
            if "price sync" in msg:
                name = "Price sync failure"
            elif "image sync" in msg:
                name = "Image sync failure"
            elif "wordpress" in msg or "wp" in msg:
                name = "WordPress operation failure"
            elif "sns" in msg or "instagram" in msg or "facebook" in msg:
                name = "SNS posting failure"
            elif "blog" in msg or "article" in msg:
                name = "Blog generation failure"
            else:
                name = "Automation failure"

            issues.append(_make_issue(
                "automation", name,
                f.get("message", "")[:100],
                "Automated process did not complete",
                "Check details in finding",
                agent, priority,
            ))

    # price_sync_log チェック
    price_log = _load_json("price_sync_log.json")
    if price_log:
        last_run = price_log.get("last_run", "")
        if _days_since(last_run) > 2:
            issues.append(_make_issue(
                "automation", "Price sync stale",
                "Last run: %s (%d days ago)" % (last_run, _days_since(last_run)),
                "Prices may be out of sync with eBay",
                "Daily inspection may not be running or price sync is erroring",
                "price-auditor", "high",
            ))

    # image_sync_log チェック
    image_log = _load_json("image_sync_log.json")
    if image_log:
        last_run = image_log.get("last_run", "")
        if _days_since(last_run) > 2:
            issues.append(_make_issue(
                "automation", "Image sync stale",
                "Last run: %s" % last_run,
                "New eBay images may not be reflected on Shopify",
                "Image sync not running in daily inspection",
                "catalog-migration-planner", "medium",
            ))

    return issues


# ============================================================
# 3. データ異常
# ============================================================

def _audit_data():
    """データの不整合・欠損・staleを検出"""
    issues = []

    # 主要データファイルの存在と鮮度
    data_files = {
        "shared_state.json": ("self-learning", "high", "Agent coordination breaks"),
        "proposal_tracking.json": ("self-learning", "medium", "Proposal learning stops"),
        "experiment_log.json": ("self-learning", "medium", "Experiment tracking stops"),
        "research_log.json": ("self-learning", "low", "Research audit incomplete"),
        "blog_state.json": ("blog-analyst", "medium", "Blog PDCA stops"),
        "sns_posted.json": ("sns-manager", "medium", "SNS PDCA stops"),
        "adoption_tracking.json": ("catalog-migration-planner", "medium", "Adoption analysis stops"),
    }

    for filename, (agent, priority, impact) in data_files.items():
        data = _load_json(filename)
        if data is None:
            issues.append(_make_issue(
                "data", "%s missing" % filename, "File not found",
                impact, "File not yet created or deleted",
                agent, priority,
            ))
        else:
            # 更新日チェック
            last_updated = data.get("last_updated", data.get("_last_updated", ""))
            if _days_since(last_updated) > 3:
                issues.append(_make_issue(
                    "data", "%s stale" % filename,
                    "Last updated: %s (%d days ago)" % (last_updated, _days_since(last_updated)),
                    impact + " (using stale data)",
                    "Daily inspection may not be updating this file",
                    agent, "medium",
                ))

    # proposal_tracking の0件継続チェック
    pt = _load_json("proposal_tracking.json")
    if pt and len(pt.get("proposals", [])) == 0:
        issues.append(_make_issue(
            "data", "proposal_tracking empty",
            "0 proposals tracked",
            "Proposal accuracy evaluation impossible",
            "No proposals generated or tracking not running",
            "self-learning", "high",
        ))

    # experiments の0件チェック
    exp = _load_json("experiment_log.json")
    if exp and len(exp.get("experiments", [])) == 0 and len(exp.get("completed", [])) == 0:
        issues.append(_make_issue(
            "data", "experiments empty",
            "0 experiments registered",
            "No controlled improvement testing",
            "No experiments auto-registered",
            "self-learning", "medium",
        ))

    return issues


# ============================================================
# 4. 品質異常
# ============================================================

def _audit_quality(all_findings):
    """品質関連の異常を集計"""
    issues = []

    # findings から品質問題を抽出
    quality_counts = {
        "no_image_articles": 0,
        "no_category_articles": 0,
        "no_tag_articles": 0,
        "short_descriptions": 0,
        "no_trust_products": 0,
        "no_cta_articles": 0,
        "no_internal_links": 0,
    }

    for f in all_findings:
        msg = f.get("message", "").lower()
        details = f.get("details", [])
        details_text = " ".join(str(d) for d in details).lower()

        if "no image" in msg or "no-image" in details_text:
            try:
                count = int(re.search(r"(\d+)\s*no.image", msg + " " + details_text).group(1))
                quality_counts["no_image_articles"] = max(quality_counts["no_image_articles"], count)
            except (AttributeError, ValueError):
                quality_counts["no_image_articles"] += 1

        if "category" in msg and ("未設定" in msg or "missing" in details_text or "default" in details_text):
            quality_counts["no_category_articles"] += 1

        if "short" in msg and ("desc" in msg or "words" in msg):
            quality_counts["short_descriptions"] += 1

    # 品質カウントから異常を生成
    if quality_counts["no_image_articles"] > 0:
        issues.append(_make_issue(
            "quality", "Articles without images",
            "%d articles have no images" % quality_counts["no_image_articles"],
            "Reader engagement and SEO suffer",
            "Auto-generated articles may lack image insertion",
            "blog-analyst", "high",
        ))

    if quality_counts["short_descriptions"] > 0:
        issues.append(_make_issue(
            "quality", "Product pages with thin descriptions",
            "%d products have short descriptions" % quality_counts["short_descriptions"],
            "Low conversion rate and poor SEO",
            "Product migration may have imported minimal descriptions",
            "store-setup", "medium",
        ))

    return issues


# ============================================================
# 5. エージェント運用異常
# ============================================================

def _audit_agents(all_findings):
    """エージェントの動作異常を検出"""
    issues = []

    # エージェント別の出力カウント
    agent_output = defaultdict(int)
    for f in all_findings:
        agent_output[f.get("agent", "unknown")] += 1

    expected_agents = [
        "growth-foundation", "store-setup", "catalog-migration-planner",
        "price-auditor", "sns-manager", "content-strategist",
        "competitive-intelligence", "blog-analyst", "self-learning",
        "project-orchestrator",
    ]

    silent_agents = [a for a in expected_agents if agent_output.get(a, 0) == 0]
    if silent_agents:
        issues.append(_make_issue(
            "agent", "Silent agents detected",
            "No output from: %s" % ", ".join(silent_agents),
            "These agents' inspections may have failed or been skipped",
            "Module import error, API timeout, or logic skip",
            "project-orchestrator", "high",
        ))

    # shared_state の更新停止チェック
    ss = _load_json("shared_state.json")
    if ss:
        last = ss.get("last_updated", "")
        if _days_since(last) > 3:
            issues.append(_make_issue(
                "agent", "shared_state update stopped",
                "Last updated: %s (%d days)" % (last, _days_since(last)),
                "Agent coordination using stale focus/weights",
                "Weekly focus or learning update not running",
                "project-orchestrator", "medium",
            ))

    return issues


# ============================================================
# 6. 再発監視
# ============================================================

def _check_recurrence(current_issues, bug_log):
    """既存の異常と比較して、新規/継続/解消を判定"""
    existing = {i["key"]: i for i in bug_log.get("issues", [])}
    new_issues = []
    continuing = []
    resolved = []

    current_keys = set()
    for issue in current_issues:
        key = issue["key"]
        current_keys.add(key)

        if key in existing:
            # 継続中
            prev = existing[key]
            days = _days_since(prev.get("detected_date", NOW.strftime("%Y-%m-%d"))) + 1
            issue["status"] = "continuing"
            issue["consecutive_days"] = days
            issue["first_detected"] = prev.get("first_detected", prev.get("detected_date", ""))
            continuing.append(issue)
        else:
            # 新規
            issue["status"] = "new"
            issue["consecutive_days"] = 1
            issue["first_detected"] = NOW.strftime("%Y-%m-%d")
            new_issues.append(issue)

    # 解消された異常
    for key, prev in existing.items():
        if key not in current_keys:
            prev["status"] = "resolved"
            prev["resolved_date"] = NOW.strftime("%Y-%m-%d")
            resolved.append(prev)

    return new_issues, continuing, resolved


# ============================================================
# 7. メイン: レポート生成
# ============================================================

def generate_bug_audit(all_findings):
    """バグ・異常監査レポートを生成"""
    result_findings = []
    bug_log = _load_bug_log()

    # === 全異常を収集 ===
    all_issues = []
    all_issues.extend(_audit_api(all_findings))
    all_issues.extend(_audit_automation(all_findings))
    all_issues.extend(_audit_data())
    all_issues.extend(_audit_quality(all_findings))
    all_issues.extend(_audit_agents(all_findings))

    # === 再発監視 ===
    new_issues, continuing, resolved = _check_recurrence(all_issues, bug_log)

    # === サマリ ===
    total = len(new_issues) + len(continuing)
    critical_count = sum(1 for i in all_issues if i["priority"] == "critical")
    high_count = sum(1 for i in all_issues if i["priority"] == "high")

    summary_details = [
        "=== Bug & Anomaly Audit ===",
        "Total: %d issues (%d new, %d continuing, %d resolved)" % (total, len(new_issues), len(continuing), len(resolved)),
        "Critical: %d, High: %d, Medium: %d, Low: %d" % (
            critical_count, high_count,
            sum(1 for i in all_issues if i["priority"] == "medium"),
            sum(1 for i in all_issues if i["priority"] == "low"),
        ),
    ]

    # 新規異常
    if new_issues:
        summary_details.append("")
        summary_details.append("--- NEW Issues ---")
        for i in sorted(new_issues, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["priority"], 4)):
            summary_details.append(
                "[%s] [%s] [%s] %s" % (i["priority"].upper(), i["category"], i["agent"], i["name"])
            )
            summary_details.append("  Detail: %s" % i["detail"][:80])
            summary_details.append("  Impact: %s" % i["impact"][:80])

    # 継続異常
    if continuing:
        summary_details.append("")
        summary_details.append("--- CONTINUING Issues ---")
        for i in sorted(continuing, key=lambda x: -x.get("consecutive_days", 0)):
            summary_details.append(
                "[%s] [%dd] [%s] %s" % (i["priority"].upper(), i.get("consecutive_days", 1), i["agent"], i["name"])
            )

    # 解消
    if resolved:
        summary_details.append("")
        summary_details.append("--- RESOLVED ---")
        for i in resolved[:5]:
            summary_details.append("[RESOLVED] %s (was %s)" % (i["name"], i["priority"]))

    # findings に追加
    severity = "critical" if critical_count > 0 else "suggestion" if high_count > 0 else "info" if total > 0 else "ok"
    result_findings.append({
        "type": severity,
        "agent": "project-orchestrator",
        "message": "Bug audit: %d issues (%d new, %d continuing, %d resolved)" % (total, len(new_issues), len(continuing), len(resolved)),
        "details": summary_details,
    })

    # 品質異常カウント（別finding）
    quality_issues = [i for i in all_issues if i["category"] == "quality"]
    if quality_issues:
        q_details = ["=== Quality Anomaly Count ==="]
        for qi in quality_issues:
            q_details.append("[%s] %s: %s" % (qi["priority"].upper(), qi["name"], qi["detail"][:60]))
        result_findings.append({
            "type": "suggestion" if quality_issues else "ok",
            "agent": "blog-analyst",
            "message": "Quality anomalies: %d issues detected" % len(quality_issues),
            "details": q_details,
        })

    # === ログ保存 ===
    bug_log["issues"] = new_issues + continuing
    bug_log["resolved"].extend(resolved)
    _save_bug_log(bug_log)

    return result_findings
