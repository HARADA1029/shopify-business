# ============================================================
# SNS PDCA 統合モジュール
#
# 実行→結果→学習→次回改善のフルループを管理する。
#
# 出力セクション:
# 1. SNS実行サマリ（投稿件数/SNS/タイプ/画像動画/商品連携）
# 2. SNS結果サマリ（表示/クリック/いいね/保存/遷移）
# 3. SNS学習サマリ（良い型/弱い型/次回強化/次回削減）
# 4. SNS基盤監査（トークン/API/アカウント/分析基盤）
# 5. proposal_history / experiments 連携
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

POSTED_FILE = os.path.join(SCRIPT_DIR, "sns_posted.json")
SNS_WEIGHTS_FILE = os.path.join(SCRIPT_DIR, "sns_weights.json")
SNS_LEARNING_FILE = os.path.join(SCRIPT_DIR, "sns_learning.json")


def _load_posted():
    if not os.path.exists(POSTED_FILE):
        return {"posted": [], "history": []}
    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"posted": [], "history": []}


def _load_weights():
    if not os.path.exists(SNS_WEIGHTS_FILE):
        return {"categories": {}, "platforms": {}, "media_types": {}, "last_updated": ""}
    try:
        with open(SNS_WEIGHTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"categories": {}, "platforms": {}, "media_types": {}, "last_updated": ""}


