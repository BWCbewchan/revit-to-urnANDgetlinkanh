import os
import base64
import uuid
import requests
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient

app = Flask(__name__)

# Cấu hình thư mục tải lên
app.config['UPLOAD_FOLDER'] = 'uploads'

# Đảm bảo thư mục tải lên tồn tại
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Cấu hình Imgur
IMGUR_CLIENT_ID = 'f8b1f35e5690a24'
IMGUR_CLIENT_SECRET = '59213a42ba249f295354daf2f2f12a980dc009e6'

client_id = '8nDGPR55nVA4GWG46L7kayavng4osxT1V2HGAOMBCRQH692R'
client_secret = 'jyxdCnzmGoSz7tQSLo1OAgGGSIwuy2zUg5rbAMzLNpyyR62Innx0vJnMLc0odAuI'

mongo_client = MongoClient('mongodb+srv://ngophuc2911:phuc29112003@cluster0.buhheri.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
db = mongo_client['test']

def get_access_token():
    auth_url = 'https://developer.api.autodesk.com/authentication/v1/authenticate'
    auth_data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials',
        'scope': 'data:read data:write data:create bucket:create bucket:read'
    }
    response = requests.post(auth_url, data=auth_data, timeout=10)
    response.raise_for_status()
    return response.json().get('access_token')

def create_bucket(access_token):
    bucket_key = f'bucket_{uuid.uuid4()}'
    bucket_url = 'https://developer.api.autodesk.com/oss/v2/buckets'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    bucket_data = {
        'bucketKey': bucket_key,
        'policyKey': 'transient'
    }
    response = requests.post(bucket_url, headers=headers, json=bucket_data, timeout=10)
    response.raise_for_status()
    return bucket_key

def translate_file(access_token, bucket_key, object_name):
    urn = base64.urlsafe_b64encode(f'urn:adsk.objects:os.object:{bucket_key}/{object_name}'.encode()).decode().strip('=')
    translate_url = 'https://developer.api.autodesk.com/modelderivative/v2/designdata/job'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    translate_data = {
        'input': {
            'urn': urn
        },
        'output': {
            'formats': [
                {
                    'type': 'svf',
                    'views': ['2d', '3d']
                }
            ]
        }
    }
    response = requests.post(translate_url, headers=headers, json=translate_data, timeout=10)
    response.raise_for_status()
    return urn

def upload_to_imgur(image_file):
    headers = {
        'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'
    }
    files = {
        'image': image_file.read()
    }
    response = requests.post('https://api.imgur.com/3/upload', headers=headers, files=files)
    response_data = response.json()
    if response_data['success']:
        return response_data['data']['link']
    else:
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/collections', methods=['GET'])
def get_collections():
    collections = db.list_collection_names()
    return jsonify(collections)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'rvtFile' not in request.files or 'imageFile' not in request.files:
        return jsonify({'message': 'No file part'})

    rvt_file = request.files['rvtFile']
    image_file = request.files['imageFile']
    name = request.form.get('name')
    location = request.form.get('location')
    collection_name = request.form.get('collection')

    if rvt_file.filename == '':
        return jsonify({'message': 'No selected RVT file'})

    if not rvt_file.filename.endswith('.rvt'):
        return jsonify({'message': 'File type not allowed, please upload a .rvt file'})

    if image_file.filename == '':
        return jsonify({'message': 'No selected image file'})

    if not collection_name:
        return jsonify({'message': 'No collection name provided'})

    rvt_filename = rvt_file.filename
    rvt_file_path = os.path.join(app.config['UPLOAD_FOLDER'], rvt_filename)
    rvt_file.save(rvt_file_path)

    try:
        access_token = get_access_token()
        bucket_key = create_bucket(access_token)

        upload_url = f'https://developer.api.autodesk.com/oss/v2/buckets/{bucket_key}/objects/{rvt_filename}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/octet-stream'
        }

        with open(rvt_file_path, 'rb') as file_data:
            response = requests.put(upload_url, headers=headers, data=file_data, timeout=60)
            response.raise_for_status()

        urn = translate_file(access_token, bucket_key, rvt_filename)

        # Upload ảnh lên Imgur
        image_url = upload_to_imgur(image_file)
        if not image_url:
            return jsonify({'message': 'Image upload failed'}), 500

        selected_collection = db[collection_name]
        doc = {
            'name': name,
            'location': location,
            'urn': urn,
            'filename': rvt_filename,
            'linkanh': image_url
        }
        selected_collection.insert_one(doc)

        return jsonify({'urn': urn, 'image_url': image_url})

    except Exception as e:
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
