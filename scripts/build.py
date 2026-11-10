"""재건축 전후 단지 연결 + 화면용 자료 만들기

data/raw 의 실거래가에서 '재건축되어 이미 완공된 단지'를 찾아, 재건축 전(옛 단지) 거래만 모아
docs/data/<구코드>.json 으로 저장한다.

재건축 판별 규칙 (같은 구·법정동·지번 안에서)
  - 옛 단지: 건축년도가 오래되었고, 어느 때부터 거래가 끊긴 단지
  - 새 단지: 옛 단지보다 건축년도가 15년 이상 늦고, 옛 단지 거래가 끊긴 뒤 거래가 시작된 단지
  - 새 단지가 지번을 합쳐 다른 지번으로 바뀐 경우 등은 mapping.json 에 직접 적어 연결한다

    python scripts/build.py
"""

import json
import os
from collections import Counter, defaultdict

from fetch import GU, RAW, ROOT, months as all_months

OUT = os.path.join(ROOT, "docs", "data")
MAPPING = os.path.join(ROOT, "mapping.json")
MIN_GAP_YEARS = 15


def load_gu(lawd):
    folder = os.path.join(RAW, lawd)
    rows = []
    if not os.path.isdir(folder):
        return rows
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            d = json.load(f)
        i = {k: n for n, k in enumerate(d["fields"])}
        for r in d["rows"]:
            if r[i["cdealType"]] == "O":   # 해제된 거래는 뺀다
                continue
            rows.append({k: r[n] for k, n in i.items()})
    return rows


def complexes(rows):
    """(법정동, 지번, 건축년도) 단위로 단지를 묶는다. 같은 단지가 해마다 이름이 조금씩 달라도 하나로 본다."""
    groups = defaultdict(list)
    for r in rows:
        if not r["buildYear"] or not r["jibun"]:
            continue
        groups[(r["umdNm"], r["jibun"], r["buildYear"])].append(r)
    out = []
    for (dong, jibun, by), rs in groups.items():
        rs.sort(key=lambda r: r["date"])
        names = Counter(r["aptNm"] for r in rs)
        out.append({
            "dong": dong, "jibun": jibun, "buildYear": by,
            "name": names.most_common(1)[0][0],
            "names": [n for n, _ in names.most_common()],
            "first": rs[0]["date"], "last": rs[-1]["date"],
            "count": len(rs), "rows": rs,
        })
    return out


def find_pairs(cs, manual):
    by_lot = defaultdict(list)
    for c in cs:
        by_lot[(c["dong"], c["jibun"])].append(c)
    pairs = []
    for lot, group in by_lot.items():
        group.sort(key=lambda c: c["buildYear"])
        for old in group:
            for new in group:
                if (old["buildYear"] <= 1995 and old["count"] >= 10 and new["last"] >= "2022"
                        and new["buildYear"] - old["buildYear"] >= MIN_GAP_YEARS
                        and new["first"] > old["last"]
                        and int(old["last"][:4]) <= new["buildYear"]):
                    pairs.append((old, new))
    # 직접 연결 (mapping.json): {"gu": "11650", "dong": "반포동", "old": ["옛 단지명"], "new": "새 단지명", "check": true}
    #   old 에 "동이름:단지명"으로 적으면 다른 동의 단지도 연결할 수 있다. check=true 는 '연결 확인 필요' 표시
    by_name = defaultdict(list)
    for c in cs:
        for n in c["names"]:
            by_name[(c["dong"], n)].append(c)
    for m in manual:
        news = sorted(by_name.get((m["dong"], m["new"]), []), key=lambda c: -c["buildYear"])
        if not news:
            print(f"   [연결 실패] 새 단지 없음: {m['dong']} {m['new']}")
            continue
        new = news[0]
        if m.get("check"):
            new["check"] = True
        if m.get("name"):
            new["display"] = m["name"]
        for o in m["old"]:
            dong, name = o.split(":", 1) if ":" in o else (m["dong"], o)
            olds = [c for c in by_name.get((dong, name), []) if c["buildYear"] < new["buildYear"]]
            if not olds:
                print(f"   [연결 실패] 옛 단지 없음: {dong} {name} → {m['new']}")
            for old in olds:
                pairs.append((old, new))
    # 새 단지 하나에 옛 단지가 여럿일 수 있다(예: 여러 차수를 합쳐 재건축)
    merged = {}
    for old, new in pairs:
        k = (new["dong"], new["jibun"], new["buildYear"])
        e = merged.setdefault(k, {"new": new, "olds": {}})
        e["olds"][(old["dong"], old["jibun"], old["buildYear"])] = old
    return list(merged.values())


