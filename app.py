from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import base64
import threading
import uuid
import time
import math
import random
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import textwrap

app = Flask(__name__)

# In-memory job storage
jobs = {}

MANGA_BACKGROUNDS = [
    "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=720&h=1280&fit=crop",
]

def download_image(url, path):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        return True
    except:
        return False

def ease_in_out(t):
    return t * t * (3 - 2 * t)

def draw_text_with_shadow(draw, pos, text, font, color, shadow_color=(0,0,0), offset=3):
    x, y = pos
    draw.text((x+offset, y+offset), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=color)

def create_animated_frame(script, frame_num, total_frames, bg_img=None):
    width, height = 720, 1280
    fps = 24
    t = frame_num / total_frames  # 0.0 to 1.0

    # Base background
    if bg_img:
        img = bg_img.copy().resize((width, height))
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.3)
    else:
        img = Image.new('RGB', (width, height), (10, 10, 20))

    draw = ImageDraw.Draw(img)

    # Load fonts
    try:
        f_huge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
        f_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
        f_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        f_huge = f_title = f_body = f_small = ImageFont.load_default()

    # Animated speed lines (always visible, rotating)
    cx, cy = width // 2, height // 2
    angle_offset = frame_num * 2
    for angle in range(0, 360, 12):
        rad = math.radians(angle + angle_offset)
        length = 800 + 100 * math.sin(math.radians(frame_num * 5 + angle))
        x_end = cx + int(math.cos(rad) * length)
        y_end = cy + int(math.sin(rad) * length)
        alpha = int(15 + 10 * math.sin(math.radians(frame_num * 3)))
        draw.line([(cx, cy), (x_end, y_end)], fill=(80, 80, 120), width=1)

    # Animated border pulse
    pulse = int(4 + 4 * math.sin(math.radians(frame_num * 8)))
    draw.rectangle([(pulse, pulse), (width-pulse, height-pulse)], outline=(255, 220, 0), width=pulse)
    draw.rectangle([(pulse+12, pulse+12), (width-pulse-12, height-pulse-12)], outline=(255, 255, 255), width=2)

    # PHASE 1: Title intro (0-20%)
    if t < 0.20:
        phase_t = t / 0.20
        eased = ease_in_out(phase_t)

        # Flash effect at start
        if phase_t < 0.15:
            flash_alpha = int(255 * (1 - phase_t / 0.15))
            flash = Image.new('RGBA', (width, height), (255, 255, 255, flash_alpha))
            img = img.convert('RGBA')
            img = Image.alpha_composite(img, flash)
            img = img.convert('RGB')
            draw = ImageDraw.Draw(img)

        # Impact lines
        for i in range(20):
            angle = random.randint(0, 360)
            rad = math.radians(angle)
            x1 = cx + int(math.cos(rad) * 50)
            y1 = cy + int(math.sin(rad) * 50)
            x2 = cx + int(math.cos(rad) * (200 + random.randint(0, 300)))
            y2 = cy + int(math.sin(rad) * (200 + random.randint(0, 300)))
            draw.line([(x1, y1), (x2, y2)], fill=(255, 220, 0), width=2)

        # Title slides in from top
        title = script.get('titre', 'LE SAVIEZ-VOUS ?')
        wrapped = textwrap.fill(title, width=18)
        slide_y = int(-200 + eased * 320)

        # Title box
        box_y1 = slide_y
        box_y2 = slide_y + 280
        draw.rectangle([(30, box_y1), (width-30, box_y2)], fill=(0, 0, 0))
        draw.rectangle([(30, box_y1), (width-30, box_y2)], outline=(255, 220, 0), width=6)
        draw_text_with_shadow(draw, (50, box_y1 + 20), wrapped, f_title, (255, 255, 255))

        # Exclamation animated
        exc_scale = int(50 + 40 * math.sin(math.radians(frame_num * 15)))
        draw_text_with_shadow(draw, (30, height - 200), "!", f_huge, (255, 50, 50))
        draw_text_with_shadow(draw, (width - 100, height - 200), "!", f_huge, (255, 220, 0))

    # PHASE 2: Fact 1 slides in (20-45%)
    elif t < 0.45:
        phase_t = (t - 0.20) / 0.25
        eased = ease_in_out(phase_t)

        # Header
        header_w = int(eased * (width - 60))
        draw.rectangle([(30, 60), (30 + header_w, 120)], fill=(255, 50, 50))
        if eased > 0.5:
            draw_text_with_shadow(draw, (50, 70), "FAIT #1", f_body, (255, 255, 255))

        # Fact box slides from right
        box_x = int(width + 50 - eased * (width + 50 - 30))
        fact1 = script.get('fait1', '')
        wrapped = textwrap.fill(fact1, width=26)
        lines = wrapped.split('\n')
        box_h = len(lines) * 52 + 60

        draw.rectangle([(box_x, 140), (box_x + width - 60, 140 + box_h)], fill=(0, 0, 0))
        draw.rectangle([(box_x, 140), (box_x + width - 60, 140 + box_h)], outline=(255, 255, 255), width=3)

        if eased > 0.3:
            char_reveal = int((eased - 0.3) / 0.7 * len(fact1))
            revealed_text = textwrap.fill(fact1[:char_reveal], width=26)
            draw_text_with_shadow(draw, (box_x + 20, 160), revealed_text, f_body, (255, 255, 255))

        # Bouncing arrow
        arrow_y = int(140 + box_h + 40 + 20 * math.sin(math.radians(frame_num * 10)))
        draw_text_with_shadow(draw, (cx - 20, arrow_y), "▼", f_title, (255, 220, 0))

    # PHASE 3: Fact 2 slides in (45-70%)
    elif t < 0.70:
        phase_t = (t - 0.45) / 0.25
        eased = ease_in_out(phase_t)

        header_w = int(eased * (width - 60))
        draw.rectangle([(30, 60), (30 + header_w, 120)], fill=(50, 100, 255))
        if eased > 0.5:
            draw_text_with_shadow(draw, (50, 70), "FAIT #2", f_body, (255, 255, 255))

        # Slides from left this time
        box_x = int(-width + eased * (width - 30))
        fact2 = script.get('fait2', '')
        wrapped = textwrap.fill(fact2, width=26)
        lines = wrapped.split('\n')
        box_h = len(lines) * 52 + 60

        draw.rectangle([(box_x, 140), (box_x + width - 60, 140 + box_h)], fill=(0, 0, 30))
        draw.rectangle([(box_x, 140), (box_x + width - 60, 140 + box_h)], outline=(50, 100, 255), width=3)

        if eased > 0.3:
            char_reveal = int((eased - 0.3) / 0.7 * len(fact2))
            revealed_text = textwrap.fill(fact2[:char_reveal], width=26)
            draw_text_with_shadow(draw, (box_x + 20, 160), revealed_text, f_body, (200, 220, 255))

        arrow_y = int(140 + box_h + 40 + 20 * math.sin(math.radians(frame_num * 10)))
        draw_text_with_shadow(draw, (cx - 20, arrow_y), "▼", f_title, (255, 220, 0))

    # PHASE 4: Conclusion zoom in (70-90%)
    elif t < 0.90:
        phase_t = (t - 0.70) / 0.20
        eased = ease_in_out(phase_t)

        # Zoom effect on conclusion box
        box_margin = int(30 + (1 - eased) * 200)
        draw.rectangle([(box_margin, 80), (width - box_margin, 900)], fill=(0, 0, 0))
        draw.rectangle([(box_margin, 80), (width - box_margin, 900)], outline=(255, 220, 0), width=6)

        conclusion = script.get('conclusion', '')
        if eased > 0.2:
            alpha_text = min(1.0, (eased - 0.2) / 0.8)
            wrapped = textwrap.fill(conclusion, width=22)
            draw_text_with_shadow(draw, (box_margin + 20, 120), wrapped, f_body, (255, 220, 0))

        # Pulsing stars
        for i in range(5):
            star_x = 60 + i * 120
            star_y = int(920 + 15 * math.sin(math.radians(frame_num * 8 + i * 72)))
            draw_text_with_shadow(draw, (star_x, star_y), "★", f_body, (255, 220, 0))

    # PHASE 5: Call to action (90-100%)
    else:
        phase_t = (t - 0.90) / 0.10
        eased = ease_in_out(phase_t)

        conclusion = script.get('conclusion', '')
        wrapped = textwrap.fill(conclusion, width=22)
        draw.rectangle([(30, 80), (width-30, 500)], fill=(0, 0, 0))
        draw.rectangle([(30, 80), (width-30, 500)], outline=(255, 220, 0), width=4)
        draw_text_with_shadow(draw, (50, 100), wrapped, f_body, (255, 220, 0))

        # CTA pulsing
        cta_scale = 1 + 0.05 * math.sin(math.radians(frame_num * 12))
        cta_y = int(height - 300 + 10 * math.sin(math.radians(frame_num * 8)))
        draw.rectangle([(30, cta_y), (width-30, cta_y + 100)], fill=(255, 50, 50))
        draw.rectangle([(30, cta_y), (width-30, cta_y + 100)], outline=(255, 255, 255), width=3)
        draw_text_with_shadow(draw, (50, cta_y + 20), "SUIVEZ POUR PLUS ! 🔥", f_body, (255, 255, 255))

        hashtags = script.get('hashtags', '')
        draw_text_with_shadow(draw, (40, height - 140), hashtags[:40], f_small, (150, 200, 255))

    return img.convert('RGB')


