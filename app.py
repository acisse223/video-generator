from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
import urllib.request
import json
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import textwrap

app = Flask(__name__)

MANGA_BACKGROUNDS = [
    "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1502318217862-aa4e294ba657?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=720&h=1280&fit=crop",
    "https://images.unsplash.com/photo-1518791841217-8f162f1912da?w=720&h=1280&fit=crop",
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

def create_manga_frame(script, frame_num, total_frames, bg_path=None):
    width, height = 720, 1280
    
    # Load or create background
    if bg_path and os.path.exists(bg_path):
        try:
            bg = Image.open(bg_path).convert('RGB').resize((width, height))
            # Apply manga/comic filter
            enhancer = ImageEnhance.Contrast(bg)
            bg = enhancer.enhance(1.5)
            enhancer = ImageEnhance.Sharpness(bg)
            bg = enhancer.enhance(2.0)
            # Convert to high contrast black and white manga style
            bg_gray = bg.convert('L')
            bg = bg_gray.convert('RGB')
            enhancer = ImageEnhance.Contrast(bg)
            bg = enhancer.enhance(2.0)
        except:
            bg = Image.new('RGB', (width, height), (20, 20, 30))
    else:
        bg = Image.new('RGB', (width, height), (20, 20, 30))
    
    img = bg.copy()
    draw = ImageDraw.Draw(img)
    
    # Add dark overlay for readability
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 140))
    img = img.convert('RGBA')
    img = Image.alpha_composite(img, overlay)
    img = img.convert('RGB')
    draw = ImageDraw.Draw(img)
    
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_big = ImageFont.load_default()

    progress = frame_num / max(total_frames - 1, 1)
    
    # Draw manga-style speed lines in corners
    import math
    center_x, center_y = width // 2, height // 2
    for angle in range(0, 360, 15):
        rad = math.radians(angle)
        x_end = center_x + int(math.cos(rad) * 800)
        y_end = center_y + int(math.sin(rad) * 1400)
        draw.line([(center_x, center_y), (x_end, y_end)], fill=(50, 50, 80, 30), width=1)

    # Animated border (manga panel style)
    border_color = (255, 220, 0)  # Yellow manga border
    border_width = 8
    draw.rectangle([(border_width, border_width), (width - border_width, height - border_width)], 
                   outline=border_color, width=border_width)
    
    # Inner border
    draw.rectangle([(20, 20), (width - 20, height - 20)], 
                   outline=(255, 255, 255), width=2)

    # Phase 1: Show title with animation (0-25%)
    if progress <= 0.25:
        phase_progress = progress / 0.25
        
        # Exclamation marks manga style
        draw.text((width//2 - 60, 80), "!", font=font_big, fill=(255, 50, 50))
        draw.text((width//2 + 10, 80), "!", font=font_big, fill=(255, 220, 0))
        
        # Title box
        draw.rectangle([(30, 220), (width - 30, 420)], fill=(0, 0, 0, 200))
        draw.rectangle([(30, 220), (width - 30, 420)], outline=(255, 220, 0), width=4)
        
        title = script.get('titre', 'FAIT DU JOUR')
        wrapped = textwrap.fill(title, width=20)
        
        # Shadow effect
        draw.text((54, 244), wrapped, font=font_title, fill=(255, 100, 0))
        draw.text((50, 240), wrapped, font=font_title, fill=(255, 255, 255))
        
        # "Le saviez-vous?" badge
        draw.rectangle([(30, 440), (340, 490)], fill=(255, 50, 50))
        draw.text((40, 448), "LE SAVIEZ-VOUS ?", font=font_small, fill=(255, 255, 255))

    # Phase 2: Show fact 1 (25-50%)
    elif progress <= 0.50:
        phase_progress = (progress - 0.25) / 0.25
        
        # Panel header
        draw.rectangle([(30, 60), (width - 30, 120)], fill=(255, 50, 50))
        draw.text((40, 70), "FAIT #1", font=font_body, fill=(255, 255, 255))
        
        # Fact box
        draw.rectangle([(30, 140), (width - 30, 700)], fill=(0, 0, 0))
        draw.rectangle([(30, 140), (width - 30, 700)], outline=(255, 255, 255), width=3)
        
        fact1 = script.get('fait1', '')
        wrapped = textwrap.fill(fact1, width=28)
        draw.text((50, 160), wrapped, font=font_body, fill=(255, 255, 255))
        
        # Animated arrow
        arrow_y = int(720 + phase_progress * 50)
        draw.text((width//2 - 20, arrow_y), "▼", font=font_title, fill=(255, 220, 0))

    # Phase 3: Show fact 2 (50-75%)
    elif progress <= 0.75:
        phase_progress = (progress - 0.50) / 0.25
        
        draw.rectangle([(30, 60), (width - 30, 120)], fill=(50, 100, 255))
        draw.text((40, 70), "FAIT #2", font=font_body, fill=(255, 255, 255))
        
        draw.rectangle([(30, 140), (width - 30, 700)], fill=(0, 0, 0))
        draw.rectangle([(30, 140), (width - 30, 700)], outline=(255, 255, 255), width=3)
        
        fact2 = script.get('fait2', '')
        wrapped = textwrap.fill(fact2, width=28)
        draw.text((50, 160), wrapped, font=font_body, fill=(255, 255, 255))
        
        arrow_y = int(720 + phase_progress * 50)
        draw.text((width//2 - 20, arrow_y), "▼", font=font_title, fill=(255, 220, 0))

    # Phase 4: Show conclusion (75-100%)
    else:
        draw.rectangle([(30, 60), (width - 30, 120)], fill=(255, 220, 0))
        draw.text((40, 70), "CONCLUSION", font=font_body, fill=(0, 0, 0))
        
        draw.rectangle([(30, 140), (width - 30, 800)], fill=(0, 0, 0))
        draw.rectangle([(30, 140), (width - 30, 800)], outline=(255, 220, 0), width=4)
        
        conclusion = script.get('conclusion', '')
        wrapped = textwrap.fill(conclusion, width=26)
        draw.text((50, 160), wrapped, font=font_body, fill=(255, 220, 0))
        
        # Follow badge
        draw.rectangle([(30, 1100), (width - 30, 1180)], fill=(255, 50, 50))
        draw.text((50, 1115), "SUIVEZ POUR PLUS ! 🔥", font=font_body, fill=(255, 255, 255))

    # Frame counter (manga style)
    draw.text((width - 80, height - 60), f"{frame_num+1}", font=font_small, fill=(150, 150, 150))
    
    return img

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/generate-video', methods=['POST'])
def generate_video():
    try:
        data = request.json
        script = data.get('script', {})
        
        fps = 12
        duration = 30
        total_frames = fps * duration

        with tempfile.TemporaryDirectory() as tmpdir:
            # Try to download a background image
            bg_path = os.path.join(tmpdir, 'bg.jpg')
            bg_downloaded = False
            import random
            bg_url = random.choice(MANGA_BACKGROUNDS)
            bg_downloaded = download_image(bg_url, bg_path)
            
            # Generate frames
            frames_dir = os.path.join(tmpdir, 'frames')
            os.makedirs(frames_dir)
            
            for i in range(total_frames):
                frame = create_manga_frame(
                    script, i, total_frames,
                    bg_path if bg_downloaded else None
                )
                frame_path = os.path.join(frames_dir, f'frame_{i:04d}.png')
                frame.save(frame_path, 'PNG')
            
            output_path = os.path.join(tmpdir, 'video.mp4')
            
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%04d.png'),
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '28',
                '-pix_fmt', 'yuv420p',
                '-vf', f'scale=720:1280',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            
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
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
