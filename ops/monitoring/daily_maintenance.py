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

# needs_reinforcement 判定基準（数値固定）
REINFORCEMENT_THRESHOLDS = {
    "stale_proposals_min": 3,         # pending>14日が3件以上で要補強
    "no_result_adopted_min": 2,       # 採用済み結果なしが2件以上
    "missing_log_files_min": 2,       # ログ欠損が2ファイル以上
    "stale_log_files_min": 3,         # staleログが3ファイル以上
    "api_high_missing_min": 1,        # HIGH APIが1件以上欠損
    "no_today_proposals": True,       # 今日の提案が0件
    "no_active_experiments": True,    # 活動実験が0件
}


def _judge_reinforcement_need(all_issues):
    """needs_reinforcement を数値基準で判定"""
    counts = {
        "stale_proposals": sum(1 for i in all_issues if "stale proposals" in i.lower()),
        "no_result": sum(1 for i in all_issues if "without result" in i.lower()),
        "missing_logs": sum(1 for i in all_issues if "missing" in i.lower() and ".json" in i.lower()),
        "stale_logs": sum(1 for i in all_issues if "stale" in i.lower() and ".json" in i.lower()),
        "api_high": sum(1 for i in all_issues if "[HIGH]" in i and "token" in i.lower()),
        "no_proposals_today": any("No new proposals" in i for i in all_issues),
        "no_experiments": any("No active experiments" in i for i in all_issues),
    }

    triggers = []
    if counts["stale_proposals"] >= REINFORCEMENT_THRESHOLDS["stale_proposals_min"]:
        triggers.append("stale_proposals(%d)" % counts["stale_proposals"])
    if counts["no_result"] >= REINFORCEMENT_THRESHOLDS["no_result_adopted_min"]:
        triggers.append("no_result_adopted(%d)" % counts["no_result"])
    if counts["missing_logs"] >= REINFORCEMENT_THRESHOLDS["missing_log_files_min"]:
        triggers.append("missing_logs(%d)" % counts["missing_logs"])
    if counts["stale_logs"] >= REINFORCEMENT_THRESHOLDS["stale_log_files_min"]:
        triggers.append("stale_logs(%d)" % counts["stale_logs"])
    if counts["api_high"] >= REINFORCEMENT_THRESHOLDS["api_high_missing_min"]:
        triggers.append("api_missing(%d)" % counts["api_high"])

    return triggers


