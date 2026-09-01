import os
import base64
import uuid
import requests
from flask import Flask, request, jsonify, send_file
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
import whisper

app = Flask(__name__)

# Load the lightweight model to fit within 512MB RAM limits
model = whisper.load_model("tiny")

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "shorts-renderer"}), 200

@app.route('/render-short', methods=['POST'])
def render_short():
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
            
            clip = VideoFileClip(v_path).resize(height=1920)
            clip = clip.crop(x_center=clip.w / 2, width=1080)
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
        base_video = base_video.set_audio(audio_clip)

        # Step D: Transcribe Audio for Word Timestamps
        result = model.transcribe(a_path, word_timestamps=True)
        subtitle_clips = []

        for segment in result.get('segments', []):
            for word in segment.get('words', []):
                w_text = word['word'].strip().upper()
                start = word['start']
                end = word['end']
                
                txt_clip = (TextClip(w_text, fontsize=70, color='yellow', font='Impact', stroke_color='black', stroke_width=4)
                            .set_position(('center', 1400))
                            .set_start(start)
                            .set_duration(max(end - start, 0.1)))
                subtitle_clips.append(txt_clip)

        # Step E: Layer Captions & Export MP4
        final_video = CompositeVideoClip([base_video] + subtitle_clips)
        output_path = f"/tmp/{job_id}_final.mp4"
        final_video.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")

        # Cleanup memory resources
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
