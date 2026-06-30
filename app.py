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
from gtts import gTTS

app = Flask(__name__)
jobs = {}

W, H = 720, 1280

PALETTE = [
    {"accent": (255, 56, 100), "accent2": (255, 200, 0), "name": "fire"},
    {"accent": (0, 220, 255), "accent2": (255, 0, 200), "name": "cyber"},
    {"accent": (130, 60, 255), "accent2": (0, 255, 170), "name": "purple"},
]

# Free royalty-free background music (Pixabay CDN, no copyright)
MUSIC_TRACKS = [
    "https://cdn.pixabay.com/audio/2024/03/05/audio_d0c6ff1bab.mp3",
    "https://cdn.pixabay.com/audio/2023/11/24/audio_7b3f4b1e2c.mp3",
    "https://cdn.pixabay.com/audio/2022/10/25/audio_946bc4f4a4.mp3",
]


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_out_expo(t):
    return 1 if t == 1 else 1 - pow(2, -10 * t)


def load_fonts():
    base = "/usr/share/fonts/truetype/dejavu/"
    return {
        'mega': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 84),
        'huge': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 60),
        'title': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 46),
        'body': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 38),
        'small': ImageFont.truetype(base + "DejaVuSans.ttf", 28),
        'tag': ImageFont.truetype(base + "DejaVuSans-Bold.ttf", 26),
    }


def prep_background(bg_image, frame_num, total_frames, motion_seed=0):
    """Ken Burns style zoom/pan + color grade + vignette."""
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
    zoom_start = 1.12
    zoom_end = 1.28
    zoom = zoom_start + (zoom_end - zoom_start) * t

    new_w, new_h = int(W * zoom), int(H * zoom)
    img = bg_image.resize((new_w, new_h), Image.LANCZOS)

    pan_x = math.sin(motion_seed) * 40
    pan_y = math.cos(motion_seed) * 30
    left = int((new_w - W) / 2 + pan_x * t)
    top = int((new_h - H) / 2 + pan_y * t)
    left = max(0, min(left, new_w - W))
    top = max(0, min(top, new_h - H))
    img = img.crop((left, top, left + W, top + H))

    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Brightness(img).enhance(0.62)

    return img


def add_vignette(img):
    vignette = Image.new('L', (W, H), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-W*0.3, -H*0.3, W*1.3, H*1.3], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(150))
    black = Image.new('RGB', (W, H), (0, 0, 0))
    img = Image.composite(img, black, vignette)
    return img


def draw_bottom_gradient(img, strength=210):
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    start_y = int(H * 0.30)
    for y in range(start_y, H):
        alpha = int(strength * ((y - start_y) / (H - start_y)) ** 1.3)
        gd.line([(0, y), (W, y)], fill=(5, 0, 15, alpha))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def draw_top_gradient(img, strength=140):
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    end_y = int(H * 0.30)
    for y in range(0, end_y):
        alpha = int(strength * (1 - y / end_y))
        gd.line([(0, y), (W, y)], fill=(5, 0, 15, alpha))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def draw_glow_text(draw, pos, text, font, fill, glow_color, glow_radius=3):
    x, y = pos
    for dx in range(-glow_radius, glow_radius + 1):
        for dy in range(-glow_radius, glow_radius + 1):
            if dx * dx + dy * dy <= glow_radius * glow_radius:
                draw.text((x + dx, y + dy), text, font=font, fill=(*glow_color, 40))
    draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def draw_particles(draw, frame_num, color, count=14):
    for i in range(count):
        seed = i * 137.5
        px = int((seed * 7 + frame_num * 3) % W)
        py = int((seed * 13 + frame_num * 2) % H)
        size = 2 + int(3 * abs(math.sin(frame_num * 0.05 + i)))
        alpha_mult = 0.3 + 0.4 * abs(math.sin(frame_num * 0.08 + i * 2))
        c = (*color, int(180 * alpha_mult))
        draw.ellipse([(px, py), (px + size, py + size)], fill=c)


