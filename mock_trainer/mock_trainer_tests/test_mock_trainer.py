from uuid import uuid4

from learning_loop_node.data_classes import (Context, Model, Training,
                                             TrainingData)
from learning_loop_node.globals import GLOBALS
from learning_loop_node.trainer.executor import Executor
from mock_trainer.mock_trainer import MockTrainer


async def create_mock_trainer() -> MockTrainer:
    mock_trainer = MockTrainer(model_format='mocked')
    mock_trainer.executor = Executor(GLOBALS.data_folder)
    return mock_trainer


async def test_get_model_files():
    mock_trainer = await create_mock_trainer()
    files = mock_trainer.get_latest_model_files()

    assert len(files) == 2
    assert files['mocked'] == ['/tmp/weightfile.weights', '/tmp/some_more_data.txt']
    assert files['mocked_2'] == ['/tmp/weightfile.weights', '/tmp/some_more_data.txt']


async def test_get_new_model():
    mock_trainer = await create_mock_trainer()
    await mock_trainer.start_training()

    model = Model(uuid=(str(uuid4())))
    context = Context(organization="", project="")
    mock_trainer._training = Training(
        uuid=str(uuid4()),
        context=context,
        project_folder="",
        images_folder="")
    mock_trainer._training.data = TrainingData(image_data=[], categories=[])
    model = mock_trainer.get_new_model()
    assert model is not None