def generate_video_async(job_id, script):
    jobs[job_id]['status'] = 'processing'

    try:
        fps = 24
        duration = 30
        total_frames = fps * duration

        with tempfile.TemporaryDirectory() as tmpdir:
            # Try background image
            bg_path = os.path.join(tmpdir, 'bg.jpg')
            bg_img = None
            if download_image(random.choice(MANGA_BACKGROUNDS), bg_path):
                try:
                    bg_img = Image.open(bg_path).convert('RGB')
                except:
                    bg_img = None

            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)

            for i in range(total_frames):
                frame = create_animated_frame(script, i, total_frames, bg_img)
                frame.save(os.path.join(frames_dir, f'frame_{i:04d}.png'))

            output_path = os.path.join(tmpdir, 'video.mp4')

            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%04d.png'),
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '26',
                '-pix_fmt', 'yuv420p',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = result.stderr[-300:]
                return

            with open(output_path, 'rb') as f:
                video_base64 = base64.b64encode(f.read()).decode('utf-8')

            jobs[job_id]['status'] = 'done'
            jobs[job_id]['video_base64'] = video_base64
            jobs[job_id]['filename'] = f"video_{script.get('date', 'today')}.mp4"

    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@app.route('/generate-video', methods=['POST'])
def generate_video():
    data = request.json
    script = data.get('script', {})

    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'queued', 'created_at': time.time()}

    thread = threading.Thread(target=generate_video_async, args=(job_id, script))
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
        return jsonify({'status': 'error', 'error': job.get('error', 'Unknown error')}), 500
    else:
        return jsonify({'status': job['status']})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
