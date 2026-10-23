"""카드뉴스 이미지 만들기 (1080x1350 JPEG)

원고 파일(content/*.json) 하나를 받아 out/<글번호>/1.jpg, 2.jpg ... 로 저장한다.
브랜드 색: 크림 #F6F1E7 / 먹색 #222222 / 머스타드 #E8A33D, 글꼴: 프리텐다드
"""
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
CREAM = "#F6F1E7"
INK = "#222222"
MUSTARD = "#E8A33D"
SOFT = "#6B655C"  # 보조 글씨(연한 먹색)
BRAND = "부산여자 살림코칭"
DISCLOSURE = "이 게시물은 쿠팡 파트너스 활동의 일환으로,\n이에 따른 일정액의 수수료를 제공받습니다."

COVER_TITLE_Y = 420       # 표지 제목 시작 높이
COVER_TITLE_Y_LINK = 480  # 쿠팡 링크 글은 위에 수수료 문구가 들어가서 조금 내림

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "fonts"

# 프리텐다드가 없으면(내 컴퓨터 테스트 등) 노토 산스로 대신 그린다
FALLBACK = {
    "Black": "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "Bold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "Medium": "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    p = FONT_DIR / f"Pretendard-{weight}.otf"
    if p.exists():
        return ImageFont.truetype(str(p), size)
    fb = FALLBACK.get(weight) or FALLBACK["Bold"]
    if not os.path.exists(fb):
        fb = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    for i in range(12):  # .ttc 안에서 한국어(KR) 글꼴 찾기
        try:
            f = ImageFont.truetype(fb, size, index=i)
        except OSError:
            break
        if "KR" in f.getname()[0]:
            return f
    return ImageFont.truetype(fb, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    """한국어 줄바꿈: 띄어쓰기 기준으로 끊고, 단어가 너무 길면 글자 단위로 끊는다."""
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=f) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in word:  # 긴 단어는 글자 단위로
                if draw.textlength(cur + ch, font=f) <= max_w:
                    cur += ch
                else:
                    lines.append(cur)
                    cur = ch
        lines.append(cur)
    return lines


def draw_lines(draw, lines, f, x, y, fill, gap):
    for ln in lines:
        draw.text((x, y), ln, font=f, fill=fill)
        y += f.size + gap
    return y


def footer(draw, page: int, total: int):
    f = font("Medium", 30)
    draw.text((90, H - 110), BRAND, font=f, fill=SOFT)
    num = f"{page} / {total}"
    draw.text((W - 90 - draw.textlength(num, font=f), H - 110), num, font=f, fill=SOFT)


def cover(post: dict, total: int) -> Image.Image:
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    # 머스타드 띠 + 작은 꼬리표
    d.rectangle((90, 150, 250, 162), fill=MUSTARD)
    tag = post.get("tag", "오늘의 살림")
    d.text((90, 190), tag, font=font("Bold", 44), fill=INK)
    # 쿠팡 링크 글: 공정위 지침대로 표지(첫 장) 위쪽에 수수료 문구를 잘 보이게
    if post.get("link"):
        fd = font("Bold", 30)
        d.rectangle((90, 268, 98, 352), fill=MUSTARD)
        draw_lines(d, DISCLOSURE.split("\n"), fd, 118, 270, INK, 12)
    # 큰 제목
    ft = font("Black", 108)
    lines = wrap(d, post["title"], ft, W - 180)
    y = COVER_TITLE_Y_LINK if post.get("link") else COVER_TITLE_Y
    y = draw_lines(d, lines, ft, 90, y, INK, 22)
    # 부제
    if post.get("subtitle"):
        fs = font("Medium", 46)
        y += 40
        draw_lines(d, wrap(d, post["subtitle"], fs, W - 180), fs, 90, y, SOFT, 16)
    # 넘겨보기 표시
    fa = font("Bold", 36)
    hint = "옆으로 넘겨보세요  →"
    d.text((W - 90 - d.textlength(hint, font=fa), H - 200), hint, font=fa, fill=MUSTARD)
    footer(d, 1, total)
    return im


def body(slide: dict, idx: int, page: int, total: int) -> Image.Image:
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    # 번호 동그라미
    d.ellipse((90, 150, 210, 270), fill=MUSTARD)
    fn = font("Black", 64)
    n = str(idx)
    d.text((150 - d.textlength(n, font=fn) / 2, 168), n, font=fn, fill=INK)
    # 소제목
    fh = font("Black", 72)
    y = draw_lines(d, wrap(d, slide["head"], fh, W - 180), fh, 90, 330, INK, 18)
    d.rectangle((90, y + 30, 170, y + 40), fill=MUSTARD)
    # 본문
    fb = font("Medium", 46)
    draw_lines(d, wrap(d, slide["body"], fb, W - 180), fb, 90, y + 90, INK, 26)
    footer(d, page, total)
    return im


def ending(post: dict, total: int) -> Image.Image:
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    fe = font("Black", 84)
    msg = post.get("ending", "저장해두고\n살림할 때 꺼내 보세요")
    y = draw_lines(d, wrap(d, msg, fe, W - 180), fe, 90, 380, CREAM, 22)
    d.rectangle((90, y + 40, 250, y + 52), fill=MUSTARD)
    fm = font("Bold", 44)
    d.text((90, y + 110), "매일 아침 살림 카드뉴스", font=fm, fill=MUSTARD)
    d.text((90, y + 175), "@daily_j83", font=font("Medium", 42), fill=CREAM)
    if post.get("link"):
        fd = font("Medium", 30)
        draw_lines(d, DISCLOSURE.split("\n"), fd, 90, H - 230, "#B8B1A6", 10)
    f = font("Medium", 30)
    num = f"{total} / {total}"
    d.text((W - 90 - d.textlength(num, font=f), H - 110), num, font=f, fill="#B8B1A6")
    d.text((90, H - 110), BRAND, font=f, fill="#B8B1A6")
    return im


def render(post_path: Path) -> list[Path]:
    post = json.loads(post_path.read_text(encoding="utf-8"))
    slides = post["slides"]
    total = len(slides) + 2
    if total > 10:
        raise ValueError("인스타 캐러셀은 최대 10장이에요. 본문 장수를 8장 이하로 줄여 주세요.")
    out_dir = ROOT / "out" / post_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    images = [cover(post, total)]
    images += [body(s, i + 1, i + 2, total) for i, s in enumerate(slides)]
    images.append(ending(post, total))
    paths = []
    for i, im in enumerate(images, 1):
        p = out_dir / f"{i}.jpg"
        im.save(p, "JPEG", quality=92)  # 인스타는 JPEG만 받는다
        paths.append(p)
    return paths


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        for p in render(Path(arg)):
            print(p)
