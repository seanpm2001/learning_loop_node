
from learning_loop_node.context import Context
from learning_loop_node.trainer.downloader_factory import DownloaderFactory
from annotation_node import AnnotationData, AnnotationNode, EventType, Point, UserInput, EventType
import pytest
from fastapi.encoders import jsonable_encoder
from icecream import ic
from demo_segmentation_tool import DemoSegmentationTool
import os



def default_user_input() -> UserInput:
    annotation_data = AnnotationData(
        coordinate=Point(x=0, y=0),
        event_type=EventType.MouseDown,
        context=Context(organization='zauberzeug', project='pytest'),
        image_uuid='285a92db-bc64-240d-50c2-3212d3973566'
    )
    return UserInput(data=annotation_data)


async def download_basic_data():
    downloader = DownloaderFactory.create(Context(organization='zauberzeug', project='pytest'))
    basic_data = await downloader.download_basic_data()
    image_id = basic_data.image_ids[0]
    ic(image_id)


@pytest.mark.asyncio
async def test_start_creating(create_project):

    node = AnnotationNode(name='', uuid='', tool=DemoSegmentationTool())
    input = default_user_input()
    result = await node.handle_user_input('zauberzeug', 'pytest', jsonable_encoder(input))

    assert result == "test_green_X"
