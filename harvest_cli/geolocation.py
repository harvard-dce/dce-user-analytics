import maxminddb
import logging

logger = logging.getLogger(__name__)


class Geolocate:
    def __init__(self, db):
        self.__db = db
        self.__cache = {}
        self.__open_reader()

    def close(self):
        self.__reader.close()

    # fetch from cache or make new call to db
    def get(self, ip):
        if ip in self.__cache:
            return self.__cache[ip]
        else:
            return self.__new_lookup(ip)

    def __open_reader(self):
        self.__reader = maxminddb.open_database(self.__db)

    def __new_lookup(self, ip):
        ipdata = self.__reader.get(ip)

        geoip = {"ip": ip}

        if "country" in ipdata:
            geoip["country_code2"] = ipdata["country"]["iso_code"]
            geoip["country_code3"] = ipdata["country"]["names"]["de"]
            geoip["country_name"] = ipdata["country"]["names"]["en"]

        if "continent" in ipdata:
            geoip["continent_code"] = ipdata["continent"]["code"]

        if "subdivisions" in ipdata:
            geoip["region_name"] = [
                s["iso_code"] for s in ipdata["subdivisions"]
            ]
            geoip["real_region_name"] = [
                s["names"]["en"] for s in ipdata["subdivisions"]
            ]

        if "city" in ipdata:
            geoip["city_name"] = ipdata["city"]["names"]["en"]

        if "location" in ipdata:
            loc = ipdata["location"]

            if "latitude" in loc and "longitude" in loc:
                lat, lng = loc["latitude"], loc["longitude"]
                geoip["latitude"], geoip["longitude"] = lat, lng
                geoip["location"] = [lng, lat]

            if "metro_code" in loc:
                geoip["dma_code"] = loc["metro_code"]

            if "timezone" in loc:
                geoip["timezone"] = loc["time_zone"]

        self.__cache[ip] = geoip
        logger.debug(geoip)

        return geoip
