import json
import logging
import os
import time
from shutil import rmtree

import pytest
import sputnik

from orbital.orbital import patch_sputnik

logging.basicConfig(level=logging.INFO)

SAMPLE_DIR = 'sputnik_sample'
DATA_DIR = 'data'
JSON_FILE = 'package.json'
MODEL_DIR = 'model'
INSTALL_DIR = 'installed_packages'


def _clean_up():
    if os.path.exists(SAMPLE_DIR):
        rmtree(SAMPLE_DIR)
    if os.path.exists(INSTALL_DIR):
        rmtree(INSTALL_DIR)


def timestamp():
    """return a Unix ms timestamp equivalent to Javascript's Date().valueOf()"""
    return int(time.time() * 1000)


@pytest.fixture
def package():
    """
    Create (and tear down) the require directory structure for a sputnik-managed model:
    .
    └── sputnik_sample
        ├── data
        │   └── model
        └── package.json

     Then package an archive containing all data in preparation for upload to AWS
    """
    settings = {
        'name': 'orbital_test_model',
        'description': 'This is a demo model, but it is still awesome.',
        'include': [['data', '*']],
        'version': '2.0.0',
        'license': 'Proprietary',
        'compatibility': {
            'my_library': '>=0.6.1'
        }
    }
    _clean_up()

    os.makedirs(os.path.join(SAMPLE_DIR, DATA_DIR))

    with open(os.path.join(SAMPLE_DIR, JSON_FILE), 'w') as outf:
        json.dump(settings, outf)

    # The 'model' is just a timestamp. We'll use it to verify what we've downloaded is the same
    # as what we've just uploaded
    with open(os.path.join(SAMPLE_DIR, DATA_DIR, MODEL_DIR), 'w') as outf:
        outf.write('%d' % timestamp())

    # do this when model is trained
    yield sputnik.build(SAMPLE_DIR)

    _clean_up()


def test_upload_download_round_trip(package):
    """
    Build an example model, package it, upload to AWS, remove local version, download from AWS
    and check contents
    :param package:
    """
    patch_sputnik()
    sputnik.upload('myapp', '1.0.0', package.path,
                   data_path=INSTALL_DIR)

    _clean_up()
    # at this stage all local data must be gone, so we are really testing AWS integration

    package_name_and_version = '%s==%s' % (package.name, package.version)

    # download model from AWS
    sputnik.install('my_library', '1.0.0', package_name_and_version,
                    data_path=INSTALL_DIR)

    # load model from disk
    package = sputnik.package('my_library', '1.0.0', package_name_and_version,
                              data_path=INSTALL_DIR)

    with package.open(['data', 'model'], mode='r', encoding='utf8') as f:
        date = f.read()

    # The model we downloaded must be recent (less than a few seconds).
    assert timestamp() - int(date) < 15000