def _save_weights(w):
    w["last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(SNS_WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=2, ensure_ascii=False)


def _load_learning():
    if not os.path.exists(SNS_LEARNING_FILE):
        return {"daily_summaries": [], "best_types": [], "worst_types": [], "last_updated": ""}
    try:
        with open(SNS_LEARNING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"daily_summaries": [], "best_types": [], "worst_types": [], "last_updated": ""}


def _save_learning(data):
    data["last_updated"] = NOW.strftime("%Y-%m-%d")
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    data["daily_summaries"] = [s for s in data["daily_summaries"] if s.get("date", "") >= cutoff]
    with open(SNS_LEARNING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. SNS実行サマリ
# ============================================================

def generate_execution_summary():
    """昨日と今日の投稿実行状況をサマリ化"""
    findings = []
    posted = _load_posted()
    history = posted.get("history", [])

    yesterday = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    today = NOW.strftime("%Y-%m-%d")

    for target_date, label in [(yesterday, "Yesterday"), (today, "Today")]:
        day_posts = [h for h in history if h.get("date") == target_date]

        if not day_posts:
            if label == "Yesterday":
                findings.append({
                    "type": "suggestion", "agent": "sns-manager",
                    "message": "SNS execution (%s): 0 posts — no activity recorded" % label,
                    "details": ["Check GitHub Actions logs for sns-auto-post and sns-video-post workflows"],
                })
            continue

        details = ["=== SNS Execution: %s (%s) ===" % (label, target_date)]
        details.append("Total posts: %d" % len(day_posts))

        # プラットフォーム別
        by_platform = Counter(h.get("platform", "?") for h in day_posts)
        for p, c in by_platform.most_common():
            details.append("  [%s] %d posts" % (p, c))

        # メディアタイプ別
        by_media = Counter(h.get("media_type", "unknown") for h in day_posts)
        details.append("Media: %s" % ", ".join("%s:%d" % (k, v) for k, v in by_media.most_common()))

        # 各投稿の詳細
        for h in day_posts:
            has_link = h.get("has_product_link", False)
            link_mark = "link" if has_link else "no-link"
            details.append(
                "  [%s] [%s] [%s] %s"
                % (h.get("platform", "?"), h.get("media_type", "?"), link_mark, h.get("title", "?")[:40])
            )

        findings.append({
            "type": "ok" if day_posts else "suggestion",
            "agent": "sns-manager",
            "message": "SNS execution (%s): %d posts on %d platforms" % (label, len(day_posts), len(by_platform)),
            "details": details,
        })

    return findings


# ============================================================
# 2. SNS結果サマリ（エンゲージメント取得 + 集計）
# ============================================================

def fetch_and_summarize_engagement():
    """過去の投稿のエンゲージメントを取得・集計"""
    findings = []
    posted = _load_posted()
    history = posted.get("history", [])
    if not history:
        return findings

    # Instagram トークン
    ig_token = None
    ig_path = os.path.join(PROJECT_ROOT, ".instagram_token.json")
    if os.path.exists(ig_path):
        try:
            with open(ig_path, "r") as f:
                ig_token = json.load(f).get("access_token", "")
        except (json.JSONDecodeError, IOError):
            pass

    # 2日以上前、30日以内の投稿でエンゲージメント未取得のものを更新
    updated = 0
    for entry in history:
        eng = entry.get("engagement", {})
        if sum(eng.values()) > 0:
            continue  # 既に取得済み

        post_date = entry.get("date", "")
        days_ago = (NOW.replace(tzinfo=None) - datetime.strptime(post_date, "%Y-%m-%d")).days if post_date else 999
        if days_ago < 2 or days_ago > 30:
            continue

        platform = entry.get("platform", "")

        if platform in ("instagram", "instagram_reels") and ig_token and entry.get("media_id"):
            try:
                fields = "like_count,comments_count" if platform == "instagram" else "like_count,comments_count,plays"
                resp = requests.get(
                    "https://graph.facebook.com/v25.0/%s" % entry["media_id"],
                    params={"fields": fields, "access_token": ig_token}, timeout=15,
                )
                if resp.status_code == 200:
                    d = resp.json()
                    entry["engagement"] = {
                        "views": d.get("plays", d.get("impressions", 0)),
                        "likes": d.get("like_count", 0),
                        "comments": d.get("comments_count", 0),
                        "saves": d.get("saved", 0),
                    }
                    updated += 1
            except Exception:
                pass

    if updated > 0:
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(posted, f, indent=2, ensure_ascii=False)

    # 過去14日のエンゲージメント集計
    two_weeks = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= two_weeks]

    total_eng = {"views": 0, "likes": 0, "comments": 0, "saves": 0, "shares": 0, "clicks": 0}
    posts_with_data = 0

    for h in recent:
        eng = h.get("engagement", {})
        if sum(eng.values()) > 0:
            posts_with_data += 1
            for k in total_eng:
                total_eng[k] += eng.get(k, 0)

    details = ["=== SNS Engagement Summary (14 days) ==="]
    details.append("Posts with data: %d / %d" % (posts_with_data, len(recent)))

    if posts_with_data > 0:
        details.append("Total: views:%d likes:%d comments:%d saves:%d" % (
            total_eng["views"], total_eng["likes"], total_eng["comments"], total_eng["saves"]))
        details.append("Average per post: views:%.0f likes:%.0f" % (
            total_eng["views"] / posts_with_data, total_eng["likes"] / posts_with_data))
    else:
        details.append("No engagement data yet (posts need 2+ days for data collection)")

    if updated > 0:
        details.append("Updated %d posts with fresh engagement data" % updated)

    findings.append({
        "type": "info", "agent": "sns-manager",
        "message": "SNS engagement: %d posts with data, %d views, %d likes (14d)" % (
            posts_with_data, total_eng["views"], total_eng["likes"]),
        "details": details,
    })

    return findings


# ============================================================
# 3. SNS学習サマリ
# ============================================================

def generate_learning_summary():
    """投稿結果から学習し、次回改善案を生成"""
    findings = []
    posted = _load_posted()
    history = posted.get("history", [])
    learning = _load_learning()

    if len(history) < 2:
        findings.append({
            "type": "info", "agent": "sns-manager",
            "message": "SNS learning: Not enough data yet (%d posts, need 2+)" % len(history),
        })
        return findings

    two_weeks = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= two_weeks]

    # プラットフォーム別エンゲージメント平均
    platform_stats = defaultdict(lambda: {"posts": 0, "total_likes": 0, "total_views": 0})
    media_stats = defaultdict(lambda: {"posts": 0, "total_likes": 0, "total_views": 0})
    category_stats = defaultdict(lambda: {"posts": 0, "total_likes": 0, "total_views": 0})
    link_stats = {"with_link": {"posts": 0, "total_likes": 0}, "no_link": {"posts": 0, "total_likes": 0}}

    for h in recent:
        eng = h.get("engagement", {})
        likes = eng.get("likes", 0)
        views = eng.get("views", eng.get("impressions", 0))
        platform = h.get("platform", "unknown")
        media_type = h.get("media_type", "unknown")
        category = h.get("category", "unknown")
        has_link = h.get("has_product_link", False)

        platform_stats[platform]["posts"] += 1
        platform_stats[platform]["total_likes"] += likes
        platform_stats[platform]["total_views"] += views

        media_stats[media_type]["posts"] += 1
        media_stats[media_type]["total_likes"] += likes
        media_stats[media_type]["total_views"] += views

        category_stats[category]["posts"] += 1
        category_stats[category]["total_likes"] += likes
        category_stats[category]["total_views"] += views

        key = "with_link" if has_link else "no_link"
        link_stats[key]["posts"] += 1
        link_stats[key]["total_likes"] += likes

    details = ["=== SNS Learning Summary (14 days, %d posts) ===" % len(recent)]

    # プラットフォーム比較
    if platform_stats:
        details.append("--- By Platform ---")
        best_p = max(platform_stats.items(), key=lambda x: x[1]["total_views"] / max(x[1]["posts"], 1))
        for p, s in sorted(platform_stats.items()):
            avg_v = s["total_views"] / max(s["posts"], 1)
            avg_l = s["total_likes"] / max(s["posts"], 1)
            marker = " <-- BEST" if p == best_p[0] and len(platform_stats) > 1 else ""
            details.append("  [%s] %d posts, avg views:%.0f, avg likes:%.0f%s" % (p, s["posts"], avg_v, avg_l, marker))

    # 画像 vs 動画
    if len(media_stats) > 1:
        details.append("--- Image vs Video ---")
        for m, s in sorted(media_stats.items()):
            avg_l = s["total_likes"] / max(s["posts"], 1)
            details.append("  [%s] %d posts, avg likes:%.0f" % (m, s["posts"], avg_l))

    # カテゴリ比較
    if category_stats:
        details.append("--- By Category ---")
        best_c = max(category_stats.items(), key=lambda x: x[1]["total_likes"] / max(x[1]["posts"], 1))
        worst_c = min(category_stats.items(), key=lambda x: x[1]["total_likes"] / max(x[1]["posts"], 1))
        for c, s in sorted(category_stats.items()):
            avg_l = s["total_likes"] / max(s["posts"], 1)
            details.append("  [%s] %d posts, avg likes:%.0f" % (c, s["posts"], avg_l))
        if best_c[0] != worst_c[0]:
            details.append("  Best: %s | Weakest: %s" % (best_c[0], worst_c[0]))

    # CTA（リンク）比較
    wl = link_stats["with_link"]
    nl = link_stats["no_link"]
    if wl["posts"] > 0 and nl["posts"] > 0:
        details.append("--- Link vs No-link ---")
        details.append("  With link: %d posts, avg likes:%.0f" % (wl["posts"], wl["total_likes"] / max(wl["posts"], 1)))
        details.append("  No link: %d posts, avg likes:%.0f" % (nl["posts"], nl["total_likes"] / max(nl["posts"], 1)))

    # 次回アクション
    details.append("--- Next Actions ---")
    if platform_stats:
        best_p_name = max(platform_stats.items(), key=lambda x: x[1]["total_views"] / max(x[1]["posts"], 1))[0]
        details.append("  Strengthen: %s (highest avg views)" % best_p_name)
    if category_stats and len(category_stats) > 1:
        details.append("  Increase: %s category (best engagement)" % best_c[0])
        details.append("  Review: %s category (weakest engagement)" % worst_c[0])

    # 重みを更新
    weights = _load_weights()
    if category_stats:
        for cat, s in category_stats.items():
            avg = s["total_likes"] / max(s["posts"], 1)
            current = weights.get("categories", {}).get(cat, 1.0)
            if avg > 5:
                weights.setdefault("categories", {})[cat] = min(current + 0.2, 3.0)
            elif avg < 1 and s["posts"] >= 2:
                weights.setdefault("categories", {})[cat] = max(current - 0.1, 0.5)
    if media_stats:
        for mt, s in media_stats.items():
            avg = s["total_likes"] / max(s["posts"], 1)
            weights.setdefault("media_types", {})[mt] = round(avg, 1)
    _save_weights(weights)

    # 学習履歴を保存
    learning["daily_summaries"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "posts_analyzed": len(recent),
        "best_platform": best_p[0] if platform_stats else None,
        "best_category": best_c[0] if category_stats and len(category_stats) > 1 else None,
    })
    _save_learning(learning)

    findings.append({
        "type": "info", "agent": "sns-manager",
        "message": "SNS learning: %d posts analyzed, best=%s, weights updated" % (
            len(recent), best_p[0] if platform_stats else "N/A"),
        "details": details,
    })

    return findings


