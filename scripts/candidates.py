"""재건축 전후 연결 후보 뽑기 (mapping.json 작성 도우미)

새 단지(2009년 이후 준공)마다, 같은 법정동 안에서
  - 새 단지보다 15년 이상 오래되었고
  - 새 단지 첫 거래 전 0~9년 사이에 거래가 끊긴
옛 단지를 후보로 보여 준다. 사람이 보고 맞는 것만 mapping.json 에 적는다.

    python scripts/candidates.py 11650
"""

import sys
from collections import defaultdict

from build import complexes, load_gu
from fetch import GU


def main():
    for lawd in [a for a in sys.argv[1:] if a in GU] or list(GU):
        cs = [c for c in complexes(load_gu(lawd)) if c["count"] >= 5]
        by_dong = defaultdict(list)
        for c in cs:
            by_dong[c["dong"]].append(c)
        print(f"===== {GU[lawd]} ({lawd})")
        for dong, group in sorted(by_dong.items()):
            news = [c for c in group if c["buildYear"] >= 2009 and c["first"][:4] >= str(c["buildYear"] - 1)]
            for n in sorted(news, key=lambda c: c["buildYear"]):
                y = int(n["first"][:4])
                olds = [o for o in group if o["buildYear"] <= n["buildYear"] - 15
                        and y - 9 <= int(o["last"][:4]) <= y and o["last"] < n["first"]]
                if olds:
                    print(f"{dong} | {n['name']} ({n['buildYear']}, {n['jibun']}, 첫거래 {n['first'][:7]}, {n['count']}건)")
                    for o in sorted(olds, key=lambda o: o["last"]):
                        print(f"      ← {o['name']} ({o['buildYear']}, {o['jibun']}, {o['first'][:7]}~{o['last'][:7]}, {o['count']}건)")


if __name__ == "__main__":
    main()
