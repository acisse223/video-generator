from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
import threading
import uuid
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import textwrap
import math

app = Flask(__name__)
jobs = {}

def download_image(url, path):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False

def create_styled_frame(bg_image, text_lines, frame_num, total_frames, section):
    width, height = 720, 1280
    
    # Load and process background
    if bg_image:
        try:
            bg = bg_image.copy().resize((width, height), Image.LANCZOS)
            # Subtle zoom animation
            zoom = 1.0 + 0.03 * (frame_num / total_frames)
            new_w = int(width * zoom)
            new_h = int(height * zoom)
            bg = bg.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - width) // 2
            top = (new_h - height) // 2
            bg = bg.crop((left, top, left + width, top + height))
            # Darken for readability
            enhancer = ImageEnhance.Brightness(bg)
            bg = enhancer.enhance(0.45)
        except:
            bg = Image.new('RGB', (width, height), (15, 15, 30))
    else:
        bg = Image.new('RGB', (width, height), (15, 15, 30))

    img = bg.convert('RGBA')

    # Gradient overlay at bottom for text readability
    gradient = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(height // 2, height):
        alpha = int(180 * ((y - height // 2) / (height // 2)))
        grad_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, gradient)
    img = img.convert('RGB')
    draw = ImageDraw.Draw(img)

    # Load fonts
    try:
        font_huge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 68)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        font_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except:
        font_huge = font_title = font_body = font_small = font_tag = ImageFont.load_default()

    # Animation progress
    t = frame_num / max(total_frames - 1, 1)
    
    # Slide-in animation
    slide_offset = max(0, int(80 * (1 - min(1, frame_num / 8))))

    if section == 'titre':
        # Top badge
        badge_y = 80 - slide_offset
        draw.rounded_rectangle([(40, badge_y), (220, badge_y + 46)], radius=23, fill=(255, 50, 100))
        draw.text((55, badge_y + 8), "LE SAVIEZ-VOUS ?", font=font_tag, fill=(255, 255, 255))

        # Title with shadow
        titre = text_lines.get('titre', '')
        wrapped = textwrap.fill(titre, width=20)
        title_y = 160 - slide_offset
        # Shadow
        draw.text((54, title_y + 4), wrapped, font=font_huge, fill=(0, 0, 0, 180))
        draw.text((52, title_y + 2), wrapped, font=font_huge, fill=(0, 0, 0, 120))
        # Main text
        draw.text((50, title_y), wrapped, font=font_huge, fill=(255, 240, 50))

        # Accent line
        line_y = title_y + len(wrapped.split('\n')) * 78 + 20
        pulse = int(3 + 2 * math.sin(frame_num * 0.3))
        draw.rounded_rectangle([(50, line_y), (670, line_y + pulse + 4)], radius=3, fill=(255, 50, 100))

    elif section == 'fait':
        # Fact number badge
        num = text_lines.get('num', '1')
        badge_color = [(255, 50, 100), (100, 100, 255), (50, 200, 100)][int(num) - 1] if num.isdigit() else (255, 50, 100)
        draw.ellipse([(30, 80 - slide_offset), (110, 160 - slide_offset)], fill=badge_color)
        draw.text((57, 100 - slide_offset), num, font=font_title, fill=(255, 255, 255))

        # Fact text
        fact = text_lines.get('fact', '')
        wrapped = textwrap.fill(fact, width=28)
        fact_y = 200 - slide_offset

        # Text background pill
        lines = wrapped.split('\n')
        box_h = len(lines) * 52 + 40
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle([(30, fact_y - 20), (690, fact_y + box_h)], radius=20, fill=(0, 0, 0, 160))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)

        # Shadow + text
        draw.text((54, fact_y + 4), wrapped, font=font_body, fill=(0, 0, 0))
        draw.text((52, fact_y + 2), wrapped, font=font_body, fill=(0, 0, 0))
        draw.text((50, fact_y), wrapped, font=font_body, fill=(255, 255, 255))

    elif section == 'conclusion':
        # Star icons
        for i, sx in enumerate([50, 120, 190]):
            pulse_y = int(5 * math.sin(frame_num * 0.2 + i))
            draw.text((sx, 80 + pulse_y - slide_offset), "★", font=font_body, fill=(255, 220, 50))

        # Conclusion box
        conclusion = text_lines.get('conclusion', '')
        wrapped = textwrap.fill(conclusion, width=26)
        conc_y = 160 - slide_offset
        lines = wrapped.split('\n')
        box_h = len(lines) * 58 + 50

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle([(30, conc_y - 25), (690, conc_y + box_h)], radius=20, fill=(255, 50, 100, 200))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)

        draw.text((54, conc_y + 4), wrapped, font=font_title, fill=(0, 0, 0))
        draw.text((50, conc_y), wrapped, font=font_title, fill=(255, 255, 255))

        # Hashtags
        hashtags = text_lines.get('hashtags', '')
        hash_y = conc_y + box_h + 20
        draw.text((50, hash_y), hashtags[:45], font=font_small, fill=(180, 220, 255))

        # CTA
        cta_y = height - 160
        draw.rounded_rectangle([(50, cta_y), (670, cta_y + 80)], radius=40, fill=(255, 50, 100))
        draw.text((160, cta_y + 18), "SUIVEZ POUR PLUS ! 🔥", font=font_body, fill=(255, 255, 255))

    return img.convert('RGB')


def generate_video_async(job_id, script, images_b64):
    jobs[job_id]['status'] = 'processing'
    try:
        fps = 24
        duration_per_section = 8
        sections = [
            ('titre', {'titre': script.get('titre', '')}, images_b64.get('image1')),
            ('fait', {'fact': script.get('fait1', ''), 'num': '1'}, images_b64.get('image1')),
            ('fait', {'fact': script.get('fait2', ''), 'num': '2'}, images_b64.get('image2')),
            ('fait', {'fact': script.get('fait3', ''), 'num': '3'}, images_b64.get('image3')),
            ('conclusion', {
                'conclusion': script.get('conclusion', ''),
                'hashtags': script.get('hashtags', '')
            }, images_b64.get('image3')),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)
            frame_count = 0

            for section_name, text_data, img_b64 in sections:
                # Load background image
                bg = None
                if img_b64:
                    try:
                        img_data = base64.b64decode(img_b64)
                        img_path = os.path.join(tmpdir, f'bg_{section_name}_{frame_count}.jpg')
                        with open(img_path, 'wb') as f:
                            f.write(img_data)
                        bg = Image.open(img_path).convert('RGB')
                    except Exception as e:
                        print(f"Image load error: {e}")

                total_section_frames = fps * duration_per_section
                for i in range(total_section_frames):
                    frame = create_styled_frame(bg, text_data, i, total_section_frames, section_name)
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
