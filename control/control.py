import os
import sys
import six
import signal
import config
from database import Database

DEFAULT_MODE = 'standby'


def get_config():
    return config.read_config()


def get_database(config):
    return Database.from_config(config)


def read_settings(mode, config, database):
    table_name = mode + '_settings'
    if table_name not in config:
        return {}

    settings = list(config[table_name].keys())

    with database as open_database:
        values = open_database.read_values_from_table(table_name, settings)

    return dict(zip(settings, values))


def read_settings_if_available(table_prefix, config, database):
    """
    Reads a group of settings, returning None if the settings have not been
    installed yet. This lets the modes keep working when an optional feature,
    like the recording or the fence, is missing from the database.
    """
    table_name = table_prefix + '_settings'
    if table_name not in config:
        return None

    settings = list(config[table_name].keys())
    try:
        with database as open_database:
            if not open_database.table_exists(table_name):
                return None
            values = open_database.read_values_from_table(
                table_name, settings)
    except Exception:
        return None

    return dict(zip(settings, values))


def table_is_available(table_name, config, database):
    if table_name not in config:
        return False
    try:
        with database as open_database:
            return open_database.table_exists(table_name)
    except Exception:
        return False


def read_setting(mode, setting, config, database):
    table_name = mode + '_settings'
    if table_name not in config:
        return {}

    with database as open_database:
        value = open_database.read_values_from_table(table_name, setting)

    return dict([(setting, value)])


def update_mode_in_database(mode, config, open_database):
    open_database.update_values_in_table(
        'modes',
        dict(id=0,
             current=config['modes']['current']['values'][mode]['value']))


def handle_shutdown(*args):
    config = get_config()
    with get_database(config) as open_database:
        update_mode_in_database(DEFAULT_MODE, config, open_database)
    sys.exit(0)


def register_shutdown_handler():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)


def enter_mode(mode, run_mode):
    config = get_config()
    database = get_database(config)
    with database as open_database:
        update_mode_in_database(mode, config, open_database)
    try:
        run_mode(mode, config, database)
    except:
        exc_info = sys.exc_info()
        with database as open_database:
            update_mode_in_database(DEFAULT_MODE, config, open_database)
        six.reraise(*exc_info)


def signal_mode_started(mode):
    os.utime(f'{os.environ["BM_MODE_SIGNAL_FILE_STEM"]}.{mode}')
