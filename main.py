import os
import uuid
import subprocess
import requests
from flask import Flask, request, jsonify, send_file

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

    job_id = str(uuid.uuid4())[:8]
    v_paths = []
    a_path = f"/tmp/{job_id}_a.mp3"
    list_path = f"/tmp/{job_id}_list.txt"
    output_path = f"/tmp/{job_id}_final.mp4"
    
    try:
        processed_v_paths = []
        for idx, url in enumerate(video_urls):
            raw_v_path = f"/tmp/{job_id}_raw_{idx}.mp4"
            proc_v_path = f"/tmp/{job_id}_v_{idx}.mp4"
            v_paths.extend([raw_v_path, proc_v_path])
            
            r = requests.get(url, stream=True)
            with open(raw_v_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            cmd = [
                'ffmpeg', '-y', '-i', raw_v_path,
                '-vf', 'scale=-2:1280,crop=720:1280:(in_w-720)/2:0',
                '-r', '24', '-c:v', 'libx264', '-crf', '28', '-an', proc_v_path
            ]
            subprocess.run(cmd, check=True)
            processed_v_paths.append(proc_v_path)

        r_audio = requests.get(audio_url, stream=True)
        with open(a_path, 'wb') as f:
            for chunk in r_audio.iter_content(chunk_size=1024*1024):
                f.write(chunk)

        with open(list_path, 'w') as f:
            for vp in processed_v_paths:
                f.write(f"file '{vp}'\n")
        v_paths.append(list_path)

        concat_cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,
            '-i', a_path, '-c:v', 'copy', '-c:a', 'aac', '-shortest', output_path
        ]
        subprocess.run(concat_cmd, check=True)

        return jsonify({
            "status": "success",
            "download_url": f"{request.host_url}download/{job_id}_final.mp4"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
    finally:
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
