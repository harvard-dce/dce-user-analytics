# dce-user-analytics

The project contains tools for dealing with DCE user analytics data. It is comprised mainly 
of harvesting scripts that pull data from DCE's Opencast system and the Zoom Web Conferencing API.

Deployment of these scripts is implemented by the [install-ua-harvester](https://github.com/harvard-dce/mh-opsworks-recipes/blob/master/recipes/install-ua-harvester.rb) recipe in [harvard-dce/mh-opsworks-recipes](https://github.com/harvard-dce/mh-opsworks-recipes).

## Getting Started

**Note:** Python 2.7 is required; Python 3 not yet supported :(

1. Clone the project repo:
1. Create and activate a python virtualenv
1. `pip install -r requirements.txt`
1. Copy `example.env` to `.env` and fill in appropriate values

## Usage

All operations are executed through the `harvest.py` cli. To list commands, subcommands, options, etc use:

    ./harvest.py --help
    ./harvest.py [subgroup|subcommand] --help
    ./harvest.py [subgroup] [subcommand] --help

---
    
## Opencast useractions

A command for fetching useraction events and related metadata from Opencast. The program uses the [pyhorn](https://github.com/harvard-dce/pyhorn) library for interacting with the Opencast API. Harvested useractions are fed to an SQS queue.

This script is designed in part with the assumption that it will be installed as part of an `mh-opsworks` analytics node, but independent installation/testing is also possible. Just follow these steps:

    Usage: harvest.py useractions [OPTIONS]
    
    Options:
      -s, --start TEXT                YYYYMMDDHHmmss
      -e, --end TEXT                  YYYYMMDDHHmmss; default=now
      -w, --wait INTEGER              Seconds to wait between batch requests
      -H, --engage_host TEXT          Matterhorn engage hostname  [required]
      -u, --user TEXT                 Matterhorn rest user  [required]
      -p, --password TEXT             Matterhorn rest password  [required]
      -o, --output TEXT               where to send output. use "-" for
                                      json/stdout
      -q, --queue-name TEXT           SQS queue name  [required]
      -b, --batch-size INTEGER        number of actions per request
      -i, --interval INTEGER          Harvest action from this many minutes ago
      --disable-start-end-span-check  Don't abort on too-long start-end time spans
      --help                          Show this message and exit.

This command fetches batches of useraction events based on a `--start` and `--end` timestamp. If a start/end is not specified the script will look for and use the timestamp of the last useraction fetched (stored in an S3 bucket; see settings below) as the start value and `now()` as the end value. If no timestamp is stored in S3 the default is to fetch the last `--interval` minutes of events (defaults to 2 minutes). Events are fetched in batches of `--batch-size` (default 1000) using the API endpoint's `limit` and `offset` parameters. Events are output to an SQS queue identified with `--queue-name`. If `--queue-name` is `"-"` the json data will be sent to stdout.

There is one additional option, `--disable-start-end-span-check`, that prevents the harvester's start/end timestamps from growing too large. See details below.

To reduce load on the engage server during harvesting, redis is used to cache the episode data between harvests.

It is possible to have the `useractions` command dump the useraction events to `stdout` rather than sent to an SQS queue by including the option `--output -` on the commandline. In that case no `SQS_QUEUE_NAME` is necessary.

#### Example `useractions` command:

Assuming your `.env` file has the necessary settings, this will fetch and process the last 1 minute of useractions in batches of 100 events, and dump the output to `stdout`:

        ./harvest.py useractions --batch-size 100 --interval 1 --output -

#### useraction harvest too-big timespan protection

The `useractions` command has a built-in protection against the start/end time range growing too large. This can happen if the harvester for some reason or other falls behind in fetching the most recent useraction events. For instance, the script fails for some reason or the engage node becomes unresponsive for some length of time. Because the last action timestamp value is only updated on a successful harvest run, the time span the harvester wants to fetch could grow so large that the harvesting process becomes bogged down. To protect against this the harvester will abort if this time span is longer than `MAX_START_END_SPAN` seconds. Leaving `MAX_START_END_SPAN` unset disables this protection.

If the above situation arises there are two courses of action:

1. Manually run the harvester using the `--disable-start-end-span-check` flag. It is recommended that you also ensure no other harvester processes run concurrently by either disabling any cron jobs or using something like `/bin/run-one`.
2. Reset the start time by deleting the S3 object, `s3://<S3_HARVEST_TS_BUCKET>/<S3_LAST_ACTION_TS_KEY`. You'll then need to manually harvest the useraction events that were missed. If the gap is large you can do several runs manipulating the `--start/--end` range as necessary.


## Episode index

    Usage: harvest.py load_episodes [OPTIONS]
    
    Options:
      -A, --admin-host TEXT           Matterhorn admin hostname  [required]
      -E, --engage-host TEXT          Matterhorn engage hostname  [required]
      -u, --user TEXT                 Matterhorn rest user  [required]
      -p, --password TEXT             Matterhorn rest password  [required]
      -e, --es-host TEXT              Elasticsearch host:port
      -t, --target-index TEXT         name of index the episodes will be written
                                      to; defaults to 'episodes'
      -s, --source-index-pattern TEXT
                                      useraction index pattern to query for mpids;
                                      e.g. 'useractions*-2017.10.*'; defaults to
                                      yesterday's index
      --mpid TEXT                     Index a specific mediapackage
      -w, --wait INTEGER              Seconds to wait between batch requests
      --help                          Show this message and exit.

This command fetches episode metadata from the Opencast search & workflow endpoints. To obtain the list of episodes to fetch it
finds all mpids referenced in useraction events from indexes matching `--source-index-pattern`, which defaults to the previous day's
useractions index. The episode records are augmented with additional information about live stream start/stop times and availability via the admin node's workflow API endpoint. The resulting records are sent to an Elasticsearch index, identified by `--es-host` and `--target-index`.


## ZOOM

#### Helpful Links

[Zoom API Documentation](https://zoom.github.io/api/)

[Zoom API Playground](https://developer.zoom.us/playground/)


    Usage: harvest.py zoom [OPTIONS]

    Options:
      --date TEXT                   fetch for date, e.g. YYYY-mm-dd; defaults to
                                    yesterday.
      --destination [index|stdout]  defaults to 'index'
      --es_host TEXT                Elasticsearch host:port; defaults to $ES_HOST
      --key TEXT                    zoom api key; defaults to $ZOOM_KEY
      --secret TEXT                 zoom api secret; defaults to $ZOOM_SECRET
      --help                        Show this message and exit.

##### Example to retrieve & index all meeting & participant data from yesterday.

`./harvest.py zoom --key [KEY] --secret [SECRET] --es-host localhost:9200`

##### Using the `.env` file

To avoid entering key, secret, etc, on the command line copy `example.env` to `.env` in the
project directory and fill in the values. The script will load them into the environment at
runtime and use as the command line arg defaults.

#### Terms

**`meeting_uuid`, `series_id`**

The zoom api uses "meeting id" to refer to ids for both an individual instance of a meeting and a series of meetings. These are two distinct types of ids. The zoom-harvester differentiates between the two.

- `meeting_uuid` 24 numbers, letters, and symbols uniquely refering to a meeting instance
- `series_id` 9 or 10 digits refering to a series of meetings

**`'type': 2`**

When calling /metrics/meetings, you must specify meeting type: 1(live) or 2(past). Live meetings are meetings that are currently happening and do not have an end time or duration yet. All live meetings become past meetings so meetings.py only searches for past meetings.

_**More notes on meetings ids:**_

Within the series_id, there can be several types:
- Most Common:
    * 9-digit ids tied to a repeating or scheduled series of meeting, such as a class that meets every Wednesday.
- Less Common:
    * 10-digit ids for PMIs (Personal Meeting Rooms) is a series id that an individual user can associate with their account so that every meeting that they host can be accessed with the same link in the format https://zoom.us/j/0123456789
    * 9-digit meeting ids not associated with a series of meetings or a PMI, these are instant meetings which will show up when you search for all the meetings over a period of time (/metrics/meetings/) but will not show up if you try to look them up individual (/meetings/get/)


**`user_id`**

Since only hosts have accounts, most of the time user_id refers to a host. Participants do not log in to join meetings, but the zoom api generates a `user_id` for each session. This `user_id` is not unique, it is only unique within a meeting instance.


**Sessions / participant sessions**

Each individual instance of a meeting participant entering and exiting a meeting. Can occur many times during the same meeting if, for example, the participant has a bad connection. Number of sessions for a given meeting does not equal the number of participants.


#### API Calls

meetings.py runs all these calls in order to generate meeting objects with topics and host ids and participant sessions documents

| Call                       | Requires          | Returns |
| -------------------------- |:-----------------:| :-------            |
| /report/getaccountreport/  | date(s)           |  Active host information, including host ids.   |
| /meeting/list/             | host ids          |  Meeting series data including topic and series id.  |
| /metrics/meetings/         | date(s)           |  Meeting instance data, including unique meeting ids but not participant data. |
| /metrics/meetingdetail/    | meeting uuids |  All information from /metrics/meetings/ plus detailed participant data. |

---

## dotenv Settings

A local `.env` file will be read automatically and is the preferred way of passing options to the commands. `example.env` contains the list of all settings. A complete `.env` sufficient for executing the `useractions` command would look something like this:

    # .env
    MATTERHORN_REST_USER=mh_rest_user
    MATTERHORN_REST_PASS=mh_rest_pass
    MATTERHORN_ENGAGE_HOST=matterhorn.example.edu
    S3_HARVEST_TS_BUCKET=my-harvest-timestamp-bucket
    S3_LAST_ACTION_TS_KEY=last-action-timestamp
    SQS_QUEUE_NAME=my-harvest-action-queue

To execute the `load_episode` command you will also need to include hostname of your Matterhorn admin node and the host:port combination for an elasticsearch instance.

    # .env
    ...
    MATTERHORN_ADMIN_HOST=admin.matterhorn.example.edu
    ES_HOST=localhost:9200
    
For the `zoom` command the `ZOOM_API` and `ZOOM_SECRET` settings are also required.

#### MATTERHORN_REST_USER / MATTERHORN_REST_PASS
The user/pass combo for accessing the API.

#### MATTERHORN_ENGAGE_HOST
IP or hostname of the engage node.

#### MATTERHORN_ADMIN_HOST
IP or hostname of the admin node.

#### DEFAULT_INTERVAL
If no `--start` is provided and no last action timestamp is found in s3 the useraction harvest start will be calculated as this many minutes ago.

#### LOGGLY_TOKEN
If present the script will send log events to loggly.

#### LOGGLY_TAGS
Any extra tags to attach to events sent to loggly.

#### S3_HARVEST_TS_BUCKET
Name of the S3 bucket to store the last action's timestamp value. The program will attempt to create the bucket if it does not exist.

#### S3_LAST_ACTION_TS_KEY
Name of the S3 object the last action timestamp is saved as.

#### SQS_QUEUE_NAME
Name of the SQS queue to send useraction events. The queue will be created if it doesn't exist.

#### ES_HOST
Hostname or IP of the Elasticsearch instance in which to index the episode records.

#### EPISODE_CACHE_EXPIRE
Time-to-live value for cached episodes fetched during the useraction harvesting. Defaults to 1800s (15m).

#### MAX_START_END_SPAN
Max number of seconds allowed between the useraction start/end timestamps. The harvester will abort if span in seconds is > than this value.

#### ZOOM_KEY / ZOOM_SECRET
The key/secret combo for accessing the zoom api

---
## Development Environment

A local development environment will need at least an instance of elasticsearch into which the zoom data can be indexed and inspected.
The easiest way to get a test instance of Elasticsearch running is via docker & docker-compose. 

#### Development Setup

The cli provides a few commands for spinning up a local development environment.

1. Install docker via the instructions for you OS at https://docker.com
1. Install docker-compose via `pip install docker-compose`
1. Run `./harvest.py dev init`

This will get you containers running elasticsearch and kibana. These services and volumes are defined in `docker/docker-compose.yml`. It will also install the very useful [kopf](https://github.com/lmenezes/elasticsearch-kopf) Elasticsearch plugin and load the index templates from the `index_templates` directory

To shutdown the containers run `./harvest.py dev down`

The `dev init` subcommand combines the execution of three other commands, each of which can be run individually if needed:

* `./harvest.py dev up` - runs the `docker-compose` process to bring up the containers
* `./harvest.py dev install_kopf` - installs the kopf plugin
* `./harvest.py setup load_index_templates` - see below

#### index templates

Index templates define the settings for newly created indexes that match a particular name pattern. They need to be created prior to any document indexing. Similar to ES plugins, they need to be recreated if/when the elasticsearch service container is ever removed.

To load/reload the index templates run `./harvest.py setup load_index_templates`
