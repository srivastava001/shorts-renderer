import os
import subprocess
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

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

    # Build an FFmpeg concat filter string dynamically to stream everything in memory
    # input 0..N-1 are videos, input N is the audio track
    inputs = []
    filter_complex = []
    
    for idx, url in enumerate(video_urls):
        inputs.extend(['-i', url])
        # Scale, crop, and set framerate for each video stream
        filter_complex.append(f"[{idx}:v]scale=-2:1280,crop=720:1280:(in_w-720)/2:0,fps=24[v{idx}]")

    # Add audio input last
    audio_idx = len(video_urls)
    inputs.extend(['-i', audio_url])

    # Concat video streams together
    v_concat_str = "".join([f"[v{i}]" for i in range(len(video_urls))])
    filter_complex.append(f"{v_concat_str}concat=n={len(video_urls)}:v=1:a=0[outv]")

    # Combine filter complex arguments
    full_filter = ";".join(filter_complex)

    cmd = [
        'ffmpeg', '-y',
        *inputs,
        '-filter_complex', full_filter,
        '-map', '[outv]',
        '-map', f'{audio_idx}:a',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '28',
        '-c:a', 'aac',
        '-shortest',
        '-f', 'mp4',
        '-movflags', 'frag_keyframe+empty_moov',
        'pipe:1'
    ]

    def generate():
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            process.terminate()
            process.wait()

    return Response(generate(), mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
