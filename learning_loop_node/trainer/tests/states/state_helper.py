from learning_loop_node.context import Context
from learning_loop_node.trainer import active_training
import logging
from learning_loop_node.trainer.tests.testing_trainer import TestingTrainer

from learning_loop_node.trainer.training import Training
from learning_loop_node.tests.test_helper import condition
from learning_loop_node.tests.test_helper import update_attributes


def create_active_training_file(**kwargs) -> None:
    trainer = TestingTrainer()
    details = {'categories': [],
               'id': '7f5eabb4-227a-e7c7-8f0b-f825cc47340d',  # version 1.2 of demo project
               'training_number': 0,
               'resolution': 800,
               'flip_rl': False,
               'flip_ud': False}
    trainer.init(Context(organization='zauberzeug', project='demo'), details)

    update_attributes(trainer.training, **kwargs)
    active_training.save(trainer.training)


def assert_training_file(exists: bool) -> None:
    assert active_training.exists() == exists


async def assert_training_state(training: Training, state: str, timeout: float, interval: float) -> None:
    try:
        await condition(lambda: training.training_state == state, timeout=timeout, interval=interval)
    except TimeoutError:
        msg = f"Trainer state should be '{state}' after {timeout} seconds, but is {training.training_state}"
        raise AssertionError(msg)
    except Exception as e:
        logging.exception('##### was ist das hier?')
        raise
