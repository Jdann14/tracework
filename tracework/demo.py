"""Deterministic commerce fixture. Business definitions live in the recipe, not chat."""
import csv
import io
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from .ingest import ingest, sources
from .models import PipelineSpec

QUESTION = "Which marketing channels generate the most contribution profit after product costs, refunds, and advertising spend?"


def batches(batch=1):
    tables = {
        "orders": [dict(order_id=f"O{i:03}",customer_id=f"C{(i-1)%12+1:03}",ordered_at=f"2026-08-{i:02}",currency="USD") for i in range(1,25)],
        "order_items": [],
        "customers": [dict(customer_id=f"C{i:03}",region=["West","East","Central"][i%3]) for i in range(1,13)],
        "attribution": [dict(customer_id=f"C{i:03}",channel=["Paid search","Organic","Email","Paid social"][(i-1)%4]) for i in range(1,13)],
        "ad_spend": [dict(spend_id=f"S{i}",channel=c,amount_cents=a,currency="USD") for i,(c,a) in enumerate([("Paid search",26000),("Paid social",22000),("Email",3500),("Organic",0),("Affiliates",4000)])],
        "product_costs": [dict(product_id="P1",unit_cost_cents=2200,currency="USD"),dict(product_id="P2",unit_cost_cents=900,currency="USD"),dict(product_id="P3",unit_cost_cents=1500,currency="USD")],
        "refunds": [dict(refund_id="R1",order_id="O002",amount_cents=2500,currency="USD",received_at="2026-08-20"),dict(refund_id="R2",order_id="O004",amount_cents=4500,currency="USD",received_at="2026-08-21")],
    }
    for i in range(1,25):
        tables["order_items"].append(dict(item_id=f"I{i:03}a",order_id=f"O{i:03}",product_id="P1",quantity=1,unit_price_cents=8000+(i%4)*1000))
        if i%3 == 0:
            tables["order_items"].append(dict(item_id=f"I{i:03}b",order_id=f"O{i:03}",product_id="P2",quantity=2,unit_price_cents=3000))
    if batch >= 2:
        tables["orders"].append(deepcopy(tables["orders"][0]))
        tables["attribution"] = [r for r in tables["attribution"] if r["customer_id"] != "C008"]
        tables["refunds"] += [dict(refund_id="R3",order_id="O003",amount_cents=9000,currency="USD",received_at="2026-09-03"),dict(refund_id="R4",order_id="O999",amount_cents=1700,currency="USD",received_at="2026-09-04")]
        for r in tables["ad_spend"]:
            r["spend_cents"] = r.pop("amount_cents")
        tables["ad_spend"][0]["spend_cents"] = 30000
    return tables


def encode_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


def load_batch(workspace_id, batch):
    return {name: ingest(workspace_id,name,f"{name}_batch{batch}.csv",encode_csv(rows))["id"] for name,rows in batches(batch).items()}


def expected(batch):
    """Independent Python/Decimal oracle: no DuckDB, pipeline SQL or engine imports."""
    tables = batches(batch)
    orders = {o["order_id"]: o for o in tables["orders"]}
    channels = {r["customer_id"]: r["channel"] for r in tables["attribution"]}
    costs = {r["product_id"]: r["unit_cost_cents"] for r in tables["product_costs"]}
    totals = defaultdict(lambda: {"revenue_cents":0,"cost_cents":0,"refund_cents":0,"spend_cents":0,"orders":0})
    for o in orders.values():
        channel = channels.get(o["customer_id"], "Unattributed")
        totals[channel]["orders"] += 1
        for item in tables["order_items"]:
            if item["order_id"] == o["order_id"]:
                totals[channel]["revenue_cents"] += item["quantity"] * item["unit_price_cents"]
                totals[channel]["cost_cents"] += item["quantity"] * costs[item["product_id"]]
        for refund in tables["refunds"]:
            if refund["order_id"] == o["order_id"]:
                totals[channel]["refund_cents"] += refund["amount_cents"]
    for spend in tables["ad_spend"]:
        totals[spend["channel"]]["spend_cents"] += spend.get("amount_cents",spend.get("spend_cents"))
    return {c: Decimal(t["revenue_cents"]-t["cost_cents"]-t["refund_cents"]-t["spend_cents"])/100 for c,t in totals.items()}


