"""원고(content/*.json) → 릴스 영상 (1080x1920, 60fps, MP4)

연출: 100BPM 박자에 맞춘 키네틱 타이포
  훅(5박)   첫 프레임부터 전체 화면 사진이 움직이고(빠르게 줌아웃) 큰 한 줄 문구("hook")가 바로 보임
            → 0.7초부터 제목이 아래에 작게 등장. 훅 사진이 없으면 1장 사진을 끌어다 쓴다
  본문(장당 6박) 번호 동그라미에서 원이 퍼지며 전환, 크림/먹색 배경 교대, 소제목·밑줄·본문 줄 순서 등장, 천천히 줌
  마무리(5박) "저장해두고 꺼내 보세요" + 책갈피 아이콘
음악: scripts/reel.py 가 직접 합성 (외부 음원 없음 → 저작권 걱정 없음)
쿠팡 링크 글: 처음 3.6초 동안 화면 위쪽에 "유료 광고 포함" 표시 (공정위 지침: 시작 부분 3초 이상)

사용: python scripts/reel.py content/004_window_condensation.json [--fps 60] [--out 파일.mp4]
"""
import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _ffmpeg() -> str:
    """컴퓨터에 ffmpeg 가 있으면 그것, 없으면 pip 로 받은 imageio-ffmpeg 안의 것을 쓴다"""
    import shutil
    f = shutil.which("ffmpeg")
    if f:
        return f
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = _ffmpeg()
from render import font as card_font, wrap  # noqa: E402  (카드와 같은 글꼴·줄바꿈)

ROOT = Path(__file__).resolve().parent.parent
W, H = 1080, 1920
CREAM, INK, MUSTARD, SOFT = (246, 241, 231), (34, 34, 34), (232, 163, 61), (107, 101, 92)
LEFT, RIGHT_SAFE = 90, 150          # 오른쪽은 인스타 버튼 자리라 넓게 비운다
TEXT_W = W - LEFT - RIGHT_SAFE
BPM = 100
BEAT = 60 / BPM                     # 0.6초
HOOK_BEATS, SLIDE_BEATS, END_BEATS = 5, 6, 5   # 3.0초 / 장당 3.6초 / 3.0초


# ---------- 이징(속도 변화) ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t, s=1.7):
    t = clamp(t)
    return 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2


def progress(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


# ---------- 글자 레이어 ----------
def text_layer(text, fnt, color):
    box = fnt.getbbox(text)
    w, h = box[2] - box[0] + 4, fnt.size + int(fnt.size * 0.35)
    im = Image.new("RGBA", (max(w, 1), h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-box[0] + 2, 0), text, font=fnt, fill=color)
    return im


def outlined(text, fnt, color):
    """사진 위 글씨: 어두운 테두리로 어떤 사진에서도 잘 읽히게"""
    box = fnt.getbbox(text, stroke_width=6)
    w, h = box[2] - box[0] + 8, fnt.size + int(fnt.size * 0.45)
    im = Image.new("RGBA", (max(w, 1), h), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-box[0] + 4, 4), text, font=fnt, fill=color, stroke_width=6, stroke_fill=(20, 20, 20, 200))
    return im


def paste(frame, layer, x, y, alpha=1.0, scale=1.0):
    if alpha <= 0.01:
        return
    lay = layer
    if abs(scale - 1) > 0.005:
        nw, nh = max(1, int(lay.width * scale)), max(1, int(lay.height * scale))
        lay = lay.resize((nw, nh), Image.BICUBIC)
        x += (layer.width - nw) / 2
        y += (layer.height - nh) / 2
    if alpha < 0.999:
        a = lay.getchannel("A").point(lambda v: int(v * alpha))
        lay = lay.copy()
        lay.putalpha(a)
    frame.alpha_composite(lay, (int(round(x)), int(round(y))))


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """사진을 w×h 를 꽉 채우게 자르기 (가운데 기준)"""
    img = img.convert("RGB")
    s = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x0, y0 = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x0, y0, x0 + w, y0 + h))


def kenburns(img: Image.Image, w: int, h: int, p: float, zoom=0.10, pan=(0.0, -0.03)) -> Image.Image:
    """사진이 천천히 다가오는 효과 (img 는 w,h 보다 zoom 만큼 크게 준비돼 있음)"""
    z = 1 + zoom * ease_in_out_cubic(p)
    cw, ch = img.width / z, img.height / z
    cx = img.width / 2 + pan[0] * img.width * p
    cy = img.height / 2 + pan[1] * img.height * p
    x0 = min(max(0.0, cx - cw / 2), img.width - cw)
    y0 = min(max(0.0, cy - ch / 2), img.height - ch)
    return img.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


