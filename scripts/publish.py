"""인스타·스레드에 카드뉴스 올리기

순서: 아직 안 올린 원고 1개 고르기 → (이미지는 워크플로가 미리 만들어 깃허브에 올려 둠)
      → 인스타 캐러셀 발행 → 스레드 캐러셀 발행 → published.json 에 기록

토큰은 깃허브 '비밀 보관함(Secrets)'에서 환경변수로만 받는다. 코드·파일에 절대 적지 않는다.
  IG_TOKEN       인스타 토큰
  THREADS_TOKEN  스레드 토큰
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from check import problems

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "published.json"
IG_API = "https://graph.instagram.com/v23.0"
TH_API = "https://graph.threads.net/v1.0"
DISCLOSURE = "이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


# ---------- 기록 ----------
def load_log() -> dict:
    if LOG.exists():
        return json.loads(LOG.read_text(encoding="utf-8"))
    return {}


def save_log(log: dict):
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


SKIPPED = ROOT / "skipped.txt"  # 검수에 걸려 건너뛴 원고 (워크플로가 보고 실패 메일을 보냄)


def next_post() -> Path | None:
    """content 폴더에서 파일 이름 순서대로, 두 곳 모두 올라가지 않았고 검수를 통과한 첫 원고.
    검수에 걸린 원고는 건너뛰고 skipped.txt 에 이유를 적는다."""
    log = load_log()
    skipped = []
    found = None
    for p in sorted((ROOT / "content").glob("*.json")):
        rec = log.get(p.stem, {})
        if rec.get("instagram") and rec.get("threads"):
            continue
        if rec.get("instagram") or rec.get("threads"):
            found = p  # 한쪽만 올라간 원고는 마저 올린다 (이미 검수 통과해서 발행된 것)
            break
        probs = problems(json.loads(p.read_text(encoding="utf-8")))
        if probs:
            skipped.append(f"{p.stem}: " + " / ".join(probs))
            continue
        found = p
        break
    if skipped:
        SKIPPED.write_text("\n".join(skipped) + "\n", encoding="utf-8")
        for s in skipped:
            print(f"::warning::검수에 걸려 건너뜀 — {s}", file=sys.stderr)
    return found


# ---------- 공통 ----------
def call(method, url, **kw):
    r = requests.request(method, url, timeout=60, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in data:
        # 토큰이 로그에 찍히지 않도록 오류 내용만 보여 준다
        raise RuntimeError(f"{r.status_code} {json.dumps(data.get('error', data), ensure_ascii=False)}")
    return data


def image_urls(stem: str, count: int) -> list[str]:
    repo = os.environ["GITHUB_REPOSITORY"]  # 예: 아이디/sallim-auto (깃허브가 자동으로 넣어 줌)
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return [f"https://raw.githubusercontent.com/{repo}/{branch}/out/{stem}/{i}.jpg" for i in range(1, count + 1)]


def wait_public(urls: list[str]):
    """방금 올린 이미지가 인터넷에서 열리는지 확인 (최대 3분)"""
    for u in urls:
        for _ in range(36):
            r = requests.head(u, timeout=20)
            if r.status_code == 200:
                break
            time.sleep(5)
        else:
            raise RuntimeError(f"이미지가 아직 공개되지 않았어요: {u}")


def build_text(post: dict, for_threads: bool) -> str:
    parts = []
    if post.get("link"):
        # 공정위 지침: 수수료 문구는 '더보기' 전에 보이는 첫 줄에
        parts.append("[광고] " + DISCLOSURE)
    parts.append(post["caption"].strip())
    if post.get("link"):
        # 스레드는 게시물 안 링크가 눌림 → 바로 넣기 / 인스타 캡션 링크는 안 눌림 → 스레드로 안내
        name = post.get("product") or "글에 나온 제품"
        if for_threads:
            parts.append(f"👉 {name} 보러 가기\n{post['link']}")
        else:
            parts.append(f"👉 {name} 링크는 스레드(@daily_j83) 같은 게시물에 있어요")
    hashtags = [t.lstrip("#") for t in post.get("hashtags", [])]
    if post.get("link"):
        hashtags = ["광고"] + [t for t in hashtags if t != "광고"]  # #광고는 맨 앞
    post = {**post, "hashtags": hashtags}
    tags = " ".join("#" + t for t in hashtags)
    if tags and not for_threads:
        parts.append(tags)  # 인스타는 해시태그 여러 개 가능
    if for_threads and post.get("hashtags"):
        parts.append("#" + post["hashtags"][0].lstrip("#"))  # 스레드는 주제 태그 1개만 쓰임
    text = "\n\n".join(parts)
    return text[:500] if for_threads else text[:2200]  # 글자 수 제한


def wait_ready(check_url: str, token: str, field: str = "status_code"):
    for _ in range(30):
        d = call("GET", check_url, params={"fields": field, "access_token": token})
        st = d.get(field) or d.get("status")
        if st in ("FINISHED", "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"미디어 처리 실패: {d}")
        time.sleep(5)
    raise RuntimeError("미디어 처리가 너무 오래 걸려요")


# ---------- 인스타 ----------
def post_instagram(urls: list[str], caption: str) -> str:
    tok = os.environ["IG_TOKEN"]
    me = call("GET", f"{IG_API}/me", params={"fields": "user_id,username", "access_token": tok})
    uid = me["user_id"]
    children = []
    for u in urls:
        c = call("POST", f"{IG_API}/{uid}/media",
                 data={"image_url": u, "is_carousel_item": "true", "access_token": tok})
        children.append(c["id"])
    for cid in children:
        wait_ready(f"{IG_API}/{cid}", tok)
    car = call("POST", f"{IG_API}/{uid}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children),
        "caption": caption, "access_token": tok})
    wait_ready(f"{IG_API}/{car['id']}", tok)
    pub = call("POST", f"{IG_API}/{uid}/media_publish",
               data={"creation_id": car["id"], "access_token": tok})
    return pub["id"]


# ---------- 스레드 ----------
def post_threads(urls: list[str], text: str) -> str:
    tok = os.environ["THREADS_TOKEN"]
    children = []
    for u in urls:
        c = call("POST", f"{TH_API}/me/threads", data={
            "media_type": "IMAGE", "image_url": u, "is_carousel_item": "true", "access_token": tok})
        children.append(c["id"])
    time.sleep(30)  # 스레드 공식 문서 권장: 만든 뒤 잠깐 기다렸다 올리기
    car = call("POST", f"{TH_API}/me/threads", data={
        "media_type": "CAROUSEL", "children": ",".join(children), "text": text, "access_token": tok})
    time.sleep(30)
    pub = call("POST", f"{TH_API}/me/threads_publish",
               data={"creation_id": car["id"], "access_token": tok})
    return pub["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="실제로 올리지 않고 무엇을 올릴지만 보여 주기")
    ap.add_argument("--pick", action="store_true", help="다음에 올릴 원고 이름만 출력")
    args = ap.parse_args()

    p = next_post()
    if args.pick:
        print(p.stem if p else "")
        return
    if not p:
        print("올릴 원고가 없어요. content 폴더에 새 원고를 넣어 주세요.")
        sys.exit(0)

    post = json.loads(p.read_text(encoding="utf-8"))
    count = len(post["slides"]) + 2
    ig_text = build_text(post, for_threads=False)
    th_text = build_text(post, for_threads=True)

    if args.dry_run:
        print(f"[미리보기] {p.stem} / 카드 {count}장")
        print("---- 인스타 글 ----\n" + ig_text)
        print("---- 스레드 글 ----\n" + th_text)
        return

    from check import warnings
    warns = warnings(post, p.stem, load_log())
    if warns:
        (ROOT / "warnings.txt").write_text(f"{p.stem}\n" + "\n".join(warns) + "\n", encoding="utf-8")

    urls = image_urls(p.stem, count)
    wait_public(urls)

    log = load_log()
    rec = log.setdefault(p.stem, {})
    errors = []
    if not rec.get("instagram"):
        try:
            rec["instagram"] = post_instagram(urls, ig_text)
            print("인스타 발행 완료")
        except Exception as e:  # 한쪽이 실패해도 다른 쪽은 올린다
            errors.append(f"인스타 실패: {e}")
    if not rec.get("threads"):
        try:
            rec["threads"] = post_threads(urls, th_text)
            print("스레드 발행 완료")
        except Exception as e:
            errors.append(f"스레드 실패: {e}")
    rec["date"] = time.strftime("%Y-%m-%d")
    save_log(log)
    if errors:
        print("\n".join(errors))
        sys.exit(1)  # 깃허브가 실패 알림 메일을 보내도록


if __name__ == "__main__":
    main()
