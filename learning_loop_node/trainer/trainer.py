from abc import abstractmethod
import asyncio
import os
from typing import Dict, List, Optional, Union
from uuid import uuid4
from learning_loop_node.rest.downloader import DataDownloader
from learning_loop_node.loop import loop
from ..model_information import ModelInformation
from .executor import Executor
from .training import Training
from .model import BasicModel, PretrainedModel
from ..context import Context
from ..node import Node
from .downloader import TrainingsDownloader
from ..rest import downloads, uploads
from .. import node_helper
import logging
from icecream import ic
from .helper import is_valid_uuid4
from glob import glob
import json
from fastapi.encoders import jsonable_encoder
import shutil

class Trainer():

    def __init__(self, model_format: str) -> None:
        self.model_format: str = model_format
        self.training: Optional[Training] = None
        self.executor: Optional[Executor] = None
        self.source_model_id: str = None

    async def begin_training(self, context: Context, source_model: dict) -> None:
        downloader = TrainingsDownloader(context)
        self.training = Trainer.generate_training(context, source_model)
        self.training.data = await downloader.download_training_data(self.training.images_folder)
        self.executor = Executor(self.training.training_folder)

        self.source_model_id = source_model['id']
        if not is_valid_uuid4(self.source_model_id):
            if self.source_model_id in [m.name for m in self.provided_pretrained_models]:
                logging.debug('Should start with pretrained model')
                self.ensure_model_json()
                await self.start_training_from_scratch(self.source_model_id)
            else:
                raise ValueError(f'Pretrained model {self.source_model_id} is not supported')
        else:
            logging.debug('Should start with loop model')
            logging.info(f'downloading model {self.source_model_id} as {self.model_format}')
            await downloads.download_model(self.training.training_folder, context, self.source_model_id, self.model_format)
            logging.info(f'now starting training')
            await self.start_training()

    async def start_training(self) -> None:
        raise NotImplementedError()

    async def start_training_from_scratch(self, identifier: str) -> None:
        raise NotImplementedError()

    def stop_training(self) -> bool:
        if self.executor:
            self.executor.stop()
            self.executor = None
            return True
        else:
            logging.info('could not stop training, executor is None')
            return False

    def get_error(self) -> Optional[Union[None, str]]:
        '''Should be used to provide error informations to the Learning Loop by extracting data from self.executor.get_log().'''
        pass

    def get_log(self) -> str:
        return self.executor.get_log()

    async def save_model(self,  context: Context, model_id: str) -> None:
        files = await asyncio.get_running_loop().run_in_executor(None, self.get_model_files, model_id)
        if isinstance(files, list):
            await uploads.upload_model(context, files, model_id, self.model_format)
        elif isinstance(files, dict):
            for format in files:
                await uploads.upload_model(context, files[format], model_id, format)
        else:
            raise TypeError(f'can only save model as list or dict, but was {files}')

    def get_new_model(self) -> Optional[BasicModel]:
        '''Is called frequently to check if a new "best" model is availabe.
        Returns None if no new model could be found. Otherwise BasicModel(confusion_matrix, meta_information).
        `confusion_matrix` contains a dict of all classes: 
            - The classes must be identified by their id, not their name.
            - For each class a dict with tp, fp, fn is provided (true positives, false positives, false negatives).
        `meta_information` can hold any data which is helpful for self.on_model_published to store weight file etc for later upload via self.get_model_files
        '''
        raise NotImplementedError()

    def on_model_published(self, basic_model: BasicModel, model_id: str) -> None:
        '''Called after a BasicModel has been successfully send to the Learning Loop.
        The model_id is an uuid to identify the model within the Learning Loop.
        self.get_model_files uses this id to gather all files needed for transfering the actual data from the trainer node to the Learning Loop.
        In the simplest implementation this method just renames the weight file (encoded in BasicModel.meta_information) into a file name containing the model_id.
        '''
        raise NotImplementedError()

    def get_model_files(self, model_id: str) -> Union[List[str], Dict[str, List[str]]]:
        '''Called when the Learning Loop requests to backup a specific model. 
        Should return a list of file paths which describe the model.
        These files must contain all data neccessary for the trainer to resume a training (eg. weight file, hyperparameters, etc.) 
        and will be stored in the Learning Loop unter the format of this trainer.
        Note: by convention the weightfile should be named "model.<extension>" where extension is the file format of the weightfile.
        For example "model.pt" for pytorch or "model.weights" for darknet/yolo.

        If a trainer can also generate other formats (for example for an detector),
        a dictionary mapping format -> list of files can be returned.
        Each format should contain a model.json in the file list. 
        This file contains the trained resolution, categories including their learning loop ids to be robust about renamings etc.
        Example: {"resolution": 832, "categories":[{"name": "A", "id": "<a uuid>", "type": "box"}]}
        '''
        raise NotImplementedError()

    async def do_detections(self, context: Context, model_id: str, model_format: str):
        tmp_folder = f'/tmp/model_for_auto_detections_{model_id}_{model_format}'
        
        shutil.rmtree(tmp_folder, ignore_errors=True)
        os.makedirs(tmp_folder)
        logging.info('downloading model for detecting')
        try:
            await downloads.download_model(tmp_folder, context, model_id, model_format)
        except:
            logging.exception('download error')
        with open(f'{tmp_folder}/model.json', 'r') as f:
            content = json.load(f)
            model_information = ModelInformation.parse_obj(content)

        project_folder = Node.create_project_folder(context)
        image_folder = node_helper.create_image_folder(project_folder)
        downloader = DataDownloader(context)
        image_ids = []
        for state in ['inbox', 'annotate', 'review', 'complete']:
            basic_data = await downloader.download_basic_data(query_params=f'state={state}')
            image_ids += basic_data.image_ids
            await downloader.download_images(basic_data.image_ids, image_folder)
        images = [img for img in glob(f'{image_folder}/**/*.*', recursive=True) if os.path.splitext(os.path.basename(img))[0] in image_ids]
        logging.info(f'running detections on {len(images)} images')
        detections = await self._detect(model_information, images, tmp_folder, model_id, 'some_model_version')
        logging.info(f'uploading {len(detections)} detections')
        await self._upload_detections(context, jsonable_encoder(detections))
        return detections

    async def _detect(self, model_information: ModelInformation, images:  List[str], model_folder: str, model_id: str, model_version: str) -> List:
        raise NotImplementedError()

    async def _upload_detections(self, context: Context, detections: List[dict]):
        logging.info('uploading detections')
        try:
            data = json.dumps(detections)
            logging.info(f'uploading detections. File size : {len(data)}')
            async with loop.post(f'api/{context.organization}/projects/{context.project}/detections', data=data) as response:
                if response.status != 200:
                    logging.error(f'could not upload detections. {str(response)}')
                else:
                    logging.info('successfully uploaded detections')
        except:
            logging.exception('error uploading detections.')

    async def clear_training_data(self, training_folder: str) -> None:
        '''Called after a training has finished. Deletes all data that is not needed anymore after a training run. This can be old
        weightfiles or any additional files.
        '''
        raise NotImplementedError()

    @property
    @abstractmethod
    def provided_pretrained_models(self) -> List[PretrainedModel]:
        raise NotImplementedError()

    @staticmethod
    def generate_training(context: Context, source_model: dict) -> Training:
        training_uuid = str(uuid4())
        project_folder = Node.create_project_folder(context)
        return Training(
            id=training_uuid,
            context=context,
            project_folder=project_folder,
            images_folder=node_helper.create_image_folder(project_folder),
            training_folder=Trainer.create_training_folder(project_folder, training_uuid)
        )

    @staticmethod
    def create_training_folder(project_folder: str, trainings_id: str) -> str:
        training_folder = f'{project_folder}/trainings/{trainings_id}'
        os.makedirs(training_folder, exist_ok=True)
        return training_folder

    def ensure_model_json(self):
        modeljson_path = f'{self.training.training_folder}/model.json'
        if not os.path.exists(modeljson_path):
            with open(modeljson_path, 'w') as f:
                f.write('{}')
