#!/usr/bin/env python

import json
import boto3
import click
import arrow
import redis
from os import getenv
from pyhorn.endpoints.search import SearchEpisode

import re

import pyhorn
# force all calls to the episode search endpoint to use includeDeleted=true
pyhorn.endpoints.search.SearchEndpoint._kwarg_map['episode']['includeDeleted'] = True

import time
from botocore.exceptions import ClientError

from harvest_cli import cli
from .utils import es_connection, get_mpids_from_useractions

MAX_START_END_SPAN = getenv('MAX_START_END_SPAN')
EPISODE_CACHE_EXPIRE = getenv('EPISODE_CACHE_EXPIRE', 1800) # default to 15m

import logging
logger = logging.getLogger(__name__)

sqs = boto3.resource('sqs', region_name='us-east-1')
s3 = boto3.resource('s3')
r = redis.StrictRedis()

@cli.command()
@click.option('-s', '--start', help='YYYYMMDDHHmmss')
@click.option('-e', '--end', help='YYYYMMDDHHmmss; default=now')
@click.option('-w', '--wait', default=1,
              help="Seconds to wait between batch requests")
@click.option('-H', '--engage_host', envvar='MATTERHORN_ENGAGE_HOST',
              help="Matterhorn engage hostname", required=True)
@click.option('-u', '--user', envvar='MATTERHORN_REST_USER',
              help='Matterhorn rest user', required=True)
@click.option('-p', '--password', envvar='MATTERHORN_REST_PASS',
              help='Matterhorn rest password', required=True)
@click.option('-o', '--output', default='sqs',
              help='where to send output. use "-" for json/stdout')
@click.option('-q', '--queue-name', envvar='SQS_QUEUE_NAME',
              help='SQS queue name', required=True)
@click.option('-b', '--batch-size', default=1000,
              help='number of actions per request')
@click.option('-i', '--interval', envvar='DEFAULT_INTERVAL', default=2,
              help='Harvest action from this many minutes ago')
@click.option('--disable-start-end-span-check', is_flag=True,
              help="Don't abort on too-long start-end time spans")
def useractions(start, end, wait, engage_host, user, password, output, queue_name,
                 batch_size, interval, disable_start_end_span_check):

    # we rely on our own redis cache, so disable pyhorn's internal response caching
    mh = pyhorn.MHClient('http://' + engage_host, user, password,
                         timeout=30, cache_enabled=False)

    if output == 'sqs':
        queue = get_or_create_queue(queue_name)

    if end is None:
        end = arrow.now().format('YYYYMMDDHHmmss')

    last_action_ts_key = getenv('S3_LAST_ACTION_TS_KEY')
    if start is None:
        start = get_harvest_ts(last_action_ts_key)
        if start is None:
            start = arrow.now() \
                .replace(minutes=-interval) \
                .format('YYYYMMDDHHmmss')

    logger.info("Fetching user actions from %s to %s", start, end)

    start_end_span = arrow.get(end, 'YYYYMMDDHHmmss') - arrow.get(start, 'YYYYMMDDHHmmss')
    logger.info("Start-End time span in seconds: %d", start_end_span.seconds,
             extra={'start_end_span_seconds': start_end_span.seconds})

    if MAX_START_END_SPAN is not None and not disable_start_end_span_check:
        if start_end_span.seconds > MAX_START_END_SPAN:
            logger.error("Start-End time span %d is larger than %d",
                      start_end_span.seconds,
                      MAX_START_END_SPAN
                      )
            raise click.Abort()

    offset = 0
    batch_count = 0
    action_count = 0
    fail_count = 0
    last_action = None

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

        for action in actions:
            last_action = action
            try:
                rec = create_action_rec(action)
                if output == 'sqs':
                    queue.send_message(MessageBody=json.dumps(rec))
                else:
                    print json.dumps(rec)
            except Exception as e:
                logger.error("Exception during rec creation for %s: %s", action.id, str(e))
                fail_count += 1
                continue

        time.sleep(wait)
        offset += batch_size

    logger.info("Total actions: %d, total batches: %d, total failed: %d",
             action_count, batch_count, fail_count,
             extra={
                 'actions': action_count,
                 'batches': batch_count,
                 'failures': fail_count
             })

    try:
        if action_count == 0:
            last_action_ts = end
        else:
            last_action_ts = arrow.get(last_action.created).format('YYYYMMDDHHmmss')
        set_harvest_ts(last_action_ts_key, last_action_ts)
        logger.info("Setting last action timestamp to %s", last_action_ts)
    except Exception, e:
        logger.error("Failed setting last action timestamp: %s", str(e))

