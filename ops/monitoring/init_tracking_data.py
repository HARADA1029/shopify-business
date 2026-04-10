"""初期追跡データ投入スクリプト（1回実行用）"""
import json
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# === 1. proposal_tracking.json ===
tracking = {
    "proposals": [
        {
            "id": "P-260402-init01", "message_hash": "init01",
            "date": "2026-04-02", "agent": "store-setup",
            "type": "page_improvement", "message": "Trust badges on all product pages",
            "score": 20, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Monitor click-through impact",
        },
        {
            "id": "P-260402-init02", "message_hash": "init02",
            "date": "2026-04-02", "agent": "growth-foundation",
            "type": "analytics_based", "message": "GA4 e-commerce events setup",
            "score": 22, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Use GA4 data for product PDCA",
        },
        {
            "id": "P-260402-init03", "message_hash": "init03",
            "date": "2026-04-06", "agent": "catalog-migration-planner",
            "type": "category_gap", "message": "Trading Cards: activate 5 drafts",
            "score": 18, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Monitor Trading Cards sales performance",
        },
        {
            "id": "P-260402-init04", "message_hash": "init04",
            "date": "2026-04-06", "agent": "content-strategist",
            "type": "internal_link", "message": "Internal links between related articles",
            "score": 16, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Add more cross-category links",
        },
        {
            "id": "P-260406-init05", "message_hash": "init05",
            "date": "2026-04-06", "agent": "content-strategist",
            "type": "article_theme", "message": "Top 5 Rare Pokemon Cards from Japan",
            "score": 20, "status": "pending", "adopted_date": None,
            "result": None, "result_date": None, "next_action": None,
        },
        {
            "id": "P-260406-init06", "message_hash": "init06",
            "date": "2026-04-06", "agent": "sns-manager",
            "type": "sns_post", "message": "Pokemon Lugia Legend SNS post",
            "score": 15, "status": "pending", "adopted_date": None,
            "result": None, "result_date": None, "next_action": None,
        },
        {
            "id": "P-260408-init07", "message_hash": "init07",
            "date": "2026-04-08", "agent": "store-setup",
            "type": "page_improvement", "message": "Shipping/Refund policies via GraphQL",
            "score": 18, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Verify policies display on storefront",
        },
        {
            "id": "P-260408-init08", "message_hash": "init08",
            "date": "2026-04-08", "agent": "growth-foundation",
            "type": "page_improvement", "message": "Collection SEO (Homepage + Sale)",
            "score": 17, "status": "adopted", "adopted_date": "2026-04-08",
            "result": "success", "result_date": "2026-04-08",
            "next_action": "Monitor Search Console impressions change",
        },
    ],
    "summary": {
        "total": 8, "adopted": 6, "rejected": 0, "pending": 2,
        "success": 6, "failed": 0,
        "accuracy_by_type": {
            "page_improvement": {"proposed": 3, "adopted": 3, "success": 3},
            "analytics_based": {"proposed": 1, "adopted": 1, "success": 1},
            "category_gap": {"proposed": 1, "adopted": 1, "success": 1},
            "internal_link": {"proposed": 1, "adopted": 1, "success": 1},
            "article_theme": {"proposed": 1, "adopted": 0, "success": 0},
            "sns_post": {"proposed": 1, "adopted": 0, "success": 0},
        },
        "last_updated": NOW.strftime("%Y-%m-%d"),
    },
}

with open("proposal_tracking.json", "w", encoding="utf-8") as f:
    json.dump(tracking, f, indent=2, ensure_ascii=False)
print("proposal_tracking.json: %d proposals" % len(tracking["proposals"]))

# === 2. experiment_log.json ===
experiments = {
    "experiments": [
        {
            "id": "EXP-260408-001",
            "target": "Trading Cards category activation",
            "change": "Activated 5 draft Trading Cards to test demand",
            "start_date": "2026-04-08", "end_date": "2026-04-22",
            "period_days": 14,
            "success_condition": "1+ sale or 50+ views on Trading Cards",
            "source_agent": "catalog-migration-planner",
            "status": "running", "result": None, "decision": None,
            "metrics_before": {"trading_cards_active": 4},
            "metrics_after": {},
        },
        {
            "id": "EXP-260408-002",
            "target": "Trust block on product pages",
            "change": "Added About This Item block to all 43 products",
            "start_date": "2026-04-08", "end_date": "2026-04-22",
            "period_days": 14,
            "success_condition": "Cart add rate improvement",
            "source_agent": "store-setup",
            "status": "running", "result": None, "decision": None,
            "metrics_before": {"trust_block": False},
            "metrics_after": {},
        },
        {
            "id": "EXP-260409-003",
            "target": "Pinterest as traffic source",
            "change": "Created 7 category boards, daily pin posting planned",
            "start_date": "2026-04-09", "end_date": "2026-04-23",
            "period_days": 14,
            "success_condition": "100+ impressions or 5+ clicks from Pinterest",
            "source_agent": "sns-manager",
            "status": "running", "result": None, "decision": None,
            "metrics_before": {"pinterest_traffic": 0},
            "metrics_after": {},
        },
    ],
    "completed": [],
    "last_updated": NOW.strftime("%Y-%m-%d"),
}

with open("experiment_log.json", "w", encoding="utf-8") as f:
    json.dump(experiments, f, indent=2, ensure_ascii=False)
print("experiment_log.json: %d experiments" % len(experiments["experiments"]))

# === 3. research_log.json ===
research = {
    "entries": [
        {
            "date": "2026-04-09", "agent": "growth-foundation",
            "researched": "GA4 pageview data, Search Console impressions/clicks",
            "categories": ["Trading Cards", "Action Figures"],
            "source": "GA4 Analytics, Search Console",
            "purpose": "Identify high-impression pages and conversion gaps",
            "proposals_count": 3, "relevance": "Core categories with traffic data",
            "id": "res00001",
        },
        {
            "date": "2026-04-09", "agent": "competitive-intelligence",
            "researched": "Solaris Japan, Japan Figure, Super Anime Store pages",
            "categories": ["Scale Figures", "Action Figures"],
            "source": "Competitor websites",
            "purpose": "Feature gap analysis and UI/UX improvement ideas",
            "proposals_count": 2, "relevance": "Same niche competitors",
            "id": "res00002",
        },
        {
            "date": "2026-04-09", "agent": "catalog-migration-planner",
            "researched": "eBay recent sales, Shopify inventory gaps",
            "categories": ["Trading Cards", "Electronic Toys", "Video Games"],
            "source": "eBay API, Shopify API",
            "purpose": "Identify hot selling items not yet on Shopify",
            "proposals_count": 4, "relevance": "Direct sales data from own eBay",
            "id": "res00003",
        },
    ],
    "last_updated": NOW.strftime("%Y-%m-%d"),
}

with open("research_log.json", "w", encoding="utf-8") as f:
    json.dump(research, f, indent=2, ensure_ascii=False)
print("research_log.json: %d entries" % len(research["entries"]))
print("\nAll done!")
