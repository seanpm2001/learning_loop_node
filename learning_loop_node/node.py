from learning_loop_node.context import Context
import logging
from .status import Status, State
from fastapi import FastAPI
import socketio
import asyncio
import asyncio
import os
from icecream import ic
from .loop import loop
from aiohttp.client_exceptions import ClientConnectorError
from fastapi_utils.tasks import repeat_every
import logging
from uuid import uuid4


class Node(FastAPI):
    name: str
    uuid: str

    def __init__(self, name: str, uuid: str = None):
        super().__init__()
        host = os.environ.get('LOOP_HOST', None) or os.environ.get('HOST', 'learning-loop.ai')
        self.ws_url = f'ws{"s" if host != "backend" else ""}://' + host
        self.organization = os.environ.get('LOOP_ORGANIZATION', None) or os.environ.get('ORGANIZATION', None)
        self.project = os.environ.get('LOOP_PROJECT', None) or os.environ.get('PROJECT', None)

        self.name = name
        self.uuid = self.read_or_create_uuid() if uuid is None else uuid

        self.sio_client = socketio.AsyncClient(
            reconnection_delay=0,
            request_timeout=0.5,
            # logger=True, engineio_logger=True
        )
        self.reset()

        @self.sio_client.on('connect')
        async def on_connect():
            logging.debug('received "on_connect" from constructor event.')
            self.reset()
            state = self.get_state()
            await self.update_state(state)

        @self.sio_client.on('disconnect')
        async def on_disconnect():
            logging.debug('received "on_disconnect" from constructor event.')
            await self.update_state(State.Offline)

        self.register_lifecycle_events()

    def read_or_create_uuid(self) -> str:
        if not os.path.exists('/data/uuid.txt'):
            os.makedirs('/data', exist_ok=True)
            uuid = str(uuid4())
            with open('/data/uuid.txt', 'a+') as f:
                f.write(uuid)
        else:
            with open('/data/uuid.txt', 'r') as f:
                uuid = f.read()

        return uuid

    def register_lifecycle_events(self):
        @self.on_event("startup")
        async def startup():
            logging.debug('received "startup" event')

        @self.on_event("shutdown")
        async def shutdown():
            logging.debug('received "shutdown" event')
            await self.sio_client.disconnect()

        @self.on_event("startup")
        @repeat_every(seconds=10, raise_exceptions=False, wait_first=False)
        async def ensure_connected() -> None:
            if not self.sio_client.connected:
                await self.connect()


    def reset(self):
        self.status = Status(id=self.uuid, name=self.name)

    async def get_state(self):
        raise Exception("Override this in subclass")

    async def connect(self):
        try:
            await self.sio_client.disconnect()
        except:
            pass

        logging.info(f'connecting to Learning Loop at {self.ws_url}')
        try:
            headers = await asyncio.get_event_loop().run_in_executor(None, loop.get_headers)
            await self.sio_client.connect(f"{self.ws_url}", headers=headers, socketio_path="/ws/socket.io")
            logging.debug(f'my sid is {self.sio_client.sid}')
            logging.info('connected to Learning Loop')
        except socketio.exceptions.ConnectionError as e:
            logging.error(f'socket.io connection error to "{self.ws_url}"')
        except Exception:
            logging.exception(f'error while connecting to "{self.ws_url}"')

    async def update_state(self, state: State):
        self.status.state = state
        if self.status.state != State.Offline:
            await self.send_status()

    async def update_status(self, new_status: Status):
        self.status.id = new_status.id
        self.status.name = new_status.name
        self.status.uptime = new_status.uptime
        self.status.latest_error = new_status.latest_error

        if self.status.state != State.Offline:
            self.status.state = State.Idle
        await self.send_status()

    async def send_status(self):
        raise Exception("Override this in subclass")

    @staticmethod
    def create_project_folder(context: Context) -> str:
        project_folder = f'{context.base_folder}/{context.organization}/{context.project}'
        os.makedirs(project_folder, exist_ok=True)
        return project_folder
