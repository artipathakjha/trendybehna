"""Deal Reel / Short: three 1080x1920 scenes (hook -> product -> cta) rendered like the cards, then joined by ffmpeg
with a slow zoom and cross-fades into an H.264/AAC MP4 that Instagram and Facebook accept.

Optional Hinglish voice-over (REEL_VOICE, e.g. hi-IN-SwaraNeural, via edge-tts). A synthetic voice is "synthetically
generated information" under India's IT Rules amendment in force since 2026-02-20, so it is labelled on screen."""
from __future__ import annotations

import asyncio
import hashlib
import html
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .captions import fmt_count, show_price
from .deals import Deal
from .render import screenshot

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "reel.html"
SIZE = (1080, 1920)
FPS = 30
SCENES = (("hook", 2.6), ("product", 3.8), ("cta", 3.2))  # minimum seconds each; a voice-over can lengthen a scene
FADE = 0.4
ZOOM = 0.04  # each scene slowly zooms in by 4%
# Rotating palettes (glow, mid, edge, deep): Instagram demotes accounts whose Reels look like one repeated stamp.
THEMES = {
    "rani": ("#C8306F", "#B0145A", "#8A0E47", "#6E0A37"),
    "emerald": ("#22936F", "#127055", "#0B5240", "#06372B"),
    "royal": ("#3D5BC4", "#263FA0", "#1A2D7A", "#101D54"),
    "wine": ("#A3324A", "#842036", "#621427", "#430C1A"),
    "plum": ("#8E44AD", "#6F2A92", "#531E6F", "#38124C"),
}


def theme_for(deal: Deal) -> str:
    names = sorted(THEMES)
    return names[int(hashlib.sha1(deal.id.encode()).hexdigest(), 16) % len(names)]


def hook_html(deal: Deal, now: datetime) -> str:
    e = html.escape
    cat = e(deal.category)
    if show_price(deal, now) and deal.discount_pct and deal.discount_pct >= 30:
        return f"{cat} pe<br><b>{deal.discount_pct}% off</b>!"
    if show_price(deal, now):
        return f"<b>₹{deal.price:,}</b> mein<br>{cat}?"
    if deal.rating and deal.ratings_count:
        return f"<b>{fmt_count(deal.ratings_count)}</b> logon ne<br>diya <b>{deal.rating}★</b>"
    return f"Aaj ka<br><b>{cat}</b> deal"


def _spoken_count(n: int) -> str:
    return f"{n // 1000} hazaar se zyada" if n >= 1000 else str(n)


def narration(deal: Deal, now: datetime) -> list[str]:
    """What the voice says in each scene (plain text, numbers spelled the way the Hindi voice reads them well)."""
    if show_price(deal, now) and deal.discount_pct and deal.discount_pct >= 30:
        hook = f"{deal.category} pe {deal.discount_pct} percent off!"
    elif show_price(deal, now):
        hook = f"Sirf {deal.price} rupaye mein {deal.category}!"
    elif deal.rating and deal.ratings_count:
        hook = f"{_spoken_count(deal.ratings_count)} logon ne diya {deal.rating} star!"
    else:
        hook = f"Aaj ka {deal.category} deal!"
    product = deal.title + "."
    if deal.rating and deal.ratings_count:
        product += f" {deal.rating} star rating, {_spoken_count(deal.ratings_count)} reviews."
    if deal.blurb:
        product += " " + deal.blurb
    where = "Price Amazon pe check karo" if deal.store == "amazon" else f"{deal.store_name} pe dekho"
    return [hook, product, f"{where}, link bio mein. Aise deals ke liye follow karo Trendy Behna!"]


def scene_html(deal: Deal, scene: str, now: datetime, voiced: bool = False) -> str:
    e = html.escape
    title = deal.title if len(deal.title) <= 70 else deal.title[:67].rstrip() + "…"
    ad = "#ad · affiliate link · price same rehta hai"
    if deal.store == "amazon":
        ad += "<br>As an Amazon Associate I earn from qualifying purchases."
    if scene == "hook":
        body = (f'<div class="brand">ट्रेंडी बहना</div><div class="chip">Aaj ka deal</div>'
                f'<div class="hook">{hook_html(deal, now)}</div>')
    elif scene == "product":
        facts = []
        if show_price(deal, now):
            facts.append(f"<b>₹{deal.price:,}</b>" + (f" &nbsp;·&nbsp; {deal.discount_pct}% off" if deal.discount_pct else ""))
        if deal.rating and deal.ratings_count:
            facts.append(f"<b>{deal.rating}★</b> &nbsp;({fmt_count(deal.ratings_count)} ratings)")
        body = (f'<div class="chip">{e(deal.category)}</div><div class="title">{e(title)}</div>'
                f'<div class="facts">{"<br>".join(facts)}</div>'
                + (f'<div class="blurb">{e(deal.blurb)}</div>' if deal.blurb else ""))
    elif scene == "cta":
        store = "Check price on Amazon" if deal.store == "amazon" else f"{e(deal.store_name)} pe dekho"
        body = (f'<div class="brand">ट्रेंडी बहना</div><div class="store">{store}</div>'
                f'<div class="where">Link bio mein<br>Roz naye deals: follow @trendybehna</div>'
                f'<div class="ad">{ad}</div>')
    else:
        raise ValueError(scene)
    glow, mid, edge, deep = THEMES[theme_for(deal)]
    subs = {"{{BODY}}": body, "{{HOOK_PX}}": "116" if len(deal.category) <= 14 else "96",
            "{{TITLE_PX}}": "76" if len(title) <= 40 else "64",
            "{{THEME}}": f"--glow:{glow}; --mid:{mid}; --edge:{edge}; --deep:{deep};",
            "{{TAG}}": "#ad · affiliate" + (" · AI voice" if voiced else "")}
    out = TEMPLATE.read_text(encoding="utf-8")
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    env = os.environ.get("FFMPEG_BIN", "")
    if env and name != "ffmpeg":  # ffprobe sits next to ffmpeg
        env = str(Path(env).with_name(Path(env).name.replace("ffmpeg", name)))
    for c in [env, name]:
        if c and (shutil.which(c) or Path(c).exists()):
            return c
    raise RuntimeError(f"{name} not found; set FFMPEG_BIN")


