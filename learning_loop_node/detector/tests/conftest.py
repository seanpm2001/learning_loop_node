import pytest
from learning_loop_node import DetectorNode
from testing_detector import TestingDetector
import uvicorn
from multiprocessing import Process, log_to_stderr
import logging
import icecream
import os
import socket
import asyncio
from typing import Generator
import socketio

logging.basicConfig(level=logging.INFO)

# show ouptut from uvicorn server https://stackoverflow.com/a/66132186/364388
log_to_stderr(logging.INFO)

icecream.install()


def pytest_configure():
    pytest.detector_port = 5000


@pytest.fixture()
async def test_detector_node():
    os.environ['ORGANIZATION'] = 'zauberzeug'
    os.environ['PROJECT'] = 'demo'

    det = TestingDetector()
    node = DetectorNode(name='test', detector=det)
    await port_is(free=True)
    proc = Process(target=uvicorn.run,
                   args=(node,),
                   kwargs={
                       "host": "127.0.0.1",
                       "port": pytest.detector_port,
                   },
                   daemon=True)
    proc.start()
    await port_is(free=False)
    yield node
    await node.sio_client.disconnect()
    proc.kill()
    proc.join()

# from https://stackoverflow.com/a/52872579/364388


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


async def port_is(free: bool):
    for i in range(10):
        if not free and is_port_in_use(pytest.detector_port):
            return
        if free and not is_port_in_use(pytest.detector_port):
            return
        else:
            await asyncio.sleep(0.5)
    raise Exception(f'port {pytest.detector_port} is {"not" if free else ""} free')


@pytest.fixture()
async def sio_client() -> Generator:
    sio = socketio.AsyncClient()
    try_connect = True
    retry_count = 0
    while try_connect:
        try:
            await sio.connect(f"ws://localhost:{pytest.detector_port}", socketio_path="/ws/socket.io")
            try_connect = False
        except:
            logging.warning('trying again')
            await asyncio.sleep(1)
        retry_count += 1
        if retry_count > 10:
            raise Exception('Max Retry')

    yield sio
    await sio.disconnect()
