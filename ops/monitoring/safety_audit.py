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

    # 共通データの事前読み込み
    ss_data = _load_json("shared_state.json") or {}
    pt_data = _load_json("proposal_tracking.json") or {}
    prev_log = _load_json("safety_audit_log.json") or {}

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

    # === M. Warning減少率 ===
    pt_data = _load_json("proposal_tracking.json")
    if pt_data and pt_data.get("consistency_warnings"):
        cw = pt_data["consistency_warnings"]
        seven_d = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
        fourteen_d = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")

        recent_warnings = sum(w.get("count", 1) for w in cw if w.get("last_seen", "") >= seven_d)
        older_warnings = sum(w.get("count", 1) for w in cw if fourteen_d <= w.get("last_seen", "") < seven_d)

        if older_warnings > 0:
            change_rate = (recent_warnings - older_warnings) / older_warnings * 100
            details.append("")
            details.append("--- Warning Reduction Rate ---")
            details.append("Past 7d: %d warnings | Previous 7d: %d warnings" % (recent_warnings, older_warnings))
            if change_rate < -20:
                details.append("IMPROVING: %.0f%% reduction" % abs(change_rate))
            elif change_rate > 20:
                details.append("WORSENING: %.0f%% increase" % change_rate)
            else:
                details.append("STABLE: %.0f%% change" % change_rate)
        elif recent_warnings > 0:
            details.append("")
            details.append("--- Warning Reduction Rate ---")
            details.append("Past 7d: %d warnings (no prior data for comparison)" % recent_warnings)

    # === 重点監視サマリ ===
    details.append("")
    details.append("=== Priority Watch Items ===")

    # 1. trust強化の成果（ブログCTA/SNS別）
    if ss_data:
        trust_w = ss_data.get("scoring_weights", {}).get("trust_building", 2)
        history = ss_data.get("success_by_action_history", [])
        recent_trust = history[-1].get("actions", {}).get("trust_improvement", 0) if history else 0
        details.append("[TRUST] Weight: %.1f, recent successes: %d" % (trust_w, recent_trust))

        # ブログCTAのtrust成果
        if pt_data:
            blog_trust_s = sum(1 for p in pt_data.get("proposals", [])
                              if p.get("result") == "success"
                              and any(kw in p.get("message", "").lower() for kw in ["blog", "article", "cta"])
                              and any(kw in p.get("message", "").lower() for kw in ["trust", "inspect", "shipped", "condition"]))
            sns_trust_s = sum(1 for p in pt_data.get("proposals", [])
                             if p.get("result") == "success"
                             and any(kw in p.get("message", "").lower() for kw in ["sns", "instagram", "facebook", "post"])
                             and any(kw in p.get("message", "").lower() for kw in ["trust", "inspect", "shipped", "condition"]))
            product_trust_s = max(recent_trust - blog_trust_s - sns_trust_s, 0)
            details.append("  Product: %d | Blog CTA: %d | SNS: %d" % (product_trust_s, blog_trust_s, sns_trust_s))

        # 7日比較
        if history and len(history) >= 2:
            prev_trust = history[-2].get("actions", {}).get("trust_improvement", 0) if len(history) >= 2 else 0
            diff = recent_trust - prev_trust
            details.append("  vs prev: %+d (%s)" % (diff, "improving" if diff > 0 else "stable" if diff == 0 else "declining"))

        # trust文言パターン別の成果比較
        if pt_data:
            trust_patterns = {"shipped_from_japan": 0, "inspected": 0, "authentic": 0, "condition_desc": 0, "pre_owned": 0}
            for p in pt_data.get("proposals", []):
                if p.get("result") != "success":
                    continue
                msg = p.get("message", "").lower()
                if "shipped from japan" in msg or "ship" in msg:
                    trust_patterns["shipped_from_japan"] += 1
                if "inspect" in msg:
                    trust_patterns["inspected"] += 1
                if "authentic" in msg or "genuine" in msg:
                    trust_patterns["authentic"] += 1
                if "condition" in msg:
                    trust_patterns["condition_desc"] += 1
                if "pre-owned" in msg or "pre owned" in msg or "used" in msg:
                    trust_patterns["pre_owned"] += 1

            active_patterns = [(p, c) for p, c in trust_patterns.items() if c > 0]
            if active_patterns:
                details.append("  Trust pattern successes:")
                for pattern, count in sorted(active_patterns, key=lambda x: -x[1]):
                    details.append("    [%d] %s" % (count, pattern))
                best_pattern = max(active_patterns, key=lambda x: x[1])
                details.append("  Best single: %s (%d successes)" % (best_pattern[0], best_pattern[1]))

                # 組み合わせ比較
                combo_counts = {"ship+inspect": 0, "ship+condition": 0, "ship+inspect+condition": 0, "single_only": 0}
                for p in pt_data.get("proposals", []):
                    if p.get("result") != "success":
                        continue
                    msg = p.get("message", "").lower()
                    has_ship = "ship" in msg
                    has_insp = "inspect" in msg
                    has_cond = "condition" in msg
                    if has_ship and has_insp and has_cond:
                        combo_counts["ship+inspect+condition"] += 1
                    elif has_ship and has_insp:
                        combo_counts["ship+inspect"] += 1
                    elif has_ship and has_cond:
                        combo_counts["ship+condition"] += 1
                    elif has_ship or has_insp or has_cond:
                        combo_counts["single_only"] += 1

                active_combos = [(c, n) for c, n in combo_counts.items() if n > 0]
                if active_combos:
                    details.append("  Combination successes:")
                    for combo, count in sorted(active_combos, key=lambda x: -x[1]):
                        details.append("    [%d] %s" % (count, combo))
                    best_combo = max(active_combos, key=lambda x: x[1])
                    details.append("  Best combo: %s → prioritize this combination" % best_combo[0])

    # 2. blog_content 抑制後の変化 + suppress解除条件の監視
    if ss_data:
        action_w = ss_data.get("action_type_weights", {})
        blog_w = action_w.get("blog_content", 1.0)
        if blog_w < 1.0:
            details.append("[BLOG] blog_content weight: %.1f (suppressed)" % blog_w)

            # suppress解除条件: 直近3件中2件以上success
            if pt_data:
                blog_proposals = [p for p in pt_data.get("proposals", [])
                                  if any(kw in p.get("message", "").lower() for kw in ["blog", "article", "write"])
                                  and p.get("status") == "adopted"]
                recent_3 = blog_proposals[-3:] if len(blog_proposals) >= 3 else blog_proposals
                recent_success = sum(1 for p in recent_3 if p.get("result") == "success")
                details.append("  Suppress lift condition: 2/3 recent successes")
                details.append("  Current: %d/%d successes (%s)" % (
                    recent_success, len(recent_3),
                    "READY TO LIFT" if recent_success >= 2 and len(recent_3) >= 3 else "not yet"))

                # 解除可能な場合は自動解除
                if recent_success >= 2 and len(recent_3) >= 3:
                    action_w["blog_content"] = 1.0
                    ss_data.setdefault("weight_adjustment_log", []).append({
                        "date": NOW.strftime("%Y-%m-%d"),
                        "adjustments": ["blog_content suppress LIFTED (2/3 recent successes)"],
                    })
                    _save_json("shared_state.json", ss_data)
                    details.append("  ACTION: blog_content suppress LIFTED → weight restored to 1.0")
        else:
            details.append("[BLOG] blog_content weight: %.1f (normal)" % blog_w)

            # suppress解除後の品質監視（解除されたばかりの場合）
            log = ss_data.get("weight_adjustment_log", [])
            recently_lifted = any("blog_content suppress LIFTED" in str(l.get("adjustments", [])) for l in log[-5:])
            if recently_lifted and pt_data:
                post_lift_blogs = [p for p in pt_data.get("proposals", [])
                                   if any(kw in p.get("message", "").lower() for kw in ["blog", "article"])
                                   and p.get("status") == "adopted"]
                post_lift_recent = post_lift_blogs[-3:] if post_lift_blogs else []
                post_lift_success = sum(1 for p in post_lift_recent if p.get("result") == "success")
                post_lift_fail = sum(1 for p in post_lift_recent if p.get("result") in ("no_reaction", "failed", "weak"))

                # 解除日を特定
                lift_date = None
                for l in reversed(log[-10:]):
                    if "blog_content suppress LIFTED" in str(l.get("adjustments", [])):
                        lift_date = l.get("date", "")
                        break

                days_since_lift = 0
                if lift_date:
                    try:
                        days_since_lift = (NOW.replace(tzinfo=None) - __import__("datetime").datetime.strptime(lift_date, "%Y-%m-%d")).days
                    except (ValueError, TypeError):
                        pass

                details.append("  POST-LIFT MONITORING (day %d since lift):" % days_since_lift)
                details.append("    Recent 3 blog proposals: %d success, %d fail" % (post_lift_success, post_lift_fail))

                # 全post-lift期間のサマリ
                all_post_lift = [p for p in post_lift_blogs if p.get("adopted_date", "") >= (lift_date or "")]
                all_pl_success = sum(1 for p in all_post_lift if p.get("result") == "success")
                all_pl_fail = sum(1 for p in all_post_lift if p.get("result") in ("no_reaction", "failed", "weak"))
                all_pl_total = len(all_post_lift)
                if all_pl_total > 0:
                    details.append("    Total since lift: %d/%d success (%.0f%%)" % (
                        all_pl_success, all_pl_total, all_pl_success / all_pl_total * 100))

                if post_lift_fail >= 2:
                    details.append("  WARNING: Quality declining after suppress lift")
                    action_w = ss_data.get("action_type_weights", {})
                    action_w["blog_content"] = 0.8
                    ss_data.setdefault("weight_adjustment_log", []).append({
                        "date": NOW.strftime("%Y-%m-%d"),
                        "adjustments": ["blog_content RE-SUPPRESSED (quality dropped after lift)"],
                    })
                    _save_json("shared_state.json", ss_data)
                    details.append("  ACTION: blog_content re-suppressed → weight 0.8")
                elif post_lift_success >= 2:
                    details.append("  OK: Quality maintained after suppress lift (%d days)" % days_since_lift)
                else:
                    details.append("  MONITORING: Collecting data (%d/%d evaluated)" % (post_lift_success + post_lift_fail, len(post_lift_recent)))

        # 7日比較
        blog_state_data = _load_json("blog_state.json")
        if blog_state_data and blog_state_data.get("pdca_history"):
            pdca = blog_state_data["pdca_history"]
            if len(pdca) >= 2:
                prev_issues = pdca[-2].get("issues_found", 0)
                curr_issues = pdca[-1].get("issues_found", 0)
                details.append("  Issues: %d → %d (%s)" % (prev_issues, curr_issues,
                    "improving" if curr_issues < prev_issues else "stable" if curr_issues == prev_issues else "worsening"))

            # 品質メトリクス推移
            if len(pdca) >= 2 and pdca[-1].get("quality_metrics") and pdca[-2].get("quality_metrics"):
                prev_m = pdca[-2]["quality_metrics"]
                curr_m = pdca[-1]["quality_metrics"]
                improved = sum(1 for k in curr_m if curr_m.get(k, 0) < prev_m.get(k, 0))
                worsened = sum(1 for k in curr_m if curr_m.get(k, 0) > prev_m.get(k, 0))
                details.append("  Quality metrics: %d improved, %d worsened" % (improved, worsened))

    # 6. 投稿成功 → 実売上導線の効果確認
    if pt_data:
        # 最近の blog/SNS 成功数
        recent_date = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
        recent_blog_success = sum(1 for p in pt_data.get("proposals", [])
                                  if p.get("result") == "success"
                                  and p.get("result_date", "") >= recent_date
                                  and any(kw in p.get("message", "").lower() for kw in ["blog", "article"]))
        recent_sns_success = sum(1 for p in pt_data.get("proposals", [])
                                 if p.get("result") == "success"
                                 and p.get("result_date", "") >= recent_date
                                 and any(kw in p.get("message", "").lower() for kw in ["sns", "instagram", "post"]))

        # blog_state の追跡データ
        blog_state_data2 = _load_json("blog_state.json")
        tracking = blog_state_data2.get("post_publish_tracking", []) if blog_state_data2 else []
        active_tracking = [t for t in tracking if t.get("status") == "tracking"]

        total_pv = sum(t.get("metrics", {}).get("pageviews", 0) for t in active_tracking)
        total_cta = sum(t.get("metrics", {}).get("cta_clicks", 0) for t in active_tracking)
        total_ref = sum(t.get("metrics", {}).get("shopify_referrals", 0) for t in active_tracking)
        total_cart = sum(t.get("metrics", {}).get("add_to_cart", 0) for t in active_tracking)

        details.append("")
        details.append("[SALES PIPELINE] Content → Sales funnel (7d)")
        details.append("  Blog successes: %d | SNS successes: %d" % (recent_blog_success, recent_sns_success))
        details.append("  Tracked articles: %d" % len(active_tracking))
        details.append("  Pageviews: %d → CTA clicks: %d → Shopify refs: %d → Carts: %d" % (
            total_pv, total_cta, total_ref, total_cart))

        if total_pv > 0:
            cta_rate = total_cta / total_pv * 100
            ref_rate = total_ref / max(total_cta, 1) * 100
            cart_rate = total_cart / max(total_ref, 1) * 100
            details.append("  Funnel: PV→CTA %.1f%% | CTA→Ref %.1f%% | Ref→Cart %.1f%%" % (cta_rate, ref_rate, cart_rate))

            # ボトルネック特定
            bottleneck = None
            if cta_rate < 3:
                bottleneck = "PV→CTA (%.1f%% — target: 3%%+). Fix: improve CTA visibility/copy" % cta_rate
            elif ref_rate < 30:
                bottleneck = "CTA→Ref (%.1f%% — target: 30%%+). Fix: strengthen trust in CTA, add product photos" % ref_rate
            elif cart_rate < 10:
                bottleneck = "Ref→Cart (%.1f%% — target: 10%%+). Fix: improve product page, add related items" % cart_rate

            if bottleneck:
                details.append("  BOTTLENECK: %s" % bottleneck)
            else:
                details.append("  Funnel healthy: all stages above target")

            # 商品写真訴求の効果確認
            blog_state_check = _load_json("blog_state.json")
            if blog_state_check:
                tracking_articles = blog_state_check.get("post_publish_tracking", [])
                with_photos = [t for t in tracking_articles if t.get("metrics", {}).get("pageviews", 0) > 0]
                gen = blog_state_check.get("articles_generated", [])

                photo_rich = []  # 画像4枚以上
                photo_poor = []  # 画像3枚以下

                for t in with_photos:
                    g = [a for a in gen if a.get("wp_post_id") == t.get("wp_post_id")]
                    if g:
                        imgs = g[0].get("quality", {}).get("images", 0)
                        if imgs >= 4:
                            photo_rich.append(t)
                        else:
                            photo_poor.append(t)

                if photo_rich or photo_poor:
                    details.append("")
                    details.append("  --- Photo Impact on CTA→Ref ---")
                    for label, articles in [("4+ photos", photo_rich), ("<4 photos", photo_poor)]:
                        if not articles:
                            details.append("    [%s] No data yet" % label)
                            continue
                        pv = sum(a.get("metrics", {}).get("pageviews", 0) for a in articles)
                        cta = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in articles)
                        ref = sum(a.get("metrics", {}).get("shopify_referrals", 0) for a in articles)
                        cta_r = cta / max(pv, 1) * 100
                        ref_r = ref / max(cta, 1) * 100
                        details.append("    [%s] %d articles: PV→CTA %.1f%%, CTA→Ref %.1f%%" % (label, len(articles), cta_r, ref_r))
        else:
            details.append("  Funnel: awaiting pageview data (GA4 needs 24-48h)")

    # 3. sns-manager 偏差減少
    if prev_log and prev_log.get("audits"):
        sns_devs_recent = [a.get("deviations", 0) for a in prev_log["audits"][-7:]]
        if len(sns_devs_recent) >= 3:
            first = sum(sns_devs_recent[:len(sns_devs_recent)//2]) / max(len(sns_devs_recent)//2, 1)
            second = sum(sns_devs_recent[len(sns_devs_recent)//2:]) / max(len(sns_devs_recent) - len(sns_devs_recent)//2, 1)
            if second < first * 0.7:
                details.append("[SNS] Deviations: %.1f → %.1f (DECREASING)" % (first, second))
            elif second > first * 1.3:
                details.append("[SNS] Deviations: %.1f → %.1f (INCREASING)" % (first, second))
            else:
                details.append("[SNS] Deviations: %.1f → %.1f (stable)" % (first, second))

    # 3b. Ref→Cart 改善追跡
    if pt_data:
        blog_tracking = _load_json("blog_state.json")
        if blog_tracking and blog_tracking.get("post_publish_tracking"):
            tracked = blog_tracking["post_publish_tracking"]
            collection_date = "2026-04-10"  # コレクションリンク追加日
            before = [t for t in tracked if t.get("published_date", "") < collection_date]
            after = [t for t in tracked if t.get("published_date", "") >= collection_date]

            if before or after:
                details.append("")
                details.append("[REF→CART] Collection link effect:")
                for label, articles in [("Before collection link", before), ("After collection link", after)]:
                    ref = sum(a.get("metrics", {}).get("shopify_referrals", 0) for a in articles)
                    cart = sum(a.get("metrics", {}).get("add_to_cart", 0) for a in articles)
                    rate = cart / max(ref, 1) * 100
                    details.append("  [%s] %d articles, ref:%d → cart:%d (%.1f%%)" % (label, len(articles), ref, cart, rate))

    # 4. trust最強パターンの適用先別比較
    if pt_data:
        scope_patterns = {
            "product_page": {"ship": 0, "inspect": 0, "condition": 0, "combo": 0},
            "blog_cta": {"ship": 0, "inspect": 0, "condition": 0, "combo": 0},
            "sns_post": {"ship": 0, "inspect": 0, "condition": 0, "combo": 0},
        }

        for p in pt_data.get("proposals", []):
            if p.get("result") != "success":
                continue
            msg = p.get("message", "").lower()
            has_ship = "ship" in msg
            has_insp = "inspect" in msg
            has_cond = "condition" in msg

            # 適用先を判定
            if any(kw in msg for kw in ["blog", "article", "cta"]):
                scope = "blog_cta"
            elif any(kw in msg for kw in ["sns", "instagram", "facebook", "post", "pin"]):
                scope = "sns_post"
            else:
                scope = "product_page"

            if has_ship:
                scope_patterns[scope]["ship"] += 1
            if has_insp:
                scope_patterns[scope]["inspect"] += 1
            if has_cond:
                scope_patterns[scope]["condition"] += 1
            if has_ship and has_insp:
                scope_patterns[scope]["combo"] += 1

        has_data = any(sum(v.values()) > 0 for v in scope_patterns.values())
        if has_data:
            details.append("[TRUST SCOPE] Best pattern by channel:")
            for scope, patterns in scope_patterns.items():
                total = sum(patterns.values())
                if total > 0:
                    best = max(patterns.items(), key=lambda x: x[1])
                    details.append("  %s: %s(%d) — total %d trust successes" % (scope, best[0], best[1], total))
                else:
                    details.append("  %s: no trust successes yet → expand here" % scope)

    # 5. 全体7日比較
    if prev_log and prev_log.get("audits") and len(prev_log["audits"]) >= 7:
        week_audits = prev_log["audits"][-7:]
        first_3 = week_audits[:3]
        last_3 = week_audits[-3:]
        avg_se_before = sum(a.get("side_effects", 0) for a in first_3) / 3
        avg_se_after = sum(a.get("side_effects", 0) for a in last_3) / 3
        avg_dev_before = sum(a.get("deviations", 0) for a in first_3) / 3
        avg_dev_after = sum(a.get("deviations", 0) for a in last_3) / 3
        details.append("[7D] Side effects: %.1f → %.1f | Deviations: %.1f → %.1f" % (avg_se_before, avg_se_after, avg_dev_before, avg_dev_after))

    severity = "critical" if mode == "maintenance" else "suggestion" if (triggers or len(side_effects) > 2) else "info" if all_issues else "ok"
    result.append({
        "type": severity,
        "agent": "project-orchestrator",
        "message": "Safety audit: %s (triggers:%d side-effects:%d changes:%d)" % (status, len(triggers), len(side_effects), len(significant)),
        "details": details,
    })

    # === H. BLOCKED/HOLD/SUPPRESSED 7日推移 ===
    filter_state_path = os.path.join(SCRIPT_DIR, "proposal_filter_state.json")
    filter_history = _load_json("safety_audit_log.json") or {"audits": []}
    seven_days = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_audits = [a for a in filter_history.get("audits", []) if a.get("date", "") >= seven_days]

    if recent_audits:
        details.append("")
        details.append("--- BLOCKED/HOLD/SUPPRESS 7-Day History ---")
        for a in recent_audits:
            details.append("[%s] deviations:%d blocked:%d status:%s" % (
                a.get("date", "?"), a.get("deviations", 0), a.get("blocked", 0), a.get("status", "?")))

        total_blocked_7d = sum(a.get("blocked", 0) for a in recent_audits)
        total_dev_7d = sum(a.get("deviations", 0) for a in recent_audits)
        details.append("7d total: %d deviations, %d blocked" % (total_dev_7d, total_blocked_7d))

    # === I. 高ズレ提案のカテゴリ別・タイプ別集計 ===
    if high_deviation_proposals:
        from collections import Counter as _Counter
        dev_by_agent = _Counter(agent for agent, _, _ in high_deviation_proposals)
        dev_by_score = _Counter()
        for _, _, d in high_deviation_proposals:
            if d >= 5:
                dev_by_score["block(5+)"] += 1
            elif d >= DEVIATION_THRESHOLD:
                dev_by_score["hold(3-4)"] += 1
            else:
                dev_by_score["suppress(2)"] += 1

        details.append("")
        details.append("--- Deviation by Agent ---")
        for agent, count in dev_by_agent.most_common():
            details.append("  [%s] %d proposals" % (agent, count))
        details.append("--- Deviation by Grade ---")
        for grade, count in dev_by_score.most_common():
            details.append("  [%s] %d proposals" % (grade, count))

    # === J. 安全制御後の提案品質改善確認 ===
    if recent_audits and len(recent_audits) >= 3:
        first_half = recent_audits[:len(recent_audits)//2]
        second_half = recent_audits[len(recent_audits)//2:]
        dev_before = sum(a.get("deviations", 0) for a in first_half) / max(len(first_half), 1)
        dev_after = sum(a.get("deviations", 0) for a in second_half) / max(len(second_half), 1)

        details.append("")
        details.append("--- Post-Control Quality Check ---")
        details.append("Avg deviations: %.1f → %.1f (first vs recent half)" % (dev_before, dev_after))
        if dev_after < dev_before * 0.7:
            details.append("RESULT: Proposal quality IMPROVING after safety controls")
        elif dev_after > dev_before * 1.3:
            details.append("RESULT: Proposal quality DEGRADING — controls may need tightening")
        else:
            details.append("RESULT: Proposal quality STABLE")

    # === K. 偏差の多いエージェント/タイプを改善対象に ===
    if high_deviation_proposals:
        from collections import Counter as _C2
        agent_dev_counts = _C2(agent for agent, _, _ in high_deviation_proposals)

        # 偏差3件以上のエージェントを改善対象として明示
        high_dev_agents = [(a, c) for a, c in agent_dev_counts.most_common() if c >= 3]
        if high_dev_agents:
            details.append("")
            details.append("--- Agents Flagged for Improvement ---")
            for agent, count in high_dev_agents:
                details.append("[IMPROVE] %s: %d deviations → review research direction and proposal criteria" % (agent, count))

                # sns-manager の偏差原因を詳細分解
                if agent == "sns-manager":
                    sns_devs = [(msg, dev) for a, msg, dev in high_deviation_proposals if a == "sns-manager"]
                    sns_causes = {"genre_miss": 0, "sales_push": 0, "new_product": 0, "trust_gap": 0, "competitor_copy": 0}
                    for msg, dev in sns_devs:
                        t = msg.lower()
                        if not any(kw in t for kw in ["figure", "toy", "card", "game", "anime", "pokemon", "collectible", "japan"]):
                            sns_causes["genre_miss"] += 1
                        if any(kw in t for kw in ["buy now", "limited time", "hurry", "act now", "sale"]):
                            sns_causes["sales_push"] += 1
                        if any(kw in t for kw in ["brand new", "factory sealed", "pre-order"]):
                            sns_causes["new_product"] += 1
                        if "product" in t and not any(kw in t for kw in ["condition", "inspected", "authentic"]):
                            sns_causes["trust_gap"] += 1
                    active_causes = [(c, n) for c, n in sns_causes.items() if n > 0]
                    if active_causes:
                        details.append("  sns-manager deviation causes:")
                        for cause, n in sorted(active_causes, key=lambda x: -x[1]):
                            details.append("    [%d] %s" % (n, cause))

                        # 原因別の再発防止ルール
                        details.append("  --- Per-Cause Prevention Rules ---")
                        if sns_causes["genre_miss"] >= 2:
                            details.append("  [genre_miss] RULE: Add core keyword filter to SNS proposal generation")
                            details.append("    → proposals must contain: figure/toy/card/game/anime/pokemon/japan/collectible")
                        if sns_causes["sales_push"] >= 1:
                            details.append("  [sales_push] RULE: Block proposals with buy-now/limited-time/hurry language")
                            details.append("    → auto-downgrade to info if detected")
                        if sns_causes["trust_gap"] >= 1:
                            details.append("  [trust_gap] RULE: Require condition/inspected/shipped-from-japan in product posts")
                            details.append("    → flag for review if trust language missing")
                        if sns_causes["new_product"] >= 1:
                            details.append("  [new_product] RULE: Reject brand-new/factory-sealed language for used items")
                        if sns_causes["competitor_copy"] >= 1:
                            details.append("  [competitor_copy] RULE: Adapt competitor ideas, don't copy directly")

        # 偏差の多い提案タイプ → shared_state に記録して次回重み調整に反映
        type_dev = _C2()
        for _, msg, dev in high_deviation_proposals:
            if dev >= DEVIATION_THRESHOLD:
                from action_suggestions import _classify_proposal_type
                ptype = _classify_proposal_type(msg, "")
                type_dev[ptype] += 1

        high_dev_types = [(t, c) for t, c in type_dev.most_common() if c >= 2]
        if high_dev_types:
            details.append("")
            details.append("--- Proposal Types with High Deviation ---")
            ss = _load_json("shared_state.json")
            if ss:
                dev_weights = ss.setdefault("deviation_suppression", {})
                for ptype, count in high_dev_types:
                    current = dev_weights.get(ptype, 1.0)
                    reduced = max(current - 0.2, 0.3)
                    dev_weights[ptype] = round(reduced, 1)
                    details.append("[SUPPRESS] %s: %d deviations → weight %.1f → %.1f" % (ptype, count, current, reduced))

                ss["deviation_suppression"] = dev_weights
                ss.setdefault("weight_adjustment_log", []).append({
                    "date": NOW.strftime("%Y-%m-%d"),
                    "adjustments": ["Deviation suppression: %s" % str(dict(high_dev_types))],
                })
                _save_json("shared_state.json", ss)

    # === L. safety_audit_log と proposal_history の品質改善連動 ===
    pt = _load_json("proposal_tracking.json")
    prev_log = _load_json("safety_audit_log.json")
    if pt and prev_log and prev_log.get("audits"):
        audits = prev_log["audits"]
        recent = [a for a in audits if a.get("date", "") >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")]

        if len(recent) >= 3:
            first = recent[:len(recent)//2]
            second = recent[len(recent)//2:]
            dev_before = sum(a.get("deviations", 0) for a in first) / max(len(first), 1)
            dev_after = sum(a.get("deviations", 0) for a in second) / max(len(second), 1)

            # 改善している場合: 成功として proposal_tracking に記録
            import hashlib
            quality_hash = hashlib.md5(("quality-check:%s" % NOW.strftime("%Y-%m-%d")).encode()).hexdigest()[:10]
            existing = set(p.get("message_hash", "") for p in pt.get("proposals", []))

            if quality_hash not in existing:
                if dev_after < dev_before * 0.7 and dev_before > 0:
                    pt["proposals"].append({
                        "id": "P-%s-qc" % NOW.strftime("%y%m%d"),
                        "message_hash": quality_hash,
                        "date": NOW.strftime("%Y-%m-%d"),
                        "agent": "project-orchestrator",
                        "type": "page_improvement",
                        "message": "Quality improvement confirmed: deviations %.1f → %.1f" % (dev_before, dev_after),
                        "score": 15, "status": "adopted", "adopted_date": NOW.strftime("%Y-%m-%d"),
                        "result": "success", "result_date": NOW.strftime("%Y-%m-%d"),
                        "next_action": "Continue current safety controls",
                    })
                    details.append("")
                    details.append("LINKED: Quality improvement recorded in proposal_tracking (success)")
                elif dev_after > dev_before * 1.3 and dev_before > 0:
                    pt["proposals"].append({
                        "id": "P-%s-qd" % NOW.strftime("%y%m%d"),
                        "message_hash": quality_hash,
                        "date": NOW.strftime("%Y-%m-%d"),
                        "agent": "project-orchestrator",
                        "type": "page_improvement",
                        "message": "Quality degradation detected: deviations %.1f → %.1f" % (dev_before, dev_after),
                        "score": 20, "status": "pending",
                        "adopted_date": None, "result": None, "result_date": None,
                        "next_action": "Tighten safety controls or review deviation sources",
                    })
                    details.append("")
                    details.append("LINKED: Quality degradation recorded in proposal_tracking (pending fix)")

                pt["summary"]["total"] = len(pt["proposals"])
                pt["summary"]["last_updated"] = NOW.strftime("%Y-%m-%d")
                _save_json("proposal_tracking.json", pt)

    # === N. 抑制後の効果確認 ===
    prev_log_data = _load_json("safety_audit_log.json")
    ss_data = _load_json("shared_state.json")
    if prev_log_data and ss_data:
        suppressed_types = ss_data.get("deviation_suppression", {})
        if suppressed_types:
            audits_list = prev_log_data.get("audits", [])
            seven_d = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
            recent_audits_for_check = [a for a in audits_list if a.get("date", "") >= seven_d]

            if len(recent_audits_for_check) >= 2:
                # 抑制適用前後の偏差数を比較
                mid = len(recent_audits_for_check) // 2
                before_avg = sum(a.get("deviations", 0) for a in recent_audits_for_check[:mid]) / max(mid, 1)
                after_avg = sum(a.get("deviations", 0) for a in recent_audits_for_check[mid:]) / max(len(recent_audits_for_check) - mid, 1)

                details.append("")
                details.append("--- Suppression Effect Check ---")
                details.append("Suppressed types: %s" % ", ".join(suppressed_types.keys()))
                details.append("Deviations: %.1f → %.1f (before vs after suppression)" % (before_avg, after_avg))
                if after_avg < before_avg * 0.7:
                    details.append("EFFECTIVE: Suppression reduced deviations by %.0f%%" % ((1 - after_avg / max(before_avg, 0.1)) * 100))
                elif after_avg > before_avg * 1.2:
                    details.append("INEFFECTIVE: Deviations increased despite suppression → review root cause")
                else:
                    details.append("PARTIAL: Deviations stable — continue monitoring")

    # === O. 品質改善成功の対策別分解 ===
    if pt_data and prev_log_data:
        proposals = pt_data.get("proposals", [])
        recent_success = [p for p in proposals if p.get("result") == "success"
                         and p.get("result_date", "") >= (NOW - timedelta(days=14)).strftime("%Y-%m-%d")]

        if recent_success:
            # 対策タイプ別に成功を分解
            success_by_action = Counter()
            for p in recent_success:
                msg = p.get("message", "").lower()
                if "trust" in msg or "shipped" in msg or "inspected" in msg:
                    success_by_action["trust_improvement"] += 1
                elif "description" in msg or "expand" in msg or "content" in msg:
                    success_by_action["description_improvement"] += 1
                elif "image" in msg or "photo" in msg:
                    success_by_action["image_addition"] += 1
                elif "category" in msg or "activate" in msg or "draft" in msg:
                    success_by_action["category_expansion"] += 1
                elif "price" in msg or "sync" in msg:
                    success_by_action["price_optimization"] += 1
                elif "blog" in msg or "article" in msg:
                    success_by_action["blog_content"] += 1
                elif "policy" in msg or "shipping" in msg or "refund" in msg:
                    success_by_action["policy_setup"] += 1
                elif "quality" in msg or "deviation" in msg or "safety" in msg:
                    success_by_action["quality_control"] += 1
                else:
                    success_by_action["other"] += 1

            if success_by_action:
                details.append("")
                details.append("--- Success by Action Type (14d) ---")
                for action, count in success_by_action.most_common():
                    details.append("  [%d] %s" % (count, action))

                # 最も効果的な対策を学習
                best_action = success_by_action.most_common(1)[0]
                details.append("Most effective: %s (%d successes)" % (best_action[0], best_action[1]))

                # 効果の低い action type を検出
                low_effect = []
                if pt_data:
                    action_rates = {}
                    for p in pt_data.get("proposals", []):
                        if p.get("status") != "adopted":
                            continue
                        msg = p.get("message", "").lower()
                        for atype in ["trust_improvement", "description_improvement", "image_addition",
                                      "category_expansion", "price_optimization", "blog_content",
                                      "policy_setup", "quality_control"]:
                            if any(kw in msg for kw in atype.replace("_", " ").split()):
                                r = action_rates.setdefault(atype, {"adopted": 0, "success": 0})
                                r["adopted"] += 1
                                if p.get("result") == "success":
                                    r["success"] += 1
                                break

                    for atype, r in action_rates.items():
                        if r["adopted"] >= 3 and r["success"] / r["adopted"] < 0.4:
                            low_effect.append((atype, r["adopted"], r["success"], r["success"] / r["adopted"]))

                if low_effect:
                    details.append("")
                    details.append("--- Low-Effect Action Types ---")
                    for atype, adopted, success, sr in sorted(low_effect, key=lambda x: x[3]):
                        details.append("[REVIEW] %s: %d adopted, %d success (%.0f%%) → reduce weight" % (atype, adopted, success, sr * 100))

                # blog_content の詳細分解
                if "blog_content" in [le[0] for le in low_effect] or success_by_action.get("blog_content", 0) > 0:
                    blog_proposals = [p for p in pt_data.get("proposals", [])
                                     if p.get("status") == "adopted" and any(kw in p.get("message", "").lower() for kw in ["blog", "article", "write"])]
                    if blog_proposals:
                        blog_sub = {"image_issue": 0, "category_issue": 0, "cta_issue": 0, "content_thin": 0, "link_issue": 0, "quality_ok": 0}
                        for bp in blog_proposals:
                            msg = bp.get("message", "").lower()
                            result = bp.get("result", "")
                            if result != "success":
                                if "image" in msg or "photo" in msg:
                                    blog_sub["image_issue"] += 1
                                elif "category" in msg or "tag" in msg:
                                    blog_sub["category_issue"] += 1
                                elif "cta" in msg:
                                    blog_sub["cta_issue"] += 1
                                elif "short" in msg or "thin" in msg or "expand" in msg:
                                    blog_sub["content_thin"] += 1
                                elif "link" in msg or "internal" in msg:
                                    blog_sub["link_issue"] += 1
                                else:
                                    blog_sub["content_thin"] += 1
                            else:
                                blog_sub["quality_ok"] += 1

                        details.append("")
                        details.append("--- blog_content Failure Breakdown ---")
                        for sub, count in sorted(blog_sub.items(), key=lambda x: -x[1]):
                            if count > 0:
                                details.append("  [%d] %s" % (count, sub))

                # trust_improvement 優先強化
                trust_count = success_by_action.get("trust_improvement", 0)
                total_success = sum(success_by_action.values())
                if trust_count > 0 and trust_count >= total_success * 0.25:
                    details.append("")
                    details.append("--- trust_improvement Priority Boost ---")
                    details.append("trust accounts for %d/%d successes (%.0f%%)" % (trust_count, total_success, trust_count / max(total_success, 1) * 100))
                    details.append("ACTION: trust_building weight boosted")

                # shared_state に反映
                if ss_data:
                    ss_data.setdefault("success_by_action_history", []).append({
                        "date": NOW.strftime("%Y-%m-%d"),
                        "actions": dict(success_by_action),
                        "best": best_action[0],
                        "low_effect": [le[0] for le in low_effect],
                    })
                    ss_data["success_by_action_history"] = ss_data["success_by_action_history"][-10:]

                    # trust 重み強化 (商品ページ + ブログCTA + SNS投稿)
                    trust_total = success_by_action.get("trust_improvement", 0)
                    if best_action[0] == "trust_improvement" or (trust_total > 0 and trust_total >= total_success * 0.25):
                        weights = ss_data.get("scoring_weights", {})
                        cur = weights.get("trust_building", 2)
                        if cur < 4:
                            weights["trust_building"] = min(cur + 0.5, 4)
                            ss_data.setdefault("weight_adjustment_log", []).append({
                                "date": NOW.strftime("%Y-%m-%d"),
                                "adjustments": ["trust_building +0.5 (effective across product/blog/SNS)"],
                            })

                    # trust 適用範囲を拡大して追跡
                    details.append("")
                    details.append("--- trust_building Scope ---")
                    # ブログCTAのtrust語チェック
                    blog_trust = sum(1 for p in pt_data.get("proposals", [])
                                    if p.get("result") == "success"
                                    and any(kw in p.get("message", "").lower() for kw in ["blog", "article"])
                                    and any(kw in p.get("message", "").lower() for kw in ["trust", "inspect", "shipped", "condition"]))
                    # SNS投稿のtrust語チェック
                    sns_trust = sum(1 for p in pt_data.get("proposals", [])
                                   if p.get("result") == "success"
                                   and any(kw in p.get("message", "").lower() for kw in ["sns", "instagram", "post"])
                                   and any(kw in p.get("message", "").lower() for kw in ["trust", "inspect", "shipped", "condition"]))
                    product_trust = trust_total - blog_trust - sns_trust

                    details.append("  Product pages: %d trust successes" % max(product_trust, 0))
                    details.append("  Blog CTAs: %d trust successes" % blog_trust)
                    details.append("  SNS posts: %d trust successes" % sns_trust)
                    if blog_trust == 0:
                        details.append("  → Expand: Add trust language to blog CTA blocks")
                    if sns_trust == 0:
                        details.append("  → Expand: Add 'inspected & shipped from Japan' to SNS captions")

                    # 効果低い type の重み抑制
                    if low_effect:
                        aw = ss_data.setdefault("action_type_weights", {})
                        for atype, _, _, _ in low_effect:
                            aw[atype] = round(max(aw.get(atype, 1.0) - 0.2, 0.3), 1)
                        ss_data.setdefault("weight_adjustment_log", []).append({
                            "date": NOW.strftime("%Y-%m-%d"),
                            "adjustments": ["Low-effect weights reduced: %s" % ", ".join(le[0] for le in low_effect)],
                        })

                    _save_json("shared_state.json", ss_data)

    # ログ保存
    blocked_count_today = sum(1 for _, _, d in high_deviation_proposals if d >= 5) if high_deviation_proposals else 0
    log_data = _load_json("safety_audit_log.json") or {"audits": []}
    log_data["audits"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "status": status,
        "mode": mode,
        "triggers": len(triggers),
        "side_effects": len(side_effects),
        "deviations": len(high_deviation_proposals),
        "blocked": blocked_count_today,
        "significant_changes": len(significant),
    })
    log_data["audits"] = log_data["audits"][-30:]
    _save_json("safety_audit_log.json", log_data)

    return result


def is_maintenance_mode():
    """保守モードかどうかを返す（他モジュールから参照用）"""
    safety = _load_safety_state()
    return safety.get("mode") == "maintenance"
