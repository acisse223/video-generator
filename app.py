from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import base64
from PIL import Image, ImageDraw, ImageFont
import textwrap

app = Flask(__name__)

def create_text_image(text, width=1080, height=1920, bg_color=(15, 15, 25), text_color=(255, 255, 255)):
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Gradient background
    for i in range(height):
        r = int(15 + (i/height) * 20)
        g = int(15 + (i/height) * 10)
        b = int(25 + (i/height) * 30)
        draw.line([(0, i), (width, i)], fill=(r, g, b))
    
    # Try to use a font, fallback to default
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Draw accent line
    draw.rectangle([(80, 200), (1000, 210)], fill=(100, 100, 255))
    
    # Draw title
    title = text.get('titre', 'Fait du Jour')
    wrapped_title = textwrap.fill(title, width=20)
    draw.text((80, 230), wrapped_title, font=font_title, fill=(255, 220, 50))
    
    # Draw facts
    y_pos = 500
    facts = [text.get('fait1', ''), text.get('fait2', ''), text.get('fait3', '')]
    for i, fact in enumerate(facts):
        if fact:
            draw.text((80, y_pos), f"▶  ", font=font_body, fill=(100, 100, 255))
            wrapped = textwrap.fill(fact, width=28)
            draw.text((140, y_pos), wrapped, font=font_body, fill=(255, 255, 255))
            y_pos += len(wrapped.split('\n')) * 60 + 40
    
    # Draw conclusion
    conclusion = text.get('conclusion', '')
    if conclusion:
        draw.rectangle([(60, y_pos + 20), (1020, y_pos + 25)], fill=(100, 100, 255))
        wrapped_conclusion = textwrap.fill(conclusion, width=30)
        draw.text((80, y_pos + 50), wrapped_conclusion, font=font_small, fill=(200, 200, 255))
    
    # Draw watermark
    draw.text((80, 1820), "💡 Le Saviez-Vous ?", font=font_small, fill=(150, 150, 150))
    
    return img

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/generate-video', methods=['POST'])
def generate_video():
    try:
        data = request.json
        script = data.get('script', {})
        audio_base64 = data.get('audio_base64', '')
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save audio file
            audio_path = os.path.join(tmpdir, 'audio.mp3')
            if audio_base64:
                audio_data = base64.b64decode(audio_base64)
                with open(audio_path, 'wb') as f:
                    f.write(audio_data)
            
            # Create background image
            img = create_text_image(script)
            img_path = os.path.join(tmpdir, 'background.png')
            img.save(img_path)
            
            # Output video path
            output_path = os.path.join(tmpdir, 'video.mp4')
            
            # FFmpeg command
            if audio_base64 and os.path.exists(audio_path):
                cmd = [
                    'ffmpeg', '-y',
                    '-loop', '1',
                    '-i', img_path,
                    '-i', audio_path,
                    '-c:v', 'libx264',
                    '-tune', 'stillimage',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    '-pix_fmt', 'yuv420p',
                    '-shortest',
                    '-vf', 'scale=1080:1920',
                    output_path
                ]
            else:
                cmd = [
                    'ffmpeg', '-y',
                    '-loop', '1',
                    '-i', img_path,
                    '-c:v', 'libx264',
                    '-t', '30',
                    '-pix_fmt', 'yuv420p',
                    '-vf', 'scale=1080:1920',
                    output_path
                ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                return jsonify({'error': result.stderr}), 500
            
            # Return video as base64
            with open(output_path, 'rb') as f:
                video_base64 = base64.b64encode(f.read()).decode('utf-8')
            
            return jsonify({
                'success': True,
                'video_base64': video_base64,
                'filename': f"video_{script.get('date', 'today')}.mp4"
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
