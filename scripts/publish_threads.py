"""스레드 따로 자동발행 (2026-11-06, 사용자 확정: 노출 극대화 방식)

하루 3번 (한국 시간, 주부 생활 시간 기준):
  아침 슬롯  09시대   threads/ 폴더의 스레드 전용 글 (사진 1장 + 짧은 글 + 질문)
  점심 슬롯  13시대   threads/ 폴더의 스레드 전용 글
  밤 슬롯    21시대   그날 인스타에 올라간 카드뉴스를 '스레드용 글'로 캐러셀 발행
                      (새 카드가 없으면 threads/ 글로 대신)

노출 근거 (사용자에게 설명한 내용, 2026-11-06)
  - [공식] 스레드 추천 피드는 좋아요·답글·팔로우·프로필 클릭·넘기기를 예측해 순서를 정함 → 끝에 질문 한 줄로 답글 유도
  - [업계 자료] 사진 글이 글만 있는 글보다 반응 약 60%↑, 링크 글보다 37%↑ → 사진 필수, 링크는 본문 대신 첫 댓글(답글)
  - [공식] 텍스트 500자 제한, 하루 발행 250개·답글 1000개 한도

쿠팡 링크 글: 본문 첫 줄에 수수료 문구(고정 규칙) + 링크는 첫 답글(답글 첫 줄에도 수수료 문구).
답글 권한(threads_manage_replies)이 토큰에 없으면 예전처럼 본문에 링크를 넣고 경고만 남긴다.

기록: threads_published.json  {"글이름": {"id":…, "reply":…, "date":…, "slot":…}}
      카드뉴스 스레드 글 id 는 published.json 의 그 원고 "threads" 에도 적는다(통계가 그대로 이어지게)

사용:
  python scripts/publish_threads.py --slot auto       지금 시간 슬롯에 1개 발행 (이미 했으면 건너뜀)
  python scripts/publish_threads.py --dry-run         지금 슬롯에 무엇이 나갈지 보기만
  python scripts/publish_threads.py --check           답글 권한 확인만
  python scripts/publish_threads.py --queue           대기 중인 스레드 전용 글 수
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish as P  # noqa: E402
from check import problems, threads_problems  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TLOG = ROOT / "threads_published.json"
TDIR = ROOT / "threads"
KST = ZoneInfo("Asia/Seoul")
# 슬롯별 발행 허용 시간 (깃허브 예약이 늦게 돌아도 이 안에서만 올림)
SLOTS = {"morning": (9, 12), "lunch": (13, 16), "night": (21, 24)}


def now() -> datetime.datetime:
    return datetime.datetime.now(KST)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_slot() -> str | None:
    h = now().hour
    for name, (a, b) in SLOTS.items():
        if a <= h < b:
            return name
    return None


def slot_done(slot: str) -> bool:
    today = now().strftime("%Y-%m-%d")
    return any(r.get("date") == today and r.get("slot") == slot for r in load(TLOG).values())


# ---------- 글 고르기 ----------
def next_card() -> str | None:
    """인스타에 올라갔지만 스레드엔 아직 안 올라간 카드뉴스 (오래된 것부터)"""
    log = load(P.LOG)
    stems = [s for s, r in log.items() if r.get("instagram") and not r.get("threads")
             and (ROOT / "out" / s / "1.jpg").exists()]
    return sorted(stems)[0] if stems else None


def next_threads_post() -> Path | None:
    tlog = load(TLOG)
    skipped = []
    for p in sorted(TDIR.glob("*.json")):
        if p.stem in tlog:
            continue
        probs = threads_problems(json.loads(p.read_text(encoding="utf-8")), ROOT)
        if probs:
            skipped.append(f"{p.stem}: " + " / ".join(probs))
            continue
        if skipped:
            P.SKIPPED.write_text("\n".join(skipped) + "\n", encoding="utf-8")
        return p
    if skipped:
        P.SKIPPED.write_text("\n".join(skipped) + "\n", encoding="utf-8")
    return None


# ---------- 글 만들기 ----------
def ad_line() -> str:
    return "[광고] " + P.DISCLOSURE


def link_reply(link: str, product: str) -> str:
    return f"{ad_line()}\n\n👉 {product or '글에 나온 제품'} 보러 가기\n{link}"


def card_text(post: dict) -> str:
    """카드뉴스 원고(이미 검수·최종 확인된 내용)로 스레드용 짧은 글 만들기"""
    parts = []
    if post.get("link"):
        parts.append(ad_line())
    parts.append(post.get("cover_title") or post["title"])
    parts.append("\n".join(f"✔ {s['head']}" for s in post["slides"]))
    q = next((l for l in post.get("caption", "").splitlines() if l.startswith("💬")), "")
    if q:
        parts.append(q)
    if post.get("hashtags"):
        parts.append("#" + post["hashtags"][0].lstrip("#"))
    return "\n\n".join(parts)


def own_text(post: dict) -> str:
    parts = [ad_line()] if post.get("link") else []
    parts.append(post["text"].strip())
    if post.get("topic"):
        parts.append("#" + post["topic"].lstrip("#"))
    return "\n\n".join(parts)


def raw_url(rel: str) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


# ---------- 스레드 API ----------
def can_reply(tok: str) -> bool:
    """답글 한도 조회는 threads_manage_replies 권한이 있어야 됨 → 권한 확인용 (읽기만, 아무것도 안 올림)"""
    try:
        P.call("GET", f"{P.TH_API}/me/threads_publishing_limit",
               params={"fields": "reply_quota_usage,reply_config", "access_token": tok})
        return True
    except Exception as e:
        print(f"답글 권한 확인 실패: {e}")
        return False


def publish_container(data: dict, tok: str) -> str:
    c = P.call("POST", f"{P.TH_API}/me/threads", data={**data, "access_token": tok})
    time.sleep(30)  # 공식 문서 권장: 만든 뒤 평균 30초 기다렸다 발행
    return P.call("POST", f"{P.TH_API}/me/threads_publish",
                  data={"creation_id": c["id"], "access_token": tok})["id"]


def post_images(urls: list[str], text: str, tok: str) -> str:
    if len(urls) == 1:
        return publish_container({"media_type": "IMAGE", "image_url": urls[0], "text": text}, tok)
    children = [P.call("POST", f"{P.TH_API}/me/threads", data={
        "media_type": "IMAGE", "image_url": u, "is_carousel_item": "true", "access_token": tok})["id"]
        for u in urls[:20]]  # 공식: 캐러셀 2~20장
    time.sleep(30)
    return publish_container({"media_type": "CAROUSEL", "children": ",".join(children), "text": text}, tok)


def post_reply(parent: str, text: str, tok: str) -> str:
    return publish_container({"media_type": "TEXT", "text": text, "reply_to_id": parent}, tok)


# ---------- 실행 ----------
def plan(slot: str):
    """(이름, 종류, 원고, 본문, 사진 주소들의 저장소 경로, 링크, 제품)"""
    if slot == "night":
        stem = next_card()
        if stem:
            post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
            n = len(post["slides"]) + 2
            imgs = [f"out/{stem}/{i}.jpg" for i in range(1, n + 1)]
            return stem, "card", post, card_text(post), imgs, post.get("link", ""), post.get("product", "")
    p = next_threads_post()
    if not p:
        return None
    post = json.loads(p.read_text(encoding="utf-8"))
    imgs = post.get("images") or ([post["image"]] if post.get("image") else [])
    return p.stem, "own", post, own_text(post), imgs, post.get("link", ""), post.get("product", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", default="auto", help="auto / morning / lunch / night")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--queue", action="store_true")
    a = ap.parse_args()

    if a.queue:
        tlog = load(TLOG)
        n = sum(1 for p in TDIR.glob("*.json") if p.stem not in tlog)
        print(n)
        return
    if a.check:
        ok = can_reply(os.environ["THREADS_TOKEN"])
        print("답글(첫 댓글 링크) 권한: " + ("있음" if ok else "없음 → 링크는 본문에 들어가요"))
        sys.exit(0 if ok else 1)

    slot = current_slot() if a.slot == "auto" else a.slot
    if not slot:
        print("지금은 스레드 발행 시간대(9~12시·13~16시·21~24시)가 아니에요. 건너뜁니다.")
        return
    if not a.dry_run and slot_done(slot):
        print(f"오늘 {slot} 슬롯은 이미 발행했어요. 건너뜁니다.")
        return

    pl = plan(slot)
    if not pl:
        print(f"::warning::스레드에 올릴 글이 없어요 ({slot}). threads 폴더에 새 글을 넣어 주세요.")
        sys.exit(1)
    name, kind, post, text, imgs, link, product = pl

    tok = os.environ.get("THREADS_TOKEN", "")
    reply_ok = bool(link) and (a.dry_run or can_reply(tok))
    if link and not reply_ok:
        # 답글 권한이 없으면 링크를 본문 끝에 (예전 방식) — 수수료 문구는 이미 첫 줄에 있음
        text += f"\n\n👉 {product or '글에 나온 제품'} 보러 가기\n{link}"
        (ROOT / "warnings.txt").write_text(
            "스레드 답글 권한(threads_manage_replies)이 없어 쿠팡 링크를 본문에 넣었어요.\n", encoding="utf-8")
    if len(text) > 500:
        print(f"::error::{name}: 스레드 글이 500자를 넘어요 ({len(text)}자)")
        sys.exit(1)

    if a.dry_run:
        print(f"[미리보기] 슬롯={slot} 글={name} ({kind}) 사진 {len(imgs)}장 / {len(text)}자")
        print(text)
        if link:
            print("---- 첫 댓글 ----\n" + link_reply(link, product))
        return

    if kind == "card":
        probs = problems(post)  # 카드는 이미 인스타에 나갔지만, 혹시 몰라 한 번 더
        if probs:
            print(f"::error::{name}: " + " / ".join(probs))
            sys.exit(1)

    urls = [raw_url(i) for i in imgs]
    P.wait_public(urls)
    if urls:
        pid = post_images(urls, text, tok)
    else:
        pid = publish_container({"media_type": "TEXT", "text": text}, tok)
    rec = {"id": pid, "date": now().strftime("%Y-%m-%d"), "slot": slot, "kind": kind}
    tlog = load(TLOG)
    tlog[name] = rec
    save(TLOG, tlog)
    if kind == "card":
        log = load(P.LOG)
        log.setdefault(name, {})["threads"] = pid
        P.save_log(log)
    print(f"스레드 발행 완료: {name} ({slot})")

    if link and reply_ok:
        try:
            rec["reply"] = post_reply(pid, link_reply(link, product), tok)
            save(TLOG, {**load(TLOG), name: rec})
            print("첫 댓글(링크) 완료")
        except Exception as e:
            print(f"::error::본문은 올렸지만 링크 댓글 실패: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
