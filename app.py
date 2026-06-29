from flask import Flask, request, jsonify
import subprocess
import os
import tempfile
import base64
import threading
import uuid
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont
import textwrap

app = Flask(__name__)
jobs = {}

# Free stock video URLs from Pixabay/Pexels (no copyright)
VIDEO_BACKGROUNDS = [
    "https://cdn.pixabay.com/video/2016/09/10/5157-182481175_tiny.mp4",
    "https://cdn.pixabay.com/video/2020/07/31/46283-447022791_tiny.mp4",
    "https://cdn.pixabay.com/video/2019/04/16/23013-330882541_tiny.mp4",
    "https://cdn.pixabay.com/video/2020/04/04/35305-405666370_tiny.mp4",
    "https://cdn.pixabay.com/video/2016/12/30/6962-197634410_tiny.mp4",
]

def download_file(url, path):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False

def generate_video_async(job_id, script):
    jobs[job_id]['status'] = 'processing'

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            date = script.get('date', 'today')
            output_path = os.path.join(tmpdir, f'video_{date}.mp4')
            bg_video_path = os.path.join(tmpdir, 'bg.mp4')
            looped_bg_path = os.path.join(tmpdir, 'bg_looped.mp4')
            subtitles_path = os.path.join(tmpdir, 'subtitles.srt')

            # Download background video
            import random
            bg_url = random.choice(VIDEO_BACKGROUNDS)
            bg_downloaded = download_file(bg_url, bg_video_path)

            duration = 30

            if bg_downloaded:
                # Loop background video to fill duration
                loop_cmd = [
                    'ffmpeg', '-y',
                    '-stream_loop', '-1',
                    '-i', bg_video_path,
                    '-t', str(duration),
                    '-vf', 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280',
                    '-c:v', 'libx264',
                    '-preset', 'ultrafast',
                    '-an',
                    looped_bg_path
                ]
                loop_result = subprocess.run(loop_cmd, capture_output=True, text=True, timeout=60)
                if loop_result.returncode != 0:
                    bg_downloaded = False

            if not bg_downloaded:
                # Create gradient background as fallback
                gradient_cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', f'color=c=0x0a0a1e:size=720x1280:duration={duration}:rate=24',
                    '-c:v', 'libx264',
                    '-preset', 'ultrafast',
                    looped_bg_path
                ]
                subprocess.run(gradient_cmd, capture_output=True, text=True, timeout=30)

            # Build subtitle content
            titre = script.get('titre', 'LE SAVIEZ-VOUS ?')
            fait1 = script.get('fait1', '')
            fait2 = script.get('fait2', '')
            fait3 = script.get('fait3', '')
            conclusion = script.get('conclusion', '')
            hashtags = script.get('hashtags', '')

            def wrap_text(text, width=35):
                return '\n'.join(textwrap.wrap(text, width=width))

            srt_content = f"""1
00:00:00,000 --> 00:00:03,000
{wrap_text(titre, 30)}

2
00:00:03,500 --> 00:00:09,000
{wrap_text(fait1, 38)}

3
00:00:09,500 --> 00:00:16,000
{wrap_text(fait2, 38)}

4
00:00:16,500 --> 00:00:23,000
{wrap_text(fait3, 38)}

5
00:00:23,500 --> 00:00:28,000
{wrap_text(conclusion, 38)}

6
00:00:28,000 --> 00:00:30,000
{hashtags[:50]}
"""
            with open(subtitles_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            # Burn subtitles with styling
            subtitle_filter = (
                f"subtitles={subtitles_path}:force_style='"
                "FontName=DejaVu Sans Bold,"
                "FontSize=22,"
                "PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,"
                "BackColour=&H80000000,"
                "Bold=1,"
                "Outline=2,"
                "Shadow=1,"
                "Alignment=2,"
                "MarginV=80'"
            )

            # Add dark overlay + subtitles
            vf_filter = f"[0:v]colormatrix=bt601:bt709,curves=all='0/0 0.5/0.35 1/0.7'[darkened];[darkened]{subtitle_filter}[out]"

            final_cmd = [
                'ffmpeg', '-y',
                '-i', looped_bg_path,
                '-filter_complex', vf_filter,
                '-map', '[out]',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '26',
                '-pix_fmt', 'yuv420p',
                '-t', str(duration),
                output_path
            ]

            result = subprocess.run(final_cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                # Fallback: simpler subtitle burn
                simple_cmd = [
                    'ffmpeg', '-y',
                    '-i', looped_bg_path,
                    '-vf', f"subtitles={subtitles_path}",
                    '-c:v', 'libx264',
                    '-preset', 'ultrafast',
                    '-crf', '26',
                    '-pix_fmt', 'yuv420p',
                    '-t', str(duration),
                    output_path
                ]
                result2 = subprocess.run(simple_cmd, capture_output=True, text=True, timeout=180)

                if result2.returncode != 0:
                    jobs[job_id]['status'] = 'error'
                    jobs[job_id]['error'] = result2.stderr[-500:]
                    return

            with open(output_path, 'rb') as f:
                video_base64 = base64.b64encode(f.read()).decode('utf-8')

            jobs[job_id]['status'] = 'done'
            jobs[job_id]['video_base64'] = video_base64
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
        return jsonify({'status': 'error', 'error': job.get('error', 'Unknown')}), 500
    else:
        return jsonify({'status': job['status']})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
