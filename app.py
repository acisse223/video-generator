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
import re

app = Flask(__name__)
jobs = {}

W, H = 720, 1280

SIGNATURE = "Tiens-toi bien, ça va te choquer !"
CTA_TEXT = "Abonne-toi pour plus de faits fous !"

PALETTE = [
    {"accent": (255, 56, 100), "accent2": (255, 220, 0)},
    {"accent": (0, 200, 255), "accent2": (0, 255, 170)},
    {"accent": (255, 90, 50), "accent2": (255, 225, 0)},
    {"accent": (140, 90, 255), "accent2": (0, 245, 255)},
]

MUSIC_TRACKS = [
    "https://cdn.pixabay.com/audio/2024/03/05/audio_d0c6ff1bab.mp3",
    "https://cdn.pixabay.com/audio/2023/11/24/audio_7b3f4b1e2c.mp3",
    "https://cdn.pixabay.com/audio/2022/10/25/audio_946bc4f4a4.mp3",
    "https://cdn.pixabay.com/audio/2024/01/16/audio_5a36b4570e.mp3",
    "https://cdn.pixabay.com/audio/2023/08/10/audio_94e657e549.mp3",
    "https://cdn.pixabay.com/audio/2023/10/30/audio_f4e185ae9b.mp3",
    "https://cdn.pixabay.com/audio/2024/02/14/audio_8e53359d0e.mp3",
    "https://cdn.pixabay.com/audio/2023/05/16/audio_482aba52e8.mp3",
    "https://cdn.pixabay.com/audio/2024/04/23/audio_e16e58d533.mp3",
    "https://cdn.pixabay.com/audio/2023/09/04/audio_8e942a6d73.mp3",
]

ALL_VOICES = [
    "fr-FR-RemyMultilingualNeural",
    "fr-FR-VivienneMultilingualNeural",
    "fr-FR-LucienMultilingualNeural",
    "fr-FR-HenriNeural",
    "fr-FR-DeniseNeural",
    "fr-BE-CharlineNeural",
    "fr-CA-AntoineNeural",
    "fr-CA-SylvieNeural",
    "fr-CH-FabriceNeural",
]

CROSSFADE_FRAMES = 6  # frames de fondu entre chaque section


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def load_fonts():
    mont = "/usr/share/fonts/truetype/montserrat/"
    deja = "/usr/share/fonts/truetype/dejavu/"
    # Prefer Montserrat (modern), fallback to DejaVu
    try:
        return {
            'caption': ImageFont.truetype(mont + "Montserrat-ExtraBold.ttf", 58),
            'caption_big': ImageFont.truetype(mont + "Montserrat-ExtraBold.ttf", 68),
            'outro': ImageFont.truetype(mont + "Montserrat-ExtraBold.ttf", 60),
            'small': ImageFont.truetype(mont + "Montserrat-Bold.ttf", 30),
        }
    except Exception:
        return {
            'caption': ImageFont.truetype(deja + "DejaVuSans-Bold.ttf", 58),
            'caption_big': ImageFont.truetype(deja + "DejaVuSans-Bold.ttf", 68),
            'outro': ImageFont.truetype(deja + "DejaVuSans-Bold.ttf", 60),
            'small': ImageFont.truetype(deja + "DejaVuSans-Bold.ttf", 30),
        }


def prep_background(bg_image, frame_num, total_frames, motion_seed=0):
    if bg_image is None:
        img = Image.new('RGB', (W, H), (12, 8, 28))
        d = ImageDraw.Draw(img)
        for y in range(H):
            d.line([(0, y), (W, y)], fill=(12 + int(28*(y/H)), 8 + int(12*(y/H)), 38 + int(40*(y/H))))
        return img

    t = frame_num / max(total_frames - 1, 1)
    zoom = 1.14 + 0.18 * t
    new_w, new_h = int(W * zoom), int(H * zoom)
    img = bg_image.resize((new_w, new_h), Image.LANCZOS)

    pan_x = math.sin(motion_seed) * 45
    pan_y = math.cos(motion_seed) * 35
    left = max(0, min(int((new_w - W) / 2 + pan_x * t), new_w - W))
    top = max(0, min(int((new_h - H) / 2 + pan_y * t), new_h - H))
    img = img.crop((left, top, left + W, top + H))

    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    return img


