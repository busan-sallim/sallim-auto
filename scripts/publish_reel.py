"""릴스 (월·수·금·일 저녁)

고정 규칙
  - 영상의 사진은 그 장의 글 내용과 맞아야 한다 → 발행 전날 밤 클로드가 영상을 직접 보고 승인한 것만 발행
  - 음악은 music/tracks.json 의 use=true 곡(1번·2번)을 번갈아 쓴다

흐름
  1) 준비(--prepare): 발행 전날 밤 클로드가 reel_prepare.txt 에 원고 이름을 적어 올리면,
     깃허브가 사진(픽사베이)·음악을 넣어 docs/reels/<원고>.mp4 를 만든다 (아직 발행 안 함)
  2) 확인(--sheet → 눈으로 확인 → --approve): 클로드가 장면별 사진+글을 한 장으로 모은 그림을 열어 보고,
     사진과 글이 맞으면 승인 도장. 영상 파일 지문(sha)과 묶여서, 다시 만들면 다시 승인해야 한다
  3) 발행(--publish): 저녁 예약 실행이 승인된 영상만 인스타 릴스·스레드에 올린다 (하루 한 번)

고르는 기준(--pick): 카드뉴스로 나간 지 3일 이상 + 아직 릴스로 안 만든 원고 중 저장·공유 점수 높은 것
토큰은 깃허브 비밀 보관함에서만: IG_TOKEN, THREADS_TOKEN, PIXABAY_KEY
"""
import argparse
import datetime
import hashlib
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
    d = json.loads(REELS_LOG.read_text(encoding="utf-8")) if REELS_LOG.exists() else {}
    for k in ("posts", "music", "prepared", "approved"):
        d.setdefault(k, {})
    return d


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
        if done.get(stem, {}).get("instagram") or stem in load()["approved"]:
            continue
        f = ROOT / "content" / f"{stem}.json"
        if not f.exists() or problems(json.loads(f.read_text(encoding="utf-8"))):
            continue
        cands.append((-score(stem), rec["date"], stem))
    return sorted(cands)[0][2] if cands else ""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def render(stem: str, preview: bool = False) -> Path:
    import reel
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    n = len(post["slides"]) + 1
    pics = media.photos(post, stem, n)
    d = load()
    track = media.pick_track(d["music"].get("last"))
    want = os.environ.get("REEL_TRACK", "").strip()  # 미리보기에서 곡 번호를 고를 때
    if want:
        for t in json.loads((ROOT / "music" / "tracks.json").read_text(encoding="utf-8")):
            if str(t.get("no")) == want and (ROOT / "music" / t["file"]).exists():
                track = t
    out = ROOT / "docs" / ("preview" if preview else "reels") / f"{stem}.mp4"
    tpath = ROOT / "music" / track["file"] if track else None
    reel.render(ROOT / "content" / f"{stem}.json", out, fps=60, photos=pics,
                track=tpath, track_start=float(track.get("start", 0)) if track else 0.0)
    info = {"date": today(), "sha": sha(out), "music": track["file"] if track else "직접 만든 배경음",
            "photos": [str(x.relative_to(ROOT)) for x in pics], "queries": post.get("photos", [])}
    if not preview:
        d["prepared"][stem] = info
        d["approved"].pop(stem, None)  # 다시 만들었으면 다시 승인 받아야 함
        save(d)
    print(f"영상 완성: {out} / 사진 {len(pics)}장 / 음악 {info['music']}")
    return out


def sheet(stem: str, out: Path | None = None) -> Path:
    """장면마다 화면 한 컷 + 그 장의 글을 한 장으로 모은 확인용 그림 (클로드가 눈으로 확인)"""
    import subprocess
    import reel
    from PIL import Image, ImageDraw
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    video = ROOT / "docs" / "reels" / f"{stem}.mp4"
    beat = reel.BEAT
    times = [reel.HOOK_BEATS * beat * 0.8]
    for k in range(len(post["slides"])):
        times.append(reel.HOOK_BEATS * beat + k * reel.SLIDE_BEATS * beat + reel.SLIDE_BEATS * beat * 0.7)
    labels = ["[훅] " + post["title"]] + [f"[{k + 1}] {s['head']} — {s['body']}" for k, s in enumerate(post["slides"])]
    tw, th = 360, 640
    cols = 3
    rows = (len(times) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tw, rows * (th + 120)), "white")
    d = ImageDraw.Draw(canvas)
    f = reel.card_font("Medium", 18)
    tmp = ROOT / "out" / stem
    tmp.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(times):
        png = tmp / f"sheet_{i}.png"
        subprocess.run([reel.FFMPEG, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={tw}:{th}", str(png)], check=True)
        x, y = (i % cols) * tw, (i // cols) * (th + 120)
        canvas.paste(Image.open(png), (x, y))
        lines = reel.wrap(d, labels[i], f, tw - 12)[:4]
        for j, ln in enumerate(lines):
            d.text((x + 6, y + th + 6 + j * 26), ln, font=f, fill=(20, 20, 20))
    out = out or (tmp / "reel_sheet.jpg")
    canvas.save(out, quality=88)
    print(out)
    return out


def approve(stem: str, memo: str):
    d = load()
    video = ROOT / "docs" / "reels" / f"{stem}.mp4"
    prep = d["prepared"].get(stem)
    if not prep or not video.exists() or prep["sha"] != sha(video):
        sys.exit("준비된 영상이 없거나 바뀌었어요. 다시 준비(--prepare)부터 해 주세요.")
    d["approved"][stem] = {"date": today(), "sha": prep["sha"], "by": "claude", "memo": memo}
    save(d)
    print("릴스 승인 도장 완료:", stem)


def next_approved() -> str:
    d = load()
    ready = [(v["date"], k) for k, v in d["approved"].items() if not d["posts"].get(k, {}).get("instagram")]
    return sorted(ready)[0][1] if ready else ""


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
    d = load()
    video = ROOT / "docs" / "reels" / f"{stem}.mp4"
    ok = d["approved"].get(stem)
    if not ok or not video.exists() or ok["sha"] != sha(video):
        sys.exit(f"클로드 승인(사진·글 일치 확인)이 없는 영상이라 올리지 않아요: {stem}")
    url = video_url(stem)
    wait_public(url)
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
    rec["music"] = d["prepared"].get(stem, {}).get("music")
    if rec.get("instagram") or rec.get("threads"):
        d["music"]["last"] = rec["music"]
    save(d)
    if errors:
        print("\n".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", action="store_true", help="다음에 준비할 원고")
    ap.add_argument("--next-approved", action="store_true", help="발행할 (승인된) 원고")
    ap.add_argument("--made-today", action="store_true")
    ap.add_argument("--prepare", help="영상 만들기 (docs/reels)")
    ap.add_argument("--render", help="미리보기 영상 만들기 (--preview 와 함께)")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--sheet", help="확인용 장면 모음 그림 만들기")
    ap.add_argument("--approve", nargs=2, metavar=("원고", "메모"))
    ap.add_argument("--publish")
    a = ap.parse_args()
    if a.made_today:
        sys.exit(0 if made_today() else 1)
    if a.pick:
        print(pick())
    elif a.next_approved:
        print(next_approved())
    elif a.prepare:
        render(a.prepare, preview=False)
    elif a.render:
        render(a.render, preview=a.preview)
    elif a.sheet:
        sheet(a.sheet)
    elif a.approve:
        approve(*a.approve)
    elif a.publish:
        publish(a.publish)