def round_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


CARD = (80, 250, W - 80, 820)   # 본문 장의 사진 카드 자리
HOOK_SHADE = None


def hook_shade():
    """훅 사진 위 어둡게 깔리는 그라데이션 (글씨가 잘 보이게)"""
    global HOOK_SHADE
    if HOOK_SHADE is None:
        a = np.zeros((H, W), dtype=np.uint8)
        ys = np.arange(H)
        prof = np.clip((ys - 300) / 1400, 0, 1) * 90 + 60   # 위 60 → 아래 150 (사진이 잘 보이게 옅게)
        a[:] = prof[:, None].astype(np.uint8)
        HOOK_SHADE = Image.merge("RGBA", [Image.new("L", (W, H), 22)] * 3 + [Image.fromarray(a)])
    return HOOK_SHADE


class Scene:
    def __init__(self, start, dur):
        self.start, self.dur = start, dur

    def local(self, t):
        return t - self.start


# ---------- 장면 준비 ----------
def build(post: dict, photos=None):
    # 장면별 사진 목록 [훅, 1장, 2장, …]. 맞는 사진이 없는 장면은 None → 그 장면만 사진 없이
    photos = [Image.open(x) if x else None for x in (photos or [])]
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    scenes = []
    t = 0.0

    # 훅: 큰 한 줄 문구(hook) + 그 아래 제목. 사진은 첫 프레임부터 보이게
    if photos and photos[0] is None:
        photos[0] = next((x for x in photos[1:] if x is not None), None)  # 훅 사진이 없으면 1장 사진을 쓴다
    has_photo = bool(photos) and photos[0] is not None
    hook_text = post.get("hook") or post["title"]
    f_hook = card_font("Black", 132)
    h_lines = wrap(d, hook_text, f_hook, TEXT_W - 40)
    if len(h_lines) > 2:  # 3줄 이상이면 글씨를 줄인다
        f_hook = card_font("Black", 104)
        h_lines = wrap(d, hook_text, f_hook, TEXT_W - 40)
    lh = int(f_hook.size * 1.28)
    y = 640
    hook_lines = []
    for line in h_lines:
        hook_lines.append((text_layer(line, f_hook, INK), LEFT, y))
        y += lh
    f_title = card_font("Bold", 64)
    t_col = CREAM if has_photo else INK
    title_lines = [outlined(s, f_title, t_col) if has_photo else text_layer(s, f_title, t_col) for s in wrap(d, post["title"] if post.get("hook") else post.get("subtitle", ""), f_title, TEXT_W)]
    hook = Scene(t, HOOK_BEATS * BEAT)
    hook.lines, hook.lh, hook.title, hook.title_y = hook_lines, lh, title_lines, y + 50
    hook.photo = cover(photos[0], int(W * 1.18), int(H * 1.18)) if has_photo else None
    scenes.append(("hook", hook))
    t += hook.dur

    # 본문
    for i, sl in enumerate(post["slides"], 1):
        dark = i % 2 == 1
        fg, sub_c = (CREAM, (200, 193, 182)) if dark else (INK, SOFT)
        ph = photos[i] if i < len(photos) else None
        f_head, f_body = (card_font("Black", 100), card_font("Medium", 60)) if ph else (card_font("Black", 112), card_font("Medium", 64))
        heads = [text_layer(s, f_head, fg) for s in wrap(d, sl["head"], f_head, TEXT_W)]
        bodies = [text_layer(s, f_body, fg) for s in wrap(d, sl["body"], f_body, TEXT_W)]
        sc = Scene(t, SLIDE_BEATS * BEAT)
        sc.i, sc.dark, sc.heads, sc.bodies, sc.fg = i, dark, heads, bodies, fg
        sc.num = text_layer(str(i), card_font("Black", 96), INK)
        sc.photo = None
        if ph is not None:
            cw, ch = CARD[2] - CARD[0], CARD[3] - CARD[1]
            sc.photo = cover(ph, int(cw * 1.1), int(ch * 1.1))
            sc.mask = round_mask(cw, ch, 44)
        scenes.append(("slide", sc))
        t += sc.dur

    # 마무리
    end = Scene(t, END_BEATS * BEAT)
    f_end = card_font("Black", 120)
    end.lines = [text_layer(s, f_end, CREAM) for s in ["저장해두고", "살림할 때", "꺼내 보세요"]]
    end.sub1 = text_layer("매일 아침 살림 카드뉴스", card_font("Bold", 50), MUSTARD)
    end.sub2 = text_layer("@daily_j83", card_font("Medium", 48), CREAM)
    scenes.append(("end", end))
    t += end.dur

    ad = None
    if post.get("link"):
        ad = text_layer("유료 광고 포함 · 쿠팡 파트너스 수수료를 받아요", card_font("Bold", 38), INK)
    return scenes, t, ad


