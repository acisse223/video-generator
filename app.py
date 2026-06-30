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

app = Flask(__name__)
jobs = {}

def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)

def ease_out_elastic(t):
    if t == 0 or t == 1:
        return t
    c4 = (2 * math.pi) / 3
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1

def ease_out_cubic(t):
    return 1 - pow(1 - t, 3)

def create_dynamic_frame(bg_image, text_data, frame_num, total_frames, section, prev_bg=None, transition_frames=6):
    width, height = 720, 1280
    t = frame_num / max(total_frames - 1, 1)

    # Background with constant subtle shake + zoom for energy
    shake_x = int(3 * math.sin(frame_num * 0.8))
    shake_y = int(2 * math.cos(frame_num * 0.6))
    zoom = 1.08 + 0.04 * math.sin(frame_num * 0.15)

    if bg_image:
        bg = bg_image.copy()
        new_w = int(width * zoom)
        new_h = int(height * zoom)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - width) // 2 + shake_x
        top = (new_h - height) // 2 + shake_y
        left = max(0, min(left, new_w - width))
        top = max(0, min(top, new_h - height))
        bg = bg.crop((left, top, left + width, top + height))
        enhancer = ImageEnhance.Brightness(bg)
        bg = enhancer.enhance(0.5)
        enhancer = ImageEnhance.Color(bg)
        bg = enhancer.enhance(1.3)
        enhancer = ImageEnhance.Contrast(bg)
        bg = enhancer.enhance(1.15)
    else:
        bg = Image.new('RGB', (width, height), (15, 10, 30))

    img = bg.convert('RGBA')

    # Flash transition at start of section
    if frame_num < transition_frames:
        flash_t = 1 - (frame_num / transition_frames)
        flash_alpha = int(255 * flash_t * flash_t)
        flash_color = random.choice([(255, 255, 255), (255, 50, 100), (255, 220, 0)])
        flash = Image.new('RGBA', (width, height), (*flash_color, flash_alpha))
        img = Image.alpha_composite(img, flash)

    # Bottom gradient for text readability
    gradient = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(height // 3, height):
        alpha = int(190 * ((y - height // 3) / (height - height // 3)))
        gd.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, gradient)
    img = img.convert('RGB')
    draw = ImageDraw.Draw(img)

    try:
        f_huge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        f_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        f_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        f_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        f_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except:
        f_huge = f_title = f_body = f_small = f_tag = ImageFont.load_default()

    # Animated rotating speed lines (always present, subtle)
    cx, cy = width // 2, 200
    for angle in range(0, 360, 20):
        rad = math.radians(angle + frame_num * 3)
        length = 150 + 30 * math.sin(math.radians(frame_num * 10 + angle))
        x2 = cx + int(math.cos(rad) * length)
        y2 = cy + int(math.sin(rad) * length)
        alpha_line = int(40 + 20 * math.sin(frame_num * 0.3))
        draw.line([(cx, cy), (x2, y2)], fill=(255, 220, 100), width=2)

    # Entry animation: pop + bounce (first 10 frames of section)
    pop_progress = min(1.0, frame_num / 10)
    pop_scale = ease_out_back(pop_progress)
    entry_offset_y = int((1 - min(1, frame_num / 8)) * 60)

    # Floating particles for energy
    for i in range(8):
        px = (i * 90 + frame_num * 4) % width
        py = int(100 + 200 * math.sin(frame_num * 0.1 + i * 2))
        psize = 3 + int(2 * math.sin(frame_num * 0.2 + i))
        draw.ellipse([(px, py), (px + psize, py + psize)], fill=(255, 220, 100, 150))

    if section == 'titre':
        # Pulsing badge
        pulse = 1 + 0.1 * math.sin(frame_num * 0.4)
        badge_w = int(220 * pulse)
        draw.rounded_rectangle([(40, 60 - entry_offset_y), (40 + badge_w, 110 - entry_offset_y)],
                                radius=25, fill=(255, 50, 100))
        draw.text((58, 70 - entry_offset_y), "⚡ LE SAVIEZ-VOUS ?", font=f_tag, fill=(255, 255, 255))

        titre = text_data.get('titre', '')
        wrapped = textwrap.fill(titre, width=18)
        title_y = 140 - entry_offset_y

        # Vibrating shadow for energy
        vibrate = int(2 * math.sin(frame_num * 0.5))
        draw.text((54 + vibrate, title_y + 4), wrapped, font=f_huge, fill=(255, 50, 100))
        draw.text((50, title_y), wrapped, font=f_huge, fill=(255, 240, 50))

        lines_count = len(wrapped.split('\n'))
        line_y = title_y + lines_count * 82 + 30
        line_w = int((width - 100) * pop_scale)
        draw.rounded_rectangle([(50, line_y), (50 + max(0, line_w), line_y + 8)], radius=4, fill=(255, 50, 100))

        # Bottom hook text
        draw.text((50, height - 180), "Tu ne vas pas y croire... ⬇", font=f_body, fill=(255, 255, 255))

    elif section == 'fait':
        num = text_data.get('num', '1')
        colors = [(255, 50, 100), (50, 150, 255), (50, 220, 130)]
        badge_color = colors[int(num) - 1] if num.isdigit() and int(num) <= 3 else colors[0]

        # Bouncy number badge
        badge_size = int(90 * pop_scale)
        bx, by = 50, 70 - entry_offset_y
        draw.ellipse([(bx, by), (bx + badge_size, by + badge_size)], fill=badge_color)
        draw.text((bx + badge_size//2 - 18, by + badge_size//2 - 25), num, font=f_title, fill=(255, 255, 255))

        # "FAIT" label next to badge
        draw.text((bx + badge_size + 20, by + 20), f"FAIT #{num}", font=f_body, fill=(255, 255, 255))

        fact = text_data.get('fact', '')
        wrapped = textwrap.fill(fact, width=26)
        fact_y = 200 - entry_offset_y
        lines = wrapped.split('\n')
        box_h = len(lines) * 54 + 50

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        box_alpha = int(180 * min(1, pop_progress * 2))
        od.rounded_rectangle([(30, fact_y - 25), (690, fact_y + box_h)], radius=25, fill=(10, 10, 20, box_alpha))
        od.rounded_rectangle([(30, fact_y - 25), (690, fact_y + box_h)], radius=25, outline=badge_color, width=4)
        img2 = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        img.paste(img2)
        draw = ImageDraw.Draw(img)

        draw.text((54, fact_y + 4), wrapped, font=f_body, fill=(0, 0, 0))
        draw.text((50, fact_y), wrapped, font=f_body, fill=(255, 255, 255))

        # Progress dots
        dots_y = height - 120
        for i in range(3):
            dot_x = width // 2 - 60 + i * 60
            is_active = (i == int(num) - 1)
            dot_color = badge_color if is_active else (100, 100, 100)
            dot_r = 12 if is_active else 8
            draw.ellipse([(dot_x - dot_r, dots_y - dot_r), (dot_x + dot_r, dots_y + dot_r)], fill=dot_color)

    elif section == 'conclusion':
        # Spinning stars
        for i, base_angle in enumerate([0, 120, 240]):
            angle = base_angle + frame_num * 5
            rad = math.radians(angle)
            sx = 360 + int(200 * math.cos(rad))
            sy = 100 + int(30 * math.sin(rad))
            star_size = 1 + 0.3 * math.sin(frame_num * 0.3 + i)
            draw.text((sx, sy - entry_offset_y), "★", font=f_title, fill=(255, 220, 50))

        conclusion = text_data.get('conclusion', '')
        wrapped = textwrap.fill(conclusion, width=24)
        conc_y = 180 - entry_offset_y
        lines = wrapped.split('\n')
        box_h = len(lines) * 60 + 50

        scale = pop_scale
        box_margin = int(30 + (1 - min(1, scale)) * 100)

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rounded_rectangle([(box_margin, conc_y - 25), (width - box_margin, conc_y + box_h)],
                              radius=25, fill=(255, 50, 100, 220))
        img2 = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        img.paste(img2)
        draw = ImageDraw.Draw(img)

        draw.text((box_margin + 24, conc_y + 4), wrapped, font=f_title, fill=(0, 0, 0))
        draw.text((box_margin + 20, conc_y), wrapped, font=f_title, fill=(255, 255, 255))

        hashtags = text_data.get('hashtags', '')
        draw.text((50, conc_y + box_h + 30), hashtags[:42], font=f_small, fill=(180, 220, 255))

        # Pulsing CTA button
        cta_pulse = 1 + 0.08 * math.sin(frame_num * 0.5)
        cta_y = height - 150
        cta_w = int(600 * cta_pulse)
        cta_x = (width - cta_w) // 2
        draw.rounded_rectangle([(cta_x, cta_y), (cta_x + cta_w, cta_y + 80)], radius=40, fill=(255, 220, 0))
        draw.text((cta_x + 60, cta_y + 22), "🔥 ABONNE-TOI VITE ! 🔥", font=f_body, fill=(20, 20, 20))

    return img.convert('RGB')


def generate_video_async(job_id, script, images_b64):
    jobs[job_id]['status'] = 'processing'
    try:
        fps = 24
        # Faster sections for more dynamic pacing
        sections_config = [
            ('titre', {'titre': script.get('titre', '')}, images_b64.get('image1'), 4.5),
            ('fait', {'fact': script.get('fait1', ''), 'num': '1'}, images_b64.get('image1'), 5.5),
            ('fait', {'fact': script.get('fait2', ''), 'num': '2'}, images_b64.get('image2'), 5.5),
            ('fait', {'fact': script.get('fait3', ''), 'num': '3'}, images_b64.get('image3'), 5.5),
            ('conclusion', {
                'conclusion': script.get('conclusion', ''),
                'hashtags': script.get('hashtags', '')
            }, images_b64.get('image3'), 6),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)
            frame_count = 0

            for section_name, text_data, img_b64, duration in sections_config:
                bg = None
                if img_b64:
                    try:
                        img_data = base64.b64decode(img_b64)
                        img_path = os.path.join(tmpdir, f'bg_{frame_count}.jpg')
                        with open(img_path, 'wb') as f:
                            f.write(img_data)
                        bg = Image.open(img_path).convert('RGB').resize((720, 1280), Image.LANCZOS)
                    except Exception as e:
                        print(f"Image load error: {e}")

                total_section_frames = int(fps * duration)
                for i in range(total_section_frames):
                    frame = create_dynamic_frame(bg, text_data, i, total_section_frames, section_name)
                    frame.save(os.path.join(frames_dir, f'frame_{frame_count:05d}.png'))
                    frame_count += 1

            output_path = os.path.join(tmpdir, 'video.mp4')
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%05d.png'),
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '26',
                '-pix_fmt', 'yuv420p',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = result.stderr[-500:]
                return

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
