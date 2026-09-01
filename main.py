import os
import subprocess
import tempfile
import base64
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
    audio_input = data.get('audio_url', '')
    
    if not video_urls or not audio_input:
        return jsonify({"status": "error", "message": "Missing video_urls or audio_url"}), 400

    temp_files = []
    try:
        # Decode base64 audio data URI to a temp file to avoid command-line length limits
        if audio_input.startswith('data:'):
            header, encoded = audio_input.split(',', 1)
            audio_data = base64.b64decode(encoded)
            audio_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            audio_file.write(audio_data)
            audio_file.close()
            audio_path = audio_file.name
            temp_files.append(audio_path)
        else:
            audio_path = audio_input

        # Build clean command using local paths
        cmd = [
            'ffmpeg', '-y',
            '-i', video_urls[0],
            '-i', audio_path,
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
                for tf in temp_files:
                    if os.path.exists(tf):
                        os.remove(tf)

        return Response(generate(), mimetype='video/mp4')

    except Exception as e:
        for tf in temp_files:
            if os.path.exists(tf):
                os.remove(tf)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