def caption_readability_band(img):
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(overlay)
    bt, bb = int(H * 0.30), int(H * 0.84)
    for y in range(bt, bb):
        alpha = int(125 * math.sin((y - bt) / (bb - bt) * math.pi))
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
    groups, i = [], 0
    while i < len(words):
        size = words_per_group if (len(groups) % 3 != 2) else 2
        chunk = words[i:i + size]
        if not chunk:
            break
        groups.append(chunk)
        i += size
    return groups


def draw_karaoke_caption(draw, fonts, group, t_sec, frame_in_group, base_y, highlight_color):
    """Karaoke captions with ZOOM on active word."""
    font = fonts['caption']
    font_big = fonts['caption_big']
    line_height = 70
    max_width = W - 100
    space_w = draw.textlength(' ', font=font)

    # Measure all words with normal font
    word_data = []
    for w in group:
        wt = w['text'].upper()
        active = (w['start'] <= t_sec < w['end'])
        f = font_big if active else font
        ww = draw.textlength(wt, font=f)
        word_data.append((w, wt, ww, f, active))

    # Greedy line-wrap
    lines = []
    cur, cur_w = [], 0.0
    for wd in word_data:
        w, wt, ww, f, active = wd
        add = ww if not cur else ww + space_w
        if cur and cur_w + add > max_width:
            lines.append((cur, cur_w))
            cur = [wd]
            cur_w = ww
        else:
            cur.append(wd)
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
        for (w, wt, ww, f, active) in line_words:
            color = highlight_color if active else (255, 255, 255)
            y_offset = -4 if active else 0  # active word shifts up slightly (zoom feel)
            draw_outlined_text(draw, int(x), int(y + y_offset), wt, f, color, outline_w=6)
            x += ww + space_w
        y += line_height


def draw_outro_card(draw, fonts, t_elapsed, palette):
    accent, accent2 = palette['accent'], palette['accent2']
    pop = ease_out_back(min(1.0, t_elapsed / 0.4))
    bounce = int((1 - pop) * 50)

    main = "ABONNE-TOI"
    of = fonts['outro']
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


def draw_progress_bar(draw, gfn, gtf, accent2):
    prog = gfn / max(gtf - 1, 1)
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
        if caption_groups:
            for g in caption_groups:
                if g[0]['start'] <= t < g[-1]['end']:
                    frame_in = int((t - g[0]['start']) * fps)
                    draw_karaoke_caption(draw, fonts, g, t, frame_in, int(H * 0.56), accent2)
                    break
    else:
        draw_outro_card(draw, fonts, t - outro_start, palette)

    draw_progress_bar(draw, global_frame_num, global_total_frames, accent2)
    return img.convert('RGB')


def crossfade_frames(frame_a, frame_b, alpha):
    """Blend two PIL images. alpha=0 => pure A, alpha=1 => pure B."""
    return Image.blend(frame_a, frame_b, alpha)


def add_ssml_breaks(text):
    """Insert short SSML pauses after sentences for more natural rhythm."""
    text = re.sub(r'\.(\s)', r'. <break time="350ms"/>\1', text)
    text = re.sub(r'\?(\s)', r'? <break time="400ms"/>\1', text)
    text = re.sub(r'!(\s)', r'! <break time="300ms"/>\1', text)
    return f"<speak>{text}</speak>"


