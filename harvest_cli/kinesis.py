#!/usr/bin/env python

import json
import click
import arrow
import pyhorn
import hashlib
from os import getenv
import requests
from time import sleep
from requests_futures.sessions import FuturesSession

from harvest_cli import cli
from utils import AcidCookie

import logging
logger = logging.getLogger(__name__)

@cli.command()
@click.option('--start', help='YYYYMMDDHHmmss')
@click.option('--end', help='YYYYMMDDHHmmss; default=now')
@click.option('--wait', default=1,
              help="Seconds to wait between batch requests")
@click.option('--engage_host', envvar='MATTERHORN_ENGAGE_HOST',
              help="Matterhorn engage hostname", required=True)
@click.option('--user', envvar='MATTERHORN_REST_USER',
              help='Matterhorn rest user', required=True)
@click.option('--password', envvar='MATTERHORN_REST_PASS',
              help='Matterhorn rest password', required=True)
@click.option('--interval', envvar='DEFAULT_INTERVAL', default=2,
              help='Harvest action from this many minutes ago')
@click.option('--stream-endpoint',
              help='api gateway endpoint to post events to')
@click.option('--batch-size', type=int, default=100,
              help='number of events per request')
@click.option('--workers', type=int, default=8,
              help='use this many requests_futures worker threads')
def kinesis(start, end, wait, engage_host, user, password,
                interval, stream_endpoint, batch_size, workers):

    acid_cookie_key = getenv('ACID_COOKIE_KEY')

    # we rely on our own redis cache, so disable pyhorn's internal response caching
    mh = pyhorn.MHClient('http://' + engage_host, user, password,
                         timeout=30, cache_enabled=False)

    if end is None:
        end = arrow.now().format('YYYYMMDDHHmmss')

    if start is None:
        start = arrow.now() \
            .replace(minutes=-interval) \
            .format('YYYYMMDDHHmmss')

    logger.info("Fetching user actions from %s to %s", start, end)

    offset = 0
    batch_count = 0
    action_count = 0
    fail_count = 0

    ac = AcidCookie(acid_cookie_key)
    s = FuturesSession(max_workers=workers)

    def make_cookie(action):
        jsessionid = action.sessionId.get("sessionId")
        userId = action.sessionId.get("userId")
        acid_cookie_params = {
            'huid': hashlib.md5(acid_cookie_key + str(userId)).hexdigest(),
            'type': 'HASHED_HUID'
        }
        acid_cookie = ac.encrypt(acid_cookie_params)
        return "JSESSIONID={}; acid={}".format(jsessionid, acid_cookie)


    while True:

        req_params = {
            'start': start,
            'end': end,
            'limit': batch_size,
            'offset': offset
        }

        try:
            actions = mh.user_actions(**req_params)
        except Exception, e:
            logger.error("API request failed: %s", str(e))
            raise

        if len(actions) == 0:
            logger.info("No more actions")
            break

        batch_count += 1
        action_count += len(actions)
        logger.info("Batch %d: %d actions", batch_count, len(actions))

        future_reqs = []
        for action in actions:
            try:
                event_params = {
                    "id": action.mediapackageId,
                    "type": action.type,
                    "in": action.inpoint,
                    "out": action.outpoint,
                    "playing": action.isPlaying,
                    "ip": action.sessionId.get('userIp')
                }
                headers = {
                    'Cookie': make_cookie(action),
                    'User-Agent': action.sessionId.get('userAgent'),
                }

                if stream_endpoint is not None:
                    future_req = s.get(stream_endpoint, params=event_params, headers=headers)
                    future_reqs.append(future_req)
                else:
                    print json.dumps({
                        "event_params": event_params,
                        "headers": headers
                    }, indent=True)
            except Exception as e:
                logger.error("Exception during event creation for %s: %s", action.id, str(e))
                fail_count += 1
                raise

        for fr in future_reqs:
            resp = fr.result()
            resp.raise_for_status()

        sleep(wait)
        offset += batch_size

    logger.info("Total actions: %d, total batches: %d, total failed: %d",
             action_count, batch_count, fail_count,
             extra={
                 'actions': action_count,
                 'batches': batch_count,
                 'failures': fail_count
             })



if __name__ == '__main__':
    cli()