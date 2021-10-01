import boto3
from pathlib import Path
import numpy as np
import logging
import sys

from one.api import ONE
from one.alf.files import add_uuid_string
from iblutil.io.parquet import np2str


_logger = logging.getLogger('ibllib')

AWS_ROOT_PATH = Path('aws_spikesorting')


class AWS:
    def __init__(self, s3_bucket_name, one=None):
        # TODO some initialisation routine to set up credentials for the first time

        s3 = boto3.resource('s3')
        self.bucket = s3.Bucket(s3_bucket_name)
        self.one = one or ONE()

    def _download_datasets(self, datasets):

        for _, d in datasets.iterrows():
            rel_file_path = Path(d['session_path']).joinpath(d['rel_path'])
            file_path = Path(self.one.cache_dir).joinpath(rel_file_path)
            file_path.parent.mkdir(exist_ok=True, parents=True)

            if file_path.exists():
                # already downloaded, need to have some options for overwrite, clobber, look
                # for file mismatch like in ONE
                _logger.warning(f'{file_path} already exists wont redownload')
                continue

            aws_path = AWS_ROOT_PATH.joinpath(add_uuid_string(rel_file_path,
                                                              np2str(np.r_[d.name[0], d.name[1]])))
            aws_path = as_aws_path(aws_path)
            # maybe should avoid this and do a try catch instead?, see here
            # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/collections.html#filtering
            # probably better to do filter on collection ? Not for today
            objects = list(self.bucket.objects.filter(Prefix=aws_path))
            if len(objects) == 1:
                self.bucket.download_file(aws_path, file_path)
            else:
                _logger.warning(f'{aws_path} not found on s3 bucket: {self.bucket.name}')


def as_aws_path(path):
    """
    Convert a path into one suitable for the aws. Mainly for windows to convert // to \

    :param path: A Path instance
    :return: A formatted path string

    """
    if sys.platform == 'win32':
        path = '/'.join(str(path).split('\\'))
    else:
        path = str(path)

    return path
