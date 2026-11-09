"""서울 아파트 매매 실거래가 내려받기 (국토교통부 공개 API)

서울 25개 구 × 2006년 1월부터 지난달까지를 월별로 받아 data/raw/<구코드>/<YYYYMM>.json 에 저장한다.
이미 받은 달은 건너뛰므로 여러 번 나눠 실행해도 된다(하루 호출 한도에 걸리면 멈추고 다음에 이어 받음).

    python scripts/fetch.py              # 서울 전체
    python scripts/fetch.py 11650 11680  # 서초구·강남구만

인증키: 이 폴더의 data_go_key.txt (공공데이터포털 '일반 인증키(Decoding)' 한 줄)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
KEYFILE = os.path.join(ROOT, "data_go_key.txt")
API = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}
START = (2006, 1)   # 실거래가 신고 자료가 시작된 때
# 저장할 항목: 단지명, 단지일련번호, 법정동, 지번, 전용면적, 거래금액(만원), 거래일, 층, 건축년도, 해제여부
FIELDS = ["aptNm", "aptSeq", "umdNm", "jibun", "excluUseAr", "dealAmount", "date", "floor", "buildYear", "cdealType"]


class LimitError(Exception):
    pass


def log(*a):
    print(*a, flush=True)


def months():
    y, m = START
    today = date.today()
    while (y, m) < (today.year, today.month):
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def call(key, lawd, ym, page):
    q = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                "pageNo": page, "numOfRows": 1000})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{API}?{q}", timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
            break
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                raise LimitError("HTTP 429")
            log(f"  [연결 오류, 다시 시도] {e}")
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("연결이 계속 실패함")
    if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text or "<returnReasonCode>22<" in text:
        raise LimitError("하루 호출 한도 초과")
    if "SERVICE_KEY_IS_NOT_REGISTERED" in text or "<returnReasonCode>30<" in text:
        raise SystemExit("인증키가 아직 등록되지 않았거나 틀렸습니다. 승인 직후라면 1~2시간 뒤 다시 실행하세요.")
    root = ET.fromstring(text)
    code = root.findtext(".//resultCode", "")
    if code not in ("00", "000"):
        raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg', '')} / {text[:200]}")
    total = int(root.findtext(".//totalCount", "0") or 0)
    rows = []
    for it in root.iter("item"):
        g = lambda k: (it.findtext(k) or "").strip()
        rows.append([
            g("aptNm"), g("aptSeq"), g("umdNm"), g("jibun"),
            float(g("excluUseAr") or 0),
            int(g("dealAmount").replace(",", "") or 0),
            f"{g('dealYear')}-{int(g('dealMonth') or 0):02d}-{int(g('dealDay') or 0):02d}",
            int(g("floor") or 0) if g("floor").lstrip("-").isdigit() else None,
            int(g("buildYear") or 0) if g("buildYear").isdigit() else None,
            g("cdealType"),
        ])
    return rows, total


def main():
    if not os.path.exists(KEYFILE):
        raise SystemExit("data_go_key.txt 파일이 없습니다.")
    with open(KEYFILE, encoding="utf-8-sig") as f:
        key = f.read().strip()
    targets = [a for a in sys.argv[1:] if a in GU] or list(GU)
    calls = 0
    try:
        for lawd in targets:
            folder = os.path.join(RAW, lawd)
            os.makedirs(folder, exist_ok=True)
            todo = [ym for ym in months() if not os.path.exists(os.path.join(folder, f"{ym}.json"))]
            if not todo:
                continue
            log(f"{GU[lawd]}: {len(todo)}개월 받기")
            for ym in todo:
                rows, total = call(key, lawd, ym, 1)
                calls += 1
                page = 1
                while len(rows) < total:
                    page += 1
                    more, _ = call(key, lawd, ym, page)
                    calls += 1
                    if not more:
                        break
                    rows += more
                with open(os.path.join(folder, f"{ym}.json"), "w", encoding="utf-8") as f:
                    json.dump({"fields": FIELDS, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
                if ym.endswith("12"):
                    log(f"  {ym[:4]}년 완료 (누적 호출 {calls}번)")
    except LimitError as e:
        log(f"{e}: 오늘은 여기까지 받았습니다. 내일 다시 실행하면 이어서 받습니다.")
    done = sum(len(os.listdir(os.path.join(RAW, d))) for d in os.listdir(RAW)) if os.path.exists(RAW) else 0
    need = len(GU) * len(list(months()))
    log(f"이번 호출 {calls}번 · 받은 자료 {done}/{need}개월")


if __name__ == "__main__":
    main()
