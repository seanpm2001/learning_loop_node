from typing import List
import helper
import os
from glob import glob


def to_yolo(learning_loop_box, image_width, image_height, categories):
    w = float(learning_loop_box['width']) / float(image_width)
    h = float(learning_loop_box['height']) / float(image_height)
    x = (float((learning_loop_box['x']) + float(learning_loop_box['width']) / 2) / float(image_width))
    y = (float((learning_loop_box['y']) + float(learning_loop_box['height']) / 2) / float(image_height))

    yoloID = categories.index(learning_loop_box['category_id'])

    return ' '.join([
        str(yoloID),
        str("%.6f" % x),
        str("%.6f" % y),
        str("%.6f" % w),
        str("%.6f" % h)])


def create_data_file(training_folder: str, number_of_classes: int) -> None:
    number_of_classes = f'classes = {number_of_classes}'
    train = 'train  = train.txt'
    valid = 'valid  = test.txt'
    names = 'names = names.txt'
    backup = 'backup = backup/'
    with open(f'{training_folder}/data.txt', 'w') as f:
        data_object = [number_of_classes, train, valid, names, backup]
        f.write('\n'.join(data_object))


def update_yolo_boxes(image_folder_for_training: str, data: dict) -> None:
    category_ids = helper.get_box_category_ids(data)

    for image in data['images']:
        image_width, image_height = image['width'], image['height']
        image_id = image['id']
        yolo_boxes = []
        for box in image['box_annotations']:
            yolo_box = to_yolo(box, image_width, image_height, category_ids)
            yolo_boxes.append(yolo_box)

        with open(f'{image_folder_for_training}/{image_id}.txt', 'w') as f:
            f.write('\n'.join(yolo_boxes))


def create_names_file(training_folder: str, categories: List[str]) -> None:
    with open(f'{training_folder}/names.txt', 'w') as f:
        f.write('\n'.join(categories))


def create_image_links(training_folder: str, image_folder: str, image_ids: List[str]) -> str:
    training_images_path = f'{training_folder}/images'
    os.makedirs(training_images_path, exist_ok=True)
    for image_id in image_ids:
        source = os.path.join(image_folder, f'{image_id}.jpg')
        target = os.path.join(training_images_path, f'{image_id}.jpg')
        os.symlink(source, target)

    return training_images_path


def create_train_and_test_file(training_folder: str, image_folder_for_training: str, images: List) -> None:
    with open(f'{training_folder}/train.txt', 'w') as f:
        for image in images:
            if image['set'] == 'train':
                f.write(f"{image_folder_for_training}/{image['id']}\n")

    with open(f'{training_folder}/test.txt', 'w') as f:
        for image in images:
            if image['set'] == 'test':
                f.write(f"{image_folder_for_training}/{image['id']}\n")


def replace_classes_and_filters(classes_count: int, training_folder: str) -> None:
    cfg_file = _find_cfg_file(training_folder)

    with open(cfg_file, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.startswith('filters='):
            last_known_filters_line = i
        if line.startswith('[yolo]'):
            new_line = f'filters={(classes_count+5)*3}'
            lines[last_known_filters_line] = f'filters={(classes_count+5)*3}'
            last_known_filters_line = None
        if line.startswith('classes='):
            lines[i] = f'classes={classes_count}'

    with open(cfg_file, 'w') as f:
        f.write('\n'.join(lines))


def _find_cfg_file(folder) -> str:
    cfg_files = [file for file in glob(f'{folder}/**/*', recursive=True) if file.endswith('.cfg')]
    if len(cfg_files) == 0:
        raise Exception(f'[-] Error: No cfg file found.')
    elif len(cfg_files) > 1:
        raise Exception(f'[-] Error: Found more than one cfg file')
    return cfg_files[0]
