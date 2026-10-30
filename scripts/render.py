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


def fill(photo: Image.Image, w: int, h: int) -> Image.Image:
    """사진을 w x h 칸에 꽉 차게 (가운데 기준으로 잘라 냄)"""
    photo = photo.convert("RGB")
    s = max(w / photo.width, h / photo.height)
    p = photo.resize((max(w, round(photo.width * s)), max(h, round(photo.height * s))), Image.LANCZOS)
    x, y = (p.width - w) // 2, (p.height - h) // 2
    return p.crop((x, y, x + w, y + h))


def pill(d, x, y, text, f, bg, fg):
    tw = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + tw + 48, y + f.size + 30), radius=(f.size + 30) // 2, fill=bg)
    d.text((x + 24, y + 13), text, font=f, fill=fg)


def fit_title(d, text, max_w, max_lines, sizes=(112, 104, 96, 88, 80)):
    """제목이 정해진 줄 수 안에 들어가는 가장 큰 글씨"""
    for s in sizes:
        ft = font("Black", s)
        lines = wrap(d, text, ft, max_w)
        if len(lines) <= max_lines:
            return ft, lines
    return ft, lines


def cover_photo(post: dict, total: int, photo: Image.Image, style: str = "full") -> Image.Image:
    """사진 표지 — 피드에서 손가락을 멈추게 하는 첫 장 (글자만 있는 표지보다 눈에 띔)
    full: 사진이 화면 전체, 아래쪽을 어둡게 깔고 흰 큰 제목
    top : 위 60% 사진, 아래 크림 바탕에 먹색 큰 제목 (브랜드 색 유지)"""
    link = bool(post.get("link"))
    title = post.get("cover_title") or post["title"]
    tag = post.get("tag", "오늘의 살림")
    if style == "top":
        im = Image.new("RGB", (W, H), CREAM)
        d = ImageDraw.Draw(im)
        top = 0
        if link:  # 수수료 문구는 표지 맨 위
            top = 130
            draw_lines(d, DISCLOSURE.split("\n"), font("Bold", 28), 60, 30, INK, 10)
        ph = 720 - (130 if link else 0)
        im.paste(fill(photo, W, ph), (0, top))
        y = top + ph
        pill(d, 90, y - 40, tag, font("Bold", 40), MUSTARD, INK)
        fs = font("Medium", 42)
        sub = wrap(d, post["subtitle"], fs, W - 180)[:1] if post.get("subtitle") else []
        room = H - 150 - (y + 70) - (len(sub) * (fs.size + 32))
        for s in (100, 92, 84, 76, 70):  # 아래 쪽번호와 안 겹치는 가장 큰 제목
            ft = font("Black", s)
            lines = wrap(d, title, ft, W - 180)
            if len(lines) * (s + 16) <= room:
                break
        y = draw_lines(d, lines, ft, 90, y + 70, INK, 16)
        if sub:
            draw_lines(d, sub, fs, 90, y + 16, SOFT, 12)
        footer(d, 1, total)
        return im
    # full
    im = fill(photo, W, H)
    shade = Image.new("L", (1, H))
    for yy in range(H):  # 위쪽 살짝 + 아래쪽 진하게 어둡게
        t = max(0.0, (yy - H * 0.28) / (H * 0.42))  # 제목 자리(아래 절반)는 밝은 사진도 충분히 어둡게
        top_t = max(0.0, (300 - yy) / 300) * 0.6
        shade.putpixel((0, yy), int(255 * min(0.86, t * 0.86 + top_t)))
    im = Image.composite(Image.new("RGB", (W, H), "#141210"), im, shade.resize((W, H)))
    d = ImageDraw.Draw(im)
    if link:
        fd = font("Bold", 28)
        d.rounded_rectangle((60, 50, W - 60, 160), radius=18, fill="#222222")
        draw_lines(d, DISCLOSURE.split("\n"), fd, 90, 66, CREAM, 10)
    pill(d, 90, 190 if link else 90, tag, font("Bold", 40), MUSTARD, INK)
    ft, lines = fit_title(d, title, W - 180, 4)
    fs = font("Medium", 44)
    sub = wrap(d, post["subtitle"], fs, W - 180)[:1] if post.get("subtitle") else []
    block = len(lines) * (ft.size + 18) + (len(sub) * (fs.size + 12) + 30 if sub else 0)
    y = H - 210 - block
    # 글자 뒤 은은한 그림자 (밝은 사진에서도 흰 제목이 또렷하게)
    from PIL import ImageFilter
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    draw_lines(gd, lines, ft, 90, y, 255, 18)
    if sub:
        draw_lines(gd, sub, fs, 90, y + len(lines) * (ft.size + 18) + 40, 255, 12)
    glow = glow.filter(ImageFilter.GaussianBlur(14)).point(lambda v: min(255, v * 2))
    im.paste(Image.new("RGB", (W, H), "#0E0C0A"), (0, 0), glow.point(lambda v: v * 0.75))
    d = ImageDraw.Draw(im)
    y = draw_lines(d, lines, ft, 90, y, "#FFFFFF", 18)
    if sub:
        d.rectangle((90, y + 6, 170, y + 16), fill=MUSTARD)
        draw_lines(d, sub, fs, 90, y + 40, "#EDE6D8", 12)
    f = font("Medium", 30)
    d.text((90, H - 110), BRAND, font=f, fill="#D9D2C4")
    hint = "넘겨보기 →"
    d.text((W - 90 - d.textlength(hint, font=f), H - 110), hint, font=font("Bold", 30), fill=MUSTARD)
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
    d.text((90, y + 110), "매일 저녁 살림 카드뉴스", font=fm, fill=MUSTARD)
    d.text((90, y + 175), "@daily_j83", font=font("Medium", 42), fill=CREAM)
    if post.get("link"):
        fd = font("Medium", 30)
        draw_lines(d, DISCLOSURE.split("\n"), fd, 90, H - 230, "#B8B1A6", 10)
    f = font("Medium", 30)
    num = f"{total} / {total}"
    d.text((W - 90 - d.textlength(num, font=f), H - 110), num, font=f, fill="#B8B1A6")
    d.text((90, H - 110), BRAND, font=f, fill="#B8B1A6")
    return im


