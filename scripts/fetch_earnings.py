import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.jquants.com/v2/fins/earnings-date"
KEY = os.environ.get("JQUANTS_API_KEY", "")
JST = dt.timezone(dt.timedelta(hours=9))


def get(params):
    """APIを呼ぶ。ページングと429(回数制限)のリトライ付き。"""
    rows, page_key = [], None
    while True:
        q = dict(params)
        if page_key:
            q["pagination_key"] = page_key
        req = urllib.request.Request(
            API + "?" + urllib.parse.urlencode(q), headers={"x-api-key": KEY}
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        rows += body.get("data", [])
        page_key = body.get("pagination_key")
        if not page_key:
            return rows


def pick_next(rows, today):
    """決算区分(1Q/2Q/3Q/FY)ごとに最新の公表だけを見て、今日以降で一番近い予定日を返す。"""
    latest = {}
    for r in rows:
        k = (r["FQName"], r["FYE"])
        if k not in latest or r["PubDate"] > latest[k]["PubDate"]:
            latest[k] = r
    upcoming = [r for r in latest.values() if r["SchDate"] and r["SchDate"] >= today]
    if upcoming:
        r = min(upcoming, key=lambda x: x["SchDate"])
        return {"date": r["SchDate"], "fq": r["FQName"], "status": "api"}
    limit = (dt.date.fromisoformat(today) - dt.timedelta(days=90)).isoformat()
    if any(not r["SchDate"] and r["PubDate"] >= limit for r in latest.values()):
        return {"status": "tbd"}  # 直近で「未定」に変更された
    return {}


def main():
    if not KEY:
        sys.exit("JQUANTS_API_KEY が設定されていません")
    today = dt.datetime.now(JST).strftime("%Y-%m-%d")
    with open("watchlist.json", encoding="utf-8") as f:
        watchlist = json.load(f)
    items, errors = [], 0
    for w in watchlist:
        code = str(w["code"])
        item = {"code": code, "name": w.get("name", code), "kind": w.get("kind", "watch"),
                "date": None, "fq": None, "status": "none"}
        try:
            item.update(pick_next(get({"code": code}), today))
        except Exception as e:
            errors += 1
            item["status"] = "error"
            print(f"[warn] {code}: {e}", file=sys.stderr)
        if not item["date"] and w.get("manual_date"):
            item.update(date=w["manual_date"], status="manual")
        items.append(item)
        time.sleep(0.5)
    if watchlist and errors == len(watchlist):
        sys.exit("全銘柄で取得に失敗しました（APIキーやプランを確認）")
    os.makedirs("docs", exist_ok=True)
    out = {"updated": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "items": items}
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"done: {len(items)} items, {errors} errors")


if __name__ == "__main__":
    main()