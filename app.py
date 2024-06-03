import os
import base64
import uuid
import requests
from flask import Flask, request, jsonify, render_template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pymongo import MongoClient
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from webdriver_manager.chrome import ChromeDriverManager



app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

client_id = '8nDGPR55nVA4GWG46L7kayavng4osxT1V2HGAOMBCRQH692R'
client_secret = 'jyxdCnzmGoSz7tQSLo1OAgGGSIwuy2zUg5rbAMzLNpyyR62Innx0vJnMLc0odAuI'

mongo_client = MongoClient('mongodb+srv://ngophuc2911:phuc29112003@cluster0.buhheri.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
db = mongo_client['test']

# Ensure the upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

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

def upload_image(image_file_path):

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument('--disable-dev-shm-usage')
    options.binary_location = os.path.join("/opt/render/project/.render/chrome/opt/google/chrome/")
    try:
        driver = webdriver.Chrome(ChromeDriverManager().install(),options=options)
    except Exception as e:
        return f"An error occurred initializing WebDriver: {e}"

    try:
        driver.get("https://up-anh.vi-vn.vn/")

        upload_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
        )
        upload_input.send_keys(image_file_path)

        input_element = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-url"))
        )

        uploaded_link = input_element.get_attribute("value")

    except Exception as e:
        uploaded_link = f"An error occurred during upload: {e}"

    finally:
        driver.quit()

    return uploaded_link

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

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(image_file.filename)[1]) as temp_file:
            image_file.save(temp_file.name)
            temp_file_path = temp_file.name

        absolute_image_path = os.path.abspath(temp_file_path)

        with ThreadPoolExecutor() as executor:
            future = executor.submit(upload_image, absolute_image_path)
            uploaded_link = future.result()

        os.remove(temp_file_path)

        selected_collection = db[collection_name]
        doc = {
            'name': name,
            'location': location,
            'urn': urn,
            'filename': rvt_filename,
            'linkanh': uploaded_link
        }
        selected_collection.insert_one(doc)

        return jsonify({'urn': urn})

    except Exception as e:
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
