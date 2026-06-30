from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
import threading
import uuid
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import textwrap
import math
import random
import asyncio
import edge_tts

app = Flask(__name__)
jobs = {}

W, H = 720, 1280

PALETTE = [
    {"accent": (255, 56, 100), "accent2": (255, 220, 0), "name": "fire"},
    {"accent": (0, 220, 255), "accent2": (0, 255, 170), "name": "cyber"},
    {"accent": (255, 90, 60), "accent2": (255, 230, 0), "name": "sunset"},
    {"accent": (130, 90, 255), "accent2": (0, 245, 255), "name": "purple"},
]

MUSIC_TRACKS = [
    "https://cdn.pixabay.com/audio/2024/03/05/audio_d0c6ff1bab.mp3",
    "https://cdn.pixabay.com/audio/2023/11/24/audio_7b3f4b1e2c.mp3",
    "https://cdn.pixabay.com/audio/2022/10/25/audio_946bc4f4a4.mp3",
]


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def load_fonts():
    base = "/usr/share/fonts/truetype/dejavu/"
    return {
        'caption': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 58),
        'hook': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 64),
        'small': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 30),
    }


def prep_background(bg_image, frame_num, total_frames, motion_seed=0):
    if bg_image is None:
        img = Image.new('RGB', (W, H), (12, 8, 28))
        d = ImageDraw.Draw(img)
        for y in range(H):
            r = int(12 + 28 * (y / H))
            g = int(8 + 12 * (y / H))
            b = int(38 + 40 * (y / H))
            d.line([(0, y), (W, y)], fill=(r, g, b))
        return img

    t = frame_num / max(total_frames - 1, 1)
    # Punchier Ken Burns: slightly stronger zoom for constant motion
    zoom = 1.14 + 0.18 * t
    new_w, new_h = int(W * zoom), int(H * zoom)
    img = bg_image.resize((new_w, new_h), Image.LANCZOS)

    pan_x = math.sin(motion_seed) * 45
    pan_y = math.cos(motion_seed) * 35
    left = int((new_w - W) / 2 + pan_x * t)
    top = int((new_h - H) / 2 + pan_y * t)
    left = max(0, min(left, new_w - W))
    top = max(0, min(top, new_h - H))
    img = img.crop((left, top, left + W, top + H))

    # Bright, punchy, modern grade
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    return img


def caption_readability_band(img):
    """Subtle dark gradient only in the lower-center so captions stay legible on any image,
    without the heavy old-school full vignette."""
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    band_top = int(H * 0.42)
    band_bot = int(H * 0.82)
    for y in range(band_top, band_bot):
        # bell-shaped darkening, peak in the middle of the band
        rel = (y - band_top) / (band_bot - band_top)
        alpha = int(120 * math.sin(rel * math.pi))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def build_caption_groups(word_boundaries, full_text=None, voice_duration=None, words_per_group=3):
    """Return a list of groups; each group is a list of word dicts {text, start, end}.
    Per-word timing is retained so we can highlight the spoken word (karaoke style)."""
    words = []
    if word_boundaries:
        for w in word_boundaries:
            words.append({'text': w['text'], 'start': w['offset'], 'end': w['offset'] + w['duration']})
    elif full_text and voice_duration and voice_duration > 1:
        toks = full_text.split()
        if not toks:
            return []
        slot = voice_duration / len(toks)
        for i, tok in enumerate(toks):
            words.append({'text': tok, 'start': i * slot, 'end': (i + 1) * slot})
    else:
        return []

    groups = []
    i = 0
    while i < len(words):
        size = words_per_group if (len(groups) % 3 != 2) else 2
        chunk = words[i:i + size]
        if not chunk:
            break
        groups.append(chunk)
        i += size
    return groups


