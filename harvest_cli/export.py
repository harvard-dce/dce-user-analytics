import six
import sys
import click
import logging
import requests
import itertools
from time import sleep
from math import ceil
from csv import DictWriter
from elasticsearch_dsl import Search, Q

if six.PY2:
    from urlparse import urljoin
else:
    from urllib.parse import urljoin

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from harvest_cli import cli
from .utils import es_connection, get_episodes_for_term, get_series_for_term

logger = logging.getLogger(__name__)


@cli.group()
def export():
    pass


@export.command()
@click.option("--es_host", envvar="ES_HOST")
@click.option('--term')
@click.option('--year')
def viewing_options(es_host, term, year):
    es = es_connection(es_host)
    mps = get_episodes_for_term(es, term, year, fields=['mpid'])

    event_aggs = {
        "aggs": {
            "huid": {
                "terms": {
                    "size": 100,
                    "field": "huid"
                },
                "aggs": {
                    "paella_events": {
                        "filters": {
                            "filters": {
                                "view_mode": {
                                    "term": {
                                        "action.type": "paella:button:action;edu.harvard.dce.paella.viewModeTogglePlugin"
                                    }
                                },
                                "playback_speed": {
                                    "term": {
                                        "action.type": "paella:button:action;es.upv.paella.playbackRatePlugin"
                                    }
                                },
                                "captions": {
                                    "wildcard": {
                                        "action.type": "paella:caption:enabled*"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    writer = DictWriter(
        sys.stdout,
        fieldnames=['mpid', 'huid', 'captions', 'playback_speed', 'view_mode']
    )
    writer.writeheader()

    for mp in mps:
        s = Search(using=es, index='useractions-*').extra(size=0)
        s = s.filter(
            Q('term', mpid=mp.mpid) & ~Q('term', huid='anonymous')
        )
        s.update_from_dict(event_aggs)
        res = s.execute().to_dict()
        for huid_bucket in res['aggregations']['huid']['buckets']:
            huid = huid_bucket['key']
            row = {'mpid': mp.mpid, 'huid': huid}
            for event_type, stats in huid_bucket['paella_events']['buckets'].items():
                row[event_type] = stats['doc_count']
            writer.writerow(row)


@export.command()
@click.option("--es_host", envvar="ES_HOST")
@click.option('--term')
@click.option('--year')
@click.option('--chunk-interval', type=int, default=300)
@click.option('--live/--no-live', default=False)
def attendance(es_host, term, year, chunk_interval, live):
    es = es_connection(es_host)
    mps = get_episodes_for_term(es, term, year, fields=['mpid', 'duration'])

    attendance_column = live and 'live_attendance' or 'vod_attendance'
    duration_attr = live and 'live_duration' or 'duration'

    writer = DictWriter(
        sys.stdout,
        fieldnames=['mpid', 'huid', attendance_column]
    )
    writer.writeheader()

    for mp in mps:
        s = Search(using=es, index='useractions-*').extra(size=0)
        s = s.filter(
            Q('term', mpid=mp.mpid) &
            Q('term', is_live=int(live)) &
            Q('term', **{'action.is_playing': True}) &
            Q('term', **{'action.type': 'HEARTBEAT'}) &
            ~Q('term', huid='anonymous')
        )
        s.aggs.bucket(
            name='huid',
            agg_type='terms',
            field='huid',
            size=0
        )
        s.aggs['huid'].bucket(
            name='inpoints',
            agg_type='histogram',
            field='action.inpoint',
            interval=str(chunk_interval),
            min_doc_count=1
        )

        res = s.execute().to_dict()
        duration = getattr(mp, duration_attr, None)

        if duration is None:
            logger.warning(
                "'%s' is missing for mpid %s", duration_attr, mp.mpid
            )
            continue

        total_intervals = ceil((mp.duration / 1000) / chunk_interval)

        if total_intervals == 0:
            logger.warning("zero intervals for mpid %s", mp.mpid)
            continue

        for huid in res['aggregations']['huid']['buckets']:
            interval_buckets = len(huid['inpoints']['buckets'])

            pct_watched = int(100.0 * (interval_buckets / total_intervals))
            row = {
                'huid': huid['key'],
                'mpid': mp.mpid,
                attendance_column: pct_watched
            }
            writer.writerow(row)

        sleep(.05)


@export.command()
@click.option("--es_host", envvar="ES_HOST")
@click.option("--banner", envvar='BANNER_ENDPOINT_BASE')
@click.option('--term')
@click.option('--year')
def rollcall(es_host, banner, term, year):
    banner = Banner(banner)
    es = es_connection(es_host)
    series = get_series_for_term(es, term, year)

    writer = DictWriter(
        sys.stdout,
        extrasaction='ignore',
        fieldnames=['series', 'huid', 'status', 'first_name', 'mi', 'last_name', 'reg_level']
    )
    writer.writeheader()

    for series_id in series:
        crn = series_id[6:]
        people = banner.get_course_people(term, year, crn)
        for person in people:
            # no middle initial value is represented by an empty dict
            if not isinstance(person['mi'], basestring):
                person['mi'] = ''
            person['series'] = series_id
            writer.writerow(person)
        sleep(1)


class Banner(object):

    def __init__(self, endpoint_base):

        self.endpoint_base = endpoint_base

    def get_course_people(self, term, year, crn):

        params = {
            'fmt': 'json',
            'term': year + term,
            'crn': crn
        }

        endpoint_url = urljoin(self.endpoint_base, '__get_course_people.php')
        resp = requests.get(endpoint_url, params=params)
        resp_data = resp.json()

        if 'people' not in resp_data:
            return []

        groups = []
        for group in resp_data['people'].values():
            if isinstance(group, list):
                groups.append(group)
            elif isinstance(group, dict):
                groups.append([group])
        return list(itertools.chain.from_iterable([x for x in groups]))
