"""'현재' 탭 자료: 서울의 지금 아파트 전체 (2025년 이후 매매 실거래가 있는 단지)

단지마다 건축물대장(건축HUB)의 대지면적·세대수를 받아 data/now_area.json 에 모아 두고(받은 단지는 다시 받지 않음),
docs/data/now_<구코드>.json 을 만든다. 전용면적 합은 data/excl_area.json 에 있는 단지만 붙는다.

    python scripts/now.py          # 대장 받기 + 화면 자료 만들기 (하루 호출 한도에 걸리면 다음 날 다시 실행)
    python scripts/now.py --build  # 받기 없이 화면 자료만 만들기
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from build import load_gu
from fetch import GU, KEYFILE, ROOT
from land_area import CODES, call, load

AREA = os.path.join(ROOT, "data", "now_area.json")
EXCL = os.path.join(ROOT, "data", "excl_area.json")
SINCE = "2025-01"


def complexes(lawd):
    """(법정동, 지번, 건축년도)로 단지를 묶고, SINCE 이후 거래가 있는 단지만 남긴다."""
    groups = defaultdict(list)
    for r in load_gu(lawd):
        if r["buildYear"] and r["jibun"] and r["jibun"][0].isdigit():
            groups[(r["umdNm"], r["jibun"], r["buildYear"])].append(r)
    out = []
    for (dong, jibun, by), rs in groups.items():
        rs.sort(key=lambda r: r["date"])
        if rs[-1]["date"] < SINCE:
            continue
        out.append({"id": f"{lawd}-{dong}-{jibun}-{by}", "name": Counter(r["aptNm"] for r in rs[-20:]).most_common(1)[0][0],
                    "dong": dong, "jibun": jibun, "buildYear": by,
                    "recent": [[r["date"], r["excluUseAr"], r["dealAmount"], r["floor"]] for r in rs[-10:]][::-1]})
    return out


def scan_codes(key, lawd, codes):
    """구 안의 법정동 코드를 모두 찾는다: 10100~18900 을 차례로 조회해 대장 주소의 동 이름을 읽는다."""
    if any(k.startswith(lawd + "-*") for k in codes):
        return
    err = False
    for n in range(101, 190):   # 종로·중구는 법정동이 많아 18700 까지 있다
        q = urllib.parse.urlencode({"serviceKey": key, "sigunguCd": lawd, "bjdongCd": f"{n}00", "numOfRows": 1, "pageNo": 1})
        try:
            t = urllib.request.urlopen("https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?" + q, timeout=30).read().decode()
        except Exception:
            err = True
            continue
        i = t.find("<platPlc>")
        if i >= 0:
            dong = t[i + 9:t.find("<", i + 9)].split()[2]
            codes.setdefault(f"{lawd}-{dong}", f"{n}00")
    if not err:   # 한도 초과 등으로 빠진 코드가 있으면 다음에 다시 찾는다
        codes[lawd + "-*"] = "done"


def ledger(key, lawd, bj, c):
    rows = call(key, "getBrRecapTitleInfo", lawd, bj, c["jibun"])
    rows = [r for r in rows if r["platArea"] > 0]
    if rows:   # 총괄표제부: 단지 이름이 맞는 것, 없으면 대지가 가장 큰 것
        b = max(rows, key=lambda r: (c["name"].replace(" ", "") in r["bldNm"].replace(" ", ""), r["platArea"]))
        return {"plat": b["platArea"], "hh": b["hhldCnt"], "bld": b["bldNm"]}
    rows = [r for r in call(key, "getBrTitleInfo", lawd, bj, c["jibun"]) if r["platArea"] > 0]
    if rows:   # 총괄표제부가 없는 작은 단지: 동별 표제부의 세대수를 더한다
        return {"plat": max(r["platArea"] for r in rows), "hh": sum(r["hhldCnt"] for r in rows), "bld": rows[0]["bldNm"]}
    return {"plat": 0, "hh": 0, "bld": ""}


def main():
    key = open(KEYFILE, encoding="utf-8-sig").read().strip()
    codes, area = load(CODES, {}), load(AREA, {})
    excl = load(EXCL, {})
    fetch = "--build" not in sys.argv
    stop = []
    for lawd, gu in GU.items():
        cs = complexes(lawd)
        if fetch:
            scan_codes(key, lawd, codes)
            json.dump(codes, open(CODES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            todo = [c for c in cs if c["id"] not in area and codes.get(f"{lawd}-{c['dong']}")]

            def job(c):
                if stop:   # 쉬었다 불러도 429 면 하루 한도를 다 쓴 것: 오늘은 그만
                    return c["id"], None
                try:
                    return c["id"], ledger(key, lawd, codes[f"{lawd}-{c['dong']}"], c)
                except Exception as e:
                    if "429" in str(e):
                        stop.append(1)
                    print(f"   [실패] {c['name']}: {e}", flush=True)
                    return c["id"], None

            with ThreadPoolExecutor(2) as ex:   # 4개면 429(너무 빨리 부름)가 많이 남
                for n, (cid, r) in enumerate(ex.map(job, todo), 1):
                    if r:
                        area[cid] = r
                    if n % 50 == 0:
                        json.dump(area, open(AREA, "w", encoding="utf-8"), ensure_ascii=False)
            json.dump(area, open(AREA, "w", encoding="utf-8"), ensure_ascii=False)
        items = []
        for c in cs:
            a = area.get(c["id"])
            if not a or not a["plat"] or not a["hh"]:
                continue
            e = excl.get(c["id"], {}).get("excl")
            items.append({**c, "address": f"서울특별시 {gu} {c['dong']} {c['jibun']}", "plat": a["plat"], "hh": a["hh"],
                          "excl": e or None})
        json.dump({"gu": gu, "items": items}, open(os.path.join(ROOT, "docs", "data", f"now_{lawd}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"{gu}: 단지 {len(cs)}곳 중 대장 있는 곳 {len(items)}곳", flush=True)


if __name__ == "__main__":
    main()
