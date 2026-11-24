# TikTok Saver (no watermark)

Paste a TikTok link, then download the video or slideshow photos without the TikTok watermark, at original quality.

## Run it

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/). On Windows, tick **"Add Python to PATH"** during setup.
2. Download this repo: green **Code** button → **Download ZIP**, then unzip it.
3. Start it:
   - **Windows:** double-click `start-windows.bat`
   - **Mac:** open Terminal, type `bash ` (with a space), drag `start-mac-linux.sh` into the window, press Enter
4. Your browser opens at http://127.0.0.1:5000. Keep the black window open while you use it.

The first start takes about a minute to install. The app runs only on your computer.

## How it works

- **Videos:** TikTok keeps a clean copy of every video next to the watermarked one. The app skips the watermarked file and saves the clean original byte-for-byte. Nothing is re-encoded, so quality is exactly what TikTok has (usually up to 1080p).
  - **Best quality**: highest resolution, usually H.265/HEVC. Plays on phones, Mac, Chrome, Edge and Windows with the HEVC codec.
  - **Plays everywhere**: H.264 version for older players, often a lower resolution.
- **AI upscale (optional):** for videos below 4K, you can upscale to 1080p, 1440p or 4K with [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN). It runs on your graphics card (NVIDIA, AMD, Intel or Apple). The first time, it downloads the upscaler into a `tools` folder (about 50 MB).
  - **Screen recording / text / animation** (default): fast, makes text and chart lines very crisp.
  - **Real-life camera footage:** a heavier model for people and scenery. Several times slower.
  - Time depends on your graphics card and the video length. A 30-second video can take anywhere from about a minute to 15 minutes or more. The AI predicts detail, so it looks sharper, but it can't bring back detail TikTok didn't keep.
  - If it says it can't find a graphics card, update your graphics drivers.
- **Photos / slideshows:** downloads the original full-size images, one at a time or all together as a .zip.
- Accepts full links, short share links (`vm.tiktok.com/...`, `tiktok.com/t/...`), or a whole pasted share message.

If downloads stop working at some point, TikTok probably changed something. Run the start script again; it updates `yt-dlp` automatically.

Only download posts you made or have permission to use.