def _analyze_loss_patterns():
    """no_reaction / reaction_only の共通点を提案タイプ別・カテゴリ別に分析"""
    findings_details = []
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return findings_details

    proposals = pt.get("proposals", [])
    no_reaction = [p for p in proposals if p.get("result") in ("no_reaction", "failed")]
    reaction_only = [p for p in proposals if p.get("result") in ("reaction_only", "weak")]

    # タイプ別分解
    if no_reaction:
        types = Counter(p.get("type", "?") for p in no_reaction)
        findings_details.append("--- No Reaction by type (%d total) ---" % len(no_reaction))
        for t, c in types.most_common(5):
            examples = [p.get("message", "")[:40] for p in no_reaction if p.get("type") == t][:2]
            findings_details.append("  [%s] %d times" % (t, c))
            for ex in examples:
                findings_details.append("    ex: %s" % ex)

    if reaction_only:
        types = Counter(p.get("type", "?") for p in reaction_only)
        findings_details.append("--- Reaction Only by type (%d total) ---" % len(reaction_only))
        for t, c in types.most_common(5):
            examples = [p.get("message", "")[:40] for p in reaction_only if p.get("type") == t][:2]
            findings_details.append("  [%s] %d times" % (t, c))
            for ex in examples:
                findings_details.append("    ex: %s" % ex)

    # カテゴリ別分解（メッセージからカテゴリを推定）
    all_losses = no_reaction + reaction_only
    if all_losses:
        cat_keywords = {
            "Trading Cards": ["card", "pokemon card", "tcg"],
            "Action Figures": ["figure", "figuarts", "beyblade"],
            "Scale Figures": ["scale", "nendoroid", "banpresto"],
            "Electronic Toys": ["tamagotchi", "electronic", "digivice"],
            "Video Games": ["game", "playstation", "nintendo"],
        }
        cat_losses = Counter()
        for p in all_losses:
            msg = p.get("message", "").lower()
            for cat, kws in cat_keywords.items():
                if any(kw in msg for kw in kws):
                    cat_losses[cat] += 1
                    break

        if cat_losses:
            findings_details.append("--- Loss by category ---")
            for cat, c in cat_losses.most_common():
                findings_details.append("  [%s] %d losses" % (cat, c))

    # 繰り返し失敗
    repeated = [t for t, c in Counter(p.get("type", "") for p in no_reaction).items() if c >= 3]
    if repeated:
        findings_details.append("ALERT: Repeated failures in: %s → reduce weight or change criteria" % ", ".join(repeated))

    # 失敗共通点の抽出
    if all_losses:
        common = []
        high_price = sum(1 for p in all_losses if "$500" in p.get("message", "") or "high" in p.get("message", "").lower())
        niche = sum(1 for p in all_losses if any(kw in p.get("message", "").lower() for kw in ["goods", "media", "book"]))
        if high_price > 1:
            common.append("High-price items tend to fail (%d cases)" % high_price)
        if niche > 1:
            common.append("Niche categories tend to fail (%d cases)" % niche)
        if common:
            findings_details.append("--- Common failure factors ---")
            findings_details.extend(common)

    # === 保留 / 抑制 / 禁止候補の判定 ===
    findings_details.append("")
    findings_details.append("--- Action Recommendations ---")

    type_fail_counts = Counter(p.get("type", "") for p in all_losses)
    type_total_counts = Counter(p.get("type", "") for p in proposals if p.get("status") != "pending")

    for ptype, fail_count in type_fail_counts.most_common():
        total = type_total_counts.get(ptype, fail_count)
        fail_rate = fail_count / max(total, 1)

        if fail_count >= 5 and fail_rate >= 0.8:
            findings_details.append("[PROHIBIT] %s: %d/%d failed (%.0f%%) → stop proposing this type" % (ptype, fail_count, total, fail_rate * 100))
        elif fail_count >= 3 and fail_rate >= 0.6:
            findings_details.append("[SUPPRESS] %s: %d/%d failed (%.0f%%) → reduce weight by 50%%" % (ptype, fail_count, total, fail_rate * 100))
        elif fail_count >= 2 and fail_rate >= 0.5:
            findings_details.append("[HOLD] %s: %d/%d failed (%.0f%%) → pause and review criteria" % (ptype, fail_count, total, fail_rate * 100))

    # カテゴリ別失敗傾向 → shared_state に反映
    if cat_losses:
        _apply_category_failure_weights(dict(cat_losses))

    return findings_details


def _apply_category_failure_weights(cat_losses):
    """カテゴリ別失敗傾向をshared_stateのscoring_weightsに反映"""
    ss = _load_json("shared_state.json")
    if not ss:
        return

    # 保守モードチェック
    try:
        from safety_audit import is_maintenance_mode
        if is_maintenance_mode():
            return
    except ImportError:
        pass

    adjusted = False
    cat_weights = ss.setdefault("category_failure_weights", {})

    for cat, fail_count in cat_losses.items():
        current = cat_weights.get(cat, 1.0)
        if fail_count >= 3:
            new_weight = max(current - 0.3, 0.3)
            cat_weights[cat] = round(new_weight, 1)
            adjusted = True
        elif fail_count >= 2:
            new_weight = max(current - 0.1, 0.5)
            cat_weights[cat] = round(new_weight, 1)
            adjusted = True

    if adjusted:
        ss["category_failure_weights"] = cat_weights
        ss.setdefault("weight_adjustment_log", []).append({
            "date": NOW.strftime("%Y-%m-%d"),
            "adjustments": ["Category failure weights updated: %s" % str(cat_weights)],
        })
        _save_json("shared_state.json", ss)


