
import os
import click
import requests
from os.path import join, dirname, splitext

from harvest_cli import cli

BASE_PATH = dirname(dirname(__file__))
INDEX_TEMPLATE_DIR = join(BASE_PATH, 'index_templates')


@cli.group()
def setup():
    pass


@setup.command()
@click.option('--es-host', envvar="ES_HOST")
def load_index_templates(es_host):
    templates = [x for x in os.listdir(INDEX_TEMPLATE_DIR)
                 if x.endswith('.json')]
    for t in templates:
        file_path = join(INDEX_TEMPLATE_DIR, t)
        index_name, ext = splitext(t)
        url = "http://%s/_template/dce-%s" % (es_host, index_name)
        with open(file_path, 'rb') as f:
            requests.put(url, data=f)


