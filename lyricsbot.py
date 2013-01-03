#!/usr/bin/python
# All rights to this work waived under the Creative Commons Zero Waiver
# (CC0, http://creativecommons.org/publicdomain/zero/1.0/).

import urllib2
import time
import os
import errno
from itertools import count
import pickle
from sys import stdout
from bs4 import BeautifulSoup

# From http://stackoverflow.com/questions/273192/python-best-way-to-create-directory-if-it-doesnt-exist-for-file-write
def make_sure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

def write_file(path, contents):
    with open(path, 'w') as f:
        f.write(contents)

base_url = 'http://www.metrolyrics.com/'
make_sure_path_exists('cache')

# Retrieve and cache all "Browse artists" pages
artistpages = ['1'] + [chr(x) for x in range(ord('a'),ord('z')+1)]
for artistpage in artistpages:
    filename = get_page_filename(artistpage, 1)
    for pagenum in count(1):
        page_filename = get_page_filename(artistpage, pagenum)
        cache_path = 'cache/' + page_filename
        if not os.path.isfile(cache_path):
            stdout.write('Retrieving ' + page_filename + '...'); stdout.flush()
            response = urllib2.urlopen(base_url + page_filename)
            html = response.read()
            if page_filename != filename and '(Page: 1)' in html:
                stdout.write("not found.\n")
                write_file(cache_path, '') # Avoid re-retrieval later
                break
            write_file(cache_path, html)
            stdout.write("done.\n")
            stdout.write('Sleeping for 5 seconds...'); stdout.flush()
            time.sleep(5)
            stdout.write("done.\n")
        else:
            if read_file(cache_path) == '':
                break

# Extract artists from Browse artists pages
artists_cache_path = 'cache/artists.pickle'
if os.path.isfile(artists_cache_path):
    with open(artists_cache_path, 'r') as f:
        artists = pickle.load(f)
else:
    artist_links = []
    for artistpage in artistpages:
        filename = get_page_filename(artistpage, 1)
        for pagenum in count(1):
            page_filename = get_page_filename(artistpage, pagenum)
            cache_path = 'cache/' + page_filename

            print 'Parsing ' + page_filename + '.'
            if os.path.isfile(cache_path):
                html = read_file(cache_path)
                soup = BeautifulSoup(html)
                for artist_list in soup.find_all('ul', class_='artist-list'):
                    artist_links += artist_list.find_all('a')
            else:
                break 
    artists = [{'url': x['href'][1:], 'name': x.text.strip()} for x in artist_links]
    with open(artists_cache_path, 'w') as f:
        pickle.dump(artists, f)

# Retrieve and cache all artist pages (each listing all their songs)
for artist in artists:
    filename = artist['url']
    cache_path = 'cache/' + filename
    if not os.path.isfile(cache_path):
        stdout.write('Retrieving ' + filename + '...'); stdout.flush()
        response = urllib2.urlopen(base_url + filename)
        html = response.read()
        write_file(cache_path, html)
        stdout.write("done.\n")
        stdout.write('Sleeping for 5 seconds...'); stdout.flush()
        time.sleep(5)
        stdout.write("done.\n")
