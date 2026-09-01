import os, requests, uuid
from flask import Flask, request, jsonify, send_file
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
import whisper

app = Flask(__name__)
model = whisper.load_model("base")

@app.route('/render-short', methods=['POST'])
def render_short():
    data = request.json
    video_urls = data.get('video_urls', [])
    audio_url = data.get('audio_url')
    
    job_id = str(uuid.uuid4())[:8]
    downloaded_clips = []
    
    try:
        for idx, url in enumerate(video_urls):
            v_path = f"/tmp/{job_id}_v_{idx}.mp4"
            r = requests.get(url, stream=True)
            with open(v_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            clip = VideoFileClip(v_path).resize(height=1920)
            clip = clip.crop(x_center=clip.w / 2, width=1080)
            downloaded_clips.append(clip)

        a_path = f"/tmp/{job_id}_a.mp3"
        r_audio = requests.get(audio_url, stream=True)
        with open(a_path, 'wb') as f:
            for chunk in r_audio.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        
        audio_clip = AudioFileClip(a_path)

        base_video = concatenate_videoclips(downloaded_clips, method="compose")
        base_video = base_video.set_audio(audio_clip)

        result = model.transcribe(a_path, word_timestamps=True)
        subtitle_clips = []

        for segment in result['segments']:
            for word in segment['words']:
                w_text = word['word'].strip().upper()
                start = word['start']
                end = word['end']
                
                txt_clip = (TextClip(w_text, fontsize=70, color='yellow', font='Impact', stroke_color='black', stroke_width=4)
                            .set_position(('center', 1400))
                            .set_start(start)
                            .set_duration(end - start))
                subtitle_clips.append(txt_clip)

        final_video = CompositeVideoClip([base_video] + subtitle_clips)
        
        output_path = f"/tmp/{job_id}_final.mp4"
        final_video.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac")

        return jsonify({
            "status": "success",
            "download_url": f"{request.host_url}download/{job_id}_final.mp4"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_file(f"/tmp/{filename}", as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
