"""Load the raw sheets of dataa.xlsx into the TazeRota DynamoDB tables.

Run from app/agent:  PYTHONPATH=../../src/data uv run python ../../src/data/seed_dynamodb.py
Re-running overwrites items with the same keys.
"""
from __future__ import annotations

import os

import boto3

from excel_source import read_workbook

REGION = os.getenv("AWS_REGION", "us-east-1")
TABLE_LOTS = os.getenv("TABLE_LOTS", "tazerota-lots")
TABLE_DEALERS = os.getenv("TABLE_DEALERS", "tazerota-dealers")
TABLE_SALES = os.getenv("TABLE_SALES", "tazerota-sales")


def main() -> None:
    data = read_workbook()
    ddb = boto3.resource("dynamodb", region_name=REGION)

    with ddb.Table(TABLE_LOTS).batch_writer() as bw:
        for lot in data["lots"]:
            bw.put_item(Item=lot)
    print(f"{TABLE_LOTS}: {len(data['lots'])} lots")

    n = 0
    with ddb.Table(TABLE_DEALERS).batch_writer() as bw:
        for d in data["dealers"]:
            bw.put_item(Item={"dealer_id": d["dealer_id"], "sk": "PROFILE", "dealer_name": d["dealer_name"],
                              "lead_time_days": d["lead_time_days"]})
            n += 1
            for code, qty in d["stock"].items():
                bw.put_item(Item={"dealer_id": d["dealer_id"], "sk": f"STOCK#{code}",
                                  "product_code": code, "on_hand_qty": qty})
                n += 1
    print(f"{TABLE_DEALERS}: {n} items")

    n = 0
    with ddb.Table(TABLE_SALES).batch_writer() as bw:
        for (dealer_id, code), series in data["sales"].items():
            for day, qty in series:
                bw.put_item(Item={"pk": f"{dealer_id}#{code}", "sk": day, "dealer_id": dealer_id,
                                  "product_code": code, "qty_sold": qty})
                n += 1
    print(f"{TABLE_SALES}: {n} items")


if __name__ == "__main__":
    main()
