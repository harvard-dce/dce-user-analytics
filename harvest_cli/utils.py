
import logging
import json
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search, Q

logger = logging.getLogger(__name__)

def es_connection(es_host=None, **kwargs):

    params = { 'timeout': 30 }
    if es_host is not None:
        params['hosts'] = [es_host]

    params.update(kwargs)

    es = Elasticsearch(**params)

    try:
        info = es.info()
    except Exception as ex:
        logger.error("Connection to elasticsearch failed: %s", ex)
        raise

    return es


def get_episodes_for_term(es, term, year, fields=None):
    s = Search(using=es, index='episodes')
    s = s.filter(Q('term', term=term) & Q('term', year=year))
    if fields is not None:
        s = s.source(include=fields)
    res = list(s.scan())
    return res

def get_series_for_term(es, term, year):
    s = Search(using=es, index='episodes').extra(size=0)
    s = s.filter(Q('term', term=term) & Q('term', year=year))
    s.aggs.bucket('series', 'terms', field='series', size=0)
    res = s.execute()
    return [x['key'] for x in res.aggregations.series.buckets]

def get_mpids_from_useractions(es, index_pattern=None,
                               term=None, year=None, anonymous=True):
    s = Search(using=es, index=index_pattern).extra(size=0)
    if None not in (term, year):
        s = s.filter(
            Q('term', **{'episode.term': term }) & \
            Q('term', ** { 'episode.year': year })
        )
    if not anonymous:
        s = s.filter(~Q('term', huid='anonymous'))

    s.aggs.bucket('mpids', 'terms', field='mpid', size=0)
    res = s.execute()
    return [x['key'] for x in res.aggregations.mpids.buckets]