# ---------- 그리기 ----------
def draw_hook(fr, sc, lt):
    d = ImageDraw.Draw(fr)
    if sc.photo is not None:
        # 첫 프레임부터 움직임: 1.5초 동안 빠르게 줌아웃 → 이후 아주 천천히
        p = 1 - 0.85 * ease_out_cubic(lt / 1.5) - 0.15 * (lt / sc.dur)
        fr.paste(kenburns(sc.photo, W, H, max(0.0, p), zoom=0.18, pan=(0.0, 0.0)), (0, 0))
        fr.alpha_composite(hook_shade())
    else:
        d.rectangle((0, 0, W, H), fill=CREAM)
    # 큰 한 줄 문구: 첫 프레임부터 보임 (머스타드 띠 위 먹색 글씨), 0.18초 동안 살짝 튕김
    q = ease_out_back(progress(lt, 0.0, 0.18), 2.0)
    s = 1.04 - 0.04 * q
    for lay, x, y in sc.lines:
        pad = 18
        d.rounded_rectangle((x - pad, y - 6, x + lay.width + pad, y + sc.lh - 22), 18, fill=MUSTARD)
        paste(fr, lay, x, y, 1.0, s)
    # 제목: 0.7초부터 아래에서 올라옴
    for k, lay in enumerate(sc.title):
        q = ease_out_cubic(progress(lt, 0.7 + k * 0.08, 0.4))
        paste(fr, lay, LEFT, sc.title_y + k * 84 + 30 * (1 - q), q)


def draw_slide(fr, sc, lt, total_slides):
    d = ImageDraw.Draw(fr)
    bg = INK if sc.dark else CREAM
    cx, cy = SLIDE_CENTER
    d.rectangle((0, 0, W, H), fill=bg)
    y = 760
    if sc.photo is not None:
        # 사진 카드: 아래에서 살짝 올라오며 나타나고, 천천히 다가옴
        cw, ch = CARD[2] - CARD[0], CARD[3] - CARD[1]
        q = ease_out_cubic(progress(lt, 0.15, 0.5))
        img = kenburns(sc.photo, cw, ch, lt / sc.dur, zoom=0.09, pan=(0.02, 0.0)).convert("RGBA")
        m = sc.mask.point(lambda v: int(v * q))
        fr.paste(img, (CARD[0], int(CARD[1] + 50 * (1 - q))), m)
        cx, cy = LEFT + 80, CARD[3]
        y = CARD[3] + 110
    # 번호 동그라미: 튕기며 등장
    q = progress(lt, 0.25, 0.35)
    if q > 0:
        rr = 80 * ease_out_back(q, 2.4)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=MUSTARD)
        paste(fr, sc.num, cx - sc.num.width / 2, cy - 66, min(1, q * 2), max(0.3, ease_out_back(q, 2.4)))
    # 소제목: 위로 올라오며
    for k, lay in enumerate(sc.heads):
        q = ease_out_cubic(progress(lt, 0.45 + k * 0.07, 0.45))
        paste(fr, lay, LEFT, y + 60 * (1 - q), q)
        y += lay.height - 10
    # 밑줄이 그어짐
    u = ease_out_cubic(progress(lt, 0.75, 0.35))
    d.rectangle((LEFT, y + 26, LEFT + int(110 * u), y + 38), fill=MUSTARD)
    # 본문: 한 줄씩
    y += 90
    for k, lay in enumerate(sc.bodies):
        q = ease_out_cubic(progress(lt, 0.95 + k * 0.08, 0.45))
        paste(fr, lay, LEFT, y + 30 * (1 - q), q)
        y += lay.height + 8
    # 퇴장: 마지막 0.22초에 글씨가 위로 빠짐 (다음 원이 덮기 전에)
    return


