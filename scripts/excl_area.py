"""재건축 후 단지의 세대 전용면적 합계 받기 (건축HUB 건축물대장 전유공용면적)

data/land_area.json 의 단지마다 전유부 면적을 모두 받아, 용도가 아파트인 '전유' 면적을 호마다 한 번씩 더한다.
결과: data/excl_area.json  {단지id: {"excl": 전용합㎡, "units": 호 수}}  — 끝난 단지는 다시 받지 않는다.

    python scripts/excl_area.py
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from fetch import KEYFILE, ROOT

API = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo"
SRC = os.path.join(ROOT, "data", "land_area.json")
OUT = os.path.join(ROOT, "data", "excl_area.json")


def page(key, q, n):
    url = API + "?" + urllib.parse.urlencode({**q, "serviceKey": key, "numOfRows": 100, "pageNo": n})
    for i in range(5):
        try:
            return urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"page {n} 실패")


def rows(t):
    for item in re.findall(r"<item>(.*?)</item>", t, re.S):
        g = lambda k: (re.search(f"<{k}>([^<]*)</{k}>", item) or [None, ""])[1].strip()
        yield g("exposPubuseGbCd"), g("mainPurpsCd"), g("dongNm"), g("hoNm"), float(g("area") or 0)


def one(key, cid, v):
    sgg, dong, *rest = cid.split("-")
    bun, _, ji = "-".join(rest[:-1]).partition("-")
    q = {"sigunguCd": sgg, "bjdongCd": v["bjdongCd"], "bun": bun.zfill(4), "ji": (ji or "0").zfill(4)}
    first = page(key, q, 1)
    total = int(re.search(r"<totalCount>(\d+)", first).group(1))
    if "<resultCode>00<" not in first:
        raise RuntimeError(first[:200])
    pages = [first] + [page(key, q, n) for n in range(2, (total + 99) // 100 + 1)]
    units = {}
    for t in pages:
        for gb, purps, dn, ho, area in rows(t):
            if gb == "1" and purps == "02001":   # 전유 · 아파트
                units[(dn, ho)] = units.get((dn, ho), 0) + area
    return {"name": v["name"], "excl": round(sum(units.values()), 1), "units": len(units), "rows": total}


def main():
    key = open(KEYFILE, encoding="utf-8-sig").read().strip()
    src = json.load(open(SRC, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    todo = [(k, v) for k, v in src.items() if k not in out]

    def job(kv):
        try:
            return kv[0], one(key, *kv)
        except Exception as e:
            print(f"[실패] {kv[1]['name']}: {e}", flush=True)
            return kv[0], None

    with ThreadPoolExecutor(2) as ex:
        for k, r in ex.map(job, todo):
            if r:
                out[k] = r
                json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"{r['name']}: 전용 합 {r['excl']:,.1f}㎡ · {r['units']}호", flush=True)


if __name__ == "__main__":
    main()