def create_action_rec(action):

    is_playing = False
    if action.isPlaying > 0:
        is_playing = True

    rec = {
        'action_id': action.id,
        'timestamp': str(arrow.get(action.created).to('utc')),
        'mpid': action.mediapackageId,
        'session_id': action.sessionId['sessionId'],
        'huid': str(action.sessionId.get('userId')),
        'useragent': action.sessionId.get('userAgent'),
        'action': {
            'type': action.type,
            'inpoint': action.inpoint,
            'outpoint': action.outpoint,
            'length': action.length,
            'is_playing': is_playing
        }
    }

    ips = [x.strip() for x in action.sessionId['userIp'].split(',')]
    rec['ip'] = ips.pop(0)
    for idx, ip in enumerate(ips, 1):
        rec['proxy%d' % idx] = ip

    episode = get_episode(action)

    rec['is_live'] = 0
    if action.isPlaying == 2:
        rec['is_live'] = 1

    rec['episode'] = {}

    if episode is None:
        logger.warning("Missing episode for action %s", action.id)
    else:
        rec['episode'] = {
            'title': episode.mediapackage.title,
            'duration': int(episode.mediapackage.duration),
            'start': episode.mediapackage.start
        }

        try:
            series = str(episode.mediapackage.series)
            rec['episode'].update({
                'course': episode.mediapackage.seriestitle,
                'series': series,
                'year': series[:4],
                'term': series[4:6],
                'cdn': series[6:11]
            })
        except AttributeError:
            logger.warning("Missing series for episode %s", episode.id)

        try:
            rec['episode']['type'] = episode.dcType
        except AttributeError:
            pass

        try:
            rec['episode']['description'] = episode.dcDescription
        except AttributeError:
            pass

    return rec

def get_episode(action):
    cached_ep = r.get(action.mediapackageId)
    if cached_ep is not None:
        logger.debug("episode cache hit for %s", action.mediapackageId)
        episode_data = json.loads(cached_ep)
        episode_data['__from_cache'] = True
        # recreate the SearchEpisode obj using the current client
        episode = SearchEpisode(episode_data, action.client)
        # make sure anything else that might access the action.episode property
        # gets our cached version
        action._property_stash['episode'] = episode
    else:
        logger.debug("episode cache miss for %s", action.mediapackageId)
        episode = action.episode
        r.setex(
            action.mediapackageId,
            EPISODE_CACHE_EXPIRE,
            json.dumps(episode._raw)
        )
    return episode


@cli.command()
@click.option('-A', '--admin-host', envvar='MATTERHORN_ADMIN_HOST',
              help="Matterhorn admin hostname", required=True)
@click.option('-E', '--engage-host', envvar='MATTERHORN_ENGAGE_HOST',
              help="Matterhorn engage hostname", required=True)
@click.option('-u', '--user', envvar='MATTERHORN_REST_USER',
              help='Matterhorn rest user', required=True)
@click.option('-p', '--password', envvar='MATTERHORN_REST_PASS',
              help='Matterhorn rest password', required=True)
@click.option('-e', '--es-host', envvar='ES_HOST',
              help="Elasticsearch host:port", default='localhost:9200')
@click.option('-t', '--target-index', default="episodes",
              help="name of index the episodes will be written to; defaults to 'episodes'")
@click.option('-s', '--source-index-pattern', help=("useraction index pattern to query for mpids; "
                "e.g. 'useractions*-2017.10.*'; defaults to yesterday's index"))
