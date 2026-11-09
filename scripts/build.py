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
