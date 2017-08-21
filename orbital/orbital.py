"""
This module contains code derived from sputnik: https://github.com/explosion/sputnik/

Original License
-----------------
The MIT License (MIT)

Copyright (C) 2015 Henning Peters
              2016 spaCy GmbH
              2016 ExplosionAI UG (haftungsbeschränkt)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

History
--------
Miroslav Batchkarov, Skim.it, November 2016

Functions `_sputnik_index_update`, `_sputnik_cache_fetch` and `_sputnik_index_upload` are derived
from sputnik v0.9.3. They have been modified to interact directly with Amazon S3 without an
intermediate REST API, and to compute MD5 hashes of downloaded files in chunks to keep memory
usage independent of file size.

"""
import hashlib
import io
import json
import logging
import os

from orbital import sputnik # import from here to ensure sputnik is patched
from boto.s3.connection import S3Connection
from sputnik import Archive
from sputnik import Cache

# models are stores at S3_BUCKET_NAME/S3_SUBDIR_NAME
S3_BUCKET_NAME = os.getenv('BUCKET', 'my-sputnik-models')
S3_SUBDIR_NAME = 'models/'


def _get_s3_bucket():
    """
    Get the S3 bucket where models are stored. For this to succeed the user must be authenticated
    using one of the standard boto methods, such as ~/.boto or env variables.

    See http://boto.cloudhackers.com/en/latest/boto_config_tut.html#details
    """
    conn = S3Connection()
    return conn.get_bucket(S3_BUCKET_NAME, validate=False)  # TODO validate?


def _get_file_hash(afile, hasher, blocksize=65536):
    """
    Compute the hash of a file in chunks, keeping memory usage low.
    Source: http://stackoverflow.com/a/3431835/419338
    :param afile: an open file handle
    :param hasher: hasher instance to use, e.g. hashlib.md5(). needs to support update
    :param blocksize: size of chunk
    :return:
    """
    buf = afile.read(blocksize)
    while len(buf) > 0:
        hasher.update(buf)
        buf = afile.read(blocksize)
    return hasher.hexdigest()


def progress_callback(bytes_completed, total_bytes):
    megabytes = bytes_completed / (1024.0 * 1024.0)
    percent = (bytes_completed * 100.0) / total_bytes
    logging.info('~%1.1f MB transferred (%1.1f%%)' % (megabytes, percent))


def _sputnik_index_update(self, **kwargs):
    """
    Build a list of available packages on the server
    """
    cache = Cache(self.app_name, self.app_version, self.data_path)

    # remember cached packages for removal
    packages = cache.find()

    # index = json.load(session.open(request, 'utf8'))
    bucket = _get_s3_bucket()

    index = {}
    for key in bucket.list(S3_SUBDIR_NAME):
        if key.name.endswith('meta.json'):
            package_name = key.name.split('/')[1]
            index[package_name] = (key.name, key.etag[1:-1])

    for ident, (meta_url, package_hash) in index.items():
        if not cache.exists(ident, package_hash):
            meta = io.BytesIO()
            bucket.get_key(meta_url).get_contents_to_file(meta)
            meta = json.loads(meta.getvalue().decode('utf8'))
            cache.update(meta, url=meta_url, etag=package_hash)

        # shrink list by one
        packages = [p for p in packages if p.ident != ident]

    # remove leftovers
    for package in packages:  # pragma: no cover
        package.remove()


def _sputnik_cache_fetch(self, package_string):
    """
    Download a package from S3 to a local cache directory
    :param package_string: e.g. "mypackage==1.2.1"
    """
    package = self.get(package_string)
    path, meta_checksum, url = package.meta['archive'][:3]

    full_path = os.path.join(package.path, path)
    sputnik.util.makedirs(full_path)

    key = _get_s3_bucket().get_key(url)
    key.get_contents_to_filename(full_path, cb=progress_callback)
    key_checksum = key.md5.decode('utf-8')
    # TODO does not support resume like sputnik's original Session object

    with open(full_path, 'rb') as infile:
        local_checksum = _get_file_hash(infile, hashlib.md5())
        assert local_checksum == key_checksum, 'checksum mismatch with s3 key object'
        assert local_checksum == meta_checksum, 'checksum mismatch with meta object'

    return Archive(package.path)


def _sputnik_index_upload(self, path):
    """
    Upload package to S3
    """
    bucket = _get_s3_bucket()

    # to allow random access we upload each archive member individually
    archive = Archive(path)
    for key_name, f in archive.fileobjs().items():
        self.logger.info('preparing upload for %s', key_name)
        headers = {
            sputnik.util.s3_header('md5'): _get_file_hash(f, hashlib.md5())
        }
        f.seek(os.SEEK_SET, 0)

        self.logger.info('uploading %s...', key_name)
        key = bucket.new_key((S3_SUBDIR_NAME + '%s') % key_name)
        key.set_contents_from_file(f, headers=headers, cb=progress_callback)


def patch_sputnik():
    """
    Monkey-patches sputnik so data is stored on S3 directly. Original sputnik assumes a RESTful API
    exists at URL with the following endpoints:

     - GET URL/models
     - GET URL/<model-name>
     - PUT URL/<model-name>

    This API serves as an intermediary between sputnik and a bunch of files on the server. See
    "http://index.spacy.io/" for an example. This patched version does not need this API, but
    instead simulates it by querying S3 via boto and reconstructing a list of packages available
    in a bucket on S3
    """
    from boto.provider import Provider
    # this is what boto uses get credentials if they are not explicitly provided
    # an exception will be raised if no credentials are provided
    Provider('aws').get_credentials()

    sputnik.index.Index.update = _sputnik_index_update
    sputnik.index.Index.upload = _sputnik_index_upload
    sputnik.cache.Cache.fetch = _sputnik_cache_fetch