def media_seconds(path: Path) -> float:
    out = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=nw=1:nk=1", str(path)], check=True, capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def speak(lines: list[str], voice: str, folder: Path) -> list[Path]:
    import edge_tts  # only needed when REEL_VOICE is set

    async def run() -> None:
        for i, text in enumerate(lines):
            await edge_tts.Communicate(text, voice, rate="+6%").save(str(folder / f"vo{i}.mp3"))
    asyncio.run(run())
    return [folder / f"vo{i}.mp3" for i in range(len(lines))]


def ffmpeg_args(scene_pngs: list[Path], durations: list[float], out_mp4: Path,
                voices: list[Path] | None = None, music: Path | None = None) -> list[str]:
    args = ["-y"]
    for png, d in zip(scene_pngs, durations):
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.2f}", "-i", str(png)]
    total = sum(durations) - FADE * (len(durations) - 1)
    starts = [sum(durations[:i]) - FADE * i for i in range(len(durations))]
    if music:
        args += ["-i", str(music)]
    else:  # a silent bed keeps an audio stream even without music (some apps reject video-only files)
        args += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    for v in voices or []:
        args += ["-i", str(v)]
    chains, last = [], ""
    for i, d in enumerate(durations):
        n = round(d * FPS)
        # upscale before zoompan so the slow zoom does not jitter on whole-pixel steps
        chains.append(f"[{i}:v]scale=2160:3840,zoompan=z='1+{ZOOM}*in/{n}':x='iw/2-(iw/zoom/2)':"
                      f"y='ih/2-(ih/zoom/2)':d=1:s={SIZE[0]}x{SIZE[1]}:fps={FPS},setsar=1,format=yuv420p[v{i}]")
        if i == 0:
            last = "[v0]"
        else:
            chains.append(f"{last}[v{i}]xfade=transition=fade:duration={FADE}:offset={starts[i]:.2f}[x{i}]")
            last = f"[x{i}]"
    bed = len(durations)
    # music sits lower when a voice is talking over it
    chains.append(f"[{bed}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"volume={0.35 if voices else 1.0},atrim=0:{total:.2f}[bed]")
    mix = ["[bed]"]
    for j, _ in enumerate(voices or []):
        ms = round((starts[j] + 0.15) * 1000)
        chains.append(f"[{bed + 1 + j}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[vo{j}]")
        mix.append(f"[vo{j}]")
    chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
                  f"aformat=sample_rates=48000:channel_layouts=stereo[a]")
    args += ["-filter_complex", ";".join(chains), "-map", last, "-map", "[a]",
             "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-g", str(2 * FPS), "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
             "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_mp4)]
    return args


def render_reel(deal: Deal, out_mp4: Path, now: datetime, voice: str | None = None, music: bool = False) -> Path:
    """voice: an edge-tts voice name (e.g. hi-IN-SwaraNeural) for a voice-over; None/"" for no voice.
    music: an original track composed for this deal (tb/music.py) instead of a silent bed."""
    out_mp4 = out_mp4.resolve()
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        voices = speak(narration(deal, now), voice, folder) if voice else None
        durations = [base for _, base in SCENES]
        if voices:  # stretch a scene so its line finishes before the next cross-fade starts
            durations = [max(base, media_seconds(v) + 0.6) for base, v in zip(durations, voices)]
        pngs = [screenshot(scene_html(deal, s, now, voiced=bool(voices)), SIZE, folder / f"{s}.png")
                for s, _ in SCENES]
        track = None
        if music:
            from .music import compose, write_wav  # numpy only needed when music is on
            track = write_wav(compose(deal.id, sum(durations)), folder / "music.wav")
        subprocess.run([ffmpeg_bin(), *ffmpeg_args(pngs, durations, out_mp4, voices, track)],
                       check=True, capture_output=True, timeout=300)
    if not out_mp4.exists() or out_mp4.stat().st_size < 50_000:
        raise RuntimeError(f"reel render failed: {out_mp4}")
    return out_mp4
