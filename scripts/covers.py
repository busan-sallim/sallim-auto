"""카드뉴스 표지 사진 고르기 (고정 규칙: 사진은 글 내용과 맞아야 하고, 클로드가 눈으로 보고 고른다)

흐름
  1) 클로드가 cover_prepare.txt 첫 줄에 `candidates 009_sink_drain 010_cutting_board …` 를 적어 올림
     → 깃허브가 원고마다 후보 사진 8장 확인표 review/covers/<원고>_cands.jpg(+ .json) 를 만듦
  2) 클로드가 확인표를 열어 보고 글에 맞는 후보를 골라 원고에 "cover_photo": <사진 번호> 를 적음
     (상표·로고가 크게 보이는 사진, 사람 얼굴이 보이는 사진은 고르지 않음. 맞는 게 없으면 안 적음 → 글자 표지)
  3) 클로드가 `preview 009_sink_drain …` 를 적어 올림 → 깃허브가 실제 표지 review/covers/<원고>_cover.jpg 를 만듦
  4) 클로드가 표지를 열어 보고 → check.py --stamp / --final (cover_photo 는 도장에 묶임: 사진을 바꾸면 다시 확인)
원본 사진은 공개 저장소에 올리지 않는다 (확인표 작은 사진·완성된 표지만 올림)
검색어: 원고의 "cover_query"(영어) → 없으면 "photo" → 없으면 "photos" 첫 번째
"""
import io
import json
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media  # noqa: E402
import render as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "review" / "covers"


def query(post: dict) -> str:
    return post.get("cover_query") or post.get("photo") or (post.get("photos") or [""])[0]


def candidates(stem: str) -> Path:
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    q = query(post)
    cs = media.pixabay_candidates(q, 8, hook=True) if q else []
    tw, th = 300, 375  # 표지 비율(4:5)로 잘라서 보여 줌
    head = 90
    canvas = Image.new("RGB", (4 * tw, head + 2 * th), "white")
    d = ImageDraw.Draw(canvas)
    d.text((10, 8), f"{stem}  {post['title']}", font=R.font("Bold", 26), fill=(20, 20, 20))
    d.text((10, 48), f"검색: {q or '없음'}", font=R.font("Medium", 22), fill=(90, 90, 90))
    for k, c in enumerate(cs):
        try:
            im = Image.open(io.BytesIO(requests.get(c["thumb"], timeout=60).content))
            x, y = (k % 4) * tw, head + (k // 4) * th
            canvas.paste(R.fill(im, tw - 6, th - 6), (x + 3, y + 3))
            d.rectangle((x + 3, y + 3, x + 50, y + 48), fill=(232, 163, 61))
            d.text((x + 15, y + 2), str(k), font=R.font("Black", 34), fill=(20, 20, 20))
        except Exception as e:
            print("후보 받기 실패:", type(e).__name__)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}_cands.json").write_text(
        json.dumps([{"id": c["id"], "tags": c["tags"]} for c in cs], ensure_ascii=False, indent=1), encoding="utf-8")
    out = OUT / f"{stem}_cands.jpg"
    canvas.save(out, quality=85)
    print(out, f"후보 {len(cs)}장")
    return out


def preview(stem: str) -> Path | None:
    post = json.loads((ROOT / "content" / f"{stem}.json").read_text(encoding="utf-8"))
    ph = R.cover_source(post, stem)
    if not ph:
        print(stem, "표지 사진 없음 → 글자 표지")
        return None
    total = len(post["slides"]) + 2
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{stem}_cover.jpg"
    R.cover_photo(post, total, ph, R.COVER_STYLE).save(out, quality=90)
    print(out)
    return out


if __name__ == "__main__":
    mode, *stems = sys.argv[1:]
    for s in stems:
        try:
            (candidates if mode == "candidates" else preview)(s)
        except Exception as e:
            print(s, "실패:", type(e).__name__, e)
