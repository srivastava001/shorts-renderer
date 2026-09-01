import os
import base64
import uuid
import requests
from flask import Flask, request, jsonify, send_file
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
from google import genai

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "shorts-renderer"}), 200

@app.route('/render-short', methods=['POST'])
def render_short():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"status": "error", "message": "GEMINI_API_KEY environment variable is missing on Render"}), 500
        
    client = genai.Client(api_key=api_key)

    data = request.json or {}
    video_urls = data.get('video_urls', [])
    audio_url = data.get('audio_url', '')
    
    if not video_urls or not audio_url:
        return jsonify({"status": "error", "message": "Missing video_urls or audio_url"}), 400

    job_id = str(uuid.uuid4())[:8]
    downloaded_clips = []
    v_paths = []
    a_path = f"/tmp/{job_id}_a.mp3"
    output_path = f"/tmp/{job_id}_final.mp4"
    
    try:
        # Step A: Download & Crop Videos to Vertical 720x1280 (RAM-Optimized for Render Free Tier)
        for idx, url in enumerate(video_urls):
            v_path = f"/tmp/{job_id}_v_{idx}.mp4"
            v_paths.append(v_path)
            r = requests.get(url, stream=True)
            with open(v_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            clip = VideoFileClip(v_path).resized(height=1280)
            clip = clip.cropped(x_center=clip.w / 2, width=720)
            downloaded_clips.append(clip)

        # Step B: Handle Audio
        if audio_url.startswith("data:audio") or ";base64," in audio_url:
            base64_data = audio_url.split(";base64,")[-1]
            with open(a_path, 'wb') as f:
                f.write(base64.b64decode(base64_data))
        else:
            r_audio = requests.get(audio_url, stream=True)
            with open(a_path, 'wb') as f:
                for chunk in r_audio.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
        
        audio_clip = AudioFileClip(a_path)

        # Step C: Concatenate Clips & Attach Audio
        base_video = concatenate_videoclips(downloaded_clips, method="compose")
        base_video = base_video.with_audio(audio_clip)

        # Step D: Transcribe via Gemini API using gemini-3.6-flash
        uploaded_audio = client.files.upload(file=a_path)
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[uploaded_audio, "Provide a clean transcript of the speech in this audio."]
        )
        
        text_content = response.text if response and response.text else ""
        words_list = text_content.split()
        
        subtitle_clips = []
        duration = audio_clip.duration
        time_per_word = duration / max(len(words_list), 1)

        for i, word in enumerate(words_list):
            start = i * time_per_word
            end = start + time_per_word
            txt_clip = (TextClip(text=word.upper(), font_size=50, color='yellow', font='Impact', stroke_color='black', stroke_width=3)
                        .with_position(('center', 950))
                        .with_start(start)
                        .with_duration(max(end - start, 0.1)))
            subtitle_clips.append(txt_clip)

        # Step E: Layer Captions & Export MP4 (fps=24 saves memory)
        final_video = CompositeVideoClip([base_video] + subtitle_clips)
        final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")

        # Explicitly close all clips to free up RAM
        for clip in downloaded_clips:
            clip.close()
        base_video.close()
        audio_clip.close()
        final_video.close()
        for txt in subtitle_clips:
            txt.close()

        return jsonify({
            "status": "success",
            "download_url": f"{request.host_url}download/{job_id}_final.mp4"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
    finally:
        # Clean up temporary files from disk
        for vp in v_paths:
            if os.path.exists(vp):
                os.remove(vp)
        if os.path.exists(a_path):
            os.remove(a_path)

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_file(f"/tmp/{filename}", as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