def draw_karaoke_caption(draw, fonts, group, t_sec, frame_in_group, base_y, highlight_color):
    """Render a small word-group, big and bold, centered, with the currently spoken word highlighted."""
    font = fonts['caption']
    line_height = 70
    max_width = W - 120
    space_w = draw.textlength(' ', font=font)

    # Greedy wrap into lines, keeping word objects + measured widths
    lines = []
    cur = []
    cur_w = 0.0
    for w in group:
        wt = w['text'].upper()
        ww = draw.textlength(wt, font=font)
        add = ww if not cur else ww + space_w
        if cur and cur_w + add > max_width:
            lines.append((cur, cur_w))
            cur = [(w, ww, wt)]
            cur_w = ww
        else:
            cur.append((w, ww, wt))
            cur_w += add
    if cur:
        lines.append((cur, cur_w))

    # Entrance pop (bounce up) for the first frames of the group
    pop_t = min(1.0, frame_in_group / 5)
    scale = ease_out_back(pop_t)
    bounce = int((1 - scale) * 48) if pop_t < 1 else 0

    total_h = len(lines) * line_height
    y = base_y - total_h // 2 - bounce
    ow = 6  # outline width

    for line_words, line_w in lines:
        x = (W - line_w) // 2
        for (w, ww, wt) in line_words:
            active = (w['start'] <= t_sec < w['end'])
            color = highlight_color if active else (255, 255, 255)
            # soft drop shadow
            draw.text((x + 4, y + 6), wt, font=font, fill=(0, 0, 0, 120))
            # crisp black outline for legibility on any background
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx * dx + dy * dy <= ow * ow and (dx or dy):
                        draw.text((x + dx, y + dy), wt, font=font, fill=(0, 0, 0))
            # bright core (highlighted word = accent color, pops bigger feel via lighter weight)
            draw.text((x, y), wt, font=font, fill=color)
            x += ww + space_w
        y += line_height


def draw_progress_bar(draw, global_frame_num, global_total_frames, accent2):
    prog = global_frame_num / max(global_total_frames - 1, 1)
    draw.rectangle([0, 0, W, 8], fill=(255, 255, 255, 45))
    draw.rectangle([0, 0, int(W * prog), 8], fill=(*accent2, 255))


def create_frame(bg_image, frame_num, total_frames, palette, motion_seed,
                 caption_groups=None, global_frame_num=0, global_total_frames=1, fps=24):
    accent2 = palette['accent2']
    fonts = load_fonts()

    bg = prep_background(bg_image, frame_num, total_frames, motion_seed)
    img = caption_readability_band(bg)
    draw = ImageDraw.Draw(img, 'RGBA')

    # Quick clean white flash only on the very first frames of the whole video
    if global_frame_num < 3:
        a = int(110 * (1 - global_frame_num / 3))
        flash = Image.new('RGBA', (W, H), (255, 255, 255, a))
        img = Image.alpha_composite(img.convert('RGBA'), flash).convert('RGB')
        draw = ImageDraw.Draw(img, 'RGBA')

    # Karaoke captions = the narration, word by word, in the safe zone
    if caption_groups:
        t_sec = global_frame_num / fps
        for g in caption_groups:
            if g[0]['start'] <= t_sec < g[-1]['end']:
                frame_in = int((t_sec - g[0]['start']) * fps)
                draw_karaoke_caption(draw, fonts, g, t_sec, frame_in, int(H * 0.56), accent2)
                break

    # Retention progress bar at the top
    draw_progress_bar(draw, global_frame_num, global_total_frames, accent2)

    return img.convert('RGB')


def generate_voiceover(text, output_path):
    """Generate French voiceover using free Microsoft Edge TTS, returns (success, word_timings)."""
    try:
        voices = ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"]
        voice = random.choice(voices)
        word_boundaries = []

        async def _generate():
            communicate = edge_tts.Communicate(text, voice, rate="+22%", pitch="+10Hz")
            with open(output_path, 'wb') as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word_boundaries.append({
                            'text': chunk['text'],
                            'offset': chunk['offset'] / 10_000_000,
                            'duration': chunk['duration'] / 10_000_000
                        })

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_generate())
        finally:
            loop.close()

        success = os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        print(f"Edge TTS: success={success}, word_boundaries_count={len(word_boundaries)}")
        return success, word_boundaries
    except Exception as e:
        print(f"Edge TTS error: {e}")
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang='fr', slow=False)
            tts.save(output_path)
            return True, []
        except Exception as e2:
            print(f"gTTS fallback error: {e2}")
            return False, []


