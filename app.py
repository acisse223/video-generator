from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
import threading
import uuid
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import textwrap
import math
import random
import asyncio
import edge_tts

app = Flask(__name__)
jobs = {}

W, H = 720, 1280

# ===== BRANDING =====
SIGNATURE = "Tiens-toi bien, ça va te choquer !"
CTA_TEXT = "Abonne-toi pour plus de faits fous !"

PALETTE = [
    {"accent": (255, 56, 100), "accent2": (255, 220, 0), "name": "fire"},
    {"accent": (0, 200, 255), "accent2": (0, 255, 170), "name": "cyber"},
    {"accent": (255, 90, 50), "accent2": (255, 225, 0), "name": "sunset"},
    {"accent": (140, 90, 255), "accent2": (0, 245, 255), "name": "purple"},
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
        'outro': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 60),
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

    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    return img


def caption_readability_band(img):
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    band_top = int(H * 0.30)
    band_bot = int(H * 0.84)
    for y in range(band_top, band_bot):
        rel = (y - band_top) / (band_bot - band_top)
        alpha = int(125 * math.sin(rel * math.pi))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def draw_outlined_text(draw, x, y, text, font, fill, outline_w=6, shadow=True):
    if shadow:
        draw.text((x + 4, y + 6), text, font=font, fill=(0, 0, 0, 120))
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx * dx + dy * dy <= outline_w * outline_w and (dx or dy):
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def words_with_timing(word_boundaries, full_text, voice_duration):
    if word_boundaries:
        return [{'text': w['text'], 'start': w['offset'], 'end': w['offset'] + w['duration']}
                for w in word_boundaries]
    if full_text and voice_duration and voice_duration > 1:
        toks = full_text.split()
        if not toks:
            return []
        slot = voice_duration / len(toks)
        return [{'text': t, 'start': i * slot, 'end': (i + 1) * slot} for i, t in enumerate(toks)]
    return []


def group_words(words, words_per_group=3):
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
    font = fonts['caption']
    line_height = 70
    max_width = W - 120
    space_w = draw.textlength(' ', font=font)

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

    pop_t = min(1.0, frame_in_group / 5)
    scale = ease_out_back(pop_t)
    bounce = int((1 - scale) * 48) if pop_t < 1 else 0

    total_h = len(lines) * line_height
    y = base_y - total_h // 2 - bounce

    for line_words, line_w in lines:
        x = (W - line_w) // 2
        for (w, ww, wt) in line_words:
            active = (w['start'] <= t_sec < w['end'])
            color = highlight_color if active else (255, 255, 255)
            draw_outlined_text(draw, int(x), int(y), wt, font, color, outline_w=6)
            x += ww + space_w
        y += line_height


