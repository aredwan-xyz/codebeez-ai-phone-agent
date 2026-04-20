#!/usr/bin/env python3
"""
Seed the knowledge base with sample company content.
Run: python scripts/seed_kb.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLE_DOCUMENTS = [
    (
        "company_overview",
        """
        Acme Corp is a leading provider of enterprise software solutions.
        We were founded in 2010 and serve over 5,000 businesses worldwide.
        Our headquarters is in San Francisco, CA.
        Office hours: Monday–Friday, 9 AM to 6 PM Eastern Time.
        """,
    ),
    (
        "pricing",
        """
        Pricing Plans:
        - Starter: $49/month — up to 5 users, basic features.
        - Professional: $149/month — up to 25 users, all features.
        - Enterprise: Custom pricing — unlimited users, dedicated support, SLA guarantee.
        Annual plans include a 20% discount.
        Free 14-day trial available with no credit card required.
        """,
    ),
    (
        "support_policy",
        """
        Support tiers:
        - Starter plan: Email support with 48-hour response time.
        - Professional plan: Email + chat support, 8-hour response.
        - Enterprise plan: 24/7 phone support, 1-hour SLA, dedicated account manager.
        Refund policy: 30-day money-back guarantee on annual plans.
        """,
    ),
    (
        "product_features",
        """
        Key features of Acme Platform:
        - Real-time analytics dashboard with customizable reports.
        - Automated workflow builder with 200+ integrations.
        - AI-powered forecasting and anomaly detection.
        - Role-based access control with SSO support.
        - API access with comprehensive documentation.
        - Mobile apps for iOS and Android.
        """,
    ),
]


async def main():
    from app.db.base import init_db
    from app.tools.knowledge_base import ingest_document

    await init_db()
    print("Seeding knowledge base...")
    for source, content in SAMPLE_DOCUMENTS:
        await ingest_document(source=source, content=content)
        print(f"  ✓ {source}")
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
