"""재건축 후 단지의 대지면적 받기 (국토교통부 건축HUB 건축물대장 총괄표제부)

docs/data/<구>.json 의 단지 주소(구·법정동·지번)로 건축물대장을 조회해 data/land_area.json 에 저장한다.
법정동 코드는 몰라도 되도록, 동마다 코드를 차례로 시험해 주소가 맞는 것을 찾아 data/bjdong.json 에 저장해 둔다.

    python scripts/land_area.py
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from fetch import KEYFILE, ROOT

API = "https://apis.data.go.kr/1613000/BldRgstHubService/"
OUT = os.path.join(ROOT, "data", "land_area.json")
CODES = os.path.join(ROOT, "data", "bjdong.json")


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return d


def call(key, ep, sgg, bj, jibun):
    bun, _, ji = jibun.partition("-")
    q = urllib.parse.urlencode({"serviceKey": key, "sigunguCd": sgg, "bjdongCd": bj,
                                "bun": bun.zfill(4), "ji": (ji or "0").zfill(4), "numOfRows": 100, "pageNo": 1})
    for n in range(4):   # 서버가 가끔 500 을 내므로 몇 번 다시 시도
        try:
            t = urllib.request.urlopen(API + ep + "?" + q, timeout=30).read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or n == 3:   # 429: 너무 빨리 부름 → 잠시 쉬고 다시
                raise
            time.sleep(5 * (n + 1))
    rows = []
    for item in re.findall(r"<item>(.*?)</item>", t, re.S):
        g = lambda k: (re.search(f"<{k}>([^<]*)</{k}>", item) or [None, ""])[1]
        rows.append({"bldNm": g("bldNm"), "platArea": float(g("platArea") or 0),
                     "hhldCnt": int(g("hhldCnt") or 0), "platPlc": g("platPlc")})
    return rows


def find_code(key, sgg, dong, jibun, codes):
    """그 동의 법정동 코드를 찾는다: 10100~13900 을 시험해 대장 주소에 동 이름이 들어 있는 것."""
    k = f"{sgg}-{dong}"
    if k in codes:
        return codes[k]
    for n in range(101, 140):
        bj = f"{n}00"
        try:
            rows = call(key, "getBrTitleInfo", sgg, bj, jibun)
        except urllib.error.HTTPError:
            continue
        if any(f" {dong} " in r["platPlc"] + " " for r in rows):
            codes[k] = bj
            return bj
    return None


def main():
    key = open(KEYFILE, encoding="utf-8-sig").read().strip()
    codes, out = load(CODES, {}), load(OUT, {})
    for name in sorted(os.listdir(os.path.join(ROOT, "docs", "data"))):
        if name == "index.json":
            continue
        sgg = name[:5]
        for it in json.load(open(os.path.join(ROOT, "docs", "data", name), encoding="utf-8"))["items"]:
            if it["id"] in out:
                continue
            bj = find_code(key, sgg, it["dong"], it["jibun"], codes)
            json.dump(codes, open(CODES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if not bj:
                print(f"[법정동 코드 못 찾음] {it['dong']} {it['jibun']} {it['name']}")
                continue
            rows = call(key, "getBrRecapTitleInfo", sgg, bj, it["jibun"]) or call(key, "getBrTitleInfo", sgg, bj, it["jibun"])
            rows = [r for r in rows if r["platArea"] > 0]
            if not rows:
                print(f"[대장 없음] {it['dong']} {it['jibun']} {it['name']}")
                continue
            best = max(rows, key=lambda r: (it["name"].replace(" ", "") in r["bldNm"].replace(" ", ""), r["platArea"]))
            out[it["id"]] = {"name": it["name"], **best, "bjdongCd": bj}
            print(f"{it['name']}: 대지 {best['platArea']:,.1f}㎡ · 대장 이름 {best['bldNm']} · {best['platPlc']}")
            json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
