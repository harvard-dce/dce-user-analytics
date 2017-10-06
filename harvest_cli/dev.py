
import os
import click
from time import sleep
import docker as dockerpy
from subprocess import call
from os.path import join, dirname
from elasticsearch import Elasticsearch

from harvest_cli import cli
from .setup import load_index_templates

BASE_PATH = dirname(dirname(__file__))
DOCKER_PATH = join(BASE_PATH, 'docker')
DOCKER_COMPOSE_FILE = join(DOCKER_PATH, 'docker-compose.yml')


@cli.group()
def dev():
    pass

@dev.command()
@click.option('--es-host', envvar="ES_HOST")
@click.pass_context
def init(ctx, es_host):
    ctx.invoke(up)
    ctx.invoke(install_kopf)

    es = Elasticsearch([es_host])
    while True:
        try:
            info = es.info()
            break
        except:
            click.echo("waiting for elasticsearch to be available...")
            sleep(.5)

    ctx.invoke(load_index_templates, es_host=os.getenv("ES_HOST"))


@dev.command()
@click.option('--compose-file', default=DOCKER_COMPOSE_FILE)
def up(compose_file):

    click.echo("Running docker-compose up")
    cmdline = ['docker-compose', '-f', compose_file, 'up', '-d']
    call(cmdline)


@dev.command()
def install_kopf():

    # get the elasticsearch container
    docker_client = dockerpy.from_env()
    try:
        es_container = next(x for x in docker_client.containers.list()
                            if 'elasticsearch' in x.name)
        click.echo("Installing kopf plugin")
        exec_inst = docker_client.api.exec_create(
            es_container.id, "bin/plugin install lmenezes/elasticsearch-kopf")
        docker_client.api.exec_start(exec_inst)
    except StopIteration:
        click.echo("Elasticsearch container doesn't appear to be running",
                   err=True, color="magenta")
        raise click.Abort()


@dev.command()
@click.option('--compose-file', default=DOCKER_COMPOSE_FILE)
def down(compose_file):

    click.echo("Running docker-compose down")
    cmdline = ['docker-compose', '-f', compose_file, 'down']
    call(cmdline)

