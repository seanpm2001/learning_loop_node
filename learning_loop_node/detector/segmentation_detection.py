from dataclasses import dataclass
from typing import List


@dataclass
class Point:
    x: int
    y: int

    def __str__(self):
        return f'x:{int(self.x)} y: {int(self.y)}'


@dataclass
class Shape:
    points: List[Point]

    def __str__(self):
        return ', '. join([str(s) for s in self.points])


@dataclass
class SegmentationDetection:
    category_name: str
    shape: Shape
    model_name: str
    confidence: float
    category_id: str = ''

    @staticmethod
    def from_dict(detection: dict):
        category_id = detection['category_id'] if 'category_id' in detection else ''
        raw = detection['shape'].split(',')
        points = []
        for i in range(0, len(raw), 2):
            points.append(Point(x=int(raw[i]), y=int(raw[i+1])))

        shape = Shape(points=points)
        return SegmentationDetection(detection['category_name'], shape, detection['model_name'], detection['confidence'], category_id)

    def __str__(self):
        return f'shape:{str(self.shape)}, c: {self.confidence:.2f} -> {self.category_name}'
