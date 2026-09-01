import os
import subprocess
import tempfile
import base64
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

        # Reduced to 480p vertical with aggressive memory limits for Render's free tier
        cmd = [
            'ffmpeg', '-y',
            '-i', video_urls[0],
            '-i', audio_path,
            '-filter_complex', '[0:v]scale=-2:480,crop=270:480:(in_w-270)/2:0,fps=24[outv]',
            '-map', '[outv]',
            '-map', '1:a',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '32',
            '-maxrate', '600k',
            '-bufsize', '1200k',
            '-c:a', 'aac',
            '-b:a', '64k',
            '-shortest',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'
        ]

        def generate():
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                while True:
                    chunk = process.stdout.read(16384)
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