def draw_end(fr, sc, lt):
    d = ImageDraw.Draw(fr)
    d.rectangle((0, 0, W, H), fill=INK)
    # 책갈피 아이콘 (저장 버튼 모양) 통통
    q = progress(lt, 0.3, 0.45)
    if q > 0:
        s = ease_out_back(q, 2.5)
        bob = math.sin(max(0, lt - 0.75) * math.tau / (BEAT * 2)) * 10
        bx, by, bw, bh = LEFT, 560 + bob, 104 * s, 140 * s
        d.polygon([(bx, by), (bx + bw, by), (bx + bw, by + bh), (bx + bw / 2, by + bh * 0.72), (bx, by + bh)], fill=MUSTARD)
    y = 790
    for k, lay in enumerate(sc.lines):
        q = progress(lt, 0.45 + k * BEAT / 2, 0.3)
        if q > 0:
            paste(fr, lay, LEFT, y + 40 * (1 - ease_out_cubic(q)), min(1, q * 3), 0.6 + 0.4 * ease_out_back(q, 2))
        y += 120 + 26
    u = ease_out_cubic(progress(lt, 1.6, 0.35))
    d.rectangle((LEFT, y + 30, LEFT + int(170 * u), y + 42), fill=MUSTARD)
    q = ease_out_cubic(progress(lt, 1.8, 0.4))
    paste(fr, sc.sub1, LEFT, y + 90 + 20 * (1 - q), q)
    paste(fr, sc.sub2, LEFT, y + 160 + 20 * (1 - q), q)


SLIDE_CENTER = (LEFT + 80, 600)
END_CENTER = (W // 2, 800)
TRANS = 0.42  # 원 전환 시간(초)
WORD_GAP = BEAT / 5  # 제목 단어 간격 0.12초 (8분음표의 절반 느낌)


def hud(fr, t, idx, seg_p, nseg, dark):
    """위쪽 진행 막대(장면마다 한 칸) + 작은 글씨"""
    d = ImageDraw.Draw(fr)
    gap = 10
    seg_w = (W - LEFT - RIGHT_SAFE - (nseg - 1) * gap) / nseg
    base = (80, 78, 74) if dark else (214, 207, 194)
    for k in range(nseg):
        x0 = LEFT + k * (seg_w + gap)
        d.rectangle((x0, 150, x0 + seg_w, 156), fill=base)
        f = 1 if k < idx else (seg_p if k == idx else 0)
        if f > 0:
            d.rectangle((x0, 150, x0 + seg_w * f, 156), fill=MUSTARD)
    small = card_font("Medium", 26)
    d.text((LEFT, 182), "부산여자 살림코칭", font=small, fill=(150, 146, 140))


def draw_scene(kind, sc, lt, n):
    fr = Image.new("RGBA", (W, H), CREAM + (255,))
    if kind == "hook":
        draw_hook(fr, sc, lt)
    elif kind == "slide":
        draw_slide(fr, sc, lt, n)
    else:
        draw_end(fr, sc, lt)
    # 카메라: 장면마다 천천히 앞으로 (1.00 → 1.035), 글자 쪽을 중심으로
    z = 1 + 0.035 * ease_in_out_cubic(lt / sc.dur)
    if z > 1.001:
        cw, ch = int(W / z), int(H / z)
        x0, y0 = int((W - cw) * 0.5), int((H - ch) * 0.45)
        fr = fr.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
    return fr


# ---------- 음악 (직접 합성) ----------
def synth(duration, scene_starts, sr=44100):
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float64)
    tt = np.arange(n) / sr

    def add(sig, at):
        i = int(at * sr)
        j = min(n, i + len(sig))
        if i < n:
            out[i:j] += sig[: j - i]

    # 킥
    kt = np.arange(int(0.35 * sr)) / sr
    kick = np.sin(2 * np.pi * (45 + 90 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 9) * 0.9
    # 하이햇
    rng = np.random.default_rng(7)
    ht = np.arange(int(0.05 * sr)) / sr
    hat = rng.standard_normal(len(ht)) * np.exp(-ht * 90) * 0.12
    hat = np.diff(hat, prepend=0)
    # 휙(전환)
    wt = np.arange(int(0.45 * sr)) / sr
    whoosh = rng.standard_normal(len(wt))
    env = np.sin(np.pi * wt / wt[-1]) ** 2
    whoosh = np.convolve(whoosh, np.ones(30) / 30, mode="same") * env * 0.35
    beats = int(duration / BEAT)
    for b in range(beats):
        add(kick * (1.0 if b % 4 == 0 else 0.7), b * BEAT)
        add(hat, b * BEAT + BEAT / 2)
    for s in scene_starts[1:]:
        add(whoosh, max(0, s - 0.25))
    # 화음 패드 (따뜻한 7화음, 4박마다 바뀜)
    chords = [[261.63, 329.63, 392.0, 493.88], [220.0, 261.63, 329.63, 392.0],
              [174.61, 220.0, 261.63, 329.63], [196.0, 246.94, 293.66, 329.63]]
    bar = BEAT * 4
    pad = np.zeros(n)
    for k in range(int(duration / bar) + 1):
        ch = chords[k % 4]
        i0, i1 = int(k * bar * sr), min(n, int((k + 1) * bar * sr))
        if i0 >= n:
            break
        seg = tt[i0:i1] - k * bar
        e = np.minimum(1, seg / 0.08) * np.minimum(1, (bar - seg) / 0.25)
        for f in ch:
            pad[i0:i1] += (np.sin(2 * np.pi * f * seg) + 0.3 * np.sin(2 * np.pi * f * 2 * seg)) * e * 0.05
        # 플럭 아르페지오 (8분음표)
        for m in range(8):
            f = ch[m % 4] * 2
            pt = np.arange(int(0.3 * sr)) / sr
            pl = np.sin(2 * np.pi * f * pt) * np.exp(-pt * 14) * 0.06
            add(pl, k * bar + m * BEAT / 2)
    out += pad
    # 마무리 화음
    et = np.arange(int(1.8 * sr)) / sr
    fin = sum(np.sin(2 * np.pi * f * et) for f in [261.63, 329.63, 392.0, 523.25]) * np.exp(-et * 2.2) * 0.08
    add(fin, scene_starts[-1] + 0.4)
    # 끝 처리
    fade = np.ones(n)
    fl = int(0.4 * sr)
    fade[-fl:] = np.linspace(1, 0, fl)
    out *= fade
    out = np.tanh(out * 1.2)
    out /= max(1e-6, np.abs(out).max()) / 0.85
    return (out * 32767).astype(np.int16), sr


def write_wav(path, data, sr):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())


