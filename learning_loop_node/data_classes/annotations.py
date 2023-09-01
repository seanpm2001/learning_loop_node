
from enum import Enum
from typing import Optional

# pylint: disable=no-name-in-module
from pydantic import BaseModel

from learning_loop_node.data_classes.detections import Point, Shape
from learning_loop_node.data_classes.general import Category, Context


class SegmentationAnnotation(BaseModel):
    id: str
    shape: Shape
    image_id: str
    category_id: str


class EventType(str, Enum):
    LeftMouseDown = 'left_mouse_down'
    RightMouseDown = 'right_mouse_down'
    MouseMove = 'mouse_move'
    LeftMouseUp = 'left_mouse_up'
    RightMouseUp = 'right_mouse_up'
    KeyUp = 'key_up'
    KeyDown = 'key_down'


class AnnotationData(BaseModel):
    coordinate: Point
    event_type: EventType
    context: Context
    image_uuid: str
    category: Category
    is_shift_key_pressed: Optional[bool] = None
    key_up: Optional[str] = None
    key_down: Optional[str] = None
    epsilon: Optional[float] = None
    # keyboard_modifiers: Optional[List[str]]
    # new_annotation_uuid: Optional[str]
    # edit_annotation_uuid: Optional[str]
