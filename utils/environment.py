import logging
import os
import re
import shutil
import sys
from datetime import datetime as dt
from glob import glob
from os.path import basename, dirname, exists, join, normpath, isdir

from dateutil.relativedelta import relativedelta

from spotify.search import Search

BASE_API = "https://api.spotify.com/v1"
OPEN_URL = "https://open.spotify.com"


class Environment:

    def clean_up_env(self, days: int = 60, keep: int = 30, **kwargs) -> None:
        """
        Clears files older than {days} months if more than {leave} previous runs found

        :param days: int, default=60. Age of files in months to keep.
        :param keep: int, default=30. Number of files to keep.
        """
        log = self._log_path
        data = dirname(self.DATA_PATH)
        current = {
            "_log": os.listdir(log),
            "_data": [basename(d) for d in glob(join(data, "*")) if isdir(d)]
        }
        remove = {}

        keep = 1 if keep < 1 else keep

        for kind, files_list in current.items():
            remove_list = []
            if len(files_list) >= keep:
                remaining = len(files_list)
                for file in sorted(files_list):
                    if remaining <= keep:
                        break

                    file_dt = dt.strptime(file[:19], "%Y-%m-%d_%H.%M.%S")
                    if file_dt < dt.now() - relativedelta(days=days):
                        remove_list.append(file)
                        remaining -= 1

            remove[kind] = remove_list

        if len(remove["_log"]) > 0:
            self._logger.debug(f"Removing {len(remove['_log'])} old logs in {log}")
            [os.remove(join(log, file)) for file in remove['_log']]

        if len(remove["_data"]) > 0:
            self._logger.debug(f"Removing {len(remove['_data'])} old folders in {data}")
            [shutil.rmtree(join(data, folder)) for folder in remove['_data']]

    def get_env_vars(self, dry_run: bool = False, **kwargs) -> None:
        """
        Set object attributes from environment variables.

        :param dry_run: bool, default=False. If True, append '_dry' to data path folder name.
        """
        self.BASE_API = BASE_API
        self.OPEN_URL = OPEN_URL
        self.ALGORITHM_COMP = int(os.getenv("ALGORITHM_COMP", 4))
        self.ALGORITHM_ALBUM = int(os.getenv("ALGORITHM_ALBUM", 2))

        # handle user input for unexpected algorithm number
        search__settings = list(Search._settings.keys())
        if self.ALGORITHM_COMP > max(search__settings):
            self.ALGORITHM_COMP = max(search__settings)
        elif self.ALGORITHM_COMP < -max(search__settings):
            self.ALGORITHM_COMP = -max(search__settings)

        if self.ALGORITHM_ALBUM > max(search__settings):
            self.ALGORITHM_ALBUM = max(search__settings)
        elif self.ALGORITHM_ALBUM < -max(search__settings):
            self.ALGORITHM_ALBUM = -max(search__settings)

        # set system appropriate path and store other system's paths
        paths = {
            "win32": normpath(os.getenv("WIN_PATH", "")),
            "linux": normpath(os.getenv("LIN_PATH", "")),
            "darwin": normpath(os.getenv("MAC_PATH", "")),
        }
        self.MUSIC_PATH = paths[sys.platform]
        self.OTHER_PATHS = [p for p in paths.values() if p != self.MUSIC_PATH and len(p) > 1]

        # build full path to playlist folder from this system's music path
        playlists = normpath(os.getenv("PLAYLISTS").replace("\\", "/")).split("/")
        self._playlists_PATH = join(self.MUSIC_PATH, *playlists)

        # get path to date-specific data folder for this run
        self.DATA_PATH = normpath(os.getenv("DATA_PATH", ""))
        if self.DATA_PATH == ".":
            self.DATA_PATH = join(dirname(dirname(__file__)), "_data", self._start_time_filename)
        if dry_run:
            self.DATA_PATH += "_dry"
        if not exists(self.DATA_PATH):
            os.makedirs(self.DATA_PATH)

        # replace token path auth arg with main data path + token filename from env
        # set test args from base api
        token_filename = normpath(os.getenv("TOKEN_FILENAME", self._auth["token_path"]))
        self._auth["token_path"] = join(dirname(self.DATA_PATH), token_filename)
        self._auth["test_args"] = {"url": f"{BASE_API}/me"}
        self._auth["test_condition"] = lambda r: "error" not in r

    def set_env_vars(self, current_state: bool = True, **kwargs) -> dict:
        """
        Save settings to default environment variables.
        Loads any saved variables and updates as appropriate.

        :param current_state: bool, default=True. Use current object variables to update.
        :param **kwargs: pass kwargs for variables to update.
            Overrides current values if current_state is True.
        :return: dict. Dict of the variables saved.
        """
        env = {}
        if exists('.env'):  # load stored environment variables
            with open('.env', 'r') as file:
                env = dict([line.rstrip().split('=') for line in file])

        # acccepted vars
        env_vars = [
            'CLIENT_ID',
            'CLIENT_SECRET',
            'PLAYLISTS',
            'WIN_PATH',
            'MAC_PATH',
            'LIN_PATH',
            'DATA_PATH',
            'TOKEN_FILENAME']
        if current_state:  # update variables from current object
            env.update({var: val for var, val in vars(self).items() if var in env_vars})

        # update with given kwargs
        env.update({var: val for var, val in {**kwargs}.items() if var in env_vars})

        # build line by line strings for each variable and write new .env file
        save_vars = [f'{var}={val}\n' for var, val in env.items() if var in env_vars]
        with open('.env', 'w') as file:
            file.writelines(save_vars)

        return env

    def get_logger(self, **kwargs) -> logging.Logger:
        """
        Return logger object formatted for stdout and file handlers.

        :return logging.Logger. Logger object
        """
        # set log file path
        self._log_path = join(dirname(dirname(__file__)), "_log")
        self._log_file = join(self._log_path, f"{self._start_time_filename}.log")
        if not exists(self._log_path):  # if log folder doesn't exist
            os.makedirs(self._log_path)  # create log folder

        # get logger and clear default handlers
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.DEBUG)
        for h in logger.handlers:
            logger.removeHandler(h)

        # handler for sys out
        stdout_h = logging.StreamHandler(stream=sys.stdout)
        stdout_format = logging.Formatter(
            fmt="%(message)s",
            datefmt="%y-%b-%d %H:%M:%S"
        )
        stdout_h.setLevel(logging.INFO)
        stdout_h.setFormatter(stdout_format)
        stdout_h.addFilter(logStdOutFilter(levels=[logging.INFO, logging.WARNING]))
        logger.addHandler(stdout_h)

        # handler for file output
        file_h = logging.FileHandler(self._log_file, 'w', encoding='utf-8')
        file_format = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)8s] [%(funcName)-40s:%(lineno)4d] --- %(message)s",
            datefmt="%y-%b-%d %H:%M:%S"
        )
        file_h.setLevel(logging.DEBUG)
        file_h.setFormatter(file_format)
        file_h.addFilter(logFileFilter())
        logger.addHandler(file_h)

        # return exceptions to logger
        sys.excepthook = self.handle_exception

        return logger

    def handle_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """
        Custom exception handler. Handles exceptions through logger.
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        self._logger.critical(
            "CRITICAL ERROR: Uncaught Exception", exc_info=(
                exc_type, exc_value, exc_traceback))


class logStdOutFilter(logging.Filter):
    def __init__(self, levels: list = None):
        """
        :param levels: str, default=None. Accepted log levels to return i.e. 'info', 'debug'
            If None, set to current log level.
        """

        self.levels = levels if levels else [self.__level]

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        if record.levelno in self.levels:
            return record


class logFileFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        record.msg = re.sub("\n$", "", record.msg)
        record.msg = re.sub("\33.*?m", "", record.msg)
        record.funcName = f"{record.module}.{record.funcName}"

        return record