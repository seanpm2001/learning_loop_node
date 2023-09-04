import logging
import os
import socket
from multiprocessing import log_to_stderr

import icecream
import pytest

from learning_loop_node.data_classes import Context
from learning_loop_node.trainer.tests.testing_trainer import TestingTrainer
from learning_loop_node.trainer.trainer_node import TrainerNode

logging.basicConfig(level=logging.INFO)
# show ouptut from uvicorn server https://stackoverflow.com/a/66132186/364388
log_to_stderr(logging.INFO)

icecream.install()


@pytest.fixture()
async def test_initialized_trainer_node():
    os.environ['ORGANIZATION'] = 'zauberzeug'
    os.environ['PROJECT'] = 'demo'

    trainer = TestingTrainer()
    node = TrainerNode(name='test', trainer=trainer, uuid='00000000-0000-0000-0000-000000000000')

    await node._on_startup()

    yield node

    try:
        await node._on_shutdown()
    except Exception:
        logging.exception('error while shutting down node')


@pytest.fixture()
async def test_initialized_trainer():

    trainer = TestingTrainer()
    node = TrainerNode(name='test', trainer=trainer, uuid='00000000-0000-0000-0000-000000000000')
    await node._on_startup()
    assert node._sio_client is not None

    trainer.init(context=Context(organization='zauberzeug', project='demo'),
                 details={'categories': [],
                          'id': '917d5c7f-403d-7e92-f95f-577f79c2273a',  # version 1.2 of demo project
                          'training_number': 0,
                          'resolution': 800,
                          'flip_rl': False,
                          'flip_ud': False},
                 node_uuid=node.uuid,
                 sio_client=node._sio_client,
                 last_training_io=node.last_training_io)

    yield trainer

    # try:
    #     await trainer.
    # except:
    #     logging.exception('error while shutting down node')


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


# @pytest.fixture(autouse=True, scope='session')
# def initialize_active_training():
#     from learning_loop_node.trainer import active_training_module
#     active_training_module.init('00000000-0000-0000-0000-000000000000')
#     yield
