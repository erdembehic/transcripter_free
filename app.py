from flask import Flask, request, Response, send_file, render_template, jsonify
import os
import uuid
from transcriber import run_vosk_and_stream_progress

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    option = request.form['option']
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}_{file.filename}"
    upload_path = os.path.join("uploads", filename)
    os.makedirs("uploads", exist_ok=True)
    file.save(upload_path)
    return jsonify({"filename": filename, "language": option})

@app.route('/progress')
def progress():
    filename = request.args.get("file")
    language = request.args.get("lang")
    video_path = os.path.join("uploads", filename)
    return Response(run_vosk_and_stream_progress(video_path, language, stream=True), mimetype='text/event-stream')

@app.route('/download')
def download():
    filename = request.args.get("file")
    if not filename:
        return "file parametresi gerekli", 400
    output_path = os.path.join("output", filename)
    if not os.path.exists(output_path):
        return "Dosya henüz hazır değil", 404
    return send_file(output_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
