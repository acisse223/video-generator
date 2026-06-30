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

WORD_COLORS = [
    (255, 255, 255),
    (255, 220, 0),
    (0, 230, 255),
    (255, 60, 130),
    (130, 255, 90),
    (255, 140, 0),
    (190, 100, 255),
]

PALETTE = [
    {"accent": (255, 56, 100), "accent2": (255, 200, 0), "name": "fire"},
    {"accent": (0, 220, 255), "accent2": (255, 0, 200), "name": "cyber"},
    {"accent": (130, 60, 255), "accent2": (0, 255, 170), "name": "purple"},
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
        'mega': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 76),
        'huge': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 58),
        'caption': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 50),
        'small': ImageFont.truetype(base + "DejaVuSans.ttf", 28),
        'tag': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 24),
    }


def prep_background(bg_image, frame_num, total_frames, motion_seed=0):
    if bg_image is None:
        img = Image.new('RGB', (W, H), (10, 5, 25))
        d = ImageDraw.Draw(img)
        for y in range(H):
            r = int(10 + 30 * (y / H))
            g = int(5 + 10 * (y / H))
            b = int(35 + 40 * (y / H))
            d.line([(0, y), (W, y)], fill=(r, g, b))
        return img

    t = frame_num / max(total_frames - 1, 1)
    zoom = 1.12 + 0.16 * t
    new_w, new_h = int(W * zoom), int(H * zoom)
    img = bg_image.resize((new_w, new_h), Image.LANCZOS)

    pan_x = math.sin(motion_seed) * 40
    pan_y = math.cos(motion_seed) * 30
    left = int((new_w - W) / 2 + pan_x * t)
    top = int((new_h - H) / 2 + pan_y * t)
    left = max(0, min(left, new_w - W))
    top = max(0, min(top, new_h - H))
    img = img.crop((left, top, left + W, top + H))

    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Brightness(img).enhance(1.0)
    return img


def add_subtle_grade(img):
    """Light, modern color grade instead of old-school dark vignette."""
    return img


def draw_particles(draw, frame_num, color, count=14):
    for i in range(count):
        seed = i * 137.5
        px = int((seed * 7 + frame_num * 3) % W)
        py = int((seed * 13 + frame_num * 2) % H)
        size = 2 + int(3 * abs(math.sin(frame_num * 0.05 + i)))
        alpha_mult = 0.25 + 0.35 * abs(math.sin(frame_num * 0.08 + i * 2))
        draw.ellipse([(px, py), (px + size, py + size)], fill=(*color, int(160 * alpha_mult)))


def draw_glow_word(draw, pos, text, font, fill, glow_radius=8):
    """Clean modern caption style: bold outline + drop shadow, crisp and punchy (no old-school halo glow)."""
    x, y = pos
    # Soft drop shadow for depth
    draw.text((x + 4, y + 6), text, font=font, fill=(0, 0, 0, 110))
    # Crisp black outline for contrast on any background
    outline_w = 5
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx*dx + dy*dy <= outline_w*outline_w and (dx != 0 or dy != 0):
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
    # Bright flat color core
    draw.text((x, y), text, font=font, fill=fill)


def draw_tiktok_caption(draw, fonts, caption_text, frame_in_caption, total_frames_caption, base_y, color_index):
    pop_t = min(1.0, frame_in_caption / 5)
    scale = ease_out_back(pop_t)

    color = WORD_COLORS[color_index % len(WORD_COLORS)]
    font = fonts['caption']

    wrapped = textwrap.fill(caption_text.upper(), width=18)
    lines = wrapped.split('\n')

    line_height = 64
    total_h = len(lines) * line_height

    y = base_y - total_h // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (W - line_w) // 2
        bounce_offset = int((1 - scale) * 40) if pop_t < 1 else 0
        draw_glow_word(draw, (x, y - bounce_offset), line, font, color)
        y += line_height


