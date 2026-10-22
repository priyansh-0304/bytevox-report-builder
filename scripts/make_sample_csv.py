"""Generates sample_data/messy_sales.csv: ~3,000 fake sales rows, deliberately messy.
No personal data: names and notes are invented. Run: python scripts/make_sample_csv.py"""
import csv
import random
from datetime import date, timedelta

random.seed(42)
REGIONS = ["North", "South", "East", "West"]
PRODUCTS = {"Notebook": 120, "Pen Set": 80, "Desk Lamp": 950, "Backpack": 1800, "Headphones": 2500, "Water Bottle": 400}
NOTES = ["", "", "", "", "gift wrap", "repeat customer", "call before delivery",
         "<script>alert('hi')</script>", "Café order – rush", "quote \"as agreed\"", "ship to O'Brien Rd"]

rows = []
start = date(2024, 1, 1)
for i in range(1, 3001):
    d = start + timedelta(days=random.randint(0, 365))
    product = random.choice(list(PRODUCTS))
    units = random.randint(1, 20)
    price = PRODUCTS[product]
    amount = round(units * price * random.uniform(0.9, 1.1), 2)

    # --- deliberate mess ---
    date_s = d.isoformat()
    r = random.random()
    if r < 0.04:
        date_s = d.strftime("%d/%m/%Y")        # DD/MM/YYYY (day > 12 appears often, so it is detectable)
    elif r < 0.05:
        date_s = d.strftime("%d-%b-%Y")        # 05-Mar-2024
    elif r < 0.057:
        date_s = random.choice(["31/02/2024", "not a date", "2024-13-45", "tomorrow"])  # impossible / junk
    elif r < 0.067:
        date_s = ""                            # blank
    region = random.choice(REGIONS)
    if random.random() < 0.04:
        region = ""                            # blank category
    units_s = str(units)
    if random.random() < 0.03:
        units_s = random.choice(["", "N/A", "abc", "ten"])
    price_s = str(price)
    if random.random() < 0.05:
        price_s = f"₹{price:,}"                # currency + thousands separator
    amount_s = f"{amount:.2f}"
    if random.random() < 0.03:
        amount_s = random.choice(["", "-", "NaN", "12abc"])
    if random.random() < 0.004:
        amount_s = f"-{amount:.2f}"            # a refund (legit negative)
    rows.append([f"ORD-{i:05d}", date_s, region, product, units_s, price_s, amount_s, random.choice(NOTES)])

with open("sample_data/messy_sales.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["order_id", "order_date", "region", "product", "units", "unit_price", "amount", "notes"])
    for k, row in enumerate(rows):
        w.writerow(row)
        if k == 500:
            f.write("ORD-BAD-1,2024-02-02,North\n")                    # too few fields
        if k == 900:
            f.write("\n")                                              # blank line
        if k == 1500:
            f.write("ORD-BAD-2,2024-03-03,East,Pen Set,1,80,80,note,EXTRA\n")  # too many fields
        if k == 2200:
            f.write('ORD-BAD-3,2024-04-04,West,"unterminated quote,1,2,3,4\n')  # malformed quote
print("wrote sample_data/messy_sales.csv")
