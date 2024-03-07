import asyncio
import json
import logging
import os
import shutil
import sys
from abc import abstractmethod
from dataclasses import asdict
from datetime import datetime
from glob import glob
from time import perf_counter
from typing import Coroutine, Dict, List, Optional, Union
from uuid import uuid4

import socketio
from dacite import from_dict
from fastapi.encoders import jsonable_encoder
from tqdm import tqdm

from ..data_classes import (BasicModel, Category, Context, Detections, Hyperparameter, ModelInformation, TrainerState,
                            Training, TrainingData, TrainingError, TrainingOut)
from ..helpers.misc import create_image_folder, create_project_folder, generate_training, is_valid_uuid4
from .downloader import TrainingsDownloader
from .executor import Executor
from .io_helpers import ActiveTrainingIO
from .trainer_logic_abstraction import TrainerLogicAbstraction


class TrainerLogic(TrainerLogicAbstraction):

    def __init__(self, model_format: str) -> None:
        super().__init__(model_format)
        self.model_format: str = model_format
        # NOTE: String to be used in the file path for the model on the server:
        # '/{context.organization}/projects/{context.project}/models/{model_id}/{model_format}/file'

        self._executor: Optional[Executor] = None
        self.training_task: Optional[asyncio.Task] = None
        self.start_training_task: Optional[Coroutine] = None
        self.shutdown_event: asyncio.Event = asyncio.Event()
        self.detection_progress = 0.0

    @property
    def executor(self) -> Executor:
        assert self._executor is not None, 'executor must be set, call `run_training` first'
        return self._executor

    def init_new_training(self, context: Context, details: Dict) -> None:
        """Called on `begin_training` event from the Learning Loop.
        Note that details needs the entries 'categories' and 'training_number'"""

        project_folder = create_project_folder(context)
        if not self.keep_old_trainings:
            # NOTE: We delete all existing training folders because they are not needed anymore.
            TrainerLogic.delete_all_training_folders(project_folder)
        self._training = generate_training(project_folder, context)
        self._training.data = TrainingData(categories=Category.from_list(details['categories']))
        self._training.data.hyperparameter = from_dict(data_class=Hyperparameter, data=details)
        self._training.training_number = details['training_number']
        self._training.base_model_id = details['id']
        self._training.training_state = TrainerState.Initialized
        self._active_training_io = ActiveTrainingIO(
            self._training.training_folder, self.loop_communicator, context)
        logging.info(f'training initialized: {self._training}')

    async def try_continue_run_if_incomplete(self) -> bool:
        if not self.training_active and self.last_training_io.exists():
            logging.info('found incomplete training, continuing now.')
            self.init_from_last_training()
            asyncio.get_event_loop().create_task(self.run())
            return True
        return False

    def init_from_last_training(self) -> None:
        self._training = self.last_training_io.load()
        assert self._training is not None and self._training.training_folder is not None, 'could not restore training folder'
        self._active_training_io = ActiveTrainingIO(
            self._training.training_folder, self.loop_communicator, self._training.context)

    async def begin_training(self, organization: str, project: str, details: Dict) -> None:
        self.init_new_training(Context(organization=organization, project=project), details)
        asyncio.get_event_loop().create_task(self.run())

    async def run(self) -> None:
        """Called on `begin_training` event from the Learning Loop."""

        self.errors.reset_all()
        try:
            self.training_task = asyncio.get_running_loop().create_task(self._run_training_loop())
            await self.training_task  # Object is used to potentially cancel the task
        except asyncio.CancelledError:
            if not self.shutdown_event.is_set():
                logging.info('training task was cancelled but not by shutdown event')
                self.active_training.training_state = TrainerState.ReadyForCleanup
                self.last_training_io.save(self.active_training)
                await self.clear_training()

        except Exception as e:
            logging.exception(f'Error in train: {e}')

    # ---------------------------------------- TRAINING STATES ----------------------------------------

    async def _run_training_loop(self) -> None:
        """asyncio.CancelledError is catched in train"""

        if not self.training_active:
            logging.error('could not start training - trainer is not initialized')
            return

        while self._training is not None:
            tstate = self.active_training.training_state
            logging.info(f'STATE LOOP: {tstate}, eerrors: {self.errors.errors}')
            await asyncio.sleep(0.6)  # Note: Required for pytests!
            if tstate == TrainerState.Initialized:  # -> DataDownloading -> DataDownloaded
                await self.perform_state('prepare', TrainerState.DataDownloading, TrainerState.DataDownloaded, self._prepare)
            elif tstate == TrainerState.DataDownloaded:  # -> TrainModelDownloading -> TrainModelDownloaded
                await self.perform_state('download_model', TrainerState.TrainModelDownloading, TrainerState.TrainModelDownloaded, self._download_model)
            elif tstate == TrainerState.TrainModelDownloaded:  # -> TrainingRunning -> TrainingFinished
                await self.perform_state('run_training', TrainerState.TrainingRunning, TrainerState.TrainingFinished, self._train)
            elif tstate == TrainerState.TrainingFinished:  # -> ConfusionMatrixSyncing -> ConfusionMatrixSynced
                await self.perform_state('sync_confusion_matrix', TrainerState.ConfusionMatrixSyncing, TrainerState.ConfusionMatrixSynced, self.sync_confusion_matrix)
                # await self.ensure_confusion_matrix_synced()
            elif tstate == TrainerState.ConfusionMatrixSynced:  # -> TrainModelUploading -> TrainModelUploaded
                await self.upload_model()
            elif tstate == TrainerState.TrainModelUploaded:  # -> Detecting -> Detected
                await self.perform_state('detecting', TrainerState.Detecting, TrainerState.Detected, self._do_detections)
            elif tstate == TrainerState.Detected:  # -> DetectionUploading -> ReadyForCleanup
                await self.perform_state('upload_detections', TrainerState.DetectionUploading, TrainerState.ReadyForCleanup, self.active_training_io.upload_detetions)
            elif tstate == TrainerState.ReadyForCleanup:  # -> RESTART or TrainingFinished
                await self.clear_training()
                self.may_restart()

    async def _prepare(self) -> None:
        self.data_exchanger.set_context(self.active_training.context)
        downloader = TrainingsDownloader(self.data_exchanger)
        image_data, skipped_image_count = await downloader.download_training_data(self.active_training.images_folder)
        assert self.active_training.data is not None, 'training.data must be set'
        self.active_training.data.image_data = image_data
        self.active_training.data.skipped_image_count = skipped_image_count

    async def _download_model(self) -> None:
        model_id = self.active_training.base_model_id
        assert model_id is not None, 'model_id must be set'
        if is_valid_uuid4(
                self.active_training.base_model_id):  # TODO this checks if we continue a training -> make more explicit
            logging.info('loading model from Learning Loop')
            logging.info(f'downloading model {model_id} as {self.model_format}')
            await self.data_exchanger.download_model(self.active_training.training_folder, self.active_training.context, model_id, self.model_format)
            shutil.move(f'{self.active_training.training_folder}/model.json',
                        f'{self.active_training.training_folder}/base_model.json')
        else:
            logging.info(f'base_model_id {model_id} is not a valid uuid4, skipping download')

    async def _train(self) -> None:
        previous_state = TrainerState.TrainModelDownloaded
        error_key = 'run_training'
        self._executor = Executor(self.active_training.training_folder)
        self.active_training.training_state = TrainerState.TrainingRunning

        try:
            await self._start_training()

            last_sync_time = datetime.now()
            while True:
                if not self.executor.is_process_running():
                    break
                if (datetime.now() - last_sync_time).total_seconds() > 5:
                    last_sync_time = datetime.now()
                    if self.get_executor_error_from_log():
                        break
                    self.errors.reset(error_key)
                    try:
                        await self.sync_confusion_matrix()
                    except asyncio.CancelledError:
                        logging.warning('CancelledError in run_training')
                        raise
                    except Exception:
                        pass
                else:
                    await asyncio.sleep(0.1)

            error = self.get_executor_error_from_log()
            if error:
                self.errors.set(error_key, error)
                raise TrainingError(cause=error)
            # TODO check if this works:
            # if self.executor.return_code != 0:
            #     self.errors.set(error_key, f'Executor return code was {self.executor.return_code}')
            #     raise TrainingError(cause=f'Executor return code was {self.executor.return_code}')

        except TrainingError:
            logging.exception('Error in TrainingProcess')
            if self.executor.is_process_running():
                self.executor.stop()
            self.active_training.training_state = previous_state
            raise

    async def _start_training(self):
        self.start_training_task = None  # NOTE: this is used i.e. by tests
        if self.can_resume():
            self.start_training_task = self.resume()
        else:
            base_model_id = self.active_training.base_model_id
            if not is_valid_uuid4(base_model_id):  # TODO this check was done earlier!
                assert isinstance(base_model_id, str)
                # TODO this could be removed here and accessed via self.training.base_model_id
                self.start_training_task = self.start_training_from_scratch(base_model_id)
            else:
                self.start_training_task = self.start_training()
        await self.start_training_task

    async def sync_confusion_matrix(self):
        logging.info('Syncing confusion matrix')
        error_key = 'sync_confusion_matrix'
        try:
            try:
                model = self.get_new_model()
            except Exception as exc:
                logging.exception('error while getting new model')
                raise Exception(f'Could not get new model: {str(exc)}') from exc
            if model and self.active_training.data:
                new_training = TrainingOut(
                    trainer_id=self.node_uuid,
                    confusion_matrix=model.confusion_matrix,
                    train_image_count=self.active_training.data.train_image_count(),
                    test_image_count=self.active_training.data.test_image_count(),
                    hyperparameters=self.hyperparameters)

                await asyncio.sleep(0.1)  # NOTE needed for tests.
                result = await self.sio_client.call('update_training', (self.active_training.context.organization, self.active_training.context.project, jsonable_encoder(new_training)))
                if isinstance(result,  dict) and result['success']:
                    logging.info(f'successfully updated training {asdict(new_training)}')
                    self.on_model_published(model)
                else:
                    error_msg = f'Error for update_training: Response from loop was : {result}'
                    logging.error(error_msg)
                    raise Exception(error_msg)
        except socketio.exceptions.BadNamespaceError as e:  # type: ignore
            logging.error('Error during confusion matrix syncronization. BadNamespaceError')
            self.errors.set(error_key, str(e))
            raise
        except Exception as e:
            logging.exception('Error during confusion matrix syncronization')
            self.errors.set(error_key, str(e))
            raise

        self.errors.reset(error_key)

    async def upload_model(self) -> None:
        error_key = 'upload_model'
        previous_state = self.active_training.training_state
        self.active_training.training_state = TrainerState.TrainModelUploading
        try:
            new_model_id = await self._upload_model_return_new_model_uuid(self.active_training.context)
            if new_model_id is None:
                self.active_training.training_state = TrainerState.ReadyForCleanup
                logging.error('could not upload model - maybe training failed.. cleaning up')
                return
            assert new_model_id is not None, 'uploaded_model must be set'
            logging.info(f'successfully uploaded model and received new model id: {new_model_id}')
            self.active_training.model_id_for_detecting = new_model_id
        except asyncio.CancelledError:
            logging.warning('CancelledError in upload_model')
            raise
        except Exception as e:
            logging.exception('Error in upload_model. Exception:')
            self.errors.set(error_key, str(e))
            self.active_training.training_state = previous_state  # TODO... going back is pointless here as it ends in a deadlock ?!
            # self.training.training_state = TrainingState.ReadyForCleanup
        else:
            self.errors.reset(error_key)
            self.active_training.training_state = TrainerState.TrainModelUploaded
            self.last_training_io.save(self.active_training)

    async def _upload_model_return_new_model_uuid(self, context: Context) -> Optional[str]:
        """Upload model files, usually pytorch model (.pt) hyp.yaml and the converted .wts file.
        Note that with the latest trainers the conversion to (.wts) is done by the trainer.
        The conversion from .wts to .engine is done by the detector (needs to be done on target hardware).
        Note that trainer may train with different classes, which is why we send an initial model.json file.
        """
        files = await asyncio.get_running_loop().run_in_executor(None, self.get_latest_model_files)
        if files is None:
            return None

        if isinstance(files, List):
            files = {self.model_format: files}
        assert isinstance(files, Dict), f'can only upload model as list or dict, but was {files}'

        already_uploaded_formats = self.active_training_io.load_model_upload_progress()

        new_model_uuid = None
        for file_format in files:
            if file_format in already_uploaded_formats:
                continue
            _files = files[file_format]
            assert not any(f for f in _files if 'model.json' in f), "Upload 'model.json' not allowed (added automatically)."
            _files.append(self.dump_categories_to_json())
            new_model_uuid = await self.data_exchanger.upload_model_get_uuid(context, _files, self.active_training.training_number, file_format)
            if new_model_uuid is None:
                return None

            already_uploaded_formats.append(file_format)
            self.active_training_io.save_model_upload_progress(already_uploaded_formats)

        return new_model_uuid

    def dump_categories_to_json(self) -> str:
        content = {'categories': [asdict(c) for c in self.training_data.categories], } if self.training_data else None
        json_path = '/tmp/model.json'
        with open(json_path, 'w') as f:
            json.dump(content, f)
        return json_path

    async def _do_detections(self) -> None:
        context = self.active_training.context
        model_id = self.active_training.model_id_for_detecting
        assert model_id, 'model_id must be set'
        tmp_folder = f'/tmp/model_for_auto_detections_{model_id}_{self.model_format}'

        shutil.rmtree(tmp_folder, ignore_errors=True)
        os.makedirs(tmp_folder)
        logging.info(f'downloading detection model to {tmp_folder}')

        await self.data_exchanger.download_model(tmp_folder, context, model_id, self.model_format)
        with open(f'{tmp_folder}/model.json', 'r') as f:
            content = json.load(f)
            model_information = from_dict(data_class=ModelInformation, data=content)

        project_folder = create_project_folder(context)
        image_folder = create_image_folder(project_folder)
        self.data_exchanger.set_context(context)
        image_ids = []
        for state, p in zip(['inbox', 'annotate', 'review', 'complete'], [0.1, 0.2, 0.3, 0.4]):
            self.detection_progress = p
            logging.info(f'fetching image ids of {state}')
            new_ids = await self.data_exchanger.fetch_image_uuids(query_params=f'state={state}')
            image_ids += new_ids
            logging.info(f'downloading {len(new_ids)} images')
            await self.data_exchanger.download_images(new_ids, image_folder)
        self.detection_progress = 0.42
        # await delete_corrupt_images(image_folder)

        images = await asyncio.get_event_loop().run_in_executor(None, TrainerLogic.images_for_ids, image_ids, image_folder)
        num_images = len(images)
        logging.info(f'running detections on {num_images} images')
        batch_size = 200
        idx = 0
        if not images:
            self.active_training_io.save_detections([], idx)
        for i in tqdm(range(0, num_images, batch_size), position=0, leave=True):
            self.detection_progress = 0.5 + (i/num_images)*0.5
            batch_images = images[i:i+batch_size]
            batch_detections = await self._detect(model_information, batch_images, tmp_folder)
            self.active_training_io.save_detections(batch_detections, idx)
            idx += 1

        return None

    async def clear_training(self):
        self.active_training_io.delete_detections()
        self.active_training_io.delete_detection_upload_progress()
        self.active_training_io.delete_detections_upload_file_index()
        await self.clear_training_data(self.active_training.training_folder)
        self.last_training_io.delete()
        # self.training.training_state = TrainingState.TrainingFinished

        await self.node.send_status()
        self._training = None

    async def stop(self) -> None:
        """If executor is running, stop it. Else cancel training task."""
        if not self.training_active:
            return
        if self._executor and self._executor.is_process_running():
            self.executor.stop()
        elif self.training_task:
            logging.info('cancelling training task')
            if self.training_task.cancel():
                try:
                    await self.training_task
                except asyncio.CancelledError:
                    pass
                logging.info('cancelled training task')
                self.may_restart()

    async def shutdown(self) -> None:
        self.shutdown_event.set()
        await self.stop()
        await self.stop()  # NOTE first stop may only stop training.

    def get_log(self) -> str:
        return self.executor.get_log()

    def may_restart(self) -> None:
        if self.restart_after_training:
            logging.info('restarting')
            sys.exit(0)
        else:
            logging.info('not restarting')

    @property
    def general_progress(self) -> Optional[float]:
        """Represents the progress for different states."""
        if not self.training_active:
            return None

        t_state = self.active_training.training_state
        if t_state == TrainerState.DataDownloading:
            return self.data_exchanger.progress
        if t_state == TrainerState.TrainingRunning:
            return self.training_progress
        if t_state == TrainerState.Detecting:
            return self.detection_progress

        return None
    # ---------------------------------------- ABSTRACT METHODS ----------------------------------------

    @property
    @abstractmethod
    def training_progress(self) -> Optional[float]:
        """Represents the training progress."""
        raise NotImplementedError

    @abstractmethod
    async def start_training(self) -> None:
        '''Should be used to start a training.'''

    @abstractmethod
    async def start_training_from_scratch(self, base_model_id: str) -> None:
        '''Should be used to start a training from scratch.
        base_model_id is the id of a pretrained model provided by self.provided_pretrained_models.'''

    @abstractmethod
    def can_resume(self) -> bool:
        '''Override this method to return True if the trainer can resume training.'''

    @abstractmethod
    async def resume(self) -> None:
        '''Is called when self.can_resume() returns True.
        One may resume the training on a previously trained model stored by self.on_model_published(basic_model).'''

    @abstractmethod
    def get_executor_error_from_log(self) -> Optional[str]:  # TODO we should allow other options to get the error
        '''Should be used to provide error informations to the Learning Loop by extracting data from self.executor.get_log().'''

    @abstractmethod
    def get_new_model(self) -> Optional[BasicModel]:
        '''Is called frequently in `try_sync_model` to check if a new "best" model is availabe.
        Returns None if no new model could be found. Otherwise BasicModel(confusion_matrix, meta_information).
        `confusion_matrix` contains a dict of all classes:
            - The classes must be identified by their id, not their name.
            - For each class a dict with tp, fp, fn is provided (true positives, false positives, false negatives).
        `meta_information` can hold any data which is helpful for self.on_model_published to store weight file etc for later upload via self.get_model_files
        '''

    @abstractmethod
    def on_model_published(self, basic_model: BasicModel) -> None:
        '''Called after a BasicModel has been successfully send to the Learning Loop.
        The files for this model should be stored.
        self.get_latest_model_files is used to gather all files needed for transfering the actual data from the trainer node to the Learning Loop.
        In the simplest implementation this method just renames the weight file (encoded in BasicModel.meta_information) into a file name like latest_published_model
        '''

    @abstractmethod
    def get_latest_model_files(self) -> Optional[Union[List[str], Dict[str, List[str]]]]:
        '''Called when the Learning Loop requests to backup the latest model for the training.
        Should return a list of file paths which describe the model.
        These files must contain all data neccessary for the trainer to resume a training (eg. weight file, hyperparameters, etc.)
        and will be stored in the Learning Loop unter the format of this trainer.
        Note: by convention the weightfile should be named "model.<extension>" where extension is the file format of the weightfile.
        For example "model.pt" for pytorch or "model.weights" for darknet/yolo.

        If a trainer can also generate other formats (for example for an detector),
        a dictionary mapping format -> list of files can be returned.'''

    @abstractmethod
    async def _detect(self, model_information: ModelInformation, images: List[str], model_folder: str) -> List[Detections]:
        '''Called to run detections on a list of images.'''

    @abstractmethod
    async def clear_training_data(self, training_folder: str) -> None:
        '''Called after a training has finished. Deletes all data that is not needed anymore after a training run. 
        This can be old weightfiles or any additional files.'''

    # ---------------------------------------- HELPER METHODS ----------------------------------------

    @staticmethod
    def images_for_ids(image_ids, image_folder) -> List[str]:
        logging.info(f'### Going to get images for {len(image_ids)} images ids')
        start = perf_counter()
        images = [img for img in glob(f'{image_folder}/**/*.*', recursive=True)
                  if os.path.splitext(os.path.basename(img))[0] in image_ids]
        end = perf_counter()
        logging.info(f'found {len(images)} images for {len(image_ids)} image ids, which took {end-start:0.2f} seconds')
        return images

    @staticmethod
    def generate_training(project_folder: str, context: Context) -> Training:
        training_uuid = str(uuid4())
        return Training(
            id=training_uuid,
            context=context,
            project_folder=project_folder,
            images_folder=create_image_folder(project_folder),
            training_folder=TrainerLogic.create_training_folder(project_folder, training_uuid)
        )

    @staticmethod
    def delete_all_training_folders(project_folder: str):
        if not os.path.exists(f'{project_folder}/trainings'):
            return
        for uuid in os.listdir(f'{project_folder}/trainings'):
            shutil.rmtree(f'{project_folder}/trainings/{uuid}', ignore_errors=True)

    @staticmethod
    def create_training_folder(project_folder: str, trainings_id: str) -> str:
        training_folder = f'{project_folder}/trainings/{trainings_id}'
        os.makedirs(training_folder, exist_ok=True)
        return training_folder

    @property
    def hyperparameters(self) -> Optional[Dict]:
        if self._training and self._training.data and self._training.data.hyperparameter:
            information = {}
            information['resolution'] = self._training.data.hyperparameter.resolution
            information['flipRl'] = self._training.data.hyperparameter.flip_rl
            information['flipUd'] = self._training.data.hyperparameter.flip_ud
            return information
        return None