def create_frame(bg_image, text_data, frame_num, total_frames, section, palette, motion_seed,
                  caption_groups=None, caption_timings=None, global_frame_num=0, fps=24):
    fonts = load_fonts()
    accent2 = palette['accent2']

    # Clean bright background, no dark vignette, no old-film borders
    bg = prep_background(bg_image, frame_num, total_frames, motion_seed)
    img = bg.convert('RGB')
    draw = ImageDraw.Draw(img, 'RGBA')

    # Quick clean flash only on the very first frame of the whole video (not every section)
    if global_frame_num < 3:
        flash_alpha = int(120 * (1 - global_frame_num / 3))
        flash = Image.new('RGBA', (W, H), (255, 255, 255, flash_alpha))
        img = Image.alpha_composite(img.convert('RGBA'), flash).convert('RGB')
        draw = ImageDraw.Draw(img, 'RGBA')

    # Modern bold word-by-word captions, centered, big and clean (MrBeast/Hormozi style)
    if caption_groups and caption_timings:
        t_sec = global_frame_num / fps
        active_idx = None
        for idx, (start, end) in enumerate(caption_timings):
            if start <= t_sec < end:
                active_idx = idx
                break
        if active_idx is not None:
            cap_start, cap_end = caption_timings[active_idx]
            frame_in_caption = int((t_sec - cap_start) * fps)
            total_frames_caption = max(int((cap_end - cap_start) * fps), 1)
            draw_tiktok_caption(
                draw, fonts, caption_groups[active_idx],
                frame_in_caption, total_frames_caption,
                base_y=int(H * 0.62), color_index=active_idx
            )

    if section == 'conclusion':
        hashtags = text_data.get('hashtags', '')
        bbox = draw.textbbox((0, 0), hashtags[:42], font=fonts['small'])
        hx = (W - (bbox[2] - bbox[0])) // 2
        # Simple flat pill background, no glow/pulse gimmicks
        draw.rounded_rectangle([(hx - 16, H - 100), (hx + (bbox[2]-bbox[0]) + 16, H - 56)],
                                radius=18, fill=(0, 0, 0, 140))
        draw.text((hx, H - 92), hashtags[:42], font=fonts['small'], fill=(255, 255, 255))

    return img.convert('RGB')


def generate_voiceover(text, output_path):
    """Generate French voiceover using free Microsoft Edge TTS, returns (success, word_timings)."""
    try:
        voices = ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"]
        voice = random.choice(voices)
        word_boundaries = []

        async def _generate():
            communicate = edge_tts.Communicate(text, voice, rate="+25%", pitch="+8Hz")
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

        # Use a fresh event loop bound to this thread (threading.Thread workers
        # don't have a default event loop, which can break asyncio.run in some envs)
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


def build_caption_timeline(word_boundaries, full_text=None, voice_duration=None, words_per_group=3):
    if word_boundaries:
        groups_text = []
        groups_timing = []
        i = 0
        n = len(word_boundaries)
        while i < n:
            size = words_per_group if (len(groups_text) % 3 != 2) else 2
            chunk = word_boundaries[i:i + size]
            if not chunk:
                break
            text = ' '.join(w['text'] for w in chunk)
            start = chunk[0]['offset']
            end = chunk[-1]['offset'] + chunk[-1]['duration']
            groups_text.append(text)
            groups_timing.append((start, end))
            i += size
        return groups_text, groups_timing

    # Fallback: no word-level timing available from TTS, distribute evenly across voice_duration
    if full_text and voice_duration and voice_duration > 1:
        words = full_text.split()
        if not words:
            return [], []
        groups_text = []
        i = 0
        while i < len(words):
            size = words_per_group if (len(groups_text) % 3 != 2) else 2
            groups_text.append(' '.join(words[i:i + size]))
            i += size
        n_groups = len(groups_text)
        slot = voice_duration / n_groups
        groups_timing = [(idx * slot, (idx + 1) * slot) for idx in range(n_groups)]
        return groups_text, groups_timing

    return [], []


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

            caption_groups, caption_timings = build_caption_timeline(
                word_boundaries, full_text=voix_off_text, voice_duration=voice_duration, words_per_group=3
            )
            print(f"Caption groups built: {len(caption_groups)}")

            if voice_duration and voice_duration > 3:
                total_duration = voice_duration + 1.5
            else:
                total_duration = 25

            img_keys = ['image1', 'image2', 'image3']
            # Cycle through images more often for more visual variety (6 micro-sections instead of 3)
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

            # Map 6 micro-sections to the 3 background images: 1,2,3,1,2,3 (zoom direction alternates for variety)
            micro_to_img = [0, 1, 2, 0, 1, 2]
            section_names = ['titre', 'fait', 'fait', 'fait', 'fait', 'conclusion']

            for frame_num in range(total_frames):
                t_sec = frame_num / fps
                section_idx = min(int(t_sec / section_duration), n_micro_sections - 1)
                section_name = section_names[section_idx]
                bg = bgs[micro_to_img[section_idx]]
                local_frame_num = frame_num - int(section_idx * section_duration * fps)
                # Alternate motion seed per micro-section so the Ken Burns direction changes each time
                local_motion_seed = motion_seed + section_idx * 1.7

                frame = create_frame(
                    bg, {'hashtags': script.get('hashtags', '')},
                    local_frame_num, int(section_duration * fps), section_name,
                    palette, local_motion_seed,
                    caption_groups=caption_groups, caption_timings=caption_timings,
                    global_frame_num=frame_num, fps=fps
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
