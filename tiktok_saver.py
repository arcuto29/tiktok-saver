"""TikTok Saver: paste a TikTok link, get the original video or photos without the watermark.

Videos: TikTok stores a clean copy of every video next to the watermarked "download" file.
We skip the watermarked one and save the highest-quality clean file as-is (no re-encoding),
so quality is identical to what TikTok serves.

Photos (slideshows): TikTok's page data includes the original full-size images, which have
no watermark. We save those directly.
"""

import subprocess
import sys

try:
    import flask, yt_dlp, imageio_ffmpeg  # noqa: F401
except ImportError:
    print("First run: installing flask, yt-dlp and ffmpeg (takes a minute)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "flask", "yt-dlp", "imageio-ffmpeg"])

import atexit
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import zipfile
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, Response, after_this_request, jsonify, render_template_string, request, send_file
from yt_dlp.networking import Request

app = Flask(__name__)

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TikTok Saver · no watermark</title>
<style>
  :root {
    --bg: #0e0f13; --card: #171920; --line: #262a35; --text: #eef0f5; --muted: #8b91a1;
    --accent: #25f4ee; --accent2: #fe2c55; --radius: 14px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    display: flex; justify-content: center; padding: 48px 16px;
  }
  main { width: 100%; max-width: 640px; }
  h1 { margin: 0 0 4px; font-size: 28px; letter-spacing: -0.02em; }
  h1 span { background: linear-gradient(90deg, var(--accent), var(--accent2)); -webkit-background-clip: text; background-clip: text; color: transparent; }
  .sub { color: var(--muted); margin: 0 0 28px; }
  form { display: flex; gap: 8px; }
  input {
    flex: 1; min-width: 0; padding: 14px 16px; border-radius: var(--radius); border: 1px solid var(--line);
    background: var(--card); color: var(--text); font-size: 16px; outline: none;
  }
  input:focus { border-color: var(--accent); }
  button, .btn {
    border: 0; border-radius: var(--radius); padding: 14px 20px; font-weight: 600; font-size: 15px;
    cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 8px;
    background: var(--text); color: var(--bg); white-space: nowrap;
  }
  button:disabled { opacity: .5; cursor: default; }
  .btn.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
  .paste { background: var(--card); color: var(--text); border: 1px solid var(--line); }
  .msg { margin-top: 16px; color: var(--muted); min-height: 24px; }
  .msg.err { color: #ff6b81; }
  .card { margin-top: 20px; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; }
  .row { display: flex; gap: 16px; }
  .thumb { width: 120px; aspect-ratio: 9/16; object-fit: cover; border-radius: 10px; background: #000; flex: none; }
  .meta { min-width: 0; flex: 1; }
  .author { font-weight: 600; }
  .caption { color: var(--muted); font-size: 14px; margin: 4px 0 12px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
  .choices { display: flex; flex-direction: column; gap: 8px; }
  .choice { justify-content: space-between; width: 100%; }
  .choice small { font-weight: 400; opacity: .7; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin: 14px 0; }
  .grid a { position: relative; display: block; border-radius: 10px; overflow: hidden; background: #000; }
  .grid img { width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; }
  .grid span { position: absolute; left: 6px; bottom: 6px; font-size: 12px; background: rgba(0,0,0,.65); padding: 2px 6px; border-radius: 6px; color: #fff; }
  .spin { width: 16px; height: 16px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: s .7s linear infinite; }
  @keyframes s { to { transform: rotate(360deg); } }
  .up { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line); }
  .up-title { font-weight: 600; margin-bottom: 4px; }
  .up-title small { color: var(--muted); font-weight: 400; }
  .seg { display: inline-flex; background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 3px; margin: 8px 0 10px; flex-wrap: wrap; }
  .seg label { padding: 6px 10px; border-radius: 8px; font-size: 13px; cursor: pointer; color: var(--muted); }
  .seg input { display: none; }
  .seg label:has(input:checked) { background: var(--card); color: var(--text); }
  .targets { display: flex; gap: 8px; flex-wrap: wrap; }
  .targets button { padding: 10px 16px; background: var(--bg); color: var(--text); border: 1px solid var(--line); }
  .targets button:hover:not(:disabled) { border-color: var(--accent); }
  .bar { height: 8px; background: var(--bg); border-radius: 99px; overflow: hidden; margin: 12px 0 6px; }
  .bar div { height: 100%; width: 0; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .4s; }
  .up-line { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); align-items: center; }
  .linkbtn { background: none; border: 0; color: var(--muted); text-decoration: underline; padding: 0; font-size: 13px; font-weight: 400; }
  .hint { color: var(--muted); font-size: 13px; margin: 10px 0 0; }
  footer { margin-top: 32px; color: var(--muted); font-size: 13px; }
  @media (max-width: 480px) { form { flex-wrap: wrap; } input { flex-basis: 100%; } .thumb { width: 90px; } }
</style>
</head>
<body>
<main>
  <h1>TikTok Saver <span>no watermark</span></h1>
  <p class="sub">Paste a TikTok video or photo link. You get the original file without the watermark, at the same quality.</p>

  <form id="form">
    <input id="url" type="url" placeholder="https://www.tiktok.com/@user/video/..." autocomplete="off" required>
    <button type="button" class="paste" id="paste">Paste</button>
    <button type="submit" id="go">Get it</button>
  </form>
  <div class="msg" id="msg"></div>
  <div id="result"></div>

  <footer>Only save posts you made or have permission to use.</footer>
</main>

<script>
const $ = (id) => document.getElementById(id);
const form = $("form"), input = $("url"), go = $("go"), msg = $("msg"), result = $("result");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mb = (b) => (b ? ` · ${(b / 1048576).toFixed(1)} MB` : "");
const say = (text, err = false) => { msg.textContent = text; msg.className = "msg" + (err ? " err" : ""); };

$("paste").onclick = async () => {
  try { input.value = (await navigator.clipboard.readText()).trim(); form.requestSubmit(); }
  catch { input.focus(); say("Your browser blocked clipboard access. Press Ctrl+V / Cmd+V in the box."); }
};

form.onsubmit = async (e) => {
  e.preventDefault();
  result.innerHTML = "";
  go.disabled = true; go.innerHTML = '<span class="spin"></span> Looking';
  say("Fetching the post from TikTok…");
  try {
    const r = await fetch("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: input.value }) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Something went wrong.");
    say("");
    data.kind === "photos" ? showPhotos(data) : showVideo(data);
  } catch (err) {
    say(err.message, true);
  } finally {
    go.disabled = false; go.textContent = "Get it";
  }
};

function header(d) {
  return `<div class="author">@${esc(d.author)}</div><div class="caption">${esc(d.caption)}</div>`;
}

function showVideo(d) {
  const buttons = d.choices.map((c, i) => `
    <a class="btn choice ${i ? "ghost" : ""}" href="/api/video?token=${encodeURIComponent(d.token)}&format=${encodeURIComponent(c.id)}">
      <span>⬇ ${esc(c.label)}</span><small>${esc(c.detail)}${mb(c.size)}</small>
    </a>`).join("");
  const note = d.choices.length > 1
    ? `<p class="caption" style="margin-top:10px">If the best-quality file won't play on your device, use "Plays everywhere".</p>` : "";
  result.innerHTML = `
    <div class="card"><div class="row">
      ${d.thumbnail ? `<img class="thumb" src="${esc(d.thumbnail)}" referrerpolicy="no-referrer" alt="">` : ""}
      <div class="meta">${header(d)}<div class="choices">${buttons}</div>${note}</div>
    </div>${upscalePanel(d)}</div>`;
  result.querySelectorAll("a.choice").forEach((a) => a.addEventListener("click", () => say("Downloading… the file will appear in a moment.")));
  result.querySelectorAll(".targets button").forEach((b) => b.addEventListener("click", () => startUpscale(d, +b.dataset.t)));
}

const sizeName = (t) => (t === 2160 ? "4K" : `${t}p`);
const fmtTime = (s) => (s < 60 ? `${Math.max(1, Math.round(s))} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);

function upscalePanel(d) {
  if (!d.upscale_targets || !d.upscale_targets.length) return "";
  return `
    <div class="up">
      <div class="up-title">✨ AI upscale <small>· sharper, but takes a while</small></div>
      <div class="seg">
        <label><input type="radio" name="style" value="fast" checked>Screen recording / text / animation</label>
        <label><input type="radio" name="style" value="detailed">Real-life camera footage (slower)</label>
      </div>
      <div class="targets">${d.upscale_targets.map((t) => `<button type="button" data-t="${t}">Upscale to ${sizeName(t)}</button>`).join("")}</div>
      <div id="upstatus" hidden>
        <div class="bar"><div id="upbar"></div></div>
        <div class="up-line"><span id="upstage"></span><span><span id="upeta"></span> <button type="button" class="linkbtn" id="upcancel">Cancel</button></span></div>
      </div>
      <p class="hint">Runs on your own graphics card. The AI sharpens edges and text by predicting detail. It can't bring back detail TikTok threw away.</p>
    </div>`;
}

async function startUpscale(d, target) {
  const style = result.querySelector('input[name="style"]:checked').value;
  const btns = result.querySelectorAll(".targets button, .seg input");
  const status = $("upstatus"), bar = $("upbar"), stage = $("upstage"), eta = $("upeta"), cancel = $("upcancel");
  btns.forEach((b) => (b.disabled = true));
  status.hidden = false; cancel.hidden = false; bar.style.width = "0"; stage.textContent = "Starting…"; eta.textContent = "";
  const done = () => { btns.forEach((b) => (b.disabled = false)); cancel.hidden = true; eta.textContent = ""; };
  try {
    const r = await fetch("/api/upscale", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: d.token, target, style }) });
    const { job, error } = await r.json();
    if (!r.ok) throw new Error(error);
    cancel.onclick = () => { cancel.hidden = true; stage.textContent = "Cancelling…"; fetch(`/api/upscale/${job}/cancel`, { method: "POST" }); };
    while (true) {
      await new Promise((res) => setTimeout(res, 1000));
      const s = await (await fetch(`/api/upscale/${job}`)).json();
      if (s.error && !s.done) throw new Error(s.error);
      bar.style.width = `${Math.round((s.progress || 0) * 100)}%`;
      stage.textContent = s.stage + (s.done ? "" : "…");
      eta.textContent = s.eta ? `about ${fmtTime(s.eta)} left ·` : "";
      if (s.done) {
        if (s.error) throw new Error(s.error);
        stage.innerHTML = `Done · <a class="linkbtn" href="/api/upscale/${job}/file">download again</a>`;
        location.href = `/api/upscale/${job}/file`;
        say(`Your ${sizeName(target)} video is downloading${mb(s.size)}.`);
        break;
      }
    }
  } catch (err) {
    stage.textContent = err.message;
  } finally {
    done();
  }
}

function showPhotos(d) {
  const t = encodeURIComponent(d.token);
  const tiles = d.photos.map((p) => `
    <a href="/api/photo?token=${t}&i=${p.index}" title="Download photo ${p.index + 1}">
      <img loading="lazy" src="/api/photo?token=${t}&i=${p.index}&preview=1" alt="">
      <span>${p.index + 1}${p.width ? ` · ${p.width}×${p.height}` : ""}</span>
    </a>`).join("");
  result.innerHTML = `
    <div class="card">${header(d)}
      <div class="grid">${tiles}</div>
      <a class="btn" href="/api/photos.zip?token=${t}">⬇ Download all ${d.photos.length} photos (.zip)</a>
    </div>`;
}
</script>
</body>
</html>
"""

ALLOWED_HOSTS = ("tiktok.com", "tiktokv.com")
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
}
CACHE_TTL = 30 * 60  # seconds a resolved link stays valid
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


# ---------- helpers ----------

def is_tiktok_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and any(
        host == h or host.endswith("." + h) for h in ALLOWED_HOSTS
    )


def new_ydl(**extra) -> yt_dlp.YoutubeDL:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "http_headers": BROWSER_HEADERS}
    opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


def resolve_url(ydl: yt_dlp.YoutubeDL, url: str) -> str:
    """Follow short links (vm.tiktok.com, vt.tiktok.com, tiktok.com/t/...)."""
    with ydl.urlopen(Request(url, headers=BROWSER_HEADERS)) as resp:
        final = resp.url
    if not is_tiktok_url(final):
        raise ValueError("That link didn't lead to a TikTok post.")
    return final


def post_id_from_url(url: str) -> str | None:
    m = re.search(r"/(?:video|photo)/(\d+)", url)
    return m.group(1) if m else None


def fetch_item(ydl: yt_dlp.YoutubeDL, post_id: str) -> dict | None:
    """Read TikTok's embedded page data for a post. The /video/ path works for photo posts too."""
    page_url = f"https://www.tiktok.com/@i/video/{post_id}"
    with ydl.urlopen(Request(page_url, headers=BROWSER_HEADERS)) as resp:
        html = resp.read().decode("utf-8", "replace")
    m = re.search(
        r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        return None
    scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
    detail = scope.get("webapp.video-detail") or {}
    return (detail.get("itemInfo") or {}).get("itemStruct")


def clean_formats(info: dict) -> list[dict]:
    """All video formats except TikTok's watermarked 'download' file, best first."""
    out = []
    for f in info.get("formats") or []:
        note = (f.get("format_note") or "").lower()
        if f.get("format_id") == "download" or "watermark" in note:
            continue
        if f.get("vcodec") in (None, "none") or not f.get("height"):
            continue
        out.append(f)
    out.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    return out


def safe_name(text: str, fallback: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", text or "").strip()[:60].strip()
    return text or fallback


def cache_put(data: dict) -> str:
    token = secrets.token_urlsafe(16)
    now = time.time()
    with _cache_lock:
        for k in [k for k, v in _cache.items() if now - v["t"] > CACHE_TTL]:
            del _cache[k]
        _cache[token] = {"t": now, "data": data}
    return token


def cache_get(token: str) -> dict | None:
    with _cache_lock:
        entry = _cache.get(token or "")
    if not entry or time.time() - entry["t"] > CACHE_TTL:
        return None
    return entry["data"]


# ---------- routes ----------

@app.get("/")
def index():
    return render_template_string(INDEX_HTML)


@app.post("/api/resolve")
def api_resolve():
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    m = re.search(r"https?://\S+", url)  # allow pasting a whole share message
    url = m.group(0) if m else url
    if not is_tiktok_url(url):
        return jsonify(error="Paste a TikTok link (tiktok.com, vm.tiktok.com, ...)."), 400

    try:
        with new_ydl() as ydl:
            if not post_id_from_url(url):
                url = resolve_url(ydl, url)
            post_id = post_id_from_url(url)
            if not post_id:
                return jsonify(error="Couldn't find a post in that link."), 400

            item = fetch_item(ydl, post_id) or {}
            author = (item.get("author") or {}).get("uniqueId") or ""
            caption = item.get("desc") or ""
            base_name = safe_name(f"{author} {post_id}", post_id)

            images = ((item.get("imagePost") or {}).get("images")) or []
            if images:
                pics = []
                for img in images:
                    urls = (img.get("imageURL") or {}).get("urlList") or []
                    if urls:
                        pics.append({"urls": urls, "w": img.get("imageWidth"), "h": img.get("imageHeight")})
                token = cache_put({"kind": "photos", "pics": pics, "name": base_name})
                return jsonify(
                    kind="photos", token=token, author=author, caption=caption,
                    photos=[{"index": i, "width": p["w"], "height": p["h"]} for i, p in enumerate(pics)],
                )

            info = ydl.extract_info(f"https://www.tiktok.com/@{author or 'i'}/video/{post_id}", download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).split("ERROR:")[-1].strip()
        return jsonify(error=f"TikTok wouldn't give us that post: {msg}"), 502
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # network errors, page layout changes
        app.logger.exception("resolve failed")
        return jsonify(error=f"Something went wrong: {e}"), 500

    formats = clean_formats(info)
    if not formats:
        return jsonify(error="No watermark-free version is available for this video."), 404

    def res(f):  # "1080p" for both 1080x1920 and 1920x1080
        return min(f.get("width") or f["height"], f["height"])

    best = formats[0]
    h264 = next((f for f in formats if (f.get("vcodec") or "").startswith(("h264", "avc"))), None)
    choices = [{
        "id": best["format_id"],
        "label": f"Best quality · {res(best)}p",
        "detail": "H.265/HEVC" if not (best.get("vcodec") or "").startswith(("h264", "avc")) else "H.264",
        "size": best.get("filesize") or best.get("filesize_approx"),
    }]
    if h264 and h264["format_id"] != best["format_id"]:
        choices.append({
            "id": h264["format_id"],
            "label": f"Plays everywhere · {res(h264)}p",
            "detail": "H.264",
            "size": h264.get("filesize") or h264.get("filesize_approx"),
        })

    token = cache_put({
        "kind": "video",
        "url": info.get("webpage_url"),
        "allowed": [c["id"] for c in choices],
        "best": best["format_id"],
        "src_res": res(best),
        "name": base_name,
    })
    return jsonify(
        kind="video", token=token, author=author or info.get("uploader") or "",
        caption=caption or info.get("description") or "",
        thumbnail=info.get("thumbnail"), duration=info.get("duration"),
        width=best.get("width"), height=best.get("height"), choices=choices,
        upscale_targets=[t for t in UPSCALE_TARGETS if t > res(best)],
    )


@app.get("/api/video")
def api_video():
    data = cache_get(request.args.get("token"))
    fmt = request.args.get("format", "")
    if not data or data["kind"] != "video":
        return "This link expired. Paste it again.", 410
    if fmt not in data["allowed"]:
        return "Unknown format.", 400

    tmp = tempfile.mkdtemp(prefix="tiksave-")
    try:
        with new_ydl(format=fmt, outtmpl=os.path.join(tmp, "video.%(ext)s")) as ydl:
            ydl.download([data["url"]])
        files = os.listdir(tmp)
        if not files:
            raise RuntimeError("download produced no file")
        path = os.path.join(tmp, files[0])
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        app.logger.exception("video download failed")
        return f"Download failed: {e}", 502

    @after_this_request
    def cleanup(resp):
        resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
        return resp

    ext = os.path.splitext(path)[1] or ".mp4"
    return send_file(path, as_attachment=True, download_name=data["name"] + ext)


def _fetch_photo(ydl: yt_dlp.YoutubeDL, pic: dict) -> tuple[bytes, str]:
    last = None
    for u in pic["urls"]:  # TikTok gives mirror URLs; try each
        try:
            with ydl.urlopen(Request(u, headers=BROWSER_HEADERS)) as resp:
                ctype = resp.headers.get("Content-Type", "image/jpeg")
                return resp.read(), ctype
        except Exception as e:
            last = e
    raise RuntimeError(f"couldn't fetch image: {last}")


def _ext(ctype: str) -> str:
    return {"image/webp": ".webp", "image/png": ".png", "image/heic": ".heic"}.get(ctype.split(";")[0], ".jpg")


@app.get("/api/photo")
def api_photo():
    data = cache_get(request.args.get("token"))
    if not data or data["kind"] != "photos":
        return "This link expired. Paste it again.", 410
    try:
        i = int(request.args.get("i", "0"))
        pic = data["pics"][i]
    except (ValueError, IndexError):
        return "No such photo.", 404
    try:
        with new_ydl() as ydl:
            body, ctype = _fetch_photo(ydl, pic)
    except Exception as e:
        return f"Download failed: {e}", 502
    inline = request.args.get("preview") == "1"
    name = f"{data['name']}_{i + 1}{_ext(ctype)}"
    return Response(body, mimetype=ctype.split(";")[0], headers={
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{name}"',
        "Cache-Control": "private, max-age=1800",
    })


@app.get("/api/photos.zip")
def api_photos_zip():
    data = cache_get(request.args.get("token"))
    if not data or data["kind"] != "photos":
        return "This link expired. Paste it again.", 410
    buf = io.BytesIO()
    try:
        with new_ydl() as ydl, zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for i, pic in enumerate(data["pics"]):
                body, ctype = _fetch_photo(ydl, pic)
                zf.writestr(f"{data['name']}_{i + 1}{_ext(ctype)}", body)
    except Exception as e:
        return f"Download failed: {e}", 502
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=data["name"] + ".zip")


# ---------- AI upscaling (Real-ESRGAN, runs on your graphics card) ----------

UPSCALE_TARGETS = (1080, 1440, 2160)
UPSCALE_STYLES = {
    # name -> (Real-ESRGAN model, supported scales)
    "fast": ("realesr-animevideov3", (2, 3, 4)),  # screen recordings, text, graphics, anime
    "detailed": ("realesrgan-x4plus", (4,)),       # real camera footage; several times slower
}
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
ESRGAN_DIR = os.path.join(TOOLS_DIR, "realesrgan")
ESRGAN_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
    "realesrgan-ncnn-vulkan-20220424-{}.zip"
)
JOB_TTL = 60 * 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # don't flash console windows on Windows
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_upscale_busy = threading.Lock()  # the GPU can only do one video at a time


class Cancelled(Exception):
    pass


def _esrgan_exe() -> str:
    return os.path.join(ESRGAN_DIR, "realesrgan-ncnn-vulkan.exe" if os.name == "nt" else "realesrgan-ncnn-vulkan")


def _ensure_esrgan(job: dict) -> str:
    """Download the portable Real-ESRGAN build on first use (about 50 MB)."""
    exe = _esrgan_exe()
    if os.path.exists(exe):
        return exe
    plat = "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "ubuntu"
    os.makedirs(TOOLS_DIR, exist_ok=True)
    part_zip = os.path.join(TOOLS_DIR, "realesrgan.zip.part")
    part_dir = ESRGAN_DIR + ".part"
    with new_ydl() as ydl, ydl.urlopen(Request(ESRGAN_URL.format(plat))) as resp, open(part_zip, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while chunk := resp.read(1 << 20):
            _check_cancel(job)
            out.write(chunk)
            got += len(chunk)
            _set(job, stage="Downloading the AI upscaler (one time, about 50 MB)",
                 progress=0.05 * got / total if total else 0)
    shutil.rmtree(part_dir, ignore_errors=True)
    with zipfile.ZipFile(part_zip) as z:
        for m in z.infolist():
            base = os.path.basename(m.filename)
            if m.filename.startswith("models/") or base.startswith("realesrgan-ncnn-vulkan") or base.endswith(".dll"):
                z.extract(m, part_dir)
    os.chmod(os.path.join(part_dir, os.path.basename(exe)), 0o755)
    shutil.rmtree(ESRGAN_DIR, ignore_errors=True)
    os.replace(part_dir, ESRGAN_DIR)
    os.remove(part_zip)
    return exe


def _set(job: dict, **kw):
    with _jobs_lock:
        job.update(kw)


def _check_cancel(job: dict):
    if job.get("cancel"):
        raise Cancelled()


def _count_files(folder: str) -> int:
    with os.scandir(folder) as it:
        return sum(1 for _ in it)


def _wait(job: dict, proc: subprocess.Popen, on_tick=None):
    """Wait for a subprocess, reporting progress and honouring Cancel."""
    with _jobs_lock:
        job["proc"] = proc
    try:
        while proc.poll() is None:
            if job.get("cancel"):
                proc.terminate()
                proc.wait()
                raise Cancelled()
            if on_tick:
                on_tick()
            time.sleep(0.5)
    finally:
        with _jobs_lock:
            job["proc"] = None
    return proc.returncode


def _tail(path: str, n: int = 6) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().endswith("%")]
        return " | ".join(lines[-n:])
    except OSError:
        return ""


def _run_upscale(job: dict, data: dict, target: int, style: str):
    import imageio_ffmpeg

    tmp = job["tmp"]
    model, scales = UPSCALE_STYLES[style]
    try:
        exe = _ensure_esrgan(job)
        ff = imageio_ffmpeg.get_ffmpeg_exe()

        _set(job, stage="Downloading the original video", progress=0.05)
        with new_ydl(format=data["best"], outtmpl=os.path.join(tmp, "src.%(ext)s")) as ydl:
            ydl.download([data["url"]])
        src = next(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("src."))
        _check_cancel(job)

        frames_gen = imageio_ffmpeg.read_frames(src)
        meta = next(frames_gen)
        frames_gen.close()
        w, h = meta["source_size"]
        fps = meta.get("fps") or 30
        total = max(1, int(round((meta.get("duration") or 0) * fps)))

        in_dir, out_dir = os.path.join(tmp, "in"), os.path.join(tmp, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)

        _set(job, stage="Splitting the video into frames", progress=0.07)
        rc = _wait(job, subprocess.Popen(
            [ff, "-v", "error", "-i", src, "-vf", f"fps={fps}", "-q:v", "1", "-qmin", "1",
             os.path.join(in_dir, "%08d.jpg")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
        ), on_tick=lambda: _set(job, progress=0.07 + 0.03 * min(1, _count_files(in_dir) / total)))
        total = _count_files(in_dir)
        if rc != 0 or total == 0:
            raise RuntimeError("couldn't read the video frames")

        short = min(w, h)
        scale = next((s for s in scales if short * s >= target), scales[-1])
        _set(job, stage=f"AI upscaling {total} frames on your graphics card", progress=0.10)
        log = os.path.join(tmp, "esrgan.log")
        started = time.time()

        def tick():
            done = _count_files(out_dir)
            elapsed = time.time() - started
            eta = (elapsed / done) * (total - done) if done >= 3 else None
            _set(job, progress=0.10 + 0.80 * done / total, eta=eta,
                 stage=f"AI upscaling frame {done} of {total} on your graphics card")

        with open(log, "w") as logf:
            rc = _wait(job, subprocess.Popen(
                [exe, "-i", in_dir, "-o", out_dir, "-n", model, "-s", str(scale), "-f", "jpg",
                 "-m", os.path.join(ESRGAN_DIR, "models")],
                cwd=ESRGAN_DIR, stdout=logf, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            ), on_tick=tick)
        if rc != 0 or _count_files(out_dir) < total:
            detail = _tail(log)
            if any(s in detail.lower() for s in ("vkcreateinstance", "invalid gpu", "libvulkan", "vulkan-1.dll")):
                raise RuntimeError(
                    "the AI upscaler couldn't find a graphics card it can use. "
                    "Update your graphics drivers (NVIDIA, AMD or Intel) and try again."
                )
            raise RuntimeError(f"the AI upscaler stopped ({detail or 'exit code ' + str(rc)})")
        shutil.rmtree(in_dir, ignore_errors=True)  # free disk space before encoding

        # Final size: shorter side = target, keep aspect ratio, even numbers for the encoder
        k = target / short
        out_w, out_h = int(round(w * k / 2)) * 2, int(round(h * k / 2)) * 2
        out = os.path.join(tmp, "upscaled.mp4")
        _set(job, stage="Building the final video", progress=0.90, eta=None)
        def enc_tick():
            try:
                with open(os.path.join(tmp, "enc.txt")) as f:
                    nums = re.findall(r"^frame=(\d+)", f.read(), re.M)
                if nums:
                    _set(job, progress=0.90 + 0.10 * min(1, int(nums[-1]) / total))
            except OSError:
                pass

        with open(os.path.join(tmp, "enc.log"), "w") as enc_log:
            rc = _wait(job, subprocess.Popen(
                [ff, "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(out_dir, "%08d.jpg"),
                 "-i", src, "-map", "0:v:0", "-map", "1:a:0?",
                 "-vf", f"scale={out_w}:{out_h}:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p",
                 "-color_range", "tv",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "copy",
                 "-shortest", "-movflags", "+faststart", "-progress", os.path.join(tmp, "enc.txt"), out],
                stdout=subprocess.DEVNULL, stderr=enc_log, creationflags=NO_WINDOW,
            ), on_tick=enc_tick)
        if rc != 0:
            raise RuntimeError(f"encoding failed ({_tail(os.path.join(tmp, 'enc.log'))})")
        shutil.rmtree(out_dir, ignore_errors=True)

        label = "4K" if target == 2160 else f"{target}p"
        _set(job, stage="Done", progress=1.0, done=True, file=out,
             name=f"{data['name']} {label} AI.mp4", size=os.path.getsize(out))
    except Cancelled:
        _set(job, stage="Cancelled", done=True, error="Cancelled.")
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        app.logger.exception("upscale failed")
        _set(job, done=True, error=f"Upscale failed: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        _upscale_busy.release()


@atexit.register
def _cleanup_all_jobs():
    for job in list(_jobs.values()):
        if job.get("proc"):
            job["proc"].terminate()
        shutil.rmtree(job["tmp"], ignore_errors=True)


def _cleanup_jobs():
    now = time.time()
    with _jobs_lock:
        old = [k for k, j in _jobs.items() if j["done"] and now - j["t"] > JOB_TTL]
        for k in old:
            shutil.rmtree(_jobs.pop(k)["tmp"], ignore_errors=True)


@app.post("/api/upscale")
def api_upscale():
    body = request.get_json(silent=True) or {}
    data = cache_get(body.get("token"))
    if not data or data["kind"] != "video":
        return jsonify(error="This link expired. Paste it again."), 410
    try:
        target = int(body.get("target"))
    except (TypeError, ValueError):
        target = 0
    style = body.get("style") if body.get("style") in UPSCALE_STYLES else "fast"
    if target not in UPSCALE_TARGETS or target <= data["src_res"]:
        return jsonify(error="Pick a size bigger than the original."), 400
    _cleanup_jobs()
    if not _upscale_busy.acquire(blocking=False):
        return jsonify(error="Another video is being upscaled. Wait for it to finish or cancel it."), 409
    job_id = secrets.token_urlsafe(12)
    job = {"t": time.time(), "tmp": tempfile.mkdtemp(prefix="tiksave-up-"), "stage": "Starting",
           "progress": 0.0, "eta": None, "done": False, "error": None, "cancel": False, "proc": None}
    with _jobs_lock:
        _jobs[job_id] = job
    threading.Thread(target=_run_upscale, args=(job, data, target, style), daemon=True).start()
    return jsonify(job=job_id)


@app.get("/api/upscale/<job_id>")
def api_upscale_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error="Unknown job."), 404
        return jsonify({k: job.get(k) for k in ("stage", "progress", "eta", "done", "error", "size")})


@app.post("/api/upscale/<job_id>/cancel")
def api_upscale_cancel(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job["cancel"] = True
    return jsonify(ok=bool(job))


@app.get("/api/upscale/<job_id>/file")
def api_upscale_file(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or not job.get("file") or not os.path.exists(job["file"]):
        return "This file isn't available any more. Upscale again.", 410
    return send_file(job["file"], as_attachment=True, download_name=job["name"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  TikTok Saver is running: open http://127.0.0.1:{port} in your browser\n")
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port)
