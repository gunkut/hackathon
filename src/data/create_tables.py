"""Create the TazeRota DynamoDB tables (idempotent).

Run from app/agent:  uv run python ../../src/data/create_tables.py
"""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError

REGION = os.getenv("AWS_REGION", "us-east-1")

TABLES = {
    # Central warehouse lots (raw Urunler columns).
    os.getenv("TABLE_LOTS", "tazerota-lots"): ([("lot_id", "HASH")], [("lot_id", "S")]),
    # Dealers: sk = "PROFILE" or "STOCK#<product_code>".
    os.getenv("TABLE_DEALERS", "tazerota-dealers"): (
        [("dealer_id", "HASH"), ("sk", "RANGE")], [("dealer_id", "S"), ("sk", "S")]),
    # Daily sales: pk = "<dealer_id>#<product_code>", sk = ISO date.
    os.getenv("TABLE_SALES", "tazerota-sales"): ([("pk", "HASH"), ("sk", "RANGE")], [("pk", "S"), ("sk", "S")]),
    # Approved plans: plan_key = "<as_of>|r<risk_days>|e<early_days>".
    os.getenv("TABLE_APPROVALS", "tazerota-approvals"): ([("plan_key", "HASH")], [("plan_key", "S")]),
    # Dispatch / donation orders of an approved plan (with their notification): order_id = SE-/BG-<date>-<nnn>.
    os.getenv("TABLE_ORDERS", "tazerota-orders"): (
        [("plan_key", "HASH"), ("order_id", "RANGE")], [("plan_key", "S"), ("order_id", "S")]),
}


def main() -> None:
    ddb = boto3.client("dynamodb", region_name=REGION)
    for name, (keys, attrs) in TABLES.items():
        try:
            ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": a, "KeyType": t} for a, t in keys],
                AttributeDefinitions=[{"AttributeName": a, "AttributeType": t} for a, t in attrs],
                BillingMode="PAY_PER_REQUEST",
            )
            print(f"creating {name}")
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceInUseException":
                raise
            print(f"exists   {name}")
    for name in TABLES:
        ddb.get_waiter("table_exists").wait(TableName=name)
        print(f"ready    {name}")


if __name__ == "__main__":
    main()
