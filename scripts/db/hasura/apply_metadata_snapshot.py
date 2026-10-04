#!/usr/bin/env python
from glob import glob
import os
import sys
import time
import yaml

import requests

from pylib.base.flags import Flags
from pylib.file.file_utils import FileUtils

from log import LOG

HEALTH_ATTEMPTS = 30
HEALTH_INTERVAL_SECONDS = 5
METADATA_FOLDER = FileUtils.GetAbsPathForFile('graphql/hasura/metadata/versions/latest')


def build_metadata_dict():
    '''Convert the YAML metadata files exported using the hasura command line tools
    (how we export it in development) into a dictionary. This dictionary matches the
    format required by the Hasura metadata API endpoints.
    '''
    output = {}

    # Loop over each metadata file and add it to the combined output dictionary.
    for metadata_file in sorted(glob(f'{METADATA_FOLDER}/*.yaml')):
        with open(metadata_file) as input_file:
            data = yaml.load(input_file, Loader=yaml.Loader)

            # If the data is a dict, then we should merge it with the output object
            # directly. The keys in the data dictionary should be top level keys in the
            # output dict.
            if isinstance(data, dict):
                output.update(data)
                continue

            # All other types should be assigned to the output dictionary using the
            # filename (without the .yaml suffix) as the key.
            key = os.path.splitext(os.path.basename(metadata_file))[0]
            output[key] = data
    return output


def wait_for_hasura(hasura_host):
    for attempt in range(HEALTH_ATTEMPTS):
        try:
            if requests.get(f'{hasura_host}/healthz', timeout=10).ok:
                return True
        except requests.exceptions.ConnectionError:
            pass
        LOG.info(
            'Waiting for hasura at %s (attempt %s of %s)',
            hasura_host,
            attempt + 1,
            HEALTH_ATTEMPTS,
        )
        time.sleep(HEALTH_INTERVAL_SECONDS)
    return False


def main():
    Flags.PARSER.add_argument(
        '--hasura_host', type=str, required=True, help='Hasura host'
    )
    Flags.InitArgs()

    hasura_admin_secret = os.environ.get('HASURA_ADMIN_SECRET')
    if not hasura_admin_secret:
        LOG.error('HASURA_ADMIN_SECRET must be set to apply hasura metadata.')
        return 1

    hasura_host = Flags.ARGS.hasura_host
    hasura_metadata_api_endpoint = f'{hasura_host}/v1/metadata'
    if not wait_for_hasura(hasura_host):
        LOG.error('Hasura at %s did not become healthy.', hasura_host)
        return 1

    LOG.info('Starting hasura metadata processing.')
    res = requests.post(
        hasura_metadata_api_endpoint,
        headers={'X-Hasura-Admin-Secret': hasura_admin_secret},
        json={'type': 'replace_metadata', 'args': build_metadata_dict()},
        timeout=120,
    )
    if res.status_code != 200:
        LOG.error(
            'Failed to apply metadata to %s with status code %s: %s',
            hasura_metadata_api_endpoint,
            res.status_code,
            res.text,
        )
        return 1

    LOG.info('Successfully applied metadata to %s', hasura_metadata_api_endpoint)
    return 0


if __name__ == '__main__':
    sys.exit(main())