def draw_outro_card(draw, fonts, t_elapsed, palette):
    accent = palette['accent']
    accent2 = palette['accent2']
    pop = ease_out_back(min(1.0, t_elapsed / 0.4))
    bounce = int((1 - pop) * 50)

    of = fonts['outro']
    main = "ABONNE-TOI"
    bb = draw.textbbox((0, 0), main, font=of)
    lw = bb[2] - bb[0]
    cy = int(H * 0.44) - bounce
    pad = 44
    draw.rounded_rectangle([((W - lw) // 2 - pad, cy - 18), ((W + lw) // 2 + pad, cy + 92)],
                           radius=46, fill=(*accent, 240))
    draw.text(((W - lw) // 2, cy), main, font=of, fill=(255, 255, 255))

    sub = "POUR PLUS DE FAITS FOUS"
    sf = fonts['small']
    sbb = draw.textbbox((0, 0), sub, font=sf)
    sw = sbb[2] - sbb[0]
    draw_outlined_text(draw, (W - sw) // 2, cy + 118, sub, sf, accent2, outline_w=5)


def draw_progress_bar(draw, global_frame_num, global_total_frames, accent2):
    prog = global_frame_num / max(global_total_frames - 1, 1)
    draw.rectangle([0, 0, W, 8], fill=(255, 255, 255, 45))
    draw.rectangle([0, 0, int(W * prog), 8], fill=(*accent2, 255))


def create_frame(bg_image, frame_num, total_frames, palette, motion_seed,
                 caption_groups=None, outro_start=20.0,
                 global_frame_num=0, global_total_frames=1, fps=24):
    accent2 = palette['accent2']
    fonts = load_fonts()

    bg = prep_background(bg_image, frame_num, total_frames, motion_seed)
    img = caption_readability_band(bg)
    draw = ImageDraw.Draw(img, 'RGBA')

    if global_frame_num < 3:
        a = int(110 * (1 - global_frame_num / 3))
        flash = Image.new('RGBA', (W, H), (255, 255, 255, a))
        img = Image.alpha_composite(img.convert('RGBA'), flash).convert('RGB')
        draw = ImageDraw.Draw(img, 'RGBA')

    t = global_frame_num / fps

    if t < outro_start:
        # Karaoke: signature + narration (subject carried by the punchy hook, no static title card)
        if caption_groups:
            for g in caption_groups:
                if g[0]['start'] <= t < g[-1]['end']:
                    frame_in = int((t - g[0]['start']) * fps)
                    draw_karaoke_caption(draw, fonts, g, t, frame_in, int(H * 0.56), accent2)
                    break
    else:
        # Clear spoken outro
        draw_outro_card(draw, fonts, t - outro_start, palette)

    draw_progress_bar(draw, global_frame_num, global_total_frames, accent2)
    return img.convert('RGB')


def generate_voiceover(text, output_path):
    """Expressive French voiceover via Edge TTS multilingual voices. Returns (success, word_timings)."""
    primary = random.choice(["fr-FR-RemyMultilingualNeural", "fr-FR-VivienneMultilingualNeural"])
    voice_order = [primary, "fr-FR-HenriNeural", "fr-FR-DeniseNeural"]

    for voice in voice_order:
        try:
            word_boundaries = []

            async def _generate():
                communicate = edge_tts.Communicate(text, voice, rate="+18%", pitch="+8Hz")
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

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                print(f"Edge TTS OK voice={voice}, words={len(word_boundaries)}")
                return True, word_boundaries
        except Exception as e:
            print(f"Edge TTS failed for {voice}: {e}")
            continue

    try:
        from gtts import gTTS
        gTTS(text=text, lang='fr', slow=False).save(output_path)
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
        TAIL = 0.8

        with tempfile.TemporaryDirectory() as tmpdir:
            narration = script.get('voix_off') or (
                f"{script.get('titre', '')}. {script.get('fait1', '')} {script.get('fait2', '')} "
                f"{script.get('fait3', '')} {script.get('conclusion', '')}"
            )
            # Main segment = signature + narration (karaoke) ; CTA is a separate spoken segment
            main_text = f"{SIGNATURE} {narration}"

            main_path = os.path.join(tmpdir, 'main.mp3')
            cta_path = os.path.join(tmpdir, 'cta.mp3')
            voice_path = os.path.join(tmpdir, 'voice.mp3')

            ok_main, wb_main = generate_voiceover(main_text, main_path)
            dm = get_audio_duration(main_path) if ok_main else None

            ok_cta, _ = generate_voiceover(CTA_TEXT, cta_path)
            dc = get_audio_duration(cta_path) if ok_cta else None

            has_voice = False
            if ok_main and ok_cta and dc:
                # Concatenate main + CTA so the "abonne-toi" is actually spoken at the end
                concat_cmd = [
                    'ffmpeg', '-y', '-i', main_path, '-i', cta_path,
                    '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[a]',
                    '-map', '[a]', voice_path
                ]
                r = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and os.path.exists(voice_path) and os.path.getsize(voice_path) > 1000:
                    has_voice = True
                else:
                    voice_path = main_path
                    dc = 0
                    has_voice = True
            elif ok_main:
                voice_path = main_path
                dc = 0
                has_voice = True

            if has_voice and dm and dm > 3:
                words = words_with_timing(wb_main, main_text, dm)
                caption_groups = group_words(words, words_per_group=3)
                outro_start = dm
                total_duration = dm + (dc or 1.6) + TAIL
            else:
                caption_groups = []
                outro_start = 18.0
                total_duration = 22.0

            n_micro_sections = 8
            section_duration = total_duration / n_micro_sections
            total_frames = int(total_duration * fps)

            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)

            bgs = []
            for key in ['image1', 'image2', 'image3', 'image4']:
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

            micro_to_img = [0, 1, 2, 3, 0, 1, 2, 3]

            for frame_num in range(total_frames):
                t_sec = frame_num / fps
                section_idx = min(int(t_sec / section_duration), n_micro_sections - 1)
                bg = bgs[micro_to_img[section_idx]]
                local_frame_num = frame_num - int(section_idx * section_duration * fps)
                local_motion_seed = motion_seed + section_idx * 1.7

                frame = create_frame(
                    bg, local_frame_num, int(section_duration * fps),
                    palette, local_motion_seed,
                    caption_groups=caption_groups, outro_start=outro_start,
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

            output_path = os.path.join(tmpdir, 'final.mp4')
            music_path = download_music(tmpdir)
            mixed_ok = False
            fade_start = max(0.1, total_duration - 1.0)
            dur_str = f"{total_duration:.2f}"

            if has_voice and music_path:
                flt = (
                    f"[2:a]volume=0.10[m];[1:a]volume=1.0[v];"
                    f"[v][m]amix=inputs=2:duration=longest:dropout_transition=2[mix];"
                    f"[mix]afade=t=out:st={fade_start:.2f}:d=1.0[aout]"
                )
                mix_cmd = [
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-stream_loop', '-1', '-i', music_path,
                    '-filter_complex', flt, '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', dur_str, output_path
                ]
                mix_result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=120)
                mixed_ok = mix_result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000

            if not mixed_ok and has_voice:
                flt2 = f"[1:a]afade=t=out:st={fade_start:.2f}:d=1.0[aout]"
                simple_cmd = [
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-filter_complex', flt2, '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', dur_str, output_path
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
