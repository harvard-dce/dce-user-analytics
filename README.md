# dce-user-analytics

The project contains tools for dealing with DCE user analytics data. It is comprised mainly 
of harvesting scripts that pull data from DCE's Opencast system and the Zoom Web Conferencing API.

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

## ZOOM

#### Helpful Links

[Zoom API Documentation](https://zoom.github.io/api/)

[Zoom API Playground](https://developer.zoom.us/playground/)

#### Usage

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

## Development Environment

A local development environment will need at least an instance of elasticsearch into which the zoom data can be indexed and inspected.
The easiest way to get a test instance of Elasticsearch running is via docker & docker-compose. 

#### Setup

1. Install docker via the instructions for you OS at https://docker.com
1. Install docker-compose via `pip install docker-compose`
1. Run `./harvest.py dev init`

This will get you containers running elasticsearch and kibana. These services and volumes are defined in `docker/docker-compose.yml`. It will also install the very useful kopf Elasticsearch plugin and load the index templates from the `index_templates` directory

To shutdown the containers run `./harvest.py dev down`

#### index templates

Index templates define the settings for newly created indexes that match a particular name pattern. They need to be created prior to any document indexing. Similar to ES plugins, they need to be recreated if/when the elasticsearch service container is ever removed.

To load/reload the index templates run `./harvest.py setup load_index_templates`