def generate_sfx(tmpdir):
    """Generate simple transition sound effects using FFmpeg's built-in synthesizer."""
    sfx_paths = []
    # Whoosh (pink noise, bandpass, short)
    whoosh = os.path.join(tmpdir, 'sfx_whoosh.wav')
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i',
        'anoisesrc=d=0.25:c=pink:r=44100,highpass=f=2000,afade=t=in:st=0:d=0.08,afade=t=out:st=0.12:d=0.13',
        '-ar', '44100', whoosh
    ], capture_output=True, timeout=10)
    if os.path.exists(whoosh):
        sfx_paths.append(whoosh)

    # Impact (low sine burst)
    impact = os.path.join(tmpdir, 'sfx_impact.wav')
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i',
        'sine=frequency=65:duration=0.18,afade=t=out:st=0:d=0.18',
        '-ar', '44100', impact
    ], capture_output=True, timeout=10)
    if os.path.exists(impact):
        sfx_paths.append(impact)

    # Ding (high sine ping)
    ding = os.path.join(tmpdir, 'sfx_ding.wav')
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i',
        'sine=frequency=1200:duration=0.12,afade=t=out:st=0.02:d=0.10',
        '-ar', '44100', ding
    ], capture_output=True, timeout=10)
    if os.path.exists(ding):
        sfx_paths.append(ding)

    return sfx_paths


