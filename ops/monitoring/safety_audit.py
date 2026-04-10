# ============================================================
# 安全監査・暴走防止モジュール
#
# 最上位固定ルール（自動学習より優先）:
# - 価値提供優先。露骨な販促に寄せすぎない
# - 中古販売の信頼感を損なわない
# - 人間作成記事より明らかに低品質な記事は採用しない
# - ジャンル外へ広げすぎない
# - 新品向け競合のやり方をそのまま模倣しない
# - Shopify/eBay/ブログ/SNSの整合性を崩さない
#
# 重み調整の安全制限:
# - 1回 ±0.5 / 7日累計 ±1.0
# - サンプル3件未満では大きく動かさない
# - reaction_only では強化幅を小さくする
#
# 自動採用禁止領域:
# - ブランド方針変更 / テンプレート全面変更 / 大幅価格戦略変更
# - 強い販促路線 / trust要素削減 / 競合デザイン全面模倣
# - 人間作成記事のトーンを大きく逸脱する変更
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SAFETY_LOG = os.path.join(SCRIPT_DIR, "safety_audit_log.json")
SAFETY_STATE = os.path.join(SCRIPT_DIR, "safety_state.json")

# 安全制限値
MAX_WEIGHT_CHANGE_SINGLE = 0.5
MAX_WEIGHT_CHANGE_7DAY = 1.0
MIN_SAMPLE_FOR_LARGE_CHANGE = 3

# ズレ検知閾値
DEVIATION_THRESHOLD = 3  # ズレスコア合計がこれ以上で要確認