def _register_infra_task(causes):
    """基盤問題をproposal品質とは別枠で追跡"""
    infra_log_path = os.path.join(SCRIPT_DIR, "infra_tasks.json")
    try:
        if os.path.exists(infra_log_path):
            with open(infra_log_path, "r", encoding="utf-8") as f:
                infra = json.load(f)
        else:
            infra = {"tasks": [], "last_updated": ""}
    except (json.JSONDecodeError, IOError):
        infra = {"tasks": [], "last_updated": ""}

    today = NOW.strftime("%Y-%m-%d")
    existing_types = set(t.get("type", "") for t in infra["tasks"] if t.get("status") == "open")

    if causes.get("platform_skip", 0) > 0 and "platform_skip" not in existing_types:
        infra["tasks"].append({
            "type": "platform_skip",
            "description": "SNS platform posting failure — workflow not executing or API error",
            "priority": "high",
            "status": "open",
            "agent": "sns-manager",
            "created": today,
            "updated": today,
            "count": causes["platform_skip"],
            "fix": "Check GitHub Actions workflow logs for sns-auto-post and sns-video-post",
        })

    if causes.get("token_issue", 0) > 0 and "token_issue" not in existing_types:
        infra["tasks"].append({
            "type": "token_issue",
            "description": "SNS API token/authentication failure",
            "priority": "high",
            "status": "open",
            "agent": "sns-manager",
            "created": today,
            "updated": today,
            "count": causes["token_issue"],
            "fix": "Refresh or re-create API token for affected platform",
        })

    # 既存タスクのカウント更新
    for t in infra["tasks"]:
        if t.get("status") == "open":
            if t["type"] == "platform_skip" and causes.get("platform_skip", 0) > 0:
                t["count"] = t.get("count", 0) + causes["platform_skip"]
                t["updated"] = today
            elif t["type"] == "token_issue" and causes.get("token_issue", 0) > 0:
                t["count"] = t.get("count", 0) + causes["token_issue"]
                t["updated"] = today

    infra["last_updated"] = today
    # 30日以上解決済みのものを削除
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    infra["tasks"] = [t for t in infra["tasks"] if t.get("status") == "open" or t.get("updated", "") >= cutoff]

    with open(infra_log_path, "w", encoding="utf-8") as f:
        json.dump(infra, f, indent=2, ensure_ascii=False)


