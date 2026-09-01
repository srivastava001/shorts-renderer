import os
import subprocess
import tempfile
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

    # Create a temporary file to list inputs safely for FFmpeg concat demuxer
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for url in video_urls:
            f.write(f"file '{url}'\n")
        manifest_path = f.name

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', manifest_path,
        '-i', audio_url,
        '-filter_complex', '[0:v]scale=-2:1280,crop=720:1280:(in_w-720)/2:0,fps=24[outv]',
        '-map', '[outv]',
        '-map', '1:a',
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
            if os.path.exists(manifest_path):
                os.remove(manifest_path)

    return Response(generate(), mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