# ---------- 렌더링 ----------
def render(post_path: Path, out: Path, fps: int = 60, photos=None, track: Path | None = None, track_start: float = 0.0):
    post = json.loads(post_path.read_text(encoding="utf-8"))
    scenes, total, ad = build(post, photos)
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".wav")
    if track:
        # 사용자가 고른 무료 음원: 영상 길이만큼 자르고 앞뒤 페이드, 소리 크기 맞추기
        fo = max(0.1, total - 1.2)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(track_start), "-i", str(track), "-t", f"{total:.2f}",
                        "-af", f"afade=t=in:d=0.3,afade=t=out:st={fo:.2f}:d=1.2,loudnorm=I=-14:TP=-1.5:LRA=11",
                        "-ar", "44100", "-ac", "2", str(wav)], check=True)
    else:
        audio, sr = synth(total, [s.start for _, s in scenes])
        write_wav(wav, audio, sr)

    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(total * fps)
    n = len(post["slides"])
    for f in range(nframes):
        t = f / fps
        idx = next(k for k, (_, s) in enumerate(scenes) if s.start <= t < s.start + s.dur) if t < total else len(scenes) - 1
        kind, sc = scenes[idx]
        lt = sc.local(t)
        fr = draw_scene(kind, sc, lt, n)
        dark = (kind == "slide" and sc.dark) or kind == "end"
        if kind != "hook" and lt < TRANS:
            # 원이 퍼지며 전환: 이전 장면 마지막 모습 위로 새 장면이 원 모양으로 덮는다
            pk, ps = scenes[idx - 1]
            under = draw_scene(pk, ps, ps.dur - 1e-3, n)
            r = ease_in_out_cubic(lt / TRANS) * 2300
            cx, cy = SLIDE_CENTER if kind == "slide" else END_CENTER
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
            under.paste(fr, (0, 0), mask)
            fr = under
            dark = dark if lt > TRANS / 2 else ((pk == "slide" and ps.dark) or pk == "end")
        if kind != "hook":  # 훅 화면은 깨끗하게 (진행 막대·글씨 없이)
            hud(fr, t, idx, lt / sc.dur, len(scenes), dark)
        if ad and t < 3.6:  # 처음 3.6초: 유료 광고 표시
            dd = ImageDraw.Draw(fr)
            dd.rounded_rectangle((LEFT - 10, 228, LEFT + ad.width + 26, 228 + ad.height + 14), 14, fill=MUSTARD)
            fr.alpha_composite(ad, (LEFT + 8, 236))
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 인코딩 실패")
    wav.unlink(missing_ok=True)
    return out, total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("post")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--out")
    ap.add_argument("--photos", nargs="*", help="사진 파일들 (첫 장은 훅, 나머지는 본문 장)")
    ap.add_argument("--track", help="배경 음악 파일")
    ap.add_argument("--track-start", type=float, default=0.0)
    a = ap.parse_args()
    p = Path(a.post)
    o = Path(a.out) if a.out else ROOT / "out" / p.stem / "reel.mp4"
    path, dur = render(p, o, a.fps, a.photos, Path(a.track) if a.track else None, a.track_start)
    print(f"{path} ({dur:.1f}초)")
