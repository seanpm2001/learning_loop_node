import os
from dataclasses import asdict
from typing import Dict

import pytest
from fastapi.encoders import jsonable_encoder

from ...annotation.annotator_logic import AnnotatorLogic
from ...annotation.annotator_node import AnnotatorNode
from ...data_classes import (AnnotationData, AnnotationEventType, Category, CategoryType, Context, Point, ToolOutput,
                             UserInput)


class MockedAnnotatatorLogic(AnnotatorLogic):
    async def handle_user_input(self, user_input: UserInput, history: Dict) -> ToolOutput:
        return ToolOutput(svg="")

    def create_empty_history(self) -> dict:
        return {}

    def logout_user(self, sid: str) -> bool:
        return True


def default_user_input() -> UserInput:
    annotation_data = AnnotationData(
        coordinate=Point(x=0, y=0),
        event_type=AnnotationEventType.LeftMouseDown,
        context=Context(organization='zauberzeug', project='pytest_nodelib_annotator'),
        image_uuid='f786350c-89ca-9424-9b00-720a9a85fe09',
        category=Category(id='some_id', name='category_1', description='',
                          hotkey='', color='', type=CategoryType.Segmentation)
    )
    return UserInput(frontend_id='some_id', data=annotation_data)

# ------------------------------------------------------------ TESTS ------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_download(setup_test_project):  # pylint: disable=unused-argument
    # TODO: This test depends on a pseudo-random uuid..
    image_path = '/tmp/learning_loop_lib_data/zauberzeug/pytest_nodelib_annotator/images/f786350c-89ca-9424-9b00-720a9a85fe09.jpg'

    assert os.path.exists(image_path) is False

    node = AnnotatorNode(name="", uuid="", annotator_logic=MockedAnnotatatorLogic())
    user_input = default_user_input()
    _ = await node._handle_user_input(jsonable_encoder(asdict(user_input)))  # pylint: disable=protected-access

    assert os.path.exists(image_path) is True