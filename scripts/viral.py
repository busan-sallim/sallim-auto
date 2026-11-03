"""터진 릴스 찾기 (메타 공식 '비즈니스 검색' 기능)

viral_accounts.txt 에 적은 살림 계정들의 최근 게시물 숫자(조회수·좋아요·댓글)를
메타가 공식으로 알려 주는 대로 받아 와서, 그 계정 평소보다 크게 터진 게시물만 골라 보고서를 만든다.
남의 계정에 로그인하거나 화면을 긁지 않는다 (계정 제한 위험 없음).

필요한 비밀 값
  FB_TOKEN   : 페이스북 로그인 방식 열쇠 (instagram_basic, instagram_manage_insights, pages_read_engagement)
  IG_BIZ_ID  : 우리 인스타(@busan_sallim) 프로페셔널 계정 번호 (페이스북 페이지에 연결된 계정)

사용
  python scripts/viral.py --check   # 열쇠·연결만 확인 (저장 안 함)
  python scripts/viral.py           # 모으기 → stats/viral.md, stats/viral.json
결과의 숫자는 메타가 준 그대로, 판단(왜 터졌나)은 클로드가 영상 보기로 따로 한다.
"""
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = ROOT / "viral_accounts.txt"
OUT_MD = ROOT / "stats" / "viral.md"
OUT_JSON = ROOT / "stats" / "viral.json"
API = "https://graph.facebook.com/v23.0"
KST = timezone(timedelta(hours=9))

DAYS = 60          # 최근 며칠 안 게시물만 '터진 것' 후보로 본다
RATIO = 3.0        # 그 계정 보통(중간값)보다 몇 배 넘으면 '터짐'
MEDIA = 30         # 계정마다 최근 게시물 몇 개를 볼지
FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"


def accounts() -> list[str]:
    if not ACCOUNTS.exists():
        return []
    out = []
    for line in ACCOUNTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip().lstrip("@")
        if line:
            out.append(line)
    return out


def call(params: dict) -> dict:
    r = requests.get(f"{API}/{os.environ['IG_BIZ_ID']}", params={**params, "access_token": os.environ["FB_TOKEN"]},
                     timeout=60)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(f"{r.status_code} {data.get('error', {}).get('message', data)}")
    return data


def fetch(username: str) -> dict:
    """한 계정의 팔로워 수와 최근 게시물. 조회수(view_count)를 못 받으면 빼고 다시 묻는다."""
    for fields in (FIELDS + ",view_count", FIELDS):
        q = (f"business_discovery.username({username})"
             f"{{username,followers_count,media_count,media.limit({MEDIA}){{{fields}}}}}")
        try:
            return call({"fields": q})["business_discovery"]
        except RuntimeError as e:
            if "view_count" in fields and "view_count" in str(e):
                continue
            raise
    return {}


def score(m: dict) -> int:
    """릴스는 조회수, 조회수가 없으면 좋아요+댓글."""
    if m.get("view_count") is not None:
        return int(m["view_count"])
    return int(m.get("like_count") or 0) + int(m.get("comments_count") or 0)


def analyze(acc: dict) -> list[dict]:
    media = acc.get("media", {}).get("data", [])
    reels = [m for m in media if m.get("media_product_type") == "REELS"] or media
    nums = [score(m) for m in reels]
    if len(nums) < 5:
        return []
    mid = statistics.median(nums) or 1
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    hits = []
    for m in reels:
        t = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        r = score(m) / mid
        if t >= since and r >= RATIO:
            hits.append({
                "account": acc["username"], "followers": acc.get("followers_count"),
                "date": t.astimezone(KST).strftime("%Y-%m-%d"), "ratio": round(r, 1),
                "views": m.get("view_count"), "likes": m.get("like_count"), "comments": m.get("comments_count"),
                "type": m.get("media_product_type"), "link": m.get("permalink"),
                "caption": (m.get("caption") or "").split("\n")[0][:60],
                # 좋아요보다 댓글이 훨씬 많으면 '댓글 달면 보내 드려요' 식일 가능성
                "comment_bait": bool(m.get("comments_count") and m.get("like_count")
                                     and m["comments_count"] > m["like_count"]),
            })
    return hits


def main():
    check = "--check" in sys.argv
    if not os.environ.get("FB_TOKEN") or not os.environ.get("IG_BIZ_ID"):
        print("::error::FB_TOKEN 또는 IG_BIZ_ID 비밀 값이 비어 있어요 (페이스북 페이지 연결·열쇠 만들기 먼저)")
        sys.exit(1)
    me = call({"fields": "username,followers_count"})
    print(f"연결 확인: @{me.get('username')} (팔로워 {me.get('followers_count')})")
    names = accounts()
    if check:
        if names:
            acc = fetch(names[0])
            print(f"비즈니스 검색 확인: @{acc.get('username')} 게시물 {len(acc.get('media', {}).get('data', []))}개 받음")
        else:
            print("viral_accounts.txt 에 계정이 없어요")
        return

    hits, failed = [], []
    for name in names:
        try:
            hits += analyze(fetch(name))
        except RuntimeError as e:
            failed.append(f"@{name}: {e}")   # 개인 계정·연령 제한 계정·없는 아이디는 메타가 안 알려 줌
        time.sleep(2)                        # 메타 호출 한도에 여유 두기
    hits.sort(key=lambda h: -h["ratio"])

    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps({"date": datetime.now(KST).strftime("%Y-%m-%d"), "hits": hits,
                                    "failed": failed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# 터진 릴스 ({datetime.now(KST):%Y-%m-%d})", "",
             f"계정 {len(names)}개 · 최근 {DAYS}일 · 그 계정 보통보다 {RATIO:g}배 이상", ""]
    if hits:
        lines += ["| 배수 | 계정 | 날짜 | 조회 | 좋아요 | 댓글 | 첫 줄 |", "|---|---|---|---|---|---|---|"]
        for h in hits[:20]:
            bait = " (댓글 유도)" if h["comment_bait"] else ""
            lines.append(f"| {h['ratio']}배 | @{h['account']} | {h['date']} | {h['views'] or '-'} | {h['likes']} | "
                         f"{h['comments']}{bait} | [{h['caption'] or '보기'}]({h['link']}) |")
    else:
        lines.append("이번 주엔 크게 터진 게시물이 없어요.")
    if failed:
        lines += ["", "## 못 본 계정 (개인 계정·없는 아이디일 수 있음)"] + [f"- {f}" for f in failed]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"터진 게시물 {len(hits)}개, 못 본 계정 {len(failed)}개")


if __name__ == "__main__":
    main()
