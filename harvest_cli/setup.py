
import os
import click
import requests
from os.path import join, dirname, splitext

from harvest_cli import cli
from .utils import es_connection

BASE_PATH = dirname(dirname(__file__))
INDEX_TEMPLATE_DIR = join(BASE_PATH, 'index_templates')


@cli.group()
def setup():
    pass


@setup.command()
@click.option('--es-host', envvar="ES_HOST")
def load_index_templates(es_host):
    es = es_connection(es_host)
    templates = [x for x in os.listdir(INDEX_TEMPLATE_DIR)
                 if x.endswith('.json')]
    for t in templates:
        file_path = join(INDEX_TEMPLATE_DIR, t)
        template_name, ext = splitext(t)
        with open(file_path, 'rb') as f:
            es.indices.put_template(name=template_name, body=f.read())


