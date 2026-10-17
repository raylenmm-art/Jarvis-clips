"""Makes N vertical kids' short videos (free tools only) into ./out
Gemini (free tier) -> scripts | Pollinations -> images | edge-tts -> voice | ffmpeg -> video
"""
import asyncio, json, os, pathlib, subprocess, time, urllib.parse, urllib.request
import edge_tts

N = int(os.environ.get("NUM_CLIPS", "5"))
THEME = os.environ.get("THEME", "").strip()
KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # change if Google retires it
VOICE = os.environ.get("VOICE", "en-US-AnaNeural")
OUT = pathlib.Path("out"); OUT.mkdir(exist_ok=True)
FPS = 30


def ask_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=120))
    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])


def get_ideas():
    theme = f" Theme: {THEME}." if THEME else ""
    prompt = (
        f"Write {N} different, original, kid-safe cinematic short stories for ages 6-12.{theme} "
        "Nothing scary or violent; warm, funny or awe-inspiring. Return a JSON array of "
        f"exactly {N} objects with keys: "
        "title (max 60 chars), description (1-2 sentences), "
        "narration (75-90 words, vivid, ends on a satisfying beat), "
        "scenes (exactly 6 strings; each a detailed vertical cinematic image prompt that repeats "
        "the main character's look, in a painterly 3D animated style, no text in the image)."
    )
    return ask_gemini(prompt)[:N]


def fetch_image(prompt, path, seed):
    q = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{q}?width=1080&height=1920&nologo=true&seed={seed}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=120).read()
            if len(data) > 5000:
                path.write_bytes(data)
                return True
        except Exception as e:
            print("image retry", attempt, e)
        time.sleep(5 * (attempt + 1))
    return False


def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(path)])
    return float(out)


async def tts(text, path):
    await edge_tts.Communicate(text, VOICE).save(str(path))


def build(idx, idea):
    work = OUT / f"work{idx}"; work.mkdir(exist_ok=True)
    audio = work / "voice.mp3"
    asyncio.run(tts(idea["narration"], audio))
    total = duration(audio) + 0.5
    scenes = idea["scenes"]
    seg_len = total / len(scenes)
    frames = int(seg_len * FPS)
    segs, last = [], None
    for i, sp in enumerate(scenes):
        img = work / f"s{i}.jpg"
        if not fetch_image(sp, img, seed=idx * 100 + i):
            if last is None:
                raise RuntimeError("image generation failed")
            img.write_bytes(last.read_bytes())
        last = img
        seg = work / f"seg{i}.mp4"
        vf = (f"scale=1296:2304,zoompan=z='min(zoom+0.0012,1.2)':d={frames}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},format=yuv420p")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(img),
                        "-vf", vf, "-t", f"{seg_len:.3f}", "-c:v", "libx264", str(seg)], check=True)
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    final = OUT / f"clip{idx + 1}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)], check=True)
    return final


def main():
    manifest = []
    for i, idea in enumerate(get_ideas()):
        try:
            f = build(i, idea)
            manifest.append({"file": f.name, "title": idea["title"], "description": idea["description"]})
            print("made", f)
        except Exception as e:
            print("FAILED clip", i + 1, e)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if not manifest:
        raise SystemExit("no clips were made")


if __name__ == "__main__":
    main()