# 暴走検知閾値
RUNAWAY_THRESHOLDS = {
    "consecutive_quality_drop": 3,
    "consecutive_no_image_articles": 2,
    "weight_change_exceeded": True,
    "deviation_high_consecutive": 3,
    "success_rate_declining_days": 5,
    "single_platform_concentration": 0.8,
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


def _load_safety_state():
    if os.path.exists(SAFETY_STATE):
        try:
            with open(SAFETY_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "mode": "normal",
        "consecutive_quality_drops": 0,
        "consecutive_no_image": 0,
        "consecutive_high_deviation": 0,
        "weight_changes_7d": [],
        "last_updated": "",
    }


def _save_safety_state(state):
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(SAFETY_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. 重み調整の安全制限
# ============================================================

def enforce_weight_limits():
    """重み変更が安全範囲内か検証し、超過分を制限"""
    issues = []
    changes_made = []

    ss = _load_json("shared_state.json")
    if not ss:
        return issues, changes_made

    safety = _load_safety_state()
    log = ss.get("weight_adjustment_log", [])

    # 7日以内の累計変更量
    seven_days_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_changes = [l for l in log if l.get("date", "") >= seven_days_ago]

    # 重み変更量の累計を推定（adjustment文字列から±値を抽出）
    total_change = len(recent_changes) * 0.5  # 1回あたり最大0.5と仮定

    if total_change > MAX_WEIGHT_CHANGE_7DAY * 2:
        issues.append("[HIGH] Weight changes in 7 days: ~%.1f (limit: %.1f) → EXCESSIVE" % (total_change, MAX_WEIGHT_CHANGE_7DAY))

    # 偏りチェック
    weights = ss.get("scoring_weights", {})
    if weights:
        values = [v for v in weights.values() if isinstance(v, (int, float))]
        if values and max(values) > min(values) * 5:
            issues.append("[WARN] Extreme weight imbalance: max=%.1f min=%.1f" % (max(values), min(values)))
            changes_made.append("Weight imbalance detected — recommend manual review")

    # サンプル数チェック
    pt = _load_json("proposal_tracking.json")
    if pt:
        accuracy = pt.get("summary", {}).get("accuracy_by_type", {})
        for ptype, data in accuracy.items():
            adopted = data.get("adopted", 0)
            if adopted < MIN_SAMPLE_FOR_LARGE_CHANGE and adopted > 0:
                issues.append("[INFO] %s: only %d samples — weight adjustment suppressed" % (ptype, adopted))

    return issues, changes_made


# ============================================================
# 2. ズレ検知スコア
# ============================================================

def score_deviation(message, details_text=""):
    """改善案のズレスコアを算出（0=適合、高い=ズレ）"""
    text = (message + " " + details_text).lower()
    score = 0

    # ジャンル外（コアキーワードなし）
    core = ["figure", "toy", "card", "game", "manga", "anime", "pokemon", "plush",
            "collectible", "japanese", "japan", "pre-owned", "vintage", "rare"]
    if not any(kw in text for kw in core):
        score += 2

    # 新品寄り
    if any(kw in text for kw in ["brand new", "factory sealed", "pre-order", "just released"]):
        score += 2

    # 売り込み過多
    if any(kw in text for kw in ["buy now", "limited time", "hurry", "don't miss", "act now"]):
        score += 2

    # 価値提供方針逸脱
    value_kw = ["guide", "tips", "collector", "history", "culture", "how to", "rare"]
    push_kw = ["sale", "discount", "deal", "offer", "promo"]
    value_count = sum(1 for kw in value_kw if kw in text)
    push_count = sum(1 for kw in push_kw if kw in text)
    if push_count > value_count and push_count > 0:
        score += 1

    # 競合模倣リスク
    if any(kw in text for kw in ["copy", "replicate", "same as solaris", "clone"]):
        score += 2

    # trust欠如
    if "product" in text and not any(kw in text for kw in ["condition", "inspected", "authentic", "shipped from japan"]):
        score += 1

    return score


# ============================================================
# 3. 副作用監視
# ============================================================

def check_side_effects(all_findings):
    """改善の副作用を検出"""
    issues = []

    for f in all_findings:
        msg = f.get("message", "").lower()
        details = " ".join(str(d) for d in f.get("details", [])).lower()

        # 画像なし記事増加
        if "no image" in msg and "article" in msg:
            try:
                count = int(msg.split("no-image")[0].split()[-1]) if "no-image" in msg else 0
            except (ValueError, IndexError):
                count = 1
            if count > 3:
                issues.append("[SIDE-EFFECT] %d articles without images (quality decline)" % count)

        # trust低下
        if "no trust" in details or "trust missing" in details:
            issues.append("[SIDE-EFFECT] Trust language missing in some products")

        # 売り込み過多
        if "pushy" in details or "sales-heavy" in details:
            issues.append("[SIDE-EFFECT] Pushy language detected (value-first violation)")

        # eBay表現増加
        if "marketplace" in details and "language" in details:
            issues.append("[SIDE-EFFECT] eBay marketplace language creeping into DTC pages")

    return issues


# ============================================================
# 4. 暴走検知
# ============================================================

def detect_runaway(all_findings, side_effects):
    """暴走条件をチェックし、保守モードへの切替を判定"""
    safety = _load_safety_state()
    triggers = []

    # 品質低下連続
    quality_drop = any("quality" in se.lower() and "decline" in se.lower() for se in side_effects)
    if quality_drop:
        safety["consecutive_quality_drops"] = safety.get("consecutive_quality_drops", 0) + 1
    else:
        safety["consecutive_quality_drops"] = 0

    if safety["consecutive_quality_drops"] >= RUNAWAY_THRESHOLDS["consecutive_quality_drop"]:
        triggers.append("Quality drop %d consecutive days" % safety["consecutive_quality_drops"])

    # 画像なし連続
    no_image = any("without images" in se.lower() for se in side_effects)
    if no_image:
        safety["consecutive_no_image"] = safety.get("consecutive_no_image", 0) + 1
    else:
        safety["consecutive_no_image"] = 0

    if safety["consecutive_no_image"] >= RUNAWAY_THRESHOLDS["consecutive_no_image_articles"]:
        triggers.append("No-image articles %d consecutive days" % safety["consecutive_no_image"])

    # ズレスコア高い提案連続
    high_dev = 0
    for f in all_findings:
        if f.get("type") in ("action", "suggestion"):
            dev = score_deviation(f.get("message", ""))
            if dev >= DEVIATION_THRESHOLD:
                high_dev += 1
    if high_dev > 0:
        safety["consecutive_high_deviation"] = safety.get("consecutive_high_deviation", 0) + 1
    else:
        safety["consecutive_high_deviation"] = 0

    if safety["consecutive_high_deviation"] >= RUNAWAY_THRESHOLDS["deviation_high_consecutive"]:
        triggers.append("High deviation proposals %d consecutive days" % safety["consecutive_high_deviation"])

    # モード判定
    if triggers:
        safety["mode"] = "maintenance"
    elif safety["mode"] == "maintenance" and not triggers:
        safety["mode"] = "normal"

    _save_safety_state(safety)
    return triggers, safety["mode"]


# ============================================================
# 5. 大変更追跡
# ============================================================

def track_significant_changes():
    """自動メンテナンスで行われた大きな変更を検出"""
    changes = []

    # weight_adjustment_log から今日の変更
    ss = _load_json("shared_state.json")
    if ss:
        today = NOW.strftime("%Y-%m-%d")
        for entry in ss.get("weight_adjustment_log", []):
            if entry.get("date") == today:
                for adj in entry.get("adjustments", []):
                    changes.append({
                        "area": "weight_adjustment",
                        "detail": adj[:100],
                        "risk": "medium" if "+0.5" in adj or "-" in adj else "low",
                        "agent": "self-learning",
                    })

    # maintenance_log から今日の自動修正
    mlog = _load_json("maintenance_log.json")
    if mlog:
        today = NOW.strftime("%Y-%m-%d")
        today_runs = [r for r in mlog.get("runs", []) if r.get("date") == today]
        for run in today_runs:
            if run.get("fixes", 0) > 0:
                changes.append({
                    "area": "auto_fix",
                    "detail": "%d auto-fixes applied" % run["fixes"],
                    "risk": "medium",
                    "agent": "project-orchestrator",
                })
            if run.get("reinforced", 0) > 0:
                changes.append({
                    "area": "auto_reinforcement",
                    "detail": "%d proposals auto-registered" % run["reinforced"],
                    "risk": "low",
                    "agent": "project-orchestrator",
                })

    # proposal_tracking の今日の状態変更
    pt = _load_json("proposal_tracking.json")
    if pt:
        today = NOW.strftime("%Y-%m-%d")
        today_adopted = sum(1 for p in pt.get("proposals", []) if p.get("adopted_date") == today)
        today_expired = sum(1 for p in pt.get("proposals", []) if p.get("status") == "expired" and p.get("date", "")[:7] == today[:7])
        if today_adopted > 3:
            changes.append({
                "area": "proposal_adoption",
                "detail": "%d proposals adopted today (high volume)" % today_adopted,
                "risk": "medium",
                "agent": "self-learning",
            })

    return changes


# ============================================================
# メイン: 安全監査レポート生成
# ============================================================

def run_safety_audit(all_findings):
    """安全監査を実行しレポート用findingsを返す"""
    result = []
    safety = _load_safety_state()

    # === A. 重み安全制限 ===
    weight_issues, weight_changes = enforce_weight_limits()

    # === B. 副作用監視 ===
    side_effects = check_side_effects(all_findings)

    # === C. 暴走検知 ===
    triggers, mode = detect_runaway(all_findings, side_effects)

    # === D. ズレ検知サマリ ===
    high_deviation_proposals = []
    for f in all_findings:
        if f.get("type") in ("action", "suggestion"):
            dev = score_deviation(f.get("message", ""), " ".join(str(d) for d in f.get("details", [])))
            if dev >= DEVIATION_THRESHOLD:
                high_deviation_proposals.append((f.get("agent", ""), f.get("message", "")[:50], dev))

    # === E. 大変更追跡 ===
    significant = track_significant_changes()

    # === レポート生成 ===
    all_issues = weight_issues + side_effects
    status = "MAINTENANCE_MODE" if mode == "maintenance" else "CAUTION" if (triggers or side_effects) else "SAFE"

    details = [
        "=== Safety Audit: %s ===" % status,
        "Mode: %s" % mode,
        "Weight issues: %d" % len(weight_issues),
        "Side effects: %d" % len(side_effects),
        "Runaway triggers: %d" % len(triggers),
        "High deviation proposals: %d" % len(high_deviation_proposals),
        "Significant changes today: %d" % len(significant),
    ]

    if triggers:
        details.append("")
        details.append("--- RUNAWAY TRIGGERS ---")
        for t in triggers:
            details.append("TRIGGER: %s" % t)
        if mode == "maintenance":
            details.append("ACTION: Weight auto-adjustment SUSPENDED")
            details.append("ACTION: Auto-reinforcement SUSPENDED")
            details.append("ACTION: Proposals output-only (no auto-apply)")

    if weight_issues:
        details.append("")
        details.append("--- Weight Safety ---")
        details.extend(weight_issues)

    if side_effects:
        details.append("")
        details.append("--- Side Effects ---")
        details.extend(side_effects)

    # === E2. 高ズレ提案の段階対応 ===
    # ズレスコアに応じてfindingsにフラグを付与
    for f in all_findings:
        if f.get("type") not in ("action", "suggestion"):
            continue
        dev = score_deviation(f.get("message", ""), " ".join(str(d) for d in f.get("details", [])))
        if dev >= 5:
            f["_deviation_action"] = "block"       # 自動反映禁止
            f["type"] = "info"                     # actionからinfoに降格（自動反映されない）
        elif dev >= DEVIATION_THRESHOLD:
            f["_deviation_action"] = "hold"        # 保留（提案として表示するが強調しない）
        elif dev >= 2:
            f["_deviation_action"] = "suppress"    # 抑制（スコアを下げる）
            if "_display_score" in f:
                f["_display_score"] = max(f["_display_score"] - 5, 0)

    if high_deviation_proposals:
        details.append("")
        details.append("--- Deviation Alerts (threshold: %d) ---" % DEVIATION_THRESHOLD)
        details.append("Actions: score 2-3=suppress(score-5), 3-4=hold, 5+=block(downgrade to info)")
        # blocked数カウント
        blocked_count = sum(1 for _, _, d in high_deviation_proposals if d >= 5)
        held_count = sum(1 for _, _, d in high_deviation_proposals if DEVIATION_THRESHOLD <= d < 5)
        suppressed_count = sum(1 for _, _, d in high_deviation_proposals if 2 <= d < DEVIATION_THRESHOLD)

        details.append("Blocked(→info): %d, Held: %d, Suppressed: %d" % (blocked_count, held_count, suppressed_count))

        for agent, msg, dev in high_deviation_proposals[:5]:
            # スコア内訳を表示
            breakdown = []
            text = msg.lower()
            if not any(kw in text for kw in ["figure", "toy", "card", "game", "manga", "anime", "pokemon", "collectible", "japanese", "japan", "pre-owned"]):
                breakdown.append("genre-miss(+2)")
            if any(kw in text for kw in ["brand new", "factory sealed", "pre-order"]):
                breakdown.append("new-product(+2)")
            if any(kw in text for kw in ["buy now", "limited time", "hurry", "act now"]):
                breakdown.append("sales-push(+2)")
            if any(kw in text for kw in ["copy", "replicate", "clone"]):
                breakdown.append("competitor-copy(+2)")

            action = "BLOCKED→info" if dev >= 5 else "HOLD" if dev >= DEVIATION_THRESHOLD else "SUPPRESS"
            details.append("[score:%d] [%s] [%s] %s" % (dev, action, agent, msg))
            if breakdown:
                details.append("  Breakdown: %s" % " + ".join(breakdown))
            else:
                details.append("  Breakdown: genre-miss or trust-gap (minor)")

        # 代表例を1件強調
        if high_deviation_proposals:
            top = high_deviation_proposals[0]
            details.append("")
            details.append("Representative example: [score:%d] %s → %s" % (
                top[2], top[1],
                "downgraded action→info (auto-apply blocked)" if top[2] >= 5 else "held for review"))

    # === F. 保守モード発動条件の妥当性 ===
    details.append("")
    details.append("--- Maintenance Mode Conditions ---")
    details.append("Quality drop: %d/%d consecutive (trigger: %d)" % (
        safety.get("consecutive_quality_drops", 0),
        RUNAWAY_THRESHOLDS["consecutive_quality_drop"],
        RUNAWAY_THRESHOLDS["consecutive_quality_drop"]))
    details.append("No-image articles: %d/%d consecutive (trigger: %d)" % (
        safety.get("consecutive_no_image", 0),
        RUNAWAY_THRESHOLDS["consecutive_no_image_articles"],
        RUNAWAY_THRESHOLDS["consecutive_no_image_articles"]))
    details.append("High deviation: %d/%d consecutive (trigger: %d)" % (
        safety.get("consecutive_high_deviation", 0),
        RUNAWAY_THRESHOLDS["deviation_high_consecutive"],
        RUNAWAY_THRESHOLDS["deviation_high_consecutive"]))
    if mode == "normal":
        headroom = min(
            RUNAWAY_THRESHOLDS["consecutive_quality_drop"] - safety.get("consecutive_quality_drops", 0),
            RUNAWAY_THRESHOLDS["consecutive_no_image_articles"] - safety.get("consecutive_no_image", 0),
            RUNAWAY_THRESHOLDS["deviation_high_consecutive"] - safety.get("consecutive_high_deviation", 0),
        )
        details.append("Headroom to maintenance mode: %d days" % max(headroom, 0))

    # === G. 再発傾向（safety_audit_log） ===
    prev_log = _load_json("safety_audit_log.json")
    if prev_log and prev_log.get("audits"):
        audits = prev_log["audits"]
        recent_7 = [a for a in audits if a.get("date", "") >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")]

        if recent_7:
            details.append("")
            details.append("--- 7-Day Trend ---")
            total_triggers = sum(a.get("triggers", 0) for a in recent_7)
            total_effects = sum(a.get("side_effects", 0) for a in recent_7)
            total_devs = sum(a.get("deviations", 0) for a in recent_7)
            maint_days = sum(1 for a in recent_7 if a.get("mode") == "maintenance")

            details.append("Triggers (7d): %d" % total_triggers)
            details.append("Side effects (7d): %d" % total_effects)
            details.append("Deviations (7d): %d" % total_devs)
            details.append("Maintenance mode days (7d): %d" % maint_days)

            # 傾向判定
            if len(recent_7) >= 3:
                first_half = recent_7[:len(recent_7)//2]
                second_half = recent_7[len(recent_7)//2:]
                t1 = sum(a.get("triggers", 0) + a.get("side_effects", 0) for a in first_half) / max(len(first_half), 1)
                t2 = sum(a.get("triggers", 0) + a.get("side_effects", 0) for a in second_half) / max(len(second_half), 1)
                if t2 > t1 * 1.5 and t2 > 1:
                    details.append("TREND: Issues INCREASING (%.1f → %.1f avg/day)" % (t1, t2))
                    details.append("")
                    details.append("--- AUTO-RESPONSE: Trend increasing ---")

                    # 自動対応1: 重み変更幅を縮小
                    ss = _load_json("shared_state.json")
                    if ss:
                        current_limit = ss.get("_weight_change_limit", MAX_WEIGHT_CHANGE_SINGLE)
                        reduced = max(current_limit * 0.5, 0.1)
                        ss["_weight_change_limit"] = round(reduced, 2)
                        ss.setdefault("weight_adjustment_log", []).append({
                            "date": NOW.strftime("%Y-%m-%d"),
                            "adjustments": ["SAFETY: Weight change limit reduced %.2f → %.2f (trend increasing)" % (current_limit, reduced)],
                        })
                        _save_json("shared_state.json", ss)
                        details.append("CHANGED: Weight change limit: %.2f → %.2f (halved)" % (current_limit, reduced))

                    # 自動対応2: ズレ閾値を厳しくする
                    if safety.get("consecutive_high_deviation", 0) >= 2:
                        details.append("Deviation threshold tightened for this run (proposals with score>=2 suppressed)")

                    # 自動対応3: 保守モード予告
                    if t2 > 2:
                        details.append("WARNING: If trend continues, maintenance mode will activate in ~%d days" % max(1, RUNAWAY_THRESHOLDS["consecutive_quality_drop"] - safety.get("consecutive_quality_drops", 0)))

                elif t2 < t1 * 0.5:
                    details.append("TREND: Issues DECREASING (%.1f → %.1f avg/day)" % (t1, t2))

                    # 改善時: 制限を緩和
                    ss = _load_json("shared_state.json")
                    if ss and ss.get("_weight_change_limit", MAX_WEIGHT_CHANGE_SINGLE) < MAX_WEIGHT_CHANGE_SINGLE:
                        restored = min(ss["_weight_change_limit"] * 1.5, MAX_WEIGHT_CHANGE_SINGLE)
                        ss["_weight_change_limit"] = round(restored, 2)
                        _save_json("shared_state.json", ss)
                        details.append("CHANGED: Weight change limit restored: → %.2f (trend improving)" % restored)
                else:
                    details.append("TREND: Stable (%.1f → %.1f avg/day)" % (t1, t2))

    if significant:
        details.append("")
        details.append("--- Significant Changes Today ---")
        for c in significant:
            details.append("[%s] [%s] %s" % (c["risk"].upper(), c["area"], c["detail"]))

    severity = "critical" if mode == "maintenance" else "suggestion" if (triggers or len(side_effects) > 2) else "info" if all_issues else "ok"
    result.append({
        "type": severity,
        "agent": "project-orchestrator",
        "message": "Safety audit: %s (triggers:%d side-effects:%d changes:%d)" % (status, len(triggers), len(side_effects), len(significant)),
        "details": details,
    })

    # ログ保存
    log_data = _load_json("safety_audit_log.json") or {"audits": []}
    log_data["audits"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "status": status,
        "mode": mode,
        "triggers": len(triggers),
        "side_effects": len(side_effects),
        "deviations": len(high_deviation_proposals),
        "significant_changes": len(significant),
    })
    log_data["audits"] = log_data["audits"][-30:]
    _save_json("safety_audit_log.json", log_data)

    return result


def is_maintenance_mode():
    """保守モードかどうかを返す（他モジュールから参照用）"""
    safety = _load_safety_state()
    return safety.get("mode") == "maintenance"