def commerce_spec(workspace_id, recovery=False):
    catalog = sources(workspace_id)
    contracts = [{"name":s["name"],"columns":{c["name"]:c["type"] for c in s["versions"][0]["schema"]}} for s in catalog if s["name"] in batches()]
    spend = "spend_cents" if recovery else "amount_cents"
    def check(name, sql, severity="blocking", description=""):
        return {"name":name,"sql":sql,"severity":severity,"description":description}
    def step(name,title,sql,deps,checks=None):
        return {"name":name,"title":title,"sql":sql,"depends_on":deps,"checks":checks or []}
    money = lambda expression: f"CAST(({expression}) / 100.0 AS DECIMAL(18,2))"
    steps = [
        step("clean_orders","Establish one row per order", "SELECT DISTINCT * FROM orders" if recovery else "SELECT * FROM orders", ["orders"], [
            check("Unique order IDs","SELECT order_id, count(*) AS copies FROM clean_orders GROUP BY order_id HAVING count(*) <> 1"),
            check("USD orders only","SELECT * FROM clean_orders WHERE currency IS DISTINCT FROM 'USD' OR order_id IS NULL OR customer_id IS NULL"),
            check("Duplicate source orders","SELECT order_id,count(*) AS copies FROM orders GROUP BY order_id HAVING count(*) > 1","warning"),
        ]),
        step("costed_items","Cost each order item", "SELECT i.*, c.unit_cost_cents, c.currency AS cost_currency FROM order_items i LEFT JOIN product_costs c USING(product_id)", ["order_items","product_costs"], [
            check("One cost per product","SELECT product_id,count(*) AS copies FROM product_costs GROUP BY product_id HAVING count(*)<>1"),
            check("Join preserves item grain","SELECT (SELECT count(*) FROM costed_items) AS actual, (SELECT count(*) FROM order_items) AS expected WHERE actual<>expected"),
            check("Unique item IDs","SELECT item_id,count(*) AS copies FROM costed_items GROUP BY item_id HAVING count(*)<>1"),
            check("Valid prices and USD costs","SELECT * FROM costed_items WHERE unit_cost_cents IS NULL OR unit_cost_cents<0 OR cost_currency IS DISTINCT FROM 'USD' OR quantity IS NULL OR quantity<=0 OR unit_price_cents IS NULL OR unit_price_cents<0"),
        ]),
        step("order_margin","Aggregate items before joining refunds", "SELECT order_id, SUM(quantity * unit_price_cents)::BIGINT AS revenue_cents, SUM(quantity * unit_cost_cents)::BIGINT AS cost_cents FROM costed_items GROUP BY order_id", ["costed_items"]),
        step("refund_totals","Aggregate refunds at order grain", "SELECT order_id,SUM(amount_cents)::BIGINT AS refund_cents FROM refunds GROUP BY order_id", ["refunds","clean_orders"], [
            check("Refunds with no matching order","SELECT r.* FROM refunds r LEFT JOIN clean_orders o USING(order_id) WHERE o.order_id IS NULL","warning","Excluded from channel profit; investigate separately."),
            check("Late-arriving refunds","SELECT r.* FROM refunds r JOIN clean_orders o USING(order_id) WHERE CAST(r.received_at AS DATE) > CAST(o.ordered_at AS DATE) + INTERVAL 14 DAY","warning"),
            check("Unique refund IDs","SELECT refund_id,count(*) AS copies FROM refunds GROUP BY refund_id HAVING count(*)<>1"),
            check("Valid USD refunds","SELECT * FROM refunds WHERE amount_cents IS NULL OR amount_cents<0 OR currency IS DISTINCT FROM 'USD'"),
        ]),
        step("attributed_orders","Join customers and acquisition channel", "SELECT o.order_id, COALESCE(a.channel,'Unattributed') AS channel, m.revenue_cents,m.cost_cents,COALESCE(r.refund_cents,0) AS refund_cents FROM clean_orders o LEFT JOIN customers c USING(customer_id) LEFT JOIN attribution a ON a.customer_id=c.customer_id LEFT JOIN order_margin m USING(order_id) LEFT JOIN refund_totals r USING(order_id)", ["clean_orders","customers","attribution","order_margin","refund_totals"], [
            check("Join preserves order grain","SELECT (SELECT count(*) FROM attributed_orders) AS actual,(SELECT count(*) FROM clean_orders) AS expected WHERE actual<>expected"),
            check("Unique customer IDs","SELECT customer_id,count(*) AS copies FROM customers GROUP BY customer_id HAVING count(*)<>1"),
            check("One attribution per customer","SELECT customer_id,count(*) AS copies FROM attribution GROUP BY customer_id HAVING count(*)<>1"),
            check("Orders missing item totals","SELECT * FROM attributed_orders WHERE revenue_cents IS NULL"),
            check("Missing attribution","SELECT order_id FROM attributed_orders WHERE channel='Unattributed'","warning"),
        ]),
        step("channel_profit","Calculate contribution profit by channel", f"WITH sales AS (SELECT channel,count(*) AS orders,SUM(revenue_cents) AS revenue_cents,SUM(cost_cents) AS cost_cents,SUM(refund_cents) AS refund_cents FROM attributed_orders GROUP BY channel), spend AS (SELECT channel,SUM({spend}) AS spend_cents FROM ad_spend GROUP BY channel) SELECT COALESCE(s.channel,a.channel) AS channel,'USD' AS currency,COALESCE(orders,0) AS orders,{money('COALESCE(revenue_cents,0)')} AS revenue,{money('COALESCE(cost_cents,0)')} AS product_costs,{money('COALESCE(refund_cents,0)')} AS refunds,{money('COALESCE(spend_cents,0)')} AS ad_spend,{money('COALESCE(revenue_cents,0)-COALESCE(cost_cents,0)-COALESCE(refund_cents,0)-COALESCE(spend_cents,0)')} AS contribution_profit FROM sales s FULL OUTER JOIN spend a USING(channel) ORDER BY contribution_profit DESC,channel", ["attributed_orders","ad_spend"], [
            check("Valid USD spend",f"SELECT * FROM ad_spend WHERE currency IS DISTINCT FROM 'USD' OR {spend} IS NULL OR {spend}<0"),
            check("Unique spend IDs","SELECT spend_id,count(*) AS copies FROM ad_spend GROUP BY spend_id HAVING count(*)<>1"),
        ]),
    ]
    return PipelineSpec.model_validate({"title":"Channel contribution profit","description":"Revenue → product costs → refunds → advertising, with every join checked at its intended grain.","assumptions":[
        "USD only. Money is stored in integer cents and presented as decimal USD; no currency conversion.",
        "Revenue is quantity × unit price, excluding tax and shipping. Contribution excludes overhead, payment fees and fulfillment costs because these are absent.",
        "Customer acquisition channel is the single supplied attribution record. Missing attribution stays Unattributed; it is never guessed.",
        "Each upload is a full snapshot. All supplied orders and advertising are in scope; no incremental append or implicit date filter.",
        "Refunds reduce the original order's channel when received, including late refunds. Unmatched refunds are excluded with warnings. Product costs are not reversed on refunds.",
        "Aggregate items and refunds separately before joining at order grain. Include advertising channels with no orders.",
        "Exact duplicate order rows are removed; conflicting records with the same order ID still block." if recovery else "Duplicate order IDs block execution and require an explicit data or recipe correction.",
    ],"sources":contracts,"steps":steps,"output":"channel_profit"})


def export_demo():
    for batch in (1,2):
        folder = Path("demo") / f"batch{batch}"
        folder.mkdir(parents=True,exist_ok=True)
        for name,rows in batches(batch).items():
            (folder / f"{name}.csv").write_bytes(encode_csv(rows))


if __name__ == "__main__":
    export_demo()
