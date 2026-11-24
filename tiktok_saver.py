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
    import flask, yt_dlp  # noqa: F401
except ImportError:
    print("First run: installing flask and yt-dlp (takes a minute)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "flask", "yt-dlp"])

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
    </div></div>`;
  result.querySelectorAll("a.choice").forEach((a) => a.addEventListener("click", () => say("Downloading… the file will appear in a moment.")));
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
        "name": base_name,
    })
    return jsonify(
        kind="video", token=token, author=author or info.get("uploader") or "",
        caption=caption or info.get("description") or "",
        thumbnail=info.get("thumbnail"), duration=info.get("duration"),
        width=best.get("width"), height=best.get("height"), choices=choices,
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  TikTok Saver is running: open http://127.0.0.1:{port} in your browser\n")
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port)