def _analyze_warning_trends():
    """warning件数の7日推移、高再発warningの自動昇格、優先修正対象の特定"""
    trend_details = []
    recurrence_details = []
    auto_promoted = []

    pt = _load_json("proposal_tracking.json")
    if not pt:
        return trend_details, recurrence_details, auto_promoted

    warnings = pt.get("consistency_warnings", [])
    if not warnings:
        return trend_details, recurrence_details, auto_promoted

    # === 7日推移 ===
    today = NOW.strftime("%Y-%m-%d")
    seven_days_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")

    # 日別warning件数を集計
    daily_counts = Counter()
    for w in warnings:
        last = w.get("last_seen", "")
        if last >= seven_days_ago:
            daily_counts[last] += 1

    trend_details.append("--- Warning 7-Day Trend ---")
    for i in range(7):
        d = (NOW - timedelta(days=6-i)).strftime("%Y-%m-%d")
        count = daily_counts.get(d, 0)
        bar = "*" * min(count, 10)
        trend_details.append("[%s] %d %s" % (d, count, bar))

    total_7d = sum(daily_counts.values())
    trend_details.append("Total (7d): %d warnings" % total_7d)

    # === 高再発warningの検出 ===
    high_recurrence = [w for w in warnings if w.get("count", 0) >= 3]

    if high_recurrence:
        recurrence_details.append("--- High Recurrence Warnings (3+ times) ---")
        for w in sorted(high_recurrence, key=lambda x: -x.get("count", 0)):
            recurrence_details.append(
                "[%dx] %s (first:%s last:%s)" % (
                    w["count"], w["warning"][:60], w.get("first_seen", "?"), w.get("last_seen", "?")))

        # === 自動昇格: 再発5回以上のwarningをproposal_trackingに改善提案として登録 ===
        import hashlib
        existing_hashes = set(p.get("message_hash", "") for p in pt.get("proposals", []))

        for w in high_recurrence:
            if w.get("count", 0) >= 5:
                msg_hash = hashlib.md5(("warn-promote:" + w["warning"][:50]).encode()).hexdigest()[:10]
                if msg_hash in existing_hashes:
                    continue

                pt["proposals"].append({
                    "id": "P-%s-wrn" % NOW.strftime("%y%m%d"),
                    "message_hash": msg_hash,
                    "date": today,
                    "agent": "project-orchestrator",
                    "type": "page_improvement",
                    "message": "Auto-promoted warning (%dx): %s" % (w["count"], w["warning"][:80]),
                    "score": 22,
                    "status": "pending",
                    "adopted_date": None, "result": None, "result_date": None,
                    "next_action": "Fix root cause to prevent recurrence",
                })
                auto_promoted.append("Promoted warning (%dx): %s" % (w["count"], w["warning"][:50]))

        if auto_promoted:
            pt["summary"]["total"] = len(pt["proposals"])
            pt["summary"]["pending"] = sum(1 for p in pt["proposals"] if p.get("status") == "pending")
            pt["summary"]["last_updated"] = today
            _save_json("proposal_tracking.json", pt)

    # === warning が多い提案タイプを特定 ===
    type_keywords = {
        "sns_post": ["sns", "instagram", "facebook", "post"],
        "article_theme": ["article", "blog", "write"],
        "category_gap": ["category", "gap", "strengthen"],
        "page_improvement": ["page", "trust", "description", "image"],
    }

    warning_by_type = Counter()
    for w in warnings:
        msg = w.get("warning", "").lower()
        for ptype, kws in type_keywords.items():
            if any(kw in msg for kw in kws):
                warning_by_type[ptype] += w.get("count", 1)
                break

    if warning_by_type:
        recurrence_details.append("")
        recurrence_details.append("--- Warnings by Proposal Type ---")
        for ptype, count in warning_by_type.most_common():
            marker = "PRIORITY-FIX" if count >= 5 else "MONITOR"
            recurrence_details.append("[%s] %s: %d warnings" % (marker, ptype, count))

    # === sns_post warning の原因別分解 ===
    sns_warnings = [w for w in warnings if any(kw in w.get("warning", "").lower() for kw in ["sns", "instagram", "facebook", "post", "video"])]
    if sns_warnings:
        recurrence_details.append("")
        recurrence_details.append("--- sns_post Warning Breakdown ---")

        causes = {"expired_conflict": 0, "platform_skip": 0, "engagement_low": 0, "token_issue": 0, "other": 0}
        for w in sns_warnings:
            msg = w.get("warning", "").lower()
            count = w.get("count", 1)
            if "expired" in msg and "new proposal" in msg:
                causes["expired_conflict"] += count
            elif "skip" in msg or "not posted" in msg or "missing" in msg:
                causes["platform_skip"] += count
            elif "engagement" in msg or "reaction" in msg or "weak" in msg:
                causes["engagement_low"] += count
            elif "token" in msg or "auth" in msg:
                causes["token_issue"] += count
            else:
                causes["other"] += count

        # 提案品質問題と基盤問題を分離
        proposal_issues = causes["expired_conflict"] + causes["engagement_low"] + causes["other"]
        infra_issues = causes["platform_skip"] + causes["token_issue"]

        recurrence_details.append("Proposal quality issues: %d" % proposal_issues)
        if causes["expired_conflict"] > 0:
            recurrence_details.append("  [%d] Expired-then-reproposed (proposal logic fix applied)" % causes["expired_conflict"])
        if causes["engagement_low"] > 0:
            recurrence_details.append("  [%d] Low engagement (content/targeting issue)" % causes["engagement_low"])
        if causes["other"] > 0:
            recurrence_details.append("  [%d] Other proposal issues" % causes["other"])

        recurrence_details.append("Infrastructure issues: %d (tracked separately)" % infra_issues)
        if causes["platform_skip"] > 0:
            recurrence_details.append("  [%d] Platform skip → check workflow execution" % causes["platform_skip"])
        if causes["token_issue"] > 0:
            recurrence_details.append("  [%d] Token/auth → check API credentials" % causes["token_issue"])

        # 基盤問題を別タスクとして追跡
        if infra_issues > 0:
            _register_infra_task(causes)

    # === article_theme 悪化予防 ===
    article_warnings = [w for w in warnings if any(kw in w.get("warning", "").lower() for kw in ["article", "blog", "write", "content"])]
    article_total = sum(w.get("count", 1) for w in article_warnings)

    if article_total >= 2 and article_total < 5:
        recurrence_details.append("")
        recurrence_details.append("--- article_theme Preventive Alert ---")
        recurrence_details.append("[PREVENT] article_theme has %d warnings (threshold for auto-promote: 5)" % article_total)
        recurrence_details.append("  Recommended: review blog generation criteria before warnings escalate")
        recurrence_details.append("  Check: image insertion, category setting, CTA placement, content depth")

        # 予防修正: blog_quality_baseline を再確認するよう提案
        import hashlib
        prevent_hash = hashlib.md5(("prevent-article:%s" % NOW.strftime("%Y-%m-%d")).encode()).hexdigest()[:10]
        existing_hashes = set(p.get("message_hash", "") for p in pt.get("proposals", []))
        if prevent_hash not in existing_hashes:
            pt["proposals"].append({
                "id": "P-%s-prev" % NOW.strftime("%y%m%d"),
                "message_hash": prevent_hash,
                "date": NOW.strftime("%Y-%m-%d"),
                "agent": "blog-analyst",
                "type": "article_theme",
                "message": "Preventive: article_theme warnings rising (%d) — review quality criteria" % article_total,
                "score": 18,
                "status": "pending",
                "adopted_date": None, "result": None, "result_date": None,
                "next_action": "Verify blog_auto_post.py quality gate and Gemini prompt",
            })
            pt["summary"]["total"] = len(pt["proposals"])
            pt["summary"]["pending"] = sum(1 for p in pt["proposals"] if p.get("status") == "pending")
            pt["summary"]["last_updated"] = NOW.strftime("%Y-%m-%d")
            _save_json("proposal_tracking.json", pt)
            auto_promoted.append("Preventive proposal for article_theme (warnings: %d)" % article_total)

    return trend_details, recurrence_details, auto_promoted


