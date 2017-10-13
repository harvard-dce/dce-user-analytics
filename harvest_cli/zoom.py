#!/usr/bin/env python

import json
import time
import click
import requests
from datetime import timedelta, datetime
from elasticsearch.helpers import bulk as index_bulk

from .utils import es_connection
from harvest_cli import cli

import logging
logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.zoom.us/v1"

def yesterday(ctx, param, value):
    if value is None:
        return (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        return value


@cli.command()
@click.option("--date", callback=yesterday,
              help="fetch for date, e.g. YYYY-mm-dd; defaults to yesterday.")
@click.option("--destination", type=click.Choice(['index','stdout']),
              help="defaults to 'index'", default="index")
@click.option("--es_host", envvar="ES_HOST", default="localhost:9200",
              help="Elasticsearch host:port; defaults to $ES_HOST")
@click.option("--key", envvar="ZOOM_KEY",
              help="zoom api key; defaults to $ZOOM_KEY")
@click.option("--secret", envvar="ZOOM_SECRET",
              help="zoom api secret; defaults to $ZOOM_SECRET")
def zoom(date, destination, es_host, key, secret):

    if destination == 'index':
        es = es_connection(es_host)

    try:
        meeting_data = get_sessions_from(date, key, secret)

        for meeting_doc, session_docs in meeting_data:
            if destination == 'index':
                es.index(
                    index="meetings",
                    doc_type="meeting",
                    body=meeting_doc,
                    id=meeting_doc['uuid']
                )
                session_actions = [
                    dict(
                        _index='sessions',
                        _type='session',
                        _id=s['meeting'] + s['user_id'],
                        **s
                    ) for s in session_docs
                ]
                index_bulk(es, session_actions)
            else:
                click.echo(json.dumps(meeting_doc))
                for s in session_docs:
                    click.echo(json.dumps(s))

    except OSError as e:
        logger.error("Destination error: %s" % str(e))
    except requests.HTTPError as e:
        logger.error("Error making API request: %s" % str(e))
    except ZoomApiException as e:
        logger.error("The API returned an error response: %s" % str(e))
    except KeyboardInterrupt:
        logger.info("Quitting")
        raise click.Abort()


class ZoomApiException(Exception):
    pass


def fetch_records(report_url, params, listkey, countkey='total_records', wait=1):
    params = params.copy()
    records = []
    logger.debug("get %s" % report_url)

    while True:
        logger.debug("params %s" % str(params))

        r = requests.post(url=API_BASE_URL + report_url, data=params)
        r.raise_for_status()
        response = r.json()

        if 'error' in response.keys():
            error_code = response['error']['code']
            error_message = response['error']['message']
            if error_code == 3001:
                logger.warning(
                    "Returned error %s: %s, Call: %s, Params: %s" % (error_code, error_message, report_url, params)
                )
                break
            else:
                raise ZoomApiException(response['error'])

        records.extend([record for record in response[listkey]])

        logger.debug("Fetched %d of %d total records", len(records), response[countkey])
        if len(records) >= response[countkey]:
            break

        time.sleep(wait)

        params['page_number'] += 1

    return records


def get_active_hosts(date, key, secret):
    params = {
        'from': date,
        'to': date,
        'api_key': key,
        'api_secret': secret,
        'page_size': 300,  # max page size
        'page_number': 1
    }

    hosts = fetch_records("/report/getaccountreport", params, 'users')

    active_host_ids = [host['user_id'] for host in hosts]

    return active_host_ids


def get_series_info(host_ids, key, secret):
    series_info = {}  # series ids mapped to topic and host id

    params = {
        'api_key': key,
        'api_secret': secret,
        'page_size': 300,  # max page size
        'page_number': 1
    }

    for host_id in host_ids:

        params['host_id'] = host_id

        series = fetch_records("/meeting/list", params, 'meetings')

        for meeting in series:
            meeting_id = meeting['id']

            # this shouldn't happen
            if meeting_id in series_info:
                logger.warning(
                    "Different host_id (%s) returned same meeting (%s)",
                    host_id, meeting_id
                )

            series_info[meeting_id] = {
                'host_id': meeting['host_id'],
                'topic': meeting['topic']
            }

        time.sleep(1)

    return series_info


def get_meetings(date, key, secret):

    host_ids = get_active_hosts(date, key, secret)
    series_info = get_series_info(host_ids, key, secret)

    params = {
        'from': date,
        'to': date,
        'type': 2,  # completed meetings
        'api_key': key,
        'api_secret': secret,
        'page_size': 100,  # max page size
        'page_number': 1
    }

    meetings = fetch_records("/metrics/meetings", params, 'meetings', wait=60)  # 1 min rate limit

    for meeting in meetings:

        topic = ""
        host_id = ""
        series_id = meeting['id']

        if series_id in series_info:
            topic = series_info[series_id]['topic']
            host_id = series_info[series_id]['host_id']

        yield create_meeting_document(meeting, topic, host_id)


def get_sessions_from(date, key, secret):

    url = "/metrics/meetingdetail"

    params = {
        'api_key': key,
        'api_secret': secret,
        'type': 2,  # completed meetings
        'page_size': 100,  # max page size
        'page_number': 1
    }

    for meeting_doc in get_meetings(date, key, secret):

        uuid = meeting_doc['uuid']
        params['meeting_id'] = uuid
        sessions = fetch_records(url, params, 'participants',
                                 countkey='participants_count')

        session_docs = [create_sessions_document(session, uuid)
                        for session in sessions]

        time.sleep(1)

        yield meeting_doc, session_docs


def create_meeting_document(meeting, topic, host_id):

    doc = {
        "uuid": meeting['uuid'],
        "meeting_series_id": meeting['id'],
        "topic": topic,
        "host": {
            "host_id": host_id,
            "name": meeting['host'],
            "email": meeting['email'],
            "user_type": meeting['user_type']
        },
        "start_time": meeting['start_time'],
        "end_time": meeting['end_time'],
        "duration": to_seconds(meeting['duration']),
        "participant_sessions": meeting['participants'],  # not unique participants
        "has_pstn": meeting['has_pstn'],
        "has_voip": meeting['has_voip'],
        "has_3rd_party_audio": meeting['has_3rd_party_audio'],
        "has_video": meeting['has_video'],
        "has_screen_share": meeting['has_screen_share'],
        "recording": meeting['recording'],
    }

    return doc


def create_sessions_document(session, meeting_uuid):

    doc = {
        "meeting": meeting_uuid,
        "id": session['id'],
        "user_id": session['user_id'],
        "user_name": session['user_name'],
        "device": session['device'],
        "ip_address": session['ip_address'],
        "country": session['cn'],
        "city": session['city'],
        "network_type": session['network_type'],
        "join_time": session['join_time'],
        "leave_time": session['leave_time'],
        "share_application": session['share_application'],  # bool
        "share_desktop": session['share_desktop'],  # bool
        "share_whiteboard": session['share_whiteboard'],  # bool
        "recording": session['recording']  # bool
    }

    return doc


# convert duration from MM:SS or HH:MM:SS to seconds
def to_seconds(duration):
    try:
        dt = datetime.strptime(duration, "%H:%M:%S")
    except ValueError:
        dt = datetime.strptime(duration, "%M:%S")
    delta = timedelta(hours=dt.hour, minutes=dt.minute, seconds=dt.second)

    return int(delta.total_seconds())