PRESS = os.path.join(ROOT, "press.json")
LAND = os.path.join(ROOT, "land.json")


def add_land(lawd, gu, cs, items):
    """재건축 전 세대당 대지지분 = 새 단지 대지면적(건축물대장) ÷ 재건축 전 세대수(land.json)."""
    if not os.path.exists(LAND):
        return
    areas = json.load(open(os.path.join(ROOT, "data", "land_area.json"), encoding="utf-8"))         if os.path.exists(os.path.join(ROOT, "data", "land_area.json")) else {}
    for d in json.load(open(LAND, encoding="utf-8"))["items"]:
        if d["gu"] != lawd:
            continue
        it = next((x for x in items if x["name"] == d["name"]), None)
        if it is None:   # 2006년 전에 철거되어 재건축 전 거래가 없는 단지: 지금 단지 위치로 대지지분만 표시
            f = max([c for c in cs if d["name"] in c["names"]], key=lambda c: c["count"], default=None)
            if f:
                it = {"id": f"{lawd}-{f['dong']}-{f['jibun']}-{f['buildYear']}", "name": d["name"], "check": False,
                      "dong": f["dong"], "jibun": f["jibun"], "address": f"서울특별시 {gu} {f['dong']} {f['jibun']}",
                      "buildYear": f["buildYear"], "old": [{"name": d["old"], "names": [d["old"]], "buildYear": None,
                      "jibun": None, "first": None, "last": None, "count": 0}], "trades": []}
                items.append(it)
        a = areas.get(it["id"]) if it else None
        if not a:
            print(f"   [대지지분 못 냄] {d['name']} (단지 또는 대지면적 없음)")
            continue
        m2 = a["platArea"] / d["households"]
        it["land"] = {"py": round(m2 / 3.3058, 1), "m2": round(m2, 1), "plat": a["platArea"], "hh": d["households"],
                      "old": d["old"], "source": d["source"], "url": d["url"]}
        print(f"   [대지지분] {it['name']} ← {d['old']}: {a['platArea']:,.1f}㎡ ÷ {d['households']:,}세대 = {it['land']['py']}평")