@click.option('--mpid', help="Index a specific mediapackage")
@click.option('-w', '--wait', default=1, help="Seconds to wait between batch requests")
def load_episodes(admin_host, engage_host, user, password, es_host, target_index, source_index_pattern, mpid, wait):

    mh_engage = pyhorn.MHClient('http://' + engage_host, user, password, timeout=30)
    mh_admin = pyhorn.MHClient('http://' + admin_host, user, password, timeout=30)
    es = es_connection(es_host)

    if mpid is not None:
        mpids = [mpid]
    else:
        if source_index_pattern is None:
            source_index_pattern = "useractions*-%s" % arrow.now().replace(days=-1).format("YYYY.MM.DD")
        mpids = get_mpids_from_useractions(es, source_index_pattern)

    for mpid in mpids:
        request_params = {
            'id': mpid,
            'includeDeleted': True,
        }

        episodes = mh_engage.search_episodes(**request_params)

        if len(episodes) > 1:
            logger.warning("fetched > 1 episodes for mpid %s", mpid)
            continue
        else:
            ep = episodes[0]

        doc = {
            'title': ep.mediapackage.title,
            'mpid': ep.mediapackage.id,
            'duration': int(ep.mediapackage.duration),
            'start': str(arrow.get(ep.mediapackage.start).to('utc'))
        }

        try:
            series = str(ep.mediapackage.series)
            doc.update({
                'course': ep.mediapackage.seriestitle,
                'series': series,
                'year': series[:4],
                'term': series[4:6],
                'crn': series[6:11]
            })
        except AttributeError:
            logger.warning("Missing series for episode %s", ep.id)

        try:
            doc['type'] = ep.dcType
        except AttributeError:
            logger.warning("Missing type for episode %s", ep.id)

        try:
            doc['description'] = ep.dcDescription
        except AttributeError:
            logger.warning("Missing description for episode %s", ep.id)

        attachments = ep.mediapackage.attachments
        if isinstance(attachments, dict):
            try:
                attachments = attachments['attachment']

                for preview_type in ['presenter', 'presentation']:
                    try:
                        preview = next(a for a in attachments if a['type'] == '%s/player+preview' % preview_type)
                        doc['%s_still' % preview_type] = preview['url']
                    except StopIteration:
                        pass

                doc['slides'] = [{
                    'img': a['url'],
                    'time': re.search('time=([^;]+)', a['ref']).group(1)
                } for a in attachments if a['type'] == 'presentation/segment+preview']

            except Exception, e:
                logger.error("Failed to extract attachement info from episode %s: %s", ep.id, str(e))

            try:
                wfs = mh_admin.workflows(
                    mp=ep.mediapackage.id,
                    state='SUCCEEDED',
                    workflowdefinition='DCE-archive-publish-external'
                )

                if len(wfs) == 0:
                    raise RuntimeError("No workflow found for mpid %s" % ep.mediapackage.id)
                else:
                    # take the most recent one; fyi sort args for workflow API lookups don't actually work
                    wf = sorted(wfs, key=lambda x: int(x.id))[-1]

                ops = wf.operations

                try:
                    capture = next(x for x in ops if x.id == 'capture')
                    doc.update({
                        'live_stream': 1,
                        'live_start': str(arrow.get(capture.started / 1000)),
                        'live_end': str(arrow.get(capture.completed / 1000)),
                        'live_duration': capture.completed - capture.started
                    })
                except StopIteration:
                    doc['live_stream'] = 0

                try:
                    retract = next(x for x in ops if x.id == 'retract-element')
                    doc['available'] = str(arrow.get(retract.completed / 1000))
                except StopIteration:
                    pass

            except IndexError:
                logger.info("No matching or finished workflow found for %s: %s", ep.id, ep.mediapackage.title)
            except Exception, e:
                logger.error("Failed extracting workflow data for episode %s: %s", ep.id, str(e))

            es.index(index=target_index,
                     doc_type='episode',
                     id=mpid,
                     body=doc
                     )

        time.sleep(wait)

# s3 state bucket helpers
def set_harvest_ts(ts_key, timestamp):
    bucket = get_or_create_bucket()
    bucket.put_object(Key=ts_key, Body=timestamp)

def get_harvest_ts(ts_key):
    bucket = get_or_create_bucket()
    try:
        obj = bucket.Object(ts_key).get()
        return obj['Body'].read()
    except ClientError:
        logger.debug("No %s value found", ts_key)
        return None

def get_or_create_bucket():

    bucket_name = getenv('S3_HARVEST_TS_BUCKET')
    if bucket_name is None:
        raise RuntimeError("No timestamp bucket specified!")

    try:
        s3.meta.client.head_bucket(Bucket=bucket_name)
        return s3.Bucket(bucket_name)
    except ClientError:
        return s3.create_bucket(Bucket=bucket_name)

def get_or_create_queue(queue_name):
    try:
        return sqs.get_queue_by_name(QueueName=queue_name)
    except ClientError:
        return sqs.create_queue(QueueName=queue_name)


if __name__ == '__main__':
    cli()
