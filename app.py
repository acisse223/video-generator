from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
from PIL import Image, ImageDraw, ImageFont
import textwrap

app = Flask(__name__)

def create_text_image(script):
    width, height = 720, 1280
    img = Image.new('RGB', (width, height), (15, 15, 25))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Accent line
    draw.rectangle([(50, 130), (670, 138)], fill=(100, 100, 255))

    # Title
    title = script.get('titre', 'Fait du Jour')
    wrapped_title = textwrap.fill(title, width=22)
    draw.text((50, 150), wrapped_title, font=font_title, fill=(255, 220, 50))

    # Facts
    y_pos = 380
    facts = [script.get('fait1', ''), script.get('fait2', ''), script.get('fait3', '')]
    for fact in facts:
        if fact:
            wrapped = textwrap.fill(fact, width=35)
            draw.text((50, y_pos), "▶ " + wrapped, font=font_body, fill=(255, 255, 255))
            lines = len(wrapped.split('\n'))
            y_pos += lines * 42 + 30

    # Conclusion
    conclusion = script.get('conclusion', '')
    if conclusion and y_pos < 1100:
        draw.rectangle([(40, y_pos + 10), (680, y_pos + 14)], fill=(100, 100, 255))
        wrapped_c = textwrap.fill(conclusion, width=38)
        draw.text((50, y_pos + 30), wrapped_c, font=font_small, fill=(200, 200, 255))

    # Watermark
    draw.text((50, 1220), "💡 Le Saviez-Vous ?", font=font_small, fill=(120, 120, 120))

    return img

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/generate-video', methods=['POST'])
def generate_video():
    try:
        data = request.json
        script = data.get('script', {})

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create image
            img = create_text_image(script)
            img_path = os.path.join(tmpdir, 'bg.png')
            img.save(img_path)

            output_path = os.path.join(tmpdir, 'video.mp4')

            cmd = [
                'ffmpeg', '-y',
                '-loop', '1',
                '-i', img_path,
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '28',
                '-t', '10',
                '-pix_fmt', 'yuv420p',
                '-vf', 'scale=720:1280',
                '-r', '10',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return jsonify({'error': result.stderr[-500:]}), 500

            with open(output_path, 'rb') as f:
                video_base64 = base64.b64encode(f.read()).decode('utf-8')

            date = script.get('date', 'today')
            return jsonify({
                'success': True,
                'video_base64': video_base64,
                'filename': f'video_{date}.mp4'
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