# ============================================================
# 4. SNS基盤監査
# ============================================================

def audit_sns_infrastructure():
    """SNSの接続・アカウント・分析基盤を監査"""
    findings = []

    checks = []
    issues = []

    # トークン存在チェック
    token_checks = {
        "Instagram": (".instagram_token.json", "Posting + basic insights"),
        "Pinterest": (".pinterest_token.json", "Board/pin management (Standard access pending for analytics)"),
        "YouTube": (".youtube_token.json", "Shorts upload"),
        "TikTok": (".tiktok_token.json", "Video posting (app review pending)"),
    }

    for name, (filename, capability) in token_checks.items():
        path = os.path.join(PROJECT_ROOT, filename)
        if os.path.exists(path):
            checks.append("[OK] %s: Token available — %s" % (name, capability))
        else:
            checks.append("[MISSING] %s: Token not found" % name)
            issues.append("%s token missing — cannot post or analyze" % name)

    # Facebook（Instagram経由で投稿）
    ig_path = os.path.join(PROJECT_ROOT, ".instagram_token.json")
    if os.path.exists(ig_path):
        checks.append("[OK] Facebook: Via Instagram page token")
    else:
        checks.append("[MISSING] Facebook: Requires Instagram token")

    # 分析可能なSNS
    analyzable = []
    not_analyzable = []
    if os.path.exists(os.path.join(PROJECT_ROOT, ".instagram_token.json")):
        analyzable.append("Instagram (basic)")
    else:
        not_analyzable.append("Instagram")
    not_analyzable.append("Pinterest Analytics (needs Standard access)")
    not_analyzable.append("YouTube Analytics (needs separate scope)")
    not_analyzable.append("Facebook Page Insights (limited)")

    checks.append("Analyzable: %s" % (", ".join(analyzable) if analyzable else "none"))
    checks.append("Not analyzable: %s" % ", ".join(not_analyzable))

    # Shopify専用SNSアカウント
    config_path = os.path.join(SCRIPT_DIR, "external_links_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            shopify_sns = config.get("shopify_sns", {}).get("accounts", {})
            created = [k for k, v in shopify_sns.items() if v.get("created")]
            not_created = [k for k, v in shopify_sns.items() if not v.get("created")]
            if not_created:
                issues.append("Shopify SNS not created: %s" % ", ".join(not_created))
        except (json.JSONDecodeError, IOError):
            pass

    severity = "suggestion" if issues else "ok"
    findings.append({
        "type": severity, "agent": "sns-manager",
        "message": "SNS infrastructure: %d OK, %d issues" % (
            sum(1 for c in checks if c.startswith("[OK]")), len(issues)),
        "details": checks + (["--- Issues ---"] + issues if issues else []),
    })

    return findings


# ============================================================
# 5. proposal_history / experiments 連携
# ============================================================

def sync_sns_to_tracking():
    """SNS結果をproposal_tracking / experimentsに反映"""
    findings = []
    posted = _load_posted()
    history = posted.get("history", [])
    if not history:
        return findings

    week_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= week_ago]

    # proposal_tracking に投稿実行を記録
    tracking_path = os.path.join(SCRIPT_DIR, "proposal_tracking.json")
    if os.path.exists(tracking_path):
        try:
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)

            for proposal in tracking.get("proposals", []):
                if proposal.get("type") != "sns_post" or proposal.get("status") != "pending":
                    continue
                msg = proposal.get("message", "").lower()
                for entry in recent:
                    cat = entry.get("category", "").lower()
                    handle = entry.get("handle", "").lower()
                    if cat in msg or handle in msg:
                        proposal["status"] = "adopted"
                        proposal["adopted_date"] = entry.get("date", NOW.strftime("%Y-%m-%d"))
                        eng = entry.get("engagement", {})
                        total_eng = sum(eng.values())
                        if total_eng > 0:
                            proposal["result"] = "success" if total_eng > 10 else "weak"
                            proposal["result_date"] = NOW.strftime("%Y-%m-%d")
                        break

            with open(tracking_path, "w", encoding="utf-8") as f:
                json.dump(tracking, f, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, IOError):
            pass

    # experiments: 画像vs動画の自動登録
    exp_path = os.path.join(SCRIPT_DIR, "experiment_log.json")
    if os.path.exists(exp_path):
        try:
            with open(exp_path, "r", encoding="utf-8") as f:
                exp_data = json.load(f)

            existing = set(e.get("target", "") for e in exp_data.get("experiments", []))
            image_posts = [h for h in recent if h.get("media_type") == "image"]
            video_posts = [h for h in recent if h.get("media_type") == "video"]

            if image_posts and video_posts and "SNS: Image vs Video" not in existing:
                exp_data["experiments"].append({
                    "id": "EXP-%s-SNS01" % NOW.strftime("%y%m%d"),
                    "target": "SNS: Image vs Video",
                    "change": "Compare engagement: %d image posts vs %d video posts" % (len(image_posts), len(video_posts)),
                    "start_date": NOW.strftime("%Y-%m-%d"),
                    "end_date": (NOW + timedelta(days=14)).strftime("%Y-%m-%d"),
                    "period_days": 14,
                    "success_condition": "Video gets 2x more views than image",
                    "source_agent": "sns-manager",
                    "status": "running", "result": None, "decision": None,
                    "metrics_before": {}, "metrics_after": {},
                })
                exp_data["last_updated"] = NOW.strftime("%Y-%m-%d")

                with open(exp_path, "w", encoding="utf-8") as f:
                    json.dump(exp_data, f, indent=2, ensure_ascii=False)

                findings.append({
                    "type": "info", "agent": "sns-manager",
                    "message": "SNS experiment registered: Image vs Video comparison",
                })
        except (json.JSONDecodeError, IOError):
            pass

    return findings


