from vnstock import Company, Listing
import pandas as pd

print("=" * 60)
print("TEST 1: Listing.all_symbols() columns")
print("=" * 60)
lst = Listing()
df = lst.all_symbols()
print("Columns:", df.columns.tolist())
print("Sample VNM row:")
print(df[df["symbol"] == "VNM"].to_string())

print()
print("=" * 60)
print("TEST 2: Listing.symbols_by_exchange() columns")
print("=" * 60)
try:
    df2 = lst.symbols_by_exchange()
    print("Columns:", df2.columns.tolist())
    print("Sample VNM row:")
    print(df2[df2["symbol"] == "VNM"].to_string())
except Exception as e:
    print("ERROR:", e)

print()
print("=" * 60)
print("TEST 3: Company methods on VNM (source=VCI)")
print("=" * 60)
c = Company(symbol="VNM", source="VCI")
print("Available methods:", [m for m in dir(c) if not m.startswith("_")])
for method in ["overview", "profile", "shareholders", "officers", "subsidiaries"]:
    try:
        result = getattr(c, method)()
        if hasattr(result, "columns"):
            print(f"{method} OK - columns: {result.columns.tolist()}")
            print(result.head(1).to_string())
        else:
            print(f"{method} OK:", result)
    except Exception as e:
        print(f"{method} ERROR: {e}")

print()
print("=" * 60)
print("TEST 4: Listing extra methods")
print("=" * 60)
for method in ["symbols_by_industries", "industries_icb", "all_future_indices", "all_covered_warrant"]:
    try:
        result = getattr(lst, method)()
        if hasattr(result, "columns"):
            print(f"{method} OK - columns: {result.columns.tolist()}")
        else:
            print(f"{method} OK:", result)
    except Exception as e:
        print(f"{method} ERROR: {e}")
