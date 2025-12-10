from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from ocr_processor import process_image_ocr
import json

app = Flask(__name__)
CORS(app)  # 允許跨域請求

# 設置上傳檔案的存放目錄
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # 進行 OCR 處理
        try:
            ocr_result = process_image_ocr(filepath)
            return jsonify({
                'success': True,
                'filename': filename,
                'ocr_data': ocr_result
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/api/save_corrections', methods=['POST'])
def save_corrections():
    data = request.get_json()
    filename = data.get('filename')
    corrected_data = data.get('ocr_data')
    
    # 儲存校正結果到檔案
    output_path = f"corrected_{filename}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(corrected_data, f, ensure_ascii=False, indent=2)
    
    return jsonify({'success': True, 'message': '校正結果已保存'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True, port=5000)