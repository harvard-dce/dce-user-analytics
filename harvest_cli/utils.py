
import hashlib
import logging
from os import getenv
from Crypto.Cipher import AES
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

def get_mpids_from_useractions(es, index_pattern):
    s = Search(using=es, index=index_pattern).extra(size=0)
    s.aggs.bucket('mpids', 'terms', field='mpid', size=0)
    res = s.execute()
    if 'aggregations' not in res:
        return []
    return [x['key'] for x in res.aggregations.mpids.buckets]



class AcidCookie(object):

    MD5_LEN = 16
    TOKEN_DELIMETER = b'\x00'

    def __init__(self, keystring):
        self.key = keystring[:32].encode()
        self.iv = keystring[32:].encode()

    def decrypt(self, acid_cookie):

        # decrypt message
        cookie_bytes = acid_cookie.decode('hex')
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        decrypted = cipher.decrypt(cookie_bytes)

        # separate md5 check and text
        md5 = decrypted[:self.MD5_LEN]
        text = decrypted[self.MD5_LEN:]

        text = text.rstrip(self.TOKEN_DELIMETER)

        # md5 check
        actual_md5 = hashlib.md5(text).digest()
        if actual_md5 != md5:
            raise Exception("md5 check failed")

        # break out tokens
        tokens = text.split(self.TOKEN_DELIMETER)

        if len(tokens) % 2 != 0:
            raise Exception("Number of tokens not even. Cannot match key value pairs.")

        decoded = { tokens[i]: tokens[i+1] for i in range(0, len(tokens), 2) }
        return decoded

    def encrypt(self, params):

        text = self.TOKEN_DELIMETER.join(
            [self.TOKEN_DELIMETER.join(x) for x in params.items()]
        )
        md5 = hashlib.md5(text).digest()
        cookie_bytes = md5 + text

        # zero-pad the byte array to be divisible by 16
        if len(cookie_bytes) % 16 != 0:
            padding_length = 16 - (len(cookie_bytes) % 16)
            cookie_bytes += self.TOKEN_DELIMETER * padding_length

        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        encrypted = cipher.encrypt(cookie_bytes)
        encrypted = encrypted.encode('hex')
        return encrypted


if __name__ == '__main__':
    key = "bVnq6sB0Qp>sg]f5nfe,G{>inv3D~B2gahvkdoubG(e04ils"
    acid_cookie = "fad6b5f4c9648e7772229f1053953385f72869ef4d34d731fb41dc20f3aad4c602626d3c8e6331c8f4f1bbf5b9133f812316036434918b25183fbf03739847098b7f14e4206846c7667a4df161450d8ad3914e5ed4c776d77212f55351d8119cb067f69fb0688d6d5caf38d7bb60626a40db5876a4518cc210050bcb2e1411d5ab3eed30ea60dc3564dec8e5851127ab02005d8db7a3f06c8775d503099fda24515025924604db244d29a415e106534c2f926648cba109c8a0b9a671de06cbf829b7129ff72c11fb68b50371266f5d3a7368c3c75864cedae7045dac7202e8283f5c6f8aaedea53feb9b28bd612cc5c9"

    ac = AcidCookie(key)
    decrypted = ac.decrypt(acid_cookie)
    encrypted = ac.encrypt(decrypted)
    decrypted = ac.decrypt(encrypted)
