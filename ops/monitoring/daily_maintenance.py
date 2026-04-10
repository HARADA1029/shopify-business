# ============================================================
# 日次メンテナンスモジュール
#
# 日次レポート生成後に実行し、自己学習機能そのものを
# 監査・補強・改善する。
#
# 7つの監査:
# 1. proposal_history 監査
# 2. experiments 監査
# 3. research_log 監査
# 4. weight_adjustment_log 監査
# 5. API / 接続監査
# 6. ログ不足監査
# 7. 不足項目の自動補強
#
# 追加監査:
# - 重み調整妥当性
# - 負けパターン学習
# - 商品改善優先順位
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

MAINTENANCE_LOG = os.path.join(SCRIPT_DIR, "maintenance_log.json")


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
    path = os.path.join(SCRIPT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _days_since(date_str):
    if not date_str:
        return 999
    try:
        return (NOW.replace(tzinfo=None) - datetime.strptime(date_str[:10], "%Y-%m-%d")).days
    except ValueError:
        return 999


def _token_exists(f):
    return os.path.exists(os.path.join(PROJECT_ROOT, f))


# ============================================================
# 1. proposal_history 監査
# ============================================================

def _audit_proposals():
    issues = []
    fixes = []
    pt = _load_json("proposal_tracking.json")
    if not pt:
        issues.append("[CRITICAL] proposal_tracking.json missing")
        return issues, fixes

    proposals = pt.get("proposals", [])
    today = NOW.strftime("%Y-%m-%d")

    # 新規追加チェック
    today_new = sum(1 for p in proposals if p.get("date") == today)
    if today_new == 0:
        issues.append("[WARN] No new proposals added today")

    # stale (14日以上 pending)
    stale = [p for p in proposals if p.get("status") == "pending" and _days_since(p.get("date", "")) > 14]
    if stale:
        issues.append("[WARN] %d stale proposals (pending >14d)" % len(stale))
        # 自動補強: stale を expired に
        for p in stale:
            p["status"] = "expired"
        fixes.append("Expired %d stale proposals" % len(stale))

    # 採用済みで結果未記録 (7日以上)
    no_result = [p for p in proposals if p.get("status") == "adopted" and not p.get("result") and _days_since(p.get("adopted_date", "")) > 7]
    if no_result:
        issues.append("[WARN] %d adopted proposals without result (>7d)" % len(no_result))

    # next_action 未記入
    no_next = sum(1 for p in proposals if p.get("result") and not p.get("next_action"))
    if no_next > 0:
        issues.append("[INFO] %d results without next_action" % no_next)

    if fixes:
        pt["summary"]["last_updated"] = today
        _save_json("proposal_tracking.json", pt)

    return issues, fixes


# ============================================================
# 2. experiments 監査
# ============================================================

def _audit_experiments():
    issues = []
    fixes = []
    exp = _load_json("experiment_log.json")
    if not exp:
        issues.append("[WARN] experiment_log.json missing")
        return issues, fixes

    active = [e for e in exp.get("experiments", []) if e.get("status") == "running"]

    # 期限切れ未判定
    expired = [e for e in active if _days_since(e.get("end_date", "")) > 0]
    if expired:
        issues.append("[WARN] %d experiments past end date without judgment" % len(expired))
        for e in expired:
            e["status"] = "review_needed"
        fixes.append("Marked %d experiments as review_needed" % len(expired))

    # 成功条件なし
    no_condition = [e for e in active if not e.get("success_condition")]
    if no_condition:
        issues.append("[WARN] %d experiments without success_condition" % len(no_condition))

    # 活動実験ゼロ
    if not active and not expired:
        issues.append("[INFO] No active experiments — consider registering new ones")

    if fixes:
        exp["last_updated"] = NOW.strftime("%Y-%m-%d")
        _save_json("experiment_log.json", exp)

    return issues, fixes


# ============================================================
# 3. research_log 監査
# ============================================================

def _audit_research():
    issues = []
    rl = _load_json("research_log.json")
    if not rl:
        issues.append("[WARN] research_log.json missing")
        return issues, []

    entries = rl.get("entries", [])
    today = NOW.strftime("%Y-%m-%d")
    today_entries = sum(1 for e in entries if e.get("date") == today)
    agents = set(e.get("agent", "") for e in entries)

    if today_entries == 0:
        issues.append("[WARN] No research entries today")
    if len(agents) < 3:
        issues.append("[WARN] Only %d agents in research_log (need 3+)" % len(agents))

    # stale (7日以上エントリなし)
    if entries:
        latest = max(e.get("date", "") for e in entries)
        if _days_since(latest) > 3:
            issues.append("[WARN] research_log stale (last: %s)" % latest)

    return issues, []


# ============================================================
# 4. weight_adjustment_log 監査
# ============================================================

def _audit_weights():
    issues = []
    ss = _load_json("shared_state.json")
    if not ss:
        issues.append("[WARN] shared_state.json missing")
        return issues, []

    log = ss.get("weight_adjustment_log", [])
    weights = ss.get("scoring_weights", {})

    # stale チェック
    if not log:
        issues.append("[INFO] No weight adjustments recorded yet")
    elif _days_since(log[-1].get("date", "")) > 7:
        issues.append("[INFO] Weight adjustments stale (last: %s)" % log[-1].get("date", "?"))

    # 偏りチェック
    if weights:
        values = [v for v in weights.values() if isinstance(v, (int, float))]
        if values:
            max_w = max(values)
            min_w = min(values)
            if max_w > min_w * 4:
                issues.append("[WARN] Weight imbalance: max=%.1f min=%.1f (ratio %.1f)" % (max_w, min_w, max_w / max(min_w, 0.1)))

    return issues, []


# ============================================================
# 5. API / 接続監査
# ============================================================

def _audit_api():
    issues = []
    tokens = {
        "Shopify": ".shopify_token.json",
        "Instagram": ".instagram_token.json",
        "Pinterest": ".pinterest_token.json",
        "YouTube": ".youtube_token.json",
        "eBay": ".ebay_token.json",
    }
    for name, f in tokens.items():
        if not _token_exists(f):
            if name in ("Shopify", "Instagram"):
                issues.append("[HIGH] %s token missing" % name)
            else:
                issues.append("[MEDIUM] %s token missing" % name)

    # GCP
    gcp = os.environ.get("GCP_KEY_FILE", "")
    if not gcp and not os.path.exists(os.path.join(PROJECT_ROOT, ".gcp_service_account.json")):
        if not os.environ.get("GITHUB_ACTIONS"):
            issues.append("[MEDIUM] GCP key missing (GA4/SC affected)")

    return issues, []


# ============================================================
# 6. ログ不足監査
# ============================================================

def _audit_logs():
    issues = []
    log_files = {
        "price_sync_log.json": ("price-auditor", "Price sync history"),
        "image_sync_log.json": ("catalog-migration-planner", "Image sync history"),
        "blog_state.json": ("blog-analyst", "Blog PDCA state"),
        "sns_posted.json": ("sns-manager", "SNS posting history"),
        "adoption_tracking.json": ("catalog-migration-planner", "Adoption tracking"),
        "design_audit_log.json": ("store-setup", "Design audit history"),
        "bug_audit_log.json": ("project-orchestrator", "Bug tracking"),
        "sns_learning.json": ("sns-manager", "SNS learning state"),
    }

    for filename, (agent, desc) in log_files.items():
        data = _load_json(filename)
        if data is None:
            issues.append("[WARN] %s missing (%s)" % (filename, desc))
        elif isinstance(data, dict):
            updated = data.get("last_updated", data.get("_last_updated", data.get("last_run", "")))
            if _days_since(updated) > 3:
                issues.append("[INFO] %s stale (last: %s)" % (filename, updated or "never"))

    return issues, []


# ============================================================
# 7. 負けパターン学習
# ============================================================

def _analyze_loss_patterns():
    """no_reaction / reaction_only の共通点を分析"""
    findings_details = []
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return findings_details

    proposals = pt.get("proposals", [])
    no_reaction = [p for p in proposals if p.get("result") in ("no_reaction", "failed")]
    reaction_only = [p for p in proposals if p.get("result") in ("reaction_only", "weak")]

    if no_reaction:
        types = Counter(p.get("type", "?") for p in no_reaction)
        findings_details.append("--- No Reaction patterns (%d) ---" % len(no_reaction))
        for t, c in types.most_common(3):
            findings_details.append("  [%s] %d times" % (t, c))

    if reaction_only:
        types = Counter(p.get("type", "?") for p in reaction_only)
        findings_details.append("--- Reaction Only patterns (%d) ---" % len(reaction_only))
        for t, c in types.most_common(3):
            findings_details.append("  [%s] %d times" % (t, c))

    # 同じ失敗の繰り返しチェック
    repeated = [t for t, c in Counter(p.get("type", "") for p in no_reaction).items() if c >= 3]
    if repeated:
        findings_details.append("ALERT: Repeated failures in: %s → reduce weight or change criteria" % ", ".join(repeated))

    return findings_details


# ============================================================
# 8. 不足項目の自動補強
# ============================================================

def _auto_reinforce(all_issues):
    """不足項目を自動で補強提案として登録"""
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return []

    import hashlib
    existing = set(p.get("message_hash", "") for p in pt.get("proposals", []))
    added = []

    for issue in all_issues:
        if "[CRITICAL]" in issue or "[HIGH]" in issue:
            msg_hash = hashlib.md5(("maint:" + issue[:50]).encode()).hexdigest()[:10]
            if msg_hash in existing:
                continue

            pt["proposals"].append({
                "id": "P-%s-mnt" % NOW.strftime("%y%m%d"),
                "message_hash": msg_hash,
                "date": NOW.strftime("%Y-%m-%d"),
                "agent": "project-orchestrator",
                "type": "page_improvement",
                "message": "Auto-maintenance: %s" % issue[:100],
                "score": 20,
                "status": "pending",
                "adopted_date": None, "result": None, "result_date": None, "next_action": None,
            })
            added.append(issue[:80])

    if added:
        pt["summary"]["total"] = len(pt["proposals"])
        pt["summary"]["pending"] = sum(1 for p in pt["proposals"] if p.get("status") == "pending")
        pt["summary"]["last_updated"] = NOW.strftime("%Y-%m-%d")
        _save_json("proposal_tracking.json", pt)

    return added


# ============================================================
# メイン: 日次メンテナンス実行
# ============================================================

def run_daily_maintenance():
    """日次メンテナンスを実行し findings を返す"""
    result_findings = []
    all_issues = []
    all_fixes = []

    # 7つの監査
    i1, f1 = _audit_proposals()
    i2, f2 = _audit_experiments()
    i3, f3 = _audit_research()
    i4, f4 = _audit_weights()
    i5, f5 = _audit_api()
    i6, f6 = _audit_logs()

    all_issues = i1 + i2 + i3 + i4 + i5 + i6
    all_fixes = f1 + f2 + f3 + f4 + f5 + f6

    # 負けパターン
    loss_details = _analyze_loss_patterns()

    # 自動補強
    reinforced = _auto_reinforce(all_issues)

    # 状態判定
    critical = sum(1 for i in all_issues if "[CRITICAL]" in i or "[HIGH]" in i)
    warnings = sum(1 for i in all_issues if "[WARN]" in i)
    info = sum(1 for i in all_issues if "[INFO]" in i)

    if critical > 0:
        status = "requires_attention"
    elif warnings > 0:
        status = "needs_reinforcement"
    elif all_issues:
        status = "minor_gaps"
    else:
        status = "healthy"

    # === メンテナンス結果 ===
    details = [
        "=== Daily Maintenance Result: %s ===" % status.upper(),
        "Issues: %d critical, %d warnings, %d info" % (critical, warnings, info),
        "Auto-fixes applied: %d" % len(all_fixes),
        "Auto-reinforced proposals: %d" % len(reinforced),
    ]

    if all_issues:
        details.append("")
        details.append("--- Issues Found ---")
        for i in all_issues:
            details.append(i)

    if all_fixes:
        details.append("")
        details.append("--- Auto-Fixes Applied ---")
        for f in all_fixes:
            details.append("FIXED: %s" % f)

    if reinforced:
        details.append("")
        details.append("--- Auto-Reinforced ---")
        for r in reinforced:
            details.append("ADDED: %s" % r)

    if loss_details:
        details.append("")
        details.extend(loss_details)

    severity = "suggestion" if critical > 0 else "info"
    result_findings.append({
        "type": severity,
        "agent": "project-orchestrator",
        "message": "Daily maintenance: %s (%d issues, %d fixes, %d reinforced)" % (status, len(all_issues), len(all_fixes), len(reinforced)),
        "details": details,
    })

    # メンテナンスログ保存
    log = _load_json("maintenance_log.json") or {"runs": []}
    log["runs"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "status": status,
        "issues": len(all_issues),
        "fixes": len(all_fixes),
        "reinforced": len(reinforced),
    })
    log["runs"] = log["runs"][-30:]
    log["last_updated"] = NOW.strftime("%Y-%m-%d")
    _save_json("maintenance_log.json", log)

    return result_findings
