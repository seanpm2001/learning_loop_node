from typing import List, Optional
import shutil
import os
from glob import glob
import asyncio
from learning_loop_node.context import Context
from learning_loop_node.loop import loop
from learning_loop_node.rest import downloads
from learning_loop_node import node_helper
import logging
from icecream import ic


class DataDownloader():
    context: Context

    def __init__(self, context: Context):
        self.context = context

    async def fetch_image_ids(self, query_params: Optional[str] = '') -> List[str]:
        async with loop.get(f'api/{self.context.organization}/projects/{self.context.project}/data?{query_params}') as response:
            assert response.status == 200, response
            return (await response.json())['image_ids']

    async def download_images_data(self, ids: List[str]) -> List[dict]:
        return await downloads.download_images_data(self.context.organization, self.context.project, ids)

    async def download_images(self, image_ids: List[str], image_folder: str) -> None:
        '''Will skip existing images'''
        paths, ids = node_helper.create_resource_paths(self.context.organization, self.context.project,
                                                       DataDownloader.filter_existing_images(image_ids, image_folder))
        await downloads.download_images(paths, ids, image_folder)

    @staticmethod
    def filter_existing_images(all_image_ids, image_folder) -> List[str]:
        ids = [os.path.splitext(os.path.basename(image))[0]
               for image in glob(f'{image_folder}/*.jpg')]
        return [id for id in all_image_ids if id not in ids]
