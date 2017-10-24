import maxminddb
from functools import wraps
import logging
logger = logging.getLogger(__name__)


def memoize(func):
    cache = {}

    @wraps(func)
    def wrapper(*args):
        if args in cache:
            return cache[args]
        else:
            rv = func(*args)
            cache[args] = rv
            return rv

    return wrapper


@memoize
def geolocate(ip, db):
    reader = maxminddb.open_database(db)
    ipdata = reader.get(ip)
    reader.close()

    geoip = {
        "ip": ip
    }

    if 'country' in ipdata:
        geoip['country_code2'] = ipdata['country']['iso_code']
        geoip['country_code3'] = ipdata['country']['names']['de']
        geoip['country_name'] = ipdata['country']['names']['en']

    if 'continent' in ipdata:
        geoip['continent_code'] = ipdata['continent']['code']

    if 'subdivisions' in ipdata:
        geoip['region_name'] = [s['iso_code'] for s in ipdata['subdivisions']]
        geoip['real_region_name'] = [s['names']['en'] for s in ipdata['subdivisions']]

    if 'city' in ipdata:
        geoip['city_name'] = ipdata['city']['names']['en']

    if 'location' in ipdata:
        loc = ipdata['location']

        if 'latitude' in loc and 'longitude' in loc:
            lat, lng = loc['latitude'], loc['longitude']
            geoip['latitude'], geoip['longitude'] = lat, lng
            geoip['location'] = [lng, lat]

        if 'metro_code' in loc:
            geoip['dma_code'] = loc['metro_code']

        if 'timezone' in loc:
            geoip['timezone'] = loc['time_zone']

    logger.debug(geoip)

    return geoip