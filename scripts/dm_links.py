"""댓글 키워드 → DM 자동 링크 (인스타)

쿠팡 링크가 있는 게시물에 누가 '링크'라는 말이 들어간 댓글을 남기면
  1) 그 사람에게 DM(비공개 답장)으로 수수료 문구 + 제품 링크를 보내고
  2) 댓글에 "DM 보내 드렸어요" 같은 짧은 공개 답글을 단다 (이 답글이 '이미 보냄' 표시 역할도 함)

인스타 규칙 (공식 문서)
  - 댓글이 달린 지 7일 안에만, 댓글 1개당 DM 1번만 보낼 수 있다
  - 권한: instagram_business_manage_comments + instagram_business_manage_messages
검수 규칙 12: 개인정보는 절대 묻지 않고, 같은 문장만 반복하지 않도록 문구를 돌려 쓴다.

사용:
  python scripts/dm_links.py              실제로 보내기 (깃허브가 15분마다 실행)
  python scripts/dm_links.py --dry-run    누구에게 보낼지만 보여 주기 (아무것도 안 보냄)
  python scripts/dm_links.py --check      권한 확인만
  python scripts/dm_links.py --test 001_bath   링크가 없는 글도 '링크 모음 페이지'로 시험 발송
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
IG_API = "https://graph.instagram.com/v23.0"
KEYWORDS = ["링크", "link", "LINK", "Link"]
WINDOW_DAYS = 7
DISCLOSURE = "이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
LINK_PAGE = "https://busan-sallim.github.io/sallim-auto/"

DM_OPENERS = [
    "댓글 남겨 주셔서 고마워요!",
    "링크 요청하신 거 보내 드려요.",
    "기다리셨죠? 말씀하신 링크예요.",
    "찾으시던 제품 링크 여기 있어요.",
]
DM_CLOSERS = [
    "살림에 도움이 되면 좋겠어요 🧺",
    "써 보시고 궁금한 건 언제든 물어봐 주세요.",
    "오늘도 살림 수고 많으셨어요!",
    "다른 살림 꿀팁도 계속 올릴게요.",
]
PUBLIC_REPLIES = [
    "DM 보내 드렸어요 📩",
    "DM으로 링크 보냈어요! 확인해 보세요",
    "메시지함에 링크 넣어 드렸어요 😊",
    "DM 확인 부탁드려요~",
    "링크는 DM으로 보내 드렸어요!",
]


class NoPermission(Exception):
    pass


def call(method, url, **kw):
    r = requests.request(method, url, timeout=60, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"error": {"message": r.text[:200]}}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        msg = str(err.get("message", ""))
        if err.get("code") in (10, 190, 200) or "permission" in msg.lower():
            raise NoPermission(f"{err.get('code')} {msg[:150]}")
        raise RuntimeError(f"{r.status_code} {err.get('code')} {msg[:150]}")
    return data


def targets(test_stem: str | None) -> list[dict]:
    """최근 7일 안에 올린, 쿠팡 링크가 있는 게시물"""
    log = json.loads((ROOT / "published.json").read_text(encoding="utf-8"))
    today = dt.date.today()
    out = []
    for stem, rec in log.items():
        if not rec.get("instagram"):
            continue
        post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
        if stem == test_stem:
            post = {**post, "link": LINK_PAGE, "product": "살림코칭 추천템 모음"}
        elif not post.get("link"):
            continue
        # 게시물이 7일보다 오래돼도 최근 댓글은 받을 수 있어서 14일까지 살펴본다 (댓글별로 7일 다시 확인)
        if (today - dt.date.fromisoformat(rec["date"])).days > WINDOW_DAYS * 2:
            continue
        out.append({"stem": stem, "media": rec["instagram"], "link": post["link"],
                    "product": post.get("product") or "글에 나온 제품", "test": stem == test_stem})
    return out


def dm_text(t: dict) -> str:
    parts = []
    if not t["test"]:
        parts.append("[광고] " + DISCLOSURE)  # 공정위 지침: 수수료 문구는 맨 앞
    parts.append(random.choice(DM_OPENERS))
    parts.append(f"👉 {t['product']}\n{t['link']}")
    parts.append(random.choice(DM_CLOSERS))
    return "\n\n".join(parts)


def wants_link(text: str) -> bool:
    return any(k in (text or "") for k in KEYWORDS)


def run(dry: bool, test_stem: str | None) -> int:
    tok = os.environ["IG_TOKEN"]
    me = call("GET", f"{IG_API}/me", params={"fields": "user_id,username", "access_token": tok})
    uid, myname = me["user_id"], me["username"]
    now = dt.datetime.now(dt.timezone.utc)
    sent = failed = 0

    for t in targets(test_stem):
        comments = call("GET", f"{IG_API}/{t['media']}/comments", params={
            "fields": "id,text,timestamp,username", "limit": 100, "access_token": tok}).get("data", [])
        for c in comments:
            if c.get("username") == myname or not wants_link(c.get("text")):
                continue
            when = dt.datetime.fromisoformat(c["timestamp"].replace("+0000", "+00:00"))
            if (now - when).days >= WINDOW_DAYS:
                continue
            replies = call("GET", f"{IG_API}/{c['id']}/replies", params={
                "fields": "username", "access_token": tok}).get("data", [])
            if any(r.get("username") == myname for r in replies):
                continue  # 이미 답글 달았음 = 이미 DM 보냄
            if dry:
                print(f"[미리보기] {t['stem']} 댓글 {c['id']} → DM 보낼 예정")
                sent += 1
                continue
            try:
                call("POST", f"{IG_API}/{uid}/messages", json={
                    "recipient": {"comment_id": c["id"]}, "message": {"text": dm_text(t)}},
                    params={"access_token": tok})
            except RuntimeError as e:
                # 이미 DM을 보낸 댓글이면 공개 답글만 달아 '처리됨'으로 표시
                if "already" not in str(e).lower():
                    print(f"::warning::{t['stem']} 댓글 DM 실패: {e}")
                    failed += 1
                    continue
            call("POST", f"{IG_API}/{c['id']}/replies",
                 data={"message": random.choice(PUBLIC_REPLIES), "access_token": tok})
            print(f"{t['stem']}: 댓글 1개에 DM 보냄")
            sent += 1
    print(f"끝: 보냄 {sent}건, 실패 {failed}건")
    return failed


def check() -> bool:
    tok = os.environ.get("IG_TOKEN")
    if not tok:
        print("IG_TOKEN 이 비어 있어요")
        return False
    log = json.loads((ROOT / "published.json").read_text(encoding="utf-8"))
    media = next((r["instagram"] for r in log.values() if r.get("instagram")), None)
    try:
        d = call("GET", f"{IG_API}/{media}/comments",
                 params={"fields": "id,text,username", "access_token": tok})
        print(f"댓글 읽기 권한: 통과 (첫 글 댓글 {len(d.get('data', []))}개)")
    except NoPermission as e:
        print(f"댓글 읽기 권한: 없음 ❌ — {e}")
        return False
    print("DM 보내기 권한은 실제로 보내 봐야 알 수 있어요 → 시험 발송(--test)으로 확인")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--test", default=None, help="이 원고(예: 001_bath)는 링크 모음 페이지로 시험 발송")
    a = ap.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    try:
        failed = run(a.dry_run, a.test)
    except NoPermission as e:
        print(f"::error::권한이 없어요 — {e}")
        sys.exit(1)
    sys.exit(1 if (failed and (a.test or a.dry_run)) else 0)
