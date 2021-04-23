from pydantic.main import BaseModel
from learning_loop_node.trainer.training_data import TrainingData
from learning_loop_node.node import Node
from learning_loop_node.trainer.training import Training
import requests
import asyncio
from status import State
import os
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from learning_loop_node.status import Status


class Trainer(Node):
    training: Training

    def __init__(self, name: str, uuid: str):
        super().__init__(name, uuid)
        self.training = None

        @self.sio.on('begin_training')
        async def on_begin_training(organization, project, source_model):
            if not hasattr(self, '_begin_training'):
                msg = 'node does not provide a begin_training function'
                raise Exception(msg)

            print(f'---- running training with source model {source_model} for {organization}.{project}', flush=True)
            # self.status.model = source_model
            # self.status.organization = organization
            # self.status.project = project

            uri_base = f'{self.url}/api/{ organization}/projects/{ project}'

            response = requests.get(uri_base + '/data/data2?state=complete', headers=self.headers)
            assert response.status_code == 200
            data = response.json()

            self.training = Training(id=str(uuid4()),
                                     base_model=source_model,
                                     organization=organization,
                                     project=project,
                                     project_folder="",
                                     images_folder="",
                                     training_folder=""
                                     )
            loop = asyncio.get_event_loop()

            loop.set_debug(True)
            loop.create_task(self._begin_training(data))
            await self.update_state(State.Running)
            return True

        @self.sio.on('stop_training')
        async def stop():
            print('---- stopping', flush=True)
            if hasattr(self, '_stop_training'):
                self._stop_training()
            await self.update_state(State.Idle)
            return True

        @self.sio.on('save')
        def on_save(organization, project, model):
            print('---- saving model', model['id'], flush=True)
            if not hasattr(self, '_get_model_files'):
                return 'node does not provide a get_model_files function'
            # NOTE: Do not use self.status.organization here. The requested model maybe not belongs to the currently running training.

            uri_base = f'{self.url}/api/{organization}/projects/{project}'
            data = []
            for file_name in self._get_model_files(organization, project, model['id']):
                data.append(('files',  open(file_name, 'rb')))

            response = requests.put(
                f'{uri_base}/models/{model["id"]}/file',
                files=data
            )
            if response.status_code == 200:
                print('---- model saved', flush=True)
                return True
            else:
                print('---- could not save model', flush=True)
                return response.json()['detail']

    async def send_status(self):
        print("asdf")

        from learning_loop_node.status import TrainingStatus
        try:
            status = TrainingStatus(
                id=self.uuid,
                name=self.name,
                state=self.status.state,
                uptime=self.status.uptime
            )
        except Exception as e:
            print(e, flush=True)
            print()

        if self.training:
            status.latest_produced_model_id = self.training.last_known_model.id
            # status.organization = self.training.organization
            # status.project = self.training.project
            # if self.training.data:
            #     status.box_categories = self.training.data.box_categories

        print('sending status', status, flush=True)
        result = await self.sio.call('update_trainer', jsonable_encoder(status))
        if not result == True:
            raise Exception(result)

    async def update_status(self, status: Status):
        self.training = None
        await super().update_status(status)

    def get_model_files(self, func):
        self._get_model_files = func
        return func

    def begin_training(self, func):
        self._begin_training = func
        return func

    def stop_training(self, func):
        self._stop_training = func
        return func

    @staticmethod
    def create_image_folder(project_folder: str) -> str:
        image_folder = f'{project_folder}/images'
        os.makedirs(image_folder, exist_ok=True)
        return image_folder

    @staticmethod
    def create_training_folder(project_folder: str, trainings_id: str) -> str:
        training_folder = f'{project_folder}/trainings/{trainings_id}'
        os.makedirs(training_folder, exist_ok=True)
        return training_folder