def draw_speed_lines(draw, frame_num, cx, cy, color):
    for angle in range(0, 360, 18):
        rad = math.radians(angle + frame_num * 2.5)
        length = 120 + 50 * math.sin(math.radians(frame_num * 8 + angle))
        x2 = cx + int(math.cos(rad) * length)
        y2 = cy + int(math.sin(rad) * length)
        draw.line([(cx, cy), (x2, y2)], fill=(*color, 55), width=2)


def create_frame(bg_image, text_data, frame_num, total_frames, section, palette, motion_seed):
    fonts = load_fonts()
    accent = palette['accent']
    accent2 = palette['accent2']

    bg = prep_background(bg_image, frame_num, total_frames, motion_seed)
    img = bg.convert('RGBA')

    overlay = Image.new('RGBA', (W, H), (*accent, 18))
    img = Image.alpha_composite(img, overlay)
    img = img.convert('RGB')

    img = draw_bottom_gradient(img)
    img = draw_top_gradient(img)
    img = add_vignette(img)
    draw = ImageDraw.Draw(img, 'RGBA')

    pop_t = min(1.0, frame_num / 9)
    pop_scale = ease_out_back(pop_t)
    slide = int((1 - ease_out_expo(min(1, frame_num / 7))) * 90)

    draw_particles(draw, frame_num, accent2, count=16)

    if frame_num < 5:
        flash_alpha = int(180 * (1 - frame_num / 5) ** 2)
        flash = Image.new('RGBA', (W, H), (*accent, flash_alpha))
        img = Image.alpha_composite(img.convert('RGBA'), flash).convert('RGB')
        draw = ImageDraw.Draw(img, 'RGBA')

    bracket_len = 50
    bw = 5
    corners = [(20, 20, 1, 1), (W - 20, 20, -1, 1), (20, H - 20, 1, -1), (W - 20, H - 20, -1, -1)]
    for cxp, cyp, sx, sy in corners:
        draw.line([(cxp, cyp), (cxp + sx * bracket_len, cyp)], fill=(*accent, 220), width=bw)
        draw.line([(cxp, cyp), (cxp, cyp + sy * bracket_len)], fill=(*accent, 220), width=bw)

    if section == 'titre':
        draw_speed_lines(draw, frame_num, W // 2, 240, accent2)

        badge_w = int(260 * pop_scale)
        bx, by = 40, 70 - slide
        draw.rounded_rectangle([(bx, by), (bx + badge_w, by + 56)], radius=28, fill=accent)
        if pop_t > 0.4:
            draw.text((bx + 22, by + 13), "⚡ FAIT CHOC", font=fonts['tag'], fill=(255, 255, 255))

        titre = text_data.get('titre', '')
        wrapped = textwrap.fill(titre, width=15)
        title_y = 160 - slide

        for i, line in enumerate(wrapped.split('\n')):
            line_y = title_y + i * 96
            draw_glow_text(draw, (44, line_y), line, fonts['mega'], (255, 255, 255), accent2, glow_radius=2)

        lines_n = len(wrapped.split('\n'))
        line_y = title_y + lines_n * 96 + 20
        bar_w = int((W - 88) * pop_scale)
        draw.rounded_rectangle([(44, line_y), (44 + bar_w, line_y + 10)], radius=5, fill=accent2)

        if frame_num > total_frames * 0.5:
            hook_alpha = min(255, int((frame_num - total_frames * 0.5) / (total_frames * 0.3) * 255))
            hook_text = "Regarde jusqu'au bout 👀"
            draw.text((44, H - 140), hook_text, font=fonts['body'], fill=(255, 255, 255, hook_alpha))

    elif section == 'fait':
        num = text_data.get('num', '1')
        idx = int(num) - 1 if num.isdigit() else 0

        draw_speed_lines(draw, frame_num, 100, 130, accent2)

        badge_size = int(100 * pop_scale)
        bx, by = 40, 60 - slide
        draw.ellipse([(bx, by), (bx + badge_size, by + badge_size)], fill=accent, outline=(255, 255, 255), width=4)
        draw.text((bx + badge_size // 2 - 16, by + badge_size // 2 - 28), num, font=fonts['huge'], fill=(255, 255, 255))

        draw.rounded_rectangle([(bx + badge_size + 16, by + 22), (bx + badge_size + 240, by + 70)], radius=24, fill=(0, 0, 0, 180))
        draw.text((bx + badge_size + 34, by + 30), f"FAIT N°{num}", font=fonts['tag'], fill=accent2)

        fact = text_data.get('fact', '')
        wrapped = textwrap.fill(fact, width=23)
        fact_y = 220 - slide
        lines = wrapped.split('\n')
        box_h = len(lines) * 58 + 56

        box_alpha = int(195 * min(1, pop_t * 1.6))
        draw.rounded_rectangle([(36, fact_y - 28), (W - 36, fact_y - 28 + box_h)], radius=28, fill=(8, 5, 18, box_alpha))
        draw.rounded_rectangle([(36, fact_y - 28), (W - 36, fact_y - 28 + box_h)], radius=28, outline=accent, width=3)

        for i, line in enumerate(lines):
            draw_glow_text(draw, (60, fact_y + i * 58), line, fonts['body'], (255, 255, 255), accent, glow_radius=1)

        dots_y = H - 100
        for i in range(3):
            dot_x = W // 2 - 56 + i * 56
            active = (i == idx)
            r = 13 if active else 8
            color = accent if active else (90, 90, 100)
            draw.ellipse([(dot_x - r, dots_y - r), (dot_x + r, dots_y + r)], fill=color)
            if active:
                draw.ellipse([(dot_x - r - 5, dots_y - r - 5), (dot_x + r + 5, dots_y + r + 5)], outline=accent2, width=2)

    elif section == 'conclusion':
        for i, base_angle in enumerate([20, 140, 260]):
            angle = base_angle + frame_num * 4
            rad = math.radians(angle)
            sx = W // 2 + int(220 * math.cos(rad))
            sy = 90 + int(40 * math.sin(rad))
            draw.text((sx, sy - slide), "✦", font=fonts['title'], fill=accent2)

        conclusion = text_data.get('conclusion', '')
        wrapped = textwrap.fill(conclusion, width=21)
        conc_y = 190 - slide
        lines = wrapped.split('\n')
        box_h = len(lines) * 64 + 60

        margin = int(36 + (1 - pop_scale) * 120)
        draw.rounded_rectangle([(margin, conc_y - 30), (W - margin, conc_y - 30 + box_h)], radius=30,
                                fill=(*accent, 235))

        for i, line in enumerate(lines):
            draw.text((margin + 28, conc_y + i * 64), line, font=fonts['title'], fill=(255, 255, 255))

        hashtags = text_data.get('hashtags', '')
        draw.text((44, conc_y + box_h + 24), hashtags[:42], font=fonts['small'], fill=(*accent2, 255))

        pulse = 1 + 0.07 * math.sin(frame_num * 0.45)
        cta_w = int(620 * pulse)
        cta_x = (W - cta_w) // 2
        cta_y = H - 150
        draw.rounded_rectangle([(cta_x, cta_y), (cta_x + cta_w, cta_y + 84)], radius=42, fill=accent2)
        draw.text((cta_x + 50, cta_y + 22), "🔥 ABONNE-TOI VITE ! 🔥", font=fonts['body'], fill=(10, 10, 15))

    return img.convert('RGB')


def generate_voiceover(text, output_path):
    """Generate French voiceover using free Google TTS."""
    try:
        tts = gTTS(text=text, lang='fr', slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        print(f"TTS error: {e}")
        return False


def get_audio_duration(audio_path):
    """Get duration of an audio file using ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception:
        return None


def download_music(tmpdir):
    """Try to download a background music track, return path or None."""
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
            # 1. Generate voiceover from the full narration text
            voix_off_text = script.get('voix_off') or (
                f"{script.get('titre', '')}. {script.get('fait1', '')} {script.get('fait2', '')} "
                f"{script.get('fait3', '')} {script.get('conclusion', '')}"
            )
            voice_path = os.path.join(tmpdir, 'voice.mp3')
            has_voice = generate_voiceover(voix_off_text, voice_path)
            voice_duration = get_audio_duration(voice_path) if has_voice else None

            # 2. Compute section durations: scale to match voiceover length if available
            base_durations = [4.5, 5.5, 5.5, 5.5, 6.5]  # titre, fait1, fait2, fait3, conclusion
            base_total = sum(base_durations)

            if voice_duration and voice_duration > 3:
                target_total = max(voice_duration + 1.5, 18)  # pad a little so voice finishes within video
                scale = target_total / base_total
                durations = [d * scale for d in base_durations]
            else:
                durations = base_durations

            sections_config = [
                ('titre', {'titre': script.get('titre', '')}, images_b64.get('image1'), durations[0]),
                ('fait', {'fact': script.get('fait1', ''), 'num': '1'}, images_b64.get('image1'), durations[1]),
                ('fait', {'fact': script.get('fait2', ''), 'num': '2'}, images_b64.get('image2'), durations[2]),
                ('fait', {'fact': script.get('fait3', ''), 'num': '3'}, images_b64.get('image3'), durations[3]),
                ('conclusion', {
                    'conclusion': script.get('conclusion', ''),
                    'hashtags': script.get('hashtags', '')
                }, images_b64.get('image3'), durations[4]),
            ]

            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)
            frame_count = 0

            for section_name, text_data, img_b64, duration in sections_config:
                bg = None
                if img_b64 and len(img_b64) > 100:
                    try:
                        img_data = base64.b64decode(img_b64)
                        img_path = os.path.join(tmpdir, f'bg_{frame_count}.jpg')
                        with open(img_path, 'wb') as f:
                            f.write(img_data)
                        bg = Image.open(img_path).convert('RGB')
                    except Exception as e:
                        print(f"Image load error: {e}")
                        bg = None

                total_section_frames = int(fps * duration)
                for i in range(total_section_frames):
                    frame = create_frame(bg, text_data, i, total_section_frames, section_name, palette, motion_seed)
                    frame.save(os.path.join(frames_dir, f'frame_{frame_count:05d}.jpg'), quality=88)
                    frame_count += 1

            silent_video_path = os.path.join(tmpdir, 'silent_video.mp4')
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%05d.jpg'),
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                silent_video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)
            if result.returncode != 0:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = result.stderr[-500:]
                return

            # 3. Mix audio: voiceover (loud, centered) + background music (quiet, looped)
            output_path = os.path.join(tmpdir, 'video.mp4')
            music_path = download_music(tmpdir)

            if has_voice and music_path:
                # Voice + ducked music mixed together
                mix_cmd = [
                    'ffmpeg', '-y',
                    '-i', silent_video_path,
                    '-i', voice_path,
                    '-stream_loop', '-1', '-i', music_path,
                    '-filter_complex',
                    '[2:a]volume=0.12[music];[1:a]volume=1.0[voice];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]',
                    '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-shortest',
                    output_path
                ]
                mix_result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=120)
                if mix_result.returncode != 0:
                    # Fallback: voice only
                    has_voice_only = True
                else:
                    has_voice_only = False
            else:
                has_voice_only = True

            if has_voice_only:
                if has_voice:
                    simple_cmd = [
                        'ffmpeg', '-y',
                        '-i', silent_video_path,
                        '-i', voice_path,
                        '-map', '0:v', '-map', '1:a',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                        '-shortest',
                        output_path
                    ]
                    subprocess.run(simple_cmd, capture_output=True, text=True, timeout=120)
                else:
                    # No audio at all, just use the silent video
                    output_path = silent_video_path

            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
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
            'status': 'done',
            'success': True,
            'video_base64': job['video_base64'],
            'filename': job['filename']
        })
    elif job['status'] == 'error':
        return jsonify({'status': 'error', 'error': job.get('error', 'Unknown')}), 500
    return jsonify({'status': job['status']})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