COVER_STYLE = "full"  # 표지 사진 배치: full(사진 꽉 채움) / top(위 사진 + 아래 크림)
COVER_CACHE = ROOT / ".cache" / "covers"  # 원본 사진은 공개 저장소에 올리지 않는다 (.gitignore)


def cover_source(post: dict, stem: str):
    """원고의 cover_photo(픽사베이 사진 번호, 클로드가 확인표에서 고름) → 사진.
    없거나 못 받으면 None → 글자 표지로 대신 만든다."""
    pid = post.get("cover_photo")
    if not pid:
        return None
    f = COVER_CACHE / f"{stem}_{pid}.jpg"
    if not f.exists():
        if not os.environ.get("PIXABAY_KEY", "").strip():
            print(f"표지 사진 {pid}: 사진 열쇠(PIXABAY_KEY)가 없어 글자 표지로 만들어요")
            return None
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import media
            import requests
            u = media.pixabay_by_id(pid)
            if not u:
                raise RuntimeError("사진이 사라짐")
            r = requests.get(u, headers=media.UA, timeout=60)
            r.raise_for_status()
            COVER_CACHE.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.content)
        except Exception as e:  # 열쇠 값은 찍지 않음
            print(f"표지 사진 {pid} 받기 실패({type(e).__name__}) → 글자 표지로 만들어요")
            return None
    return Image.open(f)


def render(post_path: Path) -> list[Path]:
    post = json.loads(post_path.read_text(encoding="utf-8"))
    slides = post["slides"]
    total = len(slides) + 2
    if total > 10:
        raise ValueError("인스타 캐러셀은 최대 10장이에요. 본문 장수를 8장 이하로 줄여 주세요.")
    out_dir = ROOT / "out" / post_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    ph = cover_source(post, post_path.stem)
    images = [cover_photo(post, total, ph, COVER_STYLE) if ph else cover(post, total)]
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
