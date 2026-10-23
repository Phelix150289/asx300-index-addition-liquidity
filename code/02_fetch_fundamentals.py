"""Step 2 - EODHD universe and fundamentals (GICS sector, point-in-time share-count history).

* Symbol list: every ASX 'Common Stock' on EODHD (currently listed). The delisted list is saved for
  the audit trail but NOT fetched: with the current plan EODHD EOD prices are unavailable (403) and
  Yahoo has no prices for delisted tickers, so delisted names cannot be used as controls.
* Fundamentals are cached in compact form (data/cache/fundamentals_compact.json). Raw payloads that
  were already downloaded in v1 (archive_v1/data/eodhd_cache) are re-used so no API credits are spent.

Output: data/interim/universe_symbols.csv, data/interim/delisted_symbols.csv,
        data/cache/fundamentals_compact.json
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from common import CACHE, CONFIG, INTERIM, api_key

BASE = "https://eodhd.com/api"
COMPACT = CACHE / "fundamentals_compact.json"


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _series(block) -> list:
    """EODHD returns {'0': {...}, '1': {...}} or a list; normalise to [(date, shares)] sorted ascending."""
    if not block:
        return []
    items = block.values() if isinstance(block, dict) else block
    out = []
    for it in items:
        d = it.get("dateFormatted") or it.get("date")
        s = _num(it.get("shares"))
        if d and s and s > 0:
            out.append((str(d)[:10], s))
    return sorted(out)


def _bs_series(block) -> list:
    out = []
    for d, it in (block or {}).items():
        s = _num((it or {}).get("commonStockSharesOutstanding"))
        if s and s > 0:
            out.append((str(d)[:10], s))
    return sorted(out)


def compact(raw: dict) -> dict:
    g, hl, ss = raw.get("General") or {}, raw.get("Highlights") or {}, raw.get("SharesStats") or {}
    os_ = raw.get("outstandingShares") or {}
    bs = ((raw.get("Financials") or {}).get("Balance_Sheet") or {})
    return {
        "code": g.get("Code"), "name": g.get("Name"), "type": g.get("Type"),
        "currency": g.get("CurrencyCode"), "isin": g.get("ISIN"),
        "country": g.get("CountryISO"), "domestic": g.get("InternationalDomestic"),
        "ipo_date": g.get("IPODate"), "is_delisted": g.get("IsDelisted"),
        "gic_sector": g.get("GicSector"), "gic_group": g.get("GicGroup"),
        "gic_industry": g.get("GicIndustry"), "sector_legacy": g.get("Sector"),
        "industry_legacy": g.get("Industry"),
        "mcap_now": _num(hl.get("MarketCapitalization")),
        "shares_now": _num(ss.get("SharesOutstanding")),
        "shares_q": _series(os_.get("quarterly")), "shares_a": _series(os_.get("annual")),
        "bs_shares_q": _bs_series(bs.get("quarterly")), "bs_shares_a": _bs_series(bs.get("yearly")),
        "updated_at": g.get("UpdatedAt"),
    }


def _get_json(url: str, params: dict, tries: int = 5):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=90)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 403):
                return None
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    return None


def fetch_one(code: str):
    raw = _get_json(f"{BASE}/fundamentals/{code}.AU", {"api_token": api_key(), "fmt": "json"})
    return code, (compact(raw) if raw else None), "api"


def main() -> None:
    key = api_key()
    active = _get_json(f"{BASE}/exchange-symbol-list/AU", {"api_token": key, "fmt": "json"}) or []
    delisted = _get_json(f"{BASE}/exchange-symbol-list/AU", {"api_token": key, "fmt": "json", "delisted": 1}) or []
    df = pd.DataFrame(active)
    univ = df[df["Type"] == "Common Stock"][["Code", "Name", "Currency", "Isin"]].drop_duplicates("Code")
    univ.to_csv(INTERIM / "universe_symbols.csv", index=False)
    pd.DataFrame(delisted).query("Type == 'Common Stock'").to_csv(INTERIM / "delisted_symbols.csv", index=False)
    print(f"Listed common stocks: {len(univ)} | delisted common stocks (not used): {len(delisted)}")

    additions = pd.read_csv(CONFIG / "additions.csv")
    codes = sorted(set(univ["Code"]) | set(additions["ticker"]))
    store = json.loads(COMPACT.read_text(encoding="utf-8")) if COMPACT.exists() else {}
    todo = [c for c in codes if c not in store]
    print(f"Fundamentals: {len(store)} cached, {len(todo)} to fetch")

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch_one, c) for c in todo]
        for f in as_completed(futs):
            code, comp, src = f.result()
            store[code] = comp  # None is stored too: 'no fundamentals available'
            done += 1
            if done % 100 == 0 or done == len(todo):
                COMPACT.write_text(json.dumps(store), encoding="utf-8")
                print(f"  {done}/{len(todo)} (last source: {src})", flush=True)
    COMPACT.write_text(json.dumps(store), encoding="utf-8")
    missing = [c for c in codes if not store.get(c)]
    print(f"Fundamentals available for {len(codes) - len(missing)}/{len(codes)} codes; missing: {len(missing)}")


if __name__ == "__main__":
    main()
