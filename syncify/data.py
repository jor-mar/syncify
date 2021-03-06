import glob
import json
import re
import sys
from os.path import basename, dirname, exists, join, splitext

import mutagen
from tqdm.auto import tqdm

from syncify.process import Process


class Data(Process):

    def __init__(self):
        Process.__init__(self)

        # get list of all audio files in music path
        # used to check for case-sensitivity issues in m3u filepath entries
        self.all_files = glob.glob(join(self.MUSIC_PATH, '*', '**', '*'), recursive=True)

        # tags used for each metadata type for flac, mp3, m4a, and wma file types
        # also generic image file type for mp3, m4a, and wma file types
        self.filetype_tags = {
            '.flac': {'title': ['title'],
                      'artist': ['artist'],
                      'album': ['album'],
                      'track': ['tracknumber'],
                      'genre': ['genre'],
                      'year': ['year', 'date'],
                      'comment': ['comment'],
                      'bpm': ['bpm'],
                      'key': ['initialkey']},
            '.mp3': {'title': ['TIT2'],
                     'artist': ['TPE1', 'TPE2'],
                     'album': ['TALB'],
                     'track': ['TRCK'],
                     'genre': ['TCON'],
                     'year': ['TDRC', 'TYER', 'TDAT'],
                     'comment': ['COMM'],
                     'bpm': ['TBPM'],
                     'key': ['TKEY']},
            '.m4a': {'title': ['©nam'],
                     'artist': ['©ART', 'aART'],
                     'album': ['©alb'],
                     'track': ['trkn'],
                     'genre': ['©gen'],
                     'year': ['©day'],
                     'comment': ['©cmt'],
                     'bpm': ['tmpo'],
                     'key': ['NULL']},
            '.wma': {'title': ['Title'],
                     'artist': ['Author', 'WM/AlbumArtist'],
                     'album': ['WM/AlbumTitle'],
                     'track': ['WM/TrackNumber'],
                     'genre': ['WM/Genre'],
                     'year': ['WM/Year'],
                     'comment': ['Description'],
                     'bpm': ['WM/BeatsPerMinute'],
                     'key': ['WM/InitialKey']},
            'IMAGE': ['APIC', 'covr', 'WM/Picture']
        }

    def load_file(self, song):
        """
        Load local file using mutagen and extract file extension as string.

        :param song: str or dict. A string of the song's path or a dict containing 'path' as key
        :return: mutagen file object and file extension as string.
        """
        # extract song path
        if isinstance(song, dict) and 'path' in song:
            path = song['path']
        elif isinstance(song, str):
            path = song
        else:
            return

        # extract file extension and confirm file type is listed in self.filetype_tags dict
        file_ext = splitext(path)[1].lower()
        if file_ext not in self.filetype_tags:
            return

        try:  # load filepath and get file extension
            file_data = mutagen.File(path)
        except mutagen.MutagenError:
            # check if given path is case-insensitive, replace with case-sensitive path
            for file_path in self.all_files:
                if file_path.lower() == path.lower():
                    path = file_path
                    break

            try:  # load case-sensitive path
                file_data = mutagen.File(path)
            except mutagen.MutagenError:  # give up
                print('\nERROR: Could not load', path, end=' ', flush=True)
                file_data = None
        return file_data, file_ext

    def get_m3u_metadata(self, in_playlists=None, verbose=True):
        """
        Get metadata on all songs found in m3u playlists
        
        :param in_playlists: list, default=None. List of playlist names to include, returns all if None.
        :param verbose: bool, default=True. Print extra info on playlists and persist progress bars if True.
        :return: dict. <playlist name>: <list of tracks metadata>
        """
        # update stored list of paths to all songs
        self.all_files = glob.glob(join(self.MUSIC_PATH, '*', '**', '*'), recursive=True)

        # list of paths of .m3u files in playlists path
        filepaths = glob.glob(join(self.PLAYLISTS_PATH, '*.m3u'))
        playlists = {}

        # progress bar
        playlist_bar = tqdm(filepaths,
                            desc='Loading m3u playlists: ',
                            unit='playlists',
                            leave=verbose,
                            file=sys.stdout)

        for playlist_path in playlist_bar:
            # extract filename only process if in_playlists not defined or in in_playlists list
            playlist_name = splitext(basename(playlist_path))[0]
            if in_playlists and playlist_name not in in_playlists:
                continue

            # get list of songs in playlist
            with open(playlist_path, 'r', encoding='utf-8') as m3u:
                files = [line.rstrip() for line in m3u]

            # replace filepath stems related to other operating systems
            if any([path in files[0] for path in self.OTHER_PATHS]):
                # determine part of filepath to replace and replace
                sub = self.OTHER_PATHS[0] if files[0].startswith(self.OTHER_PATHS[0]) else self.OTHER_PATHS[1]
                files = [file.replace(sub, self.MUSIC_PATH) for file in files]

                # sanitise path separators
                if '/' in self.MUSIC_PATH:
                    files = [file.replace('\\', '/') for file in files]
                else:
                    files = [file.replace('/', '\\') for file in files]

            if len(files) > 100:  # show progress bar for large playlists
                files = tqdm(files, desc=f'{playlist_name}: ', unit='songs', leave=False, file=sys.stdout)

            # extract metadata for song path in playlist and add to dict of playlists
            playlist_metadata = [self.get_song_metadata(file, i, verbose, playlist_name)
                                 for i, file in enumerate(files)]
            playlists[playlist_name] = [song for song in playlist_metadata if song]

        if verbose:  # print track information for each playlist
            print('Found the following playlists:')

            # for appropriately aligned formatting
            max_width = len(max(playlists.keys(), key=len)) + 1

            # sort playlists in alphabetical order and print
            for name, playlist in sorted(playlists.items(), key=lambda x: x[0].lower()):
                length = str(len(playlist)) + ' tracks'
                print(f'{name : <{max_width}}', ': ', '\33[92m', f'{length : >11} ', '\33[0m', sep='')

        return playlists

    def get_all_metadata(self, ex_playlists=None, ex_folders=None, in_folders=None, verbose=True):
        """
        Get metadata on all audio files in music folder.
        
        :param ex_playlists: list, default=None. Exclude songs with paths listed in playlists in this playlist folder.
            Excludes every song from playlists in the default playlist path if True. Ignored if None.
        :param ex_folders: list, default=None. Exclude songs in these folders. Ignored if None.
        :param in_folders: list, default=None. Only include songs in these folders. Ignored if None.
        :param verbose: bool, default=True. Print extra runtime info and persist progress bars if True.
        :return: dict. <folder name>: <list of tracks metadata>
        """
        exclude = set()
        if ex_playlists:  # if user has defined path to playlists with songs to exclude
            if ex_playlists is True:  # exclude all songs that are in a playlist from the default playlist folder
                ex_playlists = self.PLAYLISTS_PATH

            # get filepaths of playlists in folder
            playlists = glob.glob(join(ex_playlists, '*.m3u'))

            for playlist in playlists:
                # get list of songs to exclude for each playlist
                with open(playlist, 'r', encoding='utf-8') as m3u:
                    files = [file.rstrip() for file in m3u]

                # replace filepath stems related to other operating systems
                if any([path in files[0] for path in self.OTHER_PATHS]):
                    sub = self.OTHER_PATHS[0] if files[0].startswith(self.OTHER_PATHS[0]) else self.OTHER_PATHS[1]
                    files = [file.replace(sub, self.MUSIC_PATH) for file in files]

                    # sanitise path separators
                    if '/' in self.MUSIC_PATH:
                        files = [file.replace('\\', '/') for file in files]
                    else:
                        files = [file.replace('/', '\\') for file in files]

                # add unique songs to list of excluded songs
                exclude = exclude | set(files)

        if not ex_folders:  # if user has not defined folders to exclude, exclude no folders
            ex_folders = []

        # get files that are .flac, .mp3, .wma, or .wma from music path that match above criteria
        files = [file for file in glob.glob(join(self.MUSIC_PATH, '*', '**', '*'), recursive=True)
                 if any([file.lower().endswith(ext) for ext in ['.flac', '.mp3', '.m4a', '.wma']])
                 and file not in exclude and basename(dirname(file)) not in ex_folders]

        if in_folders:  # reduce list of files to only those in in_folders list if defined by user
            files = [file for file in files if basename(dirname(file)) in in_folders]

        # progress bar and empty dict to fill with metadata
        folder_metadata = {}
        bar = tqdm(files, desc='Loading library: ', unit='songs', leave=verbose, file=sys.stdout)

        for file in bar:
            # get folder name and metadata for each song
            folder = basename(dirname(file))
            song = self.get_song_metadata(file, verbose=verbose)

            if song:  # if metadata successfully extracted, update metadata folder
                folder_metadata[folder] = folder_metadata.get(folder, [])
                folder_metadata[folder].append(song)

        return folder_metadata

    def get_song_metadata(self, path, position=None, verbose=True, playlist=None):
        """
        Extract metadata for a song.
        
        :param path: str. Path to the song (may be case-insensitive)
        :param position: int, default=None. Position of song in a playlist.
        :param verbose: bool, default=True. Print error messages if True.
        :param playlist: str, default=None. Playlist name to print in error message if verbose == True.
        :return: dict. Metadata dict: position, title, artist, album, track, genre, year, length, has_image, path.
        """
        # load file as mutagen object
        file_data, file_ext = self.load_file(path)
        if not file_data or not file_ext:
            return

        # record given track position
        uri = None
        metadata = {'position': position}

        # extract all tags found in filetype_tags for this filetype
        for key, tags in self.filetype_tags.get(file_ext, {'': []}).items():
            for tag in tags:
                # each filetype has a different way of extracting tags within mutagen
                if file_ext == '.wma':
                    metadata[key] = file_data.get(tag, [mutagen.asf.ASFUnicodeAttribute(None)])[0].value
                elif file_ext == '.m4a' and key == 'track':
                    metadata[key] = file_data.get(tag, [[None]])[0][0]
                elif file_ext == '.mp3' and key == 'comment':
                    metadata[key] = None
                    for file_tag in file_data:
                        if tag in file_tag:
                            metadata[key] = file_data.get(file_tag, [None])[0]
                            break
                else:
                    metadata[key] = file_data.get(tag, [None])[0]

                # if no tag found, replace with null
                if len(str(metadata[key]).strip()) == 0:
                    metadata[key] = None

                if metadata[key]:
                    # strip whitespaces from string based tags
                    if isinstance(metadata[key], str):
                        metadata[key] = metadata[key].strip()
                        if metadata[key].startswith('spotify:track:'):
                            uri = metadata[key]
                    break

        # convert track number tags to integers
        if metadata.get('track') and not isinstance(metadata.get('track'), int):
            metadata['track'] = int(re.sub('[^0-9]', '', metadata['track']))

        try:  # convert release date tags to year only
            metadata['year'] = int(re.sub('[^0-9]', '', str(metadata.get('year', '')))[:4])
        except (ValueError, TypeError):
            metadata['year'] = 0

        # add track length
        metadata['length'] = file_data.info.length

        # determine if track has image embedded
        if file_ext == '.flac':
            metadata['has_image'] = bool(file_data.pictures)
        else:
            metadata['has_image'] = any([True for tag in file_data
                                         if any(im in tag for im in self.filetype_tags['IMAGE'])])

        # add song path to metadata
        metadata['path'] = path

        # add uri if found
        if uri:
            metadata['uri'] = uri

        return metadata

    def import_uri(self, local, filename='URIs', refresh=False):
        """
        Import URIs from stored json file. File must be in format <album name: <<title>: <URI>> format.
        
        :param local: dict. Metadata in form <name>: <dict of metadata incl. path, and album>
        :param filename: str, default='URIs'. Filename of file to import from data path.
        :param refresh: bool, default=False. Overwrite current URIs with those imported from json file.
        :return: dict. Same dict as given with added keys for URIs if found.
        """
        # get path to file from data path, return if it doesn't exist
        json_path = join(self.DATA_PATH, filename + '.json')
        if not exists(json_path):
            return local

        print('Importing locally stored URIs...', end='', flush=True)

        with open(json_path, 'r') as file:  # load URI file
            uri = json.load(file)

        i = 0

        for playlist in local.values():
            for song in playlist:  # loop through each song in each playlist
                # skip songs with URI when refresh disabled
                if 'uri' in song and not refresh:
                    continue

                # get filename and album name
                filename = splitext(basename(song['path']))[0]
                album = {k.lower().strip(): v for k, v in uri.get(song.get('album'), {}).items()}

                # check if filename in URI json file, add URI to song metadata if found
                if filename.lower().strip() in album:
                    song['uri'] = album.get(filename.lower().strip())
                    if song['uri']:
                        i += 1

        print('\33[92m', f'Done. Imported {i} URIs', '\33[0m')
        return local

    def export_uri(self, local, filename='URIs'):
        """
        Export URIs from local metadata dicts in <album name: <<title>: <URI>> format.
        
        :param local: dict. Metadata in form <name>: <list of dicts of metadata incl. path, album, and URI>
        :param filename: str, default='URIs'. Filename of file to export to in data path.
        """
        # get path to file from data path, load if exists, empty dict if not
        json_path = join(self.DATA_PATH, filename + '.json')
        if exists(json_path):
            with open(json_path, 'r') as file:
                uri = json.load(file)
        else:
            uri = {}

        print('Saving URIs locally...', end='', flush=True)
        i = 0

        for playlist in local.values():
            for song in playlist:  # loop through each song in each playlist
                if 'uri' in song:  # if URI in song metadata
                    i += 1

                    # get filename and album name, update URI loaded from json file
                    filename = splitext(basename(song['path']))[0].lower()
                    uri[song['album']] = uri.get(song['album'], {})
                    uri[song['album']][filename] = song['uri']

        # sort by album name and filename
        uri = {k: {k: v for k, v in sorted(v.items(), key=lambda x: x[0].lower())}
               for k, v in sorted(uri.items(), key=lambda x: x[0].lower())}
        with open(json_path, 'w') as file:  # save json
            json.dump(uri, file, indent=2)

        print('\33[92m', f'Done. Saved {i} URIs', '\33[0m')

    def save_json(self, file, filename='data'):
        """
        Save dict to json file in data path.
        
        :param file: dict. Data to save.
        :param filename: str, default='data'. Filename to save under.
        """

        print(f'Saving {filename}.json...', end=' ', flush=True)

        # get filepath and save
        json_path = join(self.DATA_PATH, filename + '.json')
        with open(json_path, 'w') as f:
            json.dump(file, f, indent=2)

        print('\33[92m', 'Done', '\33[0m', sep='')

    def load_json(self, filename):
        """
        Load json from data path.
        
        :param filename: str. Filename to load from.
        """

        # get filepath and load
        json_path = join(self.DATA_PATH, filename + '.json')
        with open(json_path, 'r') as file:
            return json.load(file)

    @staticmethod
    def uri_as_key(local):
        """
        Convert dict from <name>: <list of dicts of metadata> to <song URI>: <song metadata>.
        
        :param local: dict. Metadata in form <name>: <list of dicts of metadata>
        :return: dict. <song URI>: <song metadata>
        """
        songs = {}
        for playlist in local.values():  # get list of song metadata for each playlist
            # if metadata given in Spotify based <url> + <tracks> format
            if isinstance(playlist, dict) and 'tracks' in playlist:
                playlist = playlist['tracks']

            for song in playlist:
                if 'uri' in song:  # if URI found
                    # add song to songs dict with dict of all metadata that isn't it's URI
                    songs[song['uri']] = {k: v for k, v in song.items() if k != 'uri'}

        return songs

    @staticmethod
    def missing_tags(local, tags=None, kind='uri', ignore=None):
        """
        Returns lists of dicts of song metadata for songs with missing tags.
        
        :param local: dict. Metadata in form <key>: <dict of metadata>
        :param tags: list, default=None. List of tags to consider missing.
        :param kind: str, default='uri'. Kind of dict fed to function through local 
            - <album>: <dict of metadata> OR <URI>: <dict of metadata>
        :param ignore: list, default=None. List of albums of playlists to exclude in search.
        :return: dict. <URI>: <metadata of song with missing tags> 
            OR <album/playlist name>: <list of metadata of songs with missing tag>
        """
        missing_tags = {}
        if kind == 'uri':
            for uri, song in local.items():  # loop through all songs
                for tag in tags:  # check all given tags
                    if not song[tag] or song[tag] == 0:  # if no tag, add to missing_tags dict
                        missing_tags[uri] = song
                        break
        else:
            for item, songs in local.items():
                if ignore and item in ignore:  # skip items in ignore list
                    continue
                missing_tags[item] = []
                for song in songs:  # loop through all songs
                    for tag in tags:  # check all given tags
                        if not song[tag] or song[tag] == 0:  # if no tag, add to missing_tags dict
                            missing_tags[item].append(song)
                            break

                if len(missing_tags[item]) == 0:  # remove entry if no missing tags
                    del missing_tags[item]

        return missing_tags

    def update_tags(self, local, tags, refresh=False, verbose=True):
        """
        Update file's tags from given dictionary of tags.
        
        :param local: dict. Metadata in form <URI>: <dict of local song metadata>
        :param tags: dict. Tags to be updated in form <URI>: <<tag name>: <tag value>>
        :param refresh: bool, default=False. Destructively replace tags in each file.
        :param verbose: Persist progress bars if True.
        """

        # progress bar
        playlist_bar = tqdm(local.items(),
                            desc='Updating file tags: ',
                            unit='albums',
                            leave=verbose,
                            file=sys.stdout)

        for uri, song in playlist_bar:        
            # load file as mutagen object
            file_data, file_ext = self.load_file(song)
            if not file_data or not file_ext:
                continue

            # loop through each tag for this song
            for tag, value in tags[uri].items():
                if not value or tag not in self.filetype_tags[file_ext]:  # skip missing tags
                    continue
                
                # get file type specific tag identifier, determine if exists, skip if not replacing
                tag_var = self.filetype_tags[file_ext][tag]
                if not refresh and tag != 'comment' and any(t in file_data for t in tag_var):
                    continue
                
                # clear up tags
                if any(t in tag for t in ['year', 'comment']):
                    clear = []

                    # produce list of tags to be deleted
                    for base_t in tag_var:
                        for file_t in file_data:
                            if base_t in file_t:
                                clear.append(file_t)
                    for file_t in clear:  # delete tag
                        del file_data[file_t]

                tag_var = tag_var[0]
                # file extension specific tag update and save updated file tags
                if file_ext == '.flac':
                    file_data[tag_var] = str(value)
                elif file_ext == '.mp3':
                    file_data[tag_var] = getattr(mutagen.id3, tag_var)(3, text=str(value))
                elif file_ext == '.m4a':
                    if tag != 'bpm':
                        file_data[tag_var] = [str(value)]
                elif file_ext == '.wma':
                    file_data[tag_var] = mutagen.asf.ASFUnicodeAttribute(str(value))
            
            try:  # try to save tags, skip if error and display path
                file_data.save()
            except mutagen.MutagenError:
                print('\nERROR: Could not save', path, end=' ', flush=True)

    def rebuild_uri_from_tag(self, local, tag='comment', filename='URIs'):
        """
        Build URI json file database with URIs tagged in local files. Replaces json file if found.

        :param local: dict. Metadata in form <name>: <list of dicts of metadata>
        :param tag: str, default='comment'. Type of tag containing URI.
        :param filename: str, default='URIs'. Filename of file to export to in data path.
        """
        uri_dict = {}
        for item, songs in local.items():
            uri_dict[songs[0]['album']] = {}
            for song in songs:
                uri = song.get(tag) if str(song.get(tag)).strip().startswith("spotify:track:") else None
                uri_dict[songs[0]['album']][splitext(basename(song['path']))[0].lower()] = uri

        uri_dict = {k: {k: v for k, v in sorted(v.items(), key=lambda x: x[0].lower())} for k, v in sorted(uri_dict.items(), key=lambda x: x[0].lower())}

        self.save_json(uri_dict, filename)
        return uri_dict