def get_audio_duration(audio_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception:
        return None


def download_music(tmpdir):
    try:
        url = random.choice(MUSIC_TRACKS)
        music_path = os.path.join(tmpdir, 'music.mp3')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(music_path, 'wb') as f:
                f.write(response.read())
        if os.path.getsize(music_path) > 1000:
            return music_path
    except Exception as e:
        print(f"Music download failed: {e}")
    return None


def generate_video_async(job_id, script, images_b64):
    jobs[job_id]['status'] = 'processing'
    try:
        fps = 24
        palette = random.choice(PALETTE)
        motion_seed = random.uniform(0, 6.28)

        with tempfile.TemporaryDirectory() as tmpdir:
            voix_off_text = script.get('voix_off') or (
                f"{script.get('titre', '')}. {script.get('fait1', '')} {script.get('fait2', '')} "
                f"{script.get('fait3', '')} {script.get('conclusion', '')}"
            )
            voice_path = os.path.join(tmpdir, 'voice.mp3')
            has_voice, word_boundaries = generate_voiceover(voix_off_text, voice_path)
            voice_duration = get_audio_duration(voice_path) if has_voice else None

            caption_groups = build_caption_groups(
                word_boundaries, full_text=voix_off_text, voice_duration=voice_duration, words_per_group=3
            )
            print(f"Caption groups built: {len(caption_groups)}")

            if voice_duration and voice_duration > 3:
                total_duration = voice_duration + 1.2
            else:
                total_duration = 24

            img_keys = ['image1', 'image2', 'image3']
            n_micro_sections = 6
            section_duration = total_duration / n_micro_sections

            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)

            total_frames = int(total_duration * fps)

            bgs = []
            for key in img_keys:
                b64v = images_b64.get(key)
                bg = None
                if b64v and len(b64v) > 100:
                    try:
                        img_data = base64.b64decode(b64v)
                        img_path = os.path.join(tmpdir, f'{key}.jpg')
                        with open(img_path, 'wb') as f:
                            f.write(img_data)
                        bg = Image.open(img_path).convert('RGB')
                    except Exception as e:
                        print(f"Image load error for {key}: {e}")
                bgs.append(bg)

            micro_to_img = [0, 1, 2, 0, 1, 2]

            for frame_num in range(total_frames):
                t_sec = frame_num / fps
                section_idx = min(int(t_sec / section_duration), n_micro_sections - 1)
                bg = bgs[micro_to_img[section_idx]]
                local_frame_num = frame_num - int(section_idx * section_duration * fps)
                local_motion_seed = motion_seed + section_idx * 1.7

                frame = create_frame(
                    bg, local_frame_num, int(section_duration * fps),
                    palette, local_motion_seed,
                    caption_groups=caption_groups,
                    global_frame_num=frame_num, global_total_frames=total_frames, fps=fps
                )
                frame.save(os.path.join(frames_dir, f'frame_{frame_num:05d}.jpg'), quality=88)

            silent_video_path = os.path.join(tmpdir, 'silent_video.mp4')
            cmd = [
                'ffmpeg', '-y', '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%05d.jpg'),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-pix_fmt', 'yuv420p', silent_video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)
            if result.returncode != 0:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = result.stderr[-500:]
                return

            output_path = os.path.join(tmpdir, 'video.mp4')
            music_path = download_music(tmpdir)
            mixed_ok = False

            if has_voice and music_path:
                mix_cmd = [
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-stream_loop', '-1', '-i', music_path,
                    '-filter_complex',
                    '[2:a]volume=0.12[music];[1:a]volume=1.0[voice];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]',
                    '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path
                ]
                mix_result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=120)
                mixed_ok = mix_result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000

            if not mixed_ok and has_voice:
                simple_cmd = [
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-map', '0:v', '-map', '1:a',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path
                ]
                subprocess.run(simple_cmd, capture_output=True, text=True, timeout=120)
                mixed_ok = os.path.exists(output_path) and os.path.getsize(output_path) > 1000

            if not mixed_ok:
                output_path = silent_video_path

            with open(output_path, 'rb') as f:
                video_b64 = base64.b64encode(f.read()).decode('utf-8')

            date = script.get('date', 'today')
            jobs[job_id]['status'] = 'done'
            jobs[job_id]['video_base64'] = video_b64
            jobs[job_id]['filename'] = f'video_{date}.mp4'

    except Exception as e:
        import traceback
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = f"{str(e)}\n{traceback.format_exc()}"


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@app.route('/generate-video', methods=['POST'])
def generate_video():
    data = request.json
    script = data.get('script', {})
    images_b64 = data.get('images', {})

    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'queued', 'created_at': time.time()}

    thread = threading.Thread(target=generate_video_async, args=(job_id, script, images_b64))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'queued'})


@app.route('/job/<job_id>', methods=['GET'])
def get_job(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    job = jobs[job_id]
    if job['status'] == 'done':
        return jsonify({
            'status': 'done', 'success': True,
            'video_base64': job['video_base64'], 'filename': job['filename']
        })
    elif job['status'] == 'error':
        return jsonify({'status': 'error', 'error': job.get('error', 'Unknown')}), 500
    return jsonify({'status': job['status']})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
