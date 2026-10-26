"""저녁 릴스 발행 (월·수·금·일)

순서: 이미 카드뉴스로 나간 원고 중 고르기 → 사진·음악 준비 → 영상 만들기(reel.py)
      → docs/reels/ 에 올려 공개 주소 만들기(깃허브 페이지) → 인스타 릴스 → 스레드 영상 → reels.json 기록

고르는 기준: 카드뉴스로 나간 지 3일 이상 + 아직 릴스로 안 만든 원고 중
            저장+공유 점수(stats/posts.json)가 높은 것, 같으면 오래된 것
안전: 검수·최종 확인 도장이 그대로인 원고만 (check.problems)

토큰은 깃허브 비밀 보관함에서만: IG_TOKEN, THREADS_TOKEN, (사진) PIXABAY_KEY
사용:
  python scripts/publish_reel.py --pick            오늘 만들 원고 이름 (없으면 빈 줄)
  python scripts/publish_reel.py --made-today      오늘 이미 릴스를 올렸으면 0
  python scripts/publish_reel.py --render 원고이름 [--preview]   영상 만들기 (docs/reels 또는 docs/preview)
  python scripts/publish_reel.py --publish 원고이름  인스타·스레드에 올리기
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
from check import problems  # noqa: E402
import media  # noqa: E402
import publish as P  # noqa: E402  (인스타·스레드 공통 함수)

ROOT = Path(__file__).resolve().parent.parent
REELS_LOG = ROOT / "reels.json"


def today() -> str:
    return datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def load() -> dict:
    return json.loads(REELS_LOG.read_text(encoding="utf-8")) if REELS_LOG.exists() else {"posts": {}, "music": {}}


def save(d: dict):
    REELS_LOG.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def made_today() -> bool:
    return any(r.get("date") == today() and (r.get("instagram") or r.get("threads")) for r in load()["posts"].values())


def score(stem: str) -> float:
    f = ROOT / "stats" / "posts.json"
    if not f.exists():
        return 0.0
    p = json.loads(f.read_text(encoding="utf-8")).get(stem, {})
    ig = p.get("instagram", {})
    reach = ig.get("reach") or 0
    good = (ig.get("saved") or 0) + (ig.get("shares") or 0)
    th = p.get("threads", {})
    # 인스타 점수 + 스레드 반응(조회 대비 좋아요·공유)을 조금 섞는다
    s = good / reach if reach else 0
    tv = th.get("views") or 0
    s += 0.3 * (((th.get("likes") or 0) + (th.get("shares") or 0) + (th.get("reposts") or 0)) / tv if tv else 0)
    return s


def pick() -> str:
    log = P.load_log()
    done = load()["posts"]
    cut = (datetime.datetime.now(ZoneInfo("Asia/Seoul")) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    cands = []
    for stem, rec in log.items():
        if not (rec.get("instagram") and rec.get("date", "9999") <= cut):
            continue
        if done.get(stem, {}).get("instagram"):
            continue
        f = ROOT / "content" / f"{stem}.json"
        if not f.exists() or problems(json.loads(f.read_text(encoding="utf-8"))):
            continue
        cands.append((-score(stem), rec["date"], stem))
    return sorted(cands)[0][2] if cands else ""


def render(stem: str, preview: bool = False) -> Path:
    import reel
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    pics = media.photos(post, stem, len(post["slides"]) + 1)
    d = load()
    track = media.pick_track(d.get("music", {}))
    out = ROOT / "docs" / ("preview" if preview else "reels") / f"{stem}.mp4"
    tpath = ROOT / "music" / track["file"] if track else None
    reel.render(ROOT / "content" / f"{stem}.json", out, fps=60, photos=pics,
                track=tpath, track_start=float(track.get("start", 0)) if track else 0.0)
    rec = d["posts"].setdefault(stem, {})
    rec.update({"music": track["file"] if track else "직접 만든 배경음",
                "photos": f"{media.photo_source()} {len(pics)}장"})
    if track and not preview:
        d["music"][track["file"]] = today()
    if not preview:
        save(d)
    print(f"영상 완성: {out} / 사진 {len(pics)}장 / 음악 {rec['music']}")
    return out


def video_url(stem: str) -> str:
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
    return f"https://{owner}.github.io/{repo}/reels/{stem}.mp4"


def wait_public(url: str):
    for _ in range(60):  # 깃허브 페이지에 반영될 때까지 최대 10분
        r = requests.head(url, timeout=20, allow_redirects=True)
        if r.status_code == 200 and "video" in r.headers.get("content-type", ""):
            return
        time.sleep(10)
    raise RuntimeError(f"영상 주소가 아직 열리지 않아요: {url}")


def caption(post: dict, threads: bool) -> str:
    base = P.build_text({**post, "caption": post["caption"].strip() + "\n\n카드뉴스 전체는 프로필에서 저장해 두세요 🧺"}, threads)
    src = media.photo_source()
    credit = f"\n\n사진: {src}" if src else ""
    limit = 500 if threads else 2200
    return (base + credit)[:limit]


def post_ig_reel(url: str, text: str) -> str:
    tok = os.environ["IG_TOKEN"]
    me = P.call("GET", f"{P.IG_API}/me", params={"fields": "user_id", "access_token": tok})
    c = P.call("POST", f"{P.IG_API}/{me['user_id']}/media", data={
        "media_type": "REELS", "video_url": url, "caption": text, "share_to_feed": "true", "access_token": tok})
    for _ in range(60):  # 영상 처리 최대 10분
        st = P.call("GET", f"{P.IG_API}/{c['id']}", params={"fields": "status_code,status", "access_token": tok})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"인스타 영상 처리 실패: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("인스타 영상 처리가 너무 오래 걸려요")
    return P.call("POST", f"{P.IG_API}/{me['user_id']}/media_publish",
                  data={"creation_id": c["id"], "access_token": tok})["id"]


def post_threads_video(url: str, text: str) -> str:
    tok = os.environ["THREADS_TOKEN"]
    c = P.call("POST", f"{P.TH_API}/me/threads", data={
        "media_type": "VIDEO", "video_url": url, "text": text, "access_token": tok})
    for _ in range(60):
        st = P.call("GET", f"{P.TH_API}/{c['id']}", params={"fields": "status,error_message", "access_token": tok})
        if st.get("status") == "FINISHED":
            break
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"스레드 영상 처리 실패: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("스레드 영상 처리가 너무 오래 걸려요")
    return P.call("POST", f"{P.TH_API}/me/threads_publish",
                  data={"creation_id": c["id"], "access_token": tok})["id"]


def publish(stem: str):
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    probs = problems(post)
    if probs:
        sys.exit(f"검수에 걸려 릴스를 올리지 않아요: {probs}")
    url = video_url(stem)
    wait_public(url)
    d = load()
    rec = d["posts"].setdefault(stem, {})
    errors = []
    if not rec.get("instagram"):
        try:
            rec["instagram"] = post_ig_reel(url, caption(post, False))
            print("인스타 릴스 발행 완료")
        except Exception as e:
            errors.append(f"인스타 릴스 실패: {e}")
    if not rec.get("threads"):
        try:
            rec["threads"] = post_threads_video(url, caption(post, True))
            print("스레드 영상 발행 완료")
        except Exception as e:
            errors.append(f"스레드 영상 실패: {e}")
    rec["date"] = today()
    save(d)
    if errors:
        print("\n".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", action="store_true")
    ap.add_argument("--made-today", action="store_true")
    ap.add_argument("--render")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--publish")
    a = ap.parse_args()
    if a.made_today:
        sys.exit(0 if made_today() else 1)
    if a.pick:
        print(pick())
    elif a.render:
        render(a.render, a.preview)
    elif a.publish:
        publish(a.publish)
