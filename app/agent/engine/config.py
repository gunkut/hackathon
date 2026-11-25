"""Tunable constants. All can be overridden with environment variables."""
from __future__ import annotations

import os
from datetime import date

# Fixed "today" of the dataset (sales history ends 24.11.2026).
AS_OF_DATE = date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-25"))
WAREHOUSE_ID = os.getenv("WAREHOUSE_ID", "DEPO-01")

REGION = os.getenv("AWS_REGION", "us-east-1")
TABLE_LOTS = os.getenv("TABLE_LOTS", "tazerota-lots")
TABLE_DEALERS = os.getenv("TABLE_DEALERS", "tazerota-dealers")
TABLE_SALES = os.getenv("TABLE_SALES", "tazerota-sales")
TABLE_APPROVALS = os.getenv("TABLE_APPROVALS", "tazerota-approvals")
TABLE_ORDERS = os.getenv("TABLE_ORDERS", "tazerota-orders")

# Single donation recipient used for donation orders (demo).
DONATION_PARTNER_ID = os.getenv("DONATION_PARTNER_ID", "BAGIS-01")
DONATION_PARTNER_NAME = os.getenv("DONATION_PARTNER_NAME", "Umut Gıda Bankası")
DONATION_LEAD_DAYS = int(os.getenv("DONATION_LEAD_DAYS", "1"))

# Risky lot: days to unsafe-ship date <= RISK_DAYS. Early warning: RISK_DAYS < days <= EARLY_DAYS.
RISK_DAYS = int(os.getenv("RISK_DAYS", "60"))
EARLY_DAYS = int(os.getenv("EARLY_DAYS", "180"))

# Daily demand = W_RECENT * (last RECENT_DAYS mean) + W_HISTORY * (HISTORY_DAYS mean).
RECENT_DAYS = 7
HISTORY_DAYS = 15
W_RECENT = 0.6
W_HISTORY = 0.4
