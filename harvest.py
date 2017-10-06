#!/usr/bin/env python

from os.path import join, dirname
from dotenv import load_dotenv
from harvest_cli import cli

load_dotenv(join(dirname(__file__), '.env'))

if __name__ == '__main__':
    cli()