def generate_voiceover(text, output_path):
    """Expressive French voiceover with SSML pauses for natural rhythm."""
    primary = random.choice(ALL_VOICES)
    voice_order = [primary, "fr-FR-RemyMultilingualNeural", "fr-FR-HenriNeural"]

    ssml_text = add_ssml_breaks(text)

    for voice in voice_order:
        try:
            word_boundaries = []

            async def _generate():
                communicate = edge_tts.Communicate(ssml_text, voice, rate="+18%", pitch="+8Hz")
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
            # If SSML fails, retry without SSML
            if '<speak>' in ssml_text:
                ssml_text = text
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
            full_text = f"{SIGNATURE} {narration}"

            main_path = os.path.join(tmpdir, 'main.mp3')
            cta_path = os.path.join(tmpdir, 'cta.mp3')
            voice_path = os.path.join(tmpdir, 'voice.mp3')

            ok_main, wb_main = generate_voiceover(full_text, main_path)
            dm = get_audio_duration(main_path) if ok_main else None

            ok_cta, _ = generate_voiceover(CTA_TEXT, cta_path)
            dc = get_audio_duration(cta_path) if ok_cta else None

            has_voice = False
            if ok_main and ok_cta and dc:
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
                words = words_with_timing(wb_main, full_text, dm)
                n_sig = len(SIGNATURE.split())
                narration_words = words[n_sig:] if len(words) > n_sig else words
                caption_groups = group_words(narration_words, words_per_group=3)
                outro_start = dm
                total_duration = dm + (dc or 1.6) + TAIL
            else:
                caption_groups = []
                outro_start = 55.0
                total_duration = 62.0

            # Ensure minimum 61s for monetization
            if total_duration < 61:
                total_duration = 62.0

            n_micro_sections = 12
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

            micro_to_img = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]

            # Generate and save frames streaming (memory-efficient)
            # For crossfade: keep only the last frame of previous section
            prev_section_last_frame = None

            for section_idx in range(n_micro_sections):
                sec_start = int(section_idx * section_duration * fps)
                sec_end = int((section_idx + 1) * section_duration * fps)
                if section_idx == n_micro_sections - 1:
                    sec_end = total_frames
                bg = bgs[micro_to_img[section_idx]]
                local_motion_seed = motion_seed + section_idx * 1.7
                sec_len = sec_end - sec_start

                for i in range(sec_len):
                    gfn = sec_start + i
                    frame = create_frame(
                        bg, i, sec_len, palette, local_motion_seed,
                        caption_groups=caption_groups, outro_start=outro_start,
                        global_frame_num=gfn, global_total_frames=total_frames, fps=fps
                    )

                    # Crossfade: blend first few frames of this section with last frame of previous
                    if prev_section_last_frame is not None and i < CROSSFADE_FRAMES:
                        alpha = i / CROSSFADE_FRAMES
                        frame = Image.blend(prev_section_last_frame, frame, alpha)

                    # Remember last frame of this section for next crossfade
                    if i == sec_len - 1:
                        prev_section_last_frame = frame.copy()

                    frame.save(os.path.join(frames_dir, f'frame_{gfn:05d}.jpg'), quality=88)
                    frame = None  # free memory immediately

            silent_video_path = os.path.join(tmpdir, 'silent_video.mp4')
            cmd = [
                'ffmpeg', '-y', '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%05d.jpg'),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-pix_fmt', 'yuv420p', silent_video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = result.stderr[-500:]
                return

            # Generate SFX and compute transition timestamps
            sfx_paths = generate_sfx(tmpdir)
            transition_times = [section_duration * i for i in range(1, n_micro_sections)]

            output_path = os.path.join(tmpdir, 'final.mp4')
            music_path = download_music(tmpdir)
            mixed_ok = False
            fade_start = max(0.1, total_duration - 1.2)
            dur_str = f"{total_duration:.2f}"

            if has_voice and music_path and sfx_paths:
                # Build SFX overlay: place a random SFX at each transition point
                sfx_filter_inputs = ""
                sfx_filter_parts = []
                sfx_input_args = []
                for ti, tt in enumerate(transition_times[:8]):  # cap at 8 SFX to avoid filter complexity
                    sfx_file = random.choice(sfx_paths)
                    input_idx = 3 + ti
                    sfx_input_args.extend(['-i', sfx_file])
                    sfx_filter_parts.append(f"[{input_idx}:a]adelay={int(tt*1000)}|{int(tt*1000)},volume=0.5[sfx{ti}]")

                sfx_mix_inputs = ''.join(f'[sfx{i}]' for i in range(len(sfx_filter_parts)))
                if sfx_filter_parts:
                    sfx_merge = f"{sfx_mix_inputs}amix=inputs={len(sfx_filter_parts)}:normalize=0[sfxmix]"
                    flt = (
                        f"[2:a]volume=0.10[m];[1:a]volume=1.0[v];"
                        f"{';'.join(sfx_filter_parts)};{sfx_merge};"
                        f"[v][m]amix=inputs=2:duration=longest:dropout_transition=2[vm];"
                        f"[vm][sfxmix]amix=inputs=2:duration=first:normalize=0[premix];"
                        f"[premix]afade=t=out:st={fade_start:.2f}:d=1.2[aout]"
                    )
                    mix_cmd = [
                        'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                        '-stream_loop', '-1', '-i', music_path,
                    ] + sfx_input_args + [
                        '-filter_complex', flt, '-map', '0:v', '-map', '[aout]',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', dur_str, output_path
                    ]
                    mix_result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=180)
                    mixed_ok = mix_result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000
                    if not mixed_ok:
                        print(f"SFX mix failed: {mix_result.stderr[-300:]}")

            # Fallback: voice + music without SFX
            if not mixed_ok and has_voice and music_path:
                flt = (
                    f"[2:a]volume=0.10[m];[1:a]volume=1.0[v];"
                    f"[v][m]amix=inputs=2:duration=longest:dropout_transition=2[mix];"
                    f"[mix]afade=t=out:st={fade_start:.2f}:d=1.2[aout]"
                )
                mix_cmd = [
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-stream_loop', '-1', '-i', music_path,
                    '-filter_complex', flt, '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', dur_str, output_path
                ]
                mix_result = subprocess.run(mix_cmd, capture_output=True, text=True, timeout=120)
                mixed_ok = mix_result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000

            # Fallback: voice only
            if not mixed_ok and has_voice:
                flt2 = f"[1:a]afade=t=out:st={fade_start:.2f}:d=1.2[aout]"
                subprocess.run([
                    'ffmpeg', '-y', '-i', silent_video_path, '-i', voice_path,
                    '-filter_complex', flt2, '-map', '0:v', '-map', '[aout]',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', dur_str, output_path
                ], capture_output=True, text=True, timeout=120)
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