def add_press(lawd, gu, cs, items):
    """press.json(2006년 이전 신문 시세)을 단지에 붙인다. 실거래가가 없는 단지는 새로 만든다."""
    if not os.path.exists(PRESS):
        return
    press = json.load(open(PRESS, encoding="utf-8"))
    for c in [c for c in press["complexes"] if c["gu"] == lawd]:
        pts = []
        for a in press["articles"]:
            for p in a["prices"]:
                if p["key"] == c["key"]:
                    pts.append([a["date"], p["pyeong"], p["low"], p["high"], p["kind"], p.get("memo", ""),
                                a["paper"], a["title"], a["url"]])
        if not pts:
            continue
        target = next((it for it in items if c["new"] and it["name"] == c["new"]), None)
        if target is None:
            # 지도 위치: 새 단지(없으면 옛 단지)의 지번
            name = c["new"] or c["old"]
            found = sorted([x for x in cs if x["dong"] == c["dong"] and name in x["names"]], key=lambda x: -x["count"])
            if not found:
                print(f"   [신문 시세 단지 위치 못 찾음] {c['dong']} {name}")
                continue
            f = found[0]
            target = {"id": f"{lawd}-press-{c['key']}", "name": c["new"] or c["old"], "check": False,
                      "dong": c["dong"], "jibun": f["jibun"], "address": f"서울특별시 {gu} {c['dong']} {f['jibun']}",
                      "buildYear": f["buildYear"] if c["new"] else None,
                      "old": [{"name": c["old"], "names": [c["old"]], "buildYear": None, "jibun": None,
                               "first": None, "last": None, "count": 0}],
                      "trades": [], "note": c.get("note", "")}
            # 옛 단지가 2006년 이후에도 거래되었다면(예: 반포주공1단지) 그 실거래가도 붙인다
            for x in cs:
                if x["dong"] == c["dong"] and c["old"] in x["names"]:
                    target["trades"] += [[r["date"], r["excluUseAr"], r["dealAmount"], r["floor"], x["name"]] for r in x["rows"]]
                    target["old"][0].update({"buildYear": x["buildYear"], "jibun": x["jibun"],
                                             "first": x["first"], "last": x["last"], "count": x["count"]})
            target["trades"].sort()
            items.append(target)
        target["press"] = sorted(target.get("press", []) + pts)
        print(f"   [신문 시세] {target['name']} ← {c['old']} {len(pts)}건")


def main():
    os.makedirs(OUT, exist_ok=True)
    manual_all = json.load(open(MAPPING, encoding="utf-8")) if os.path.exists(MAPPING) else []
    index = []
    for lawd, gu in GU.items():
        folder = os.path.join(RAW, lawd)
        if not os.path.isdir(folder) or len(os.listdir(folder)) < len(list(all_months())):
            print(f"{gu}: 아직 자료를 다 받지 않아 건너뜀")
            continue
        rows = load_gu(lawd)
        if not rows:
            continue
        cs = complexes(rows)
        found = find_pairs(cs, [m for m in manual_all if m.get("gu") == lawd])
        items = []
        for e in found:
            new, olds = e["new"], list(e["olds"].values())
            trades = []
            for o in olds:
                for r in o["rows"]:
                    trades.append([r["date"], r["excluUseAr"], r["dealAmount"], r["floor"], o["name"]])
            trades.sort()
            items.append({
                "id": f"{lawd}-{new['dong']}-{new['jibun']}-{new['buildYear']}",
                "name": new.get("display") or new["name"],
                "check": bool(new.get("check")),
                "dong": new["dong"],
                "jibun": new["jibun"],
                "address": f"서울특별시 {gu} {new['dong']} {new['jibun']}",
                "buildYear": new["buildYear"],
                "old": [{"name": o["name"], "names": o["names"], "buildYear": o["buildYear"],
                         "jibun": o["jibun"], "first": o["first"], "last": o["last"], "count": o["count"]}
                        for o in sorted(olds, key=lambda o: o["name"])],
                "trades": trades,
            })
        add_press(lawd, gu, cs, items)
        add_land(lawd, gu, cs, items)
        items.sort(key=lambda it: (it["dong"], it["name"]))
        with open(os.path.join(OUT, f"{lawd}.json"), "w", encoding="utf-8") as f:
            json.dump({"gu": gu, "items": items}, f, ensure_ascii=False, separators=(",", ":"))
        months = [t[0][:7] for it in items for t in it["trades"]]
        index.append({"code": lawd, "gu": gu, "count": len(items),
                      "first": min(months) if months else None, "last": max(months) if months else None})
        print(f"{gu}: 거래 {len(rows):,}건 · 재건축 완공 단지 {len(items)}개")
        for it in items:
            olds = ", ".join(f"{o['name']}({o['buildYear']})" for o in it["old"])
            print(f"   {it['dong']} {it['name']}({it['buildYear']}) ← {olds} · 재건축 전 거래 {len(it['trades'])}건")
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
