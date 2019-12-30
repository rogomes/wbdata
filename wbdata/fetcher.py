"""
wbdata.fetcher: retrieve and cache queries
"""

import datetime
import json
import logging
import pickle
import pprint

import appdirs
import requests

import wbdata

from pathlib import Path

EXP = 7
PER_PAGE = 1000
TODAY = datetime.date.today()
TRIES = 5


class WBResults(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_updated = None


class Cache(object):
    """Docstring for Cache """

    def __init__(self):
        self.path = Path(
            appdirs.user_cache_dir(
                appname="wbdata", version=wbdata.__version__
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("rb") as cachefile:
                self.cache = {
                    i: (date, json)
                    for i, (date, json) in pickle.load(cachefile).items()
                    if (TODAY - datetime.date.fromordinal(date)).days < EXP
                }
        except (IOError, EOFError):
            self.cache = {}

    def __getitem__(self, key):
        return self.cache[key][1]

    def __setitem__(self, key, value):
        self.cache[key] = TODAY.toordinal(), value
        self.sync()

    def __contains__(self, item):
        return item in self.cache

    def sync(self):
        """Sync cache to disk"""
        with self.path.open("wb") as cachefile:
            pickle.dump(self.cache, cachefile)


CACHE = Cache()


def get_json_from_url(url, args):
    """
    Fetch a url directly from the World Bank, up to TRIES tries

    : url: the  url to retrieve
    : args: a dictionary of GET arguments
    : returns: a string with the url contents
    """
    for i in range(TRIES):
        try:
            return requests.get(url, args).text
        except requests.ConnectionError:
            continue
    logging.error("Error connecting to {url}".format(url=url))
    raise RuntimeError("Couldn't connect to API")


def get_response(url, args, cache=True):
    """
    Get single page response from World Bank API or from cache
    : query_url: the base url to be queried
    : args: a dictionary of GET arguments
    : cache: use the cache
    : returns: a dictionary with the response from the API
    """
    logging.debug("fetching {}".format(url))
    key = (url, tuple(sorted(args.items())))
    if cache and key in CACHE:
        response = CACHE[key]
    else:
        response = get_json_from_url(url, args)
        if cache:
            CACHE[key] = response
    return json.loads(response)


def fetch(url, args=None, cache=True):
    """Fetch data from the World Bank API or from cache.

    Given the base url, keep fetching results until there are no more pages.

    : query_url: the base url to be queried
    : args: a dictionary of GET arguments
    : cache: use the cache
    : returns: a list of dictionaries containing the response to the query
    """
    if args is None:
        args = {}
    else:
        args = dict(args)
    args["format"] = "json"
    args["per_page"] = PER_PAGE
    results = []
    pages, this_page = 0, 1
    while pages != this_page:
        response = get_response(url, args, cache=cache)
        try:
            results.extend(response[1])
            this_page = response[0]["page"]
            pages = response[0]["pages"]
        except (IndexError, KeyError):
            try:
                message = response[0]["message"][0]
                raise RuntimeError(
                    "Got error {id} ({key}): {value}".format(**message)
                )
            except (IndexError, KeyError):
                raise RuntimeError(
                    "Got unexpected response:\n{}".format(
                        pprint.pformat(response)
                    )
                )
        logging.debug("Processed page {0} of {1}".format(this_page, pages))
        args["page"] = int(this_page) + 1
    for i in results:
        if "id" in i:
            i["id"] = i["id"].strip()
    results = WBResults(results)
    try:
        results.last_updated = datetime.datetime.strptime(
            response[0]["lastupdated"], "%Y-%m-%d"
        )
    except KeyError:
        pass
    return results
