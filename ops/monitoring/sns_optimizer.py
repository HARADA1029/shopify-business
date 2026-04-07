# ============================================================
# SNS 最適化ループモジュール
#
# 投稿結果を分析し、次回投稿を改善する継続的な学習ループ:
# 1. 過去の投稿結果を集計
# 2. カテゴリ/パターン/SNS 別の成績を評価
# 3. 良いパターンの重みを上げ、悪いパターンの重みを下げ
# 4. 次回投稿案を最適化して提案
# 5. 競合/バズ投稿の参考要素を抽出
#
# 安全ルール: 読み取り専用。提案のみ。
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

POSTED_FILE = os.path.join(SCRIPT_DIR, "sns_posted.json")
SNS_WEIGHTS_FILE = os.path.join(SCRIPT_DIR, "sns_weights.json")


def _load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"posted": [], "history": []}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"posted": [], "history": []}


def _load_weights():
    """SNS 投稿パターンの重みを読み込む"""
    if not os.path.exists(SNS_WEIGHTS_FILE):
        return {
            "categories": {},
            "platforms": {},
            "patterns": {},
            "last_updated": "",
        }
    try:
        with open(SNS_WEIGHTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"categories": {}, "platforms": {}, "patterns": {}, "last_updated": ""}


def _save_weights(weights):
    weights["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(SNS_WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2, ensure_ascii=False)


def analyze_post_performance():
    """投稿実績を分析して、カテゴリ/プラットフォーム/パターン別の成績を返す"""
    posted = _load_posted()
    history = posted.get("history", [])

    if not history:
        return None

    # 過去7日間の投稿
    week_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= week_ago]

    analysis = {
        "total_posts": len(recent),
        "platforms": Counter(h.get("platform", "unknown") for h in recent),
        "categories": Counter(h.get("category", "unknown") for h in recent),
        "daily_counts": Counter(h.get("date", "") for h in recent),
        "all_time_total": len(history),
    }

    # カテゴリ別の投稿頻度偏り
    cat_counts = analysis["categories"]
    if cat_counts:
        most_posted = cat_counts.most_common(1)[0]
        least_posted_cats = [
            cat for cat in [
                "Action Figures", "Scale Figures", "Trading Cards",
                "Video Games", "Electronic Toys", "Media & Books", "Plush & Soft Toys",
            ]
            if cat not in cat_counts
        ]
        analysis["over_represented"] = most_posted[0] if most_posted[1] > 3 else None
        analysis["under_represented"] = least_posted_cats

    return analysis


def update_weights(analysis):
    """分析結果に基づいて重みを更新する"""
    if not analysis:
        return

    weights = _load_weights()

    # カテゴリの重み更新（投稿が少ないカテゴリの重みを上げる）
    for cat in analysis.get("under_represented", []):
        current = weights["categories"].get(cat, 1.0)
        weights["categories"][cat] = min(current + 0.2, 3.0)

    # 投稿が多すぎるカテゴリの重みを下げる
    over = analysis.get("over_represented")
    if over:
        current = weights["categories"].get(over, 1.0)
        weights["categories"][over] = max(current - 0.1, 0.5)

    # プラットフォームの重み（現時点ではデータ不足のためデフォルト維持）
    for platform in ["instagram", "facebook", "youtube_shorts", "facebook_video", "instagram_reels"]:
        if platform not in weights["platforms"]:
            weights["platforms"][platform] = 1.0

    _save_weights(weights)
    return weights


def generate_next_post_recommendations(analysis, weights):
    """次回投稿の推奨案を生成する"""
    findings = []

    if not analysis:
        findings.append({
            "type": "info", "agent": "sns-manager",
            "message": "SNS optimization: No post history yet, using default rotation",
        })
        return findings

    details = []

    # 1. 投稿実績サマリ
    details.append("Posts this week: %d (all-time: %d)" % (analysis["total_posts"], analysis["all_time_total"]))

    # プラットフォーム別
    for platform, count in analysis["platforms"].most_common():
        details.append("  %s: %d posts" % (platform, count))

    # 2. カテゴリバランス改善案
    under = analysis.get("under_represented", [])
    if under:
        details.append("Under-posted categories: %s" % ", ".join(under[:3]))
        details.append("  -> Prioritize these in next posts")

    over = analysis.get("over_represented")
    if over:
        details.append("Over-posted: %s -> Reduce frequency" % over)

    # 3. 重み付き推奨カテゴリ
    if weights and weights.get("categories"):
        sorted_cats = sorted(weights["categories"].items(), key=lambda x: -x[1])
        top_cats = ["%s (%.1f)" % (k, v) for k, v in sorted_cats[:3] if v > 1.0]
        if top_cats:
            details.append("High-priority categories: %s" % ", ".join(top_cats))

    # 4. 次回試すべき切り口
    patterns_to_try = []
    posted = _load_posted()
    history = posted.get("history", [])
    recent_platforms = set(h.get("platform", "") for h in history[-7:])

    if "instagram_reels" not in recent_platforms:
        patterns_to_try.append("Try: Instagram Reels (not used recently)")
    if "youtube_shorts" not in recent_platforms:
        patterns_to_try.append("Try: YouTube Shorts (not used recently)")

    if patterns_to_try:
        details.extend(patterns_to_try)

    findings.append({
        "type": "action", "agent": "sns-manager",
        "message": "SNS optimization: %d posts this week, %d improvement suggestions" % (
            analysis["total_posts"], len(under) + len(patterns_to_try),
        ),
        "details": details,
    })

    return findings


def analyze_competitor_sns():
    """競合 SNS の投稿パターンを分析して参考要素を抽出する"""
    findings = []

    # 競合 Instagram アカウントを確認（公開プロフィールからメタデータを取得）
    competitor_accounts = [
        {"name": "Solaris Japan", "platform": "instagram", "handle": "solarisjapan"},
        {"name": "Japan Figure", "platform": "instagram", "handle": "japanfigure"},
    ]

    import requests

    insights = []
    for comp in competitor_accounts:
        try:
            # Instagram の公開ページはSPAなのでメタデータのみ
            resp = requests.get(
                "https://www.instagram.com/%s/" % comp["handle"],
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                html = resp.text
                # フォロワー数などはSPAで取れないが、ページタイトルからヒントを得る
                import re
                title = re.search(r"<title>(.*?)</title>", html)
                if title:
                    insights.append("%s: %s" % (comp["name"], title.group(1)[:60]))
        except Exception:
            pass

    if insights:
        findings.append({
            "type": "info", "agent": "sns-manager",
            "message": "Competitor SNS check: %d accounts scanned" % len(insights),
            "details": insights,
        })

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_sns_optimization():
    """SNS 最適化ループを実行して提案を返す"""
    all_findings = []

    # 1. 投稿実績を分析
    analysis = analyze_post_performance()

    # 2. 重みを更新
    weights = update_weights(analysis)

    # 3. 次回投稿の推奨案を生成
    all_findings.extend(generate_next_post_recommendations(analysis, weights))

    # 4. 競合 SNS チェック（軽量版）
    all_findings.extend(analyze_competitor_sns())

    return all_findings
