from typing import List
import requests
import shutil
from io import BytesIO
import zipfile
import os
from glob import glob


def download_images(url: str, image_ressources_and_ids: List[tuple], image_folder: str) -> None:
    for resource, image_id in image_ressources_and_ids:
        url = f'{url}/api{resource}'
        response = requests.get(url)
        if response.status_code == 200:
            try:
                with open(f'/{image_folder}/{image_id}.jpg', 'wb') as f:
                    f.write(response.content)
            except IOError:
                print(f"Could not save image with id {image_id}")
        else:
            # TODO How to deal with this kind of error?
            pass


def download_model(training_folder: str, organization: str, project: str, model_id: str, hostname: str):
    # download model
    download_response = requests.get(
        f'http://{hostname}/api/{organization}/projects/{project}/models/{model_id}/file')
    assert download_response.status_code == 200
    provided_filename = download_response.headers.get(
        "Content-Disposition").split("filename=")[1].strip('"')

    # unzip and place downloaded model
    target_path = f'/tmp/{os.path.splitext(provided_filename)[0]}'
    shutil.rmtree(target_path, ignore_errors=True)
    filebytes = BytesIO(download_response.content)
    with zipfile.ZipFile(filebytes, 'r') as zip:
        zip.extractall(target_path)

    files = glob(f'{target_path}/**/*', recursive=True)
    for file in files:
        shutil.move(file, training_folder)
