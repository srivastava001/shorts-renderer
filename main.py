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
    
    try:
        # Step A: Download & Crop Videos to Vertical 9:16 (1080x1920)
        for idx, url in enumerate(video_urls):
            v_path = f"/tmp/{job_id}_v_{idx}.mp4"
            r = requests.get(url, stream=True)
            with open(v_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            clip = VideoFileClip(v_path).resized(height=1920)
            clip = clip.cropped(x_center=clip.w / 2, width=1080)
            downloaded_clips.append(clip)

        # Step B: Handle Audio (URL vs Base64 Data String)
        a_path = f"/tmp/{job_id}_a.mp3"
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

        # Step D: Transcribe via Gemini API
        uploaded_audio = client.files.upload(file=a_path)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
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
            txt_clip = (TextClip(text=word.upper(), font_size=70, color='yellow', font='Impact', stroke_color='black', stroke_width=4)
                        .with_position(('center', 1400))
                        .with_start(start)
                        .with_duration(max(end - start, 0.1)))
            subtitle_clips.append(txt_clip)

        # Step E: Layer Captions & Export MP4
        final_video = CompositeVideoClip([base_video] + subtitle_clips)
        output_path = f"/tmp/{job_id}_final.mp4"
        final_video.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")

        # Memory Cleanup
        base_video.close()
        audio_clip.close()

        return jsonify({
            "status": "success",
            "download_url": f"{request.host_url}download/{job_id}_final.mp4"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_file(f"/tmp/{filename}", as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