# ============================================================
# 6. 競合SNSリサーチ（軽量版）
# ============================================================

def research_competitor_sns():
    """競合SNSの投稿パターンをリサーチ"""
    findings = []
    competitors = [
        {"name": "Solaris Japan", "handle": "solarisjapan"},
        {"name": "Japan Figure", "handle": "japanfigure"},
    ]

    insights = []
    for comp in competitors:
        try:
            resp = requests.get(
                "https://www.instagram.com/%s/" % comp["handle"],
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
            )
            if resp.status_code == 200:
                import re
                title = re.search(r"<title>(.*?)</title>", resp.text)
                if title:
                    insights.append("%s: %s" % (comp["name"], title.group(1)[:60]))
        except Exception:
            pass

    if insights:
        findings.append({
            "type": "info", "agent": "competitive-intelligence",
            "message": "Competitor SNS: %d accounts checked" % len(insights),
            "details": insights,
        })

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_sns_optimization():
    """SNS PDCA フルループを実行"""
    all_findings = []

    # 1. SNS実行サマリ
    all_findings.extend(generate_execution_summary())

    # 2. SNS結果サマリ（エンゲージメント取得）
    all_findings.extend(fetch_and_summarize_engagement())

    # 3. SNS学習サマリ
    all_findings.extend(generate_learning_summary())

    # 4. SNS基盤監査
    all_findings.extend(audit_sns_infrastructure())

    # 5. proposal_history / experiments 連携
    all_findings.extend(sync_sns_to_tracking())

    # 6. 競合SNSリサーチ
    all_findings.extend(research_competitor_sns())

    return all_findings