def _record_consistency_warnings(inconsistencies):
    """整合性警告をproposal_trackingに記録し再発を追跡"""
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return

    # 既存の警告履歴
    warnings_log = pt.setdefault("consistency_warnings", [])
    today = NOW.strftime("%Y-%m-%d")

    for ic in inconsistencies:
        # 同じ警告が過去にあるかチェック
        existing = [w for w in warnings_log if w.get("warning", "")[:50] == ic[:50]]
        if existing:
            existing[0]["count"] = existing[0].get("count", 1) + 1
            existing[0]["last_seen"] = today
        else:
            warnings_log.append({
                "warning": ic[:150],
                "first_seen": today,
                "last_seen": today,
                "count": 1,
            })

    # 30日以上見ていないものは削除
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    pt["consistency_warnings"] = [w for w in warnings_log if w.get("last_seen", "") >= cutoff]

    pt["summary"]["last_updated"] = today
    _save_json("proposal_tracking.json", pt)


def _check_fix_consistency(all_issues, all_fixes):
    """自動修正が次回提案と矛盾しないか整合性チェック"""
    inconsistencies = []

    # expired にした提案と同じタイプの新規提案が同日にないか
    pt = _load_json("proposal_tracking.json")
    if not pt:
        return inconsistencies

    today = NOW.strftime("%Y-%m-%d")
    today_expired_types = set(
        p.get("type", "") for p in pt.get("proposals", [])
        if p.get("status") == "expired" and p.get("date", "") == today
    )
    today_new_same_type = [
        p for p in pt.get("proposals", [])
        if p.get("status") == "pending" and p.get("date", "") == today
        and p.get("type", "") in today_expired_types
    ]

    if today_new_same_type:
        for p in today_new_same_type:
            inconsistencies.append(
                "[WARN] Auto-expired type '%s' but new proposal of same type added today: %s"
                % (p.get("type", ""), p.get("message", "")[:40])
            )

    return inconsistencies


# ============================================================
# 8. 不足項目の自動補強
# ============================================================

def _auto_reinforce(all_issues):
    """不足項目を自動で補強提案として登録（保守モード時は停止）"""
    try:
        from safety_audit import is_maintenance_mode
        if is_maintenance_mode():
            return ["SKIPPED: maintenance mode active — auto-reinforcement suspended"]
    except ImportError:
        pass

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

    # 整合性チェック
    inconsistencies = _check_fix_consistency(all_issues, all_fixes)

    # 状態判定（数値基準）
    critical = sum(1 for i in all_issues if "[CRITICAL]" in i or "[HIGH]" in i)
    warnings = sum(1 for i in all_issues if "[WARN]" in i)
    info = sum(1 for i in all_issues if "[INFO]" in i)

    reinforcement_triggers = _judge_reinforcement_need(all_issues)

    if critical > 0:
        status = "requires_attention"
    elif reinforcement_triggers:
        status = "needs_reinforcement"
    elif warnings > 0:
        status = "minor_gaps"
    else:
        status = "healthy"

    # === メンテナンス結果 ===
    details = [
        "=== Daily Maintenance Result: %s ===" % status.upper(),
        "Issues: %d critical, %d warnings, %d info" % (critical, warnings, info),
        "Auto-fixes applied: %d" % len(all_fixes),
        "Auto-reinforced proposals: %d" % len(reinforced),
        "Consistency warnings: %d" % len(inconsistencies),
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

    if reinforcement_triggers:
        details.append("")
        details.append("--- Reinforcement Triggers (numeric) ---")
        for t in reinforcement_triggers:
            details.append("TRIGGER: %s" % t)

    if inconsistencies:
        details.append("")
        details.append("--- Fix Consistency Warnings (%d) ---" % len(inconsistencies))
        for ic in inconsistencies[:3]:
            details.append(ic)

        # warningsをproposal_trackingに記録して再発追跡
        _record_consistency_warnings(inconsistencies)

    # === warnings 7日推移 + 高再発の自動昇格 ===
    warning_trend, high_recurrence, auto_promoted = _analyze_warning_trends()
    if warning_trend:
        details.append("")
        details.extend(warning_trend)
    if high_recurrence:
        details.append("")
        details.extend(high_recurrence)
    if auto_promoted:
        all_fixes.extend(auto_promoted)

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
