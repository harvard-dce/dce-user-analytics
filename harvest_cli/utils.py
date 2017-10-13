
import logging
from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)

def es_connection(es_host=None, **kwargs):

    params = {}
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


