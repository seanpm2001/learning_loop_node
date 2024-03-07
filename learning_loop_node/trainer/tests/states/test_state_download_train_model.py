
import asyncio
import os

from learning_loop_node.data_classes import TrainerState
from learning_loop_node.trainer.tests.state_helper import assert_training_state, create_active_training_file
from learning_loop_node.trainer.tests.testing_trainer_logic import TestingTrainerLogic


async def test_downloading_is_successful(test_initialized_trainer: TestingTrainerLogic):
    trainer = test_initialized_trainer
    create_active_training_file(trainer, training_state=TrainerState.DataDownloaded)

    trainer.model_format = 'mocked'
    trainer.init_from_last_training()

    asyncio.get_running_loop().create_task(
        trainer.perform_state('download_model',
                              TrainerState.TrainModelDownloading,
                              TrainerState.TrainModelDownloaded, trainer._download_model))
    await assert_training_state(trainer.active_training, 'train_model_downloading', timeout=1, interval=0.001)
    await assert_training_state(trainer.active_training, 'train_model_downloaded', timeout=1, interval=0.001)

    assert trainer.active_training.training_state == TrainerState.TrainModelDownloaded
    assert trainer.node.last_training_io.load() == trainer.active_training

    # file on disk
    assert os.path.exists(f'{trainer.active_training.training_folder}/base_model.json')
    assert os.path.exists(f'{trainer.active_training.training_folder}/file_1.txt')
    assert os.path.exists(f'{trainer.active_training.training_folder}/file_2.txt')


async def test_abort_download_model(test_initialized_trainer: TestingTrainerLogic):
    trainer = test_initialized_trainer
    create_active_training_file(trainer, training_state='data_downloaded')
    trainer.init_from_last_training()

    _ = asyncio.get_running_loop().create_task(trainer.run())
    await assert_training_state(trainer.active_training, 'train_model_downloading', timeout=1, interval=0.001)

    await trainer.stop()
    await asyncio.sleep(0.1)

    assert trainer._training is None
    assert trainer.node.last_training_io.exists() is False


async def test_downloading_failed(test_initialized_trainer: TestingTrainerLogic):
    trainer = test_initialized_trainer
    create_active_training_file(trainer, training_state=TrainerState.DataDownloaded,
                                base_model_id='00000000-0000-0000-0000-000000000000')  # bad model id)
    trainer.init_from_last_training()

    _ = asyncio.get_running_loop().create_task(trainer.run())
    await assert_training_state(trainer.active_training, 'train_model_downloading', timeout=1, interval=0.001)
    await assert_training_state(trainer.active_training, TrainerState.DataDownloaded, timeout=1, interval=0.001)

    assert trainer.errors.has_error_for('download_model')
    assert trainer._training is not None  # pylint: disable=protected-access
    assert trainer.active_training.training_state == TrainerState.DataDownloaded
    assert trainer.node.last_training_io.load() == trainer.active_training
