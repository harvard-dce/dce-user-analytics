
import click
import logging
logging.basicConfig()

click.disable_unicode_literals_warning = True

__version__ = '0.1.0'

logger = logging.getLogger()

@click.group()
@click.option('--log-level', default='info',
              type=click.Choice(['info','debug','warn']))
def cli(log_level):
    logger.setLevel(getattr(logging, log_level.upper()))

from .zoom import zoom
from .setup import setup
from .dev import dev
from .ocua import useractions, load_episodes
