#!/usr/bin/python
# All rights to this work waived under the Creative Commons Zero Waiver
# (CC0, http://creativecommons.org/publicdomain/zero/1.0/).

import sys
import subprocess
import urllib2
import os
import time
import mwclient
import ConfigParser
import pickle
import re
from bs4 import BeautifulSoup

def allow_bots(text, user):
    if (re.search(r'\{\{(nobots|bots\|(allow=none|deny=.*?' + user + r'.*?|optout=all|deny=all))\}\}', text)):
        return False
    return True

# Path passed without .bz2 extension, for symmetry with write_file_bz2
def read_file_bz2(path):
    subprocess.call(['bunzip2', '-k', path + '.bz2'])
    result = read_file(path)
    os.remove(path)
    return result

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

def write_file(path, contents):
    with open(path, 'w') as f:
        f.write(contents)

def get_redirect(site, title):
    page = site.Pages[title]
    if not page.exists:
        return None
    text = page.edit()
    m = re.match(r'#REDIRECT *\[\[(.*)\]\]', text)
    if m:
        return get_redirect(site, m.group(1).strip())
    else:
        return page.name

def is_disambiguation_page(site, title):
    page = site.Pages[title]
    text = page.edit().lower()
    return '{{disambiguation|' in text or '{{disambiguation}}' in text or '{{disambig|' in text or '{{disambig}}' in text or '{{dab|' in text or '{{dab}}' in text or '{{disamb|' in text or '{{disamb}}' in text

def is_song(site, title):
    page = site.Pages[title]
    text = page.edit()
    # Guess based on presence of common song-related categories
    return 'songs]]' in text or 'singles]]' in text or 'ballads]]' in text or '[[category:songs' in text.lower()

def confirm_song(site, title, artist_article, artist_name):
    page = site.Pages[title]
    text = page.edit()
    m = re.search(r'\| *Artist * = *\[\[([^\|\]]*)(\|([^\]]*))?\]\]', text, flags=re.IGNORECASE)
    if m:
        return artist_article.lower() == m.group(1).strip().lower() or \
               (m.group(3) is not None and artist_name.lower() == m.group(3).strip().lower())
    m = re.search(r'\| *Artist * = *(.*)', text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().lower().startswith(artist_name.lower()) or \
               m.group(1).strip().lower().startswith(artist_article.lower())
    return False

def fix_case(title):
    result = ''
    suffix = title
    while suffix != '':
        m = re.match(r'([\w\']*)([^\w\']*)(.*)$', suffix)
        (prefix, sep, suffix) = (m.group(1), m.group(2), m.group(3))
        prefix = prefix.capitalize()
        for word in ['on', 'in', 'at', 'for', 'to', 'from', 'a', 'the', 'of']:
            if prefix.lower() == word.lower():
                prefix = word.lower()
        if result == '' or result.endswith('('):
            prefix = prefix.capitalize()
        result += prefix + sep
    return result

def is_navbox(site, title):
    page = site.Pages[title]
    text = page.edit().lower()
    return '{{navbox' in text or 'navigational boxes|' in text or 'navigational boxes]]' in text or 'list-linking templates|' in text or 'list-linking templates]]' in text

def insert_end_of_not_last_section(text, section_name, insert_text):
    prev_section_pos = -1
    matches = re.finditer('^== *' + section_name + ' *== *$', text, flags=re.IGNORECASE | re.MULTILINE)
    ends = [m.end() for m in matches]
    # Take first if more than one
    pos = min(ends) if len(ends) > 0 else 0
    matches = re.finditer('^(.*)$', text, flags=re.MULTILINE)
    for m in matches:
        if m.start() >= pos:
            line = m.group(1)
            if line == '':
                continue
            if re.match('==(.*)== *$', line):
                break
            pos = m.end()
    
    return text[0:pos] + insert_text + text[pos:]

def insert_end_of_last_section(site, text, insert_text):
    prev_section_pos = -1
    matches = re.finditer('^==(.*)== *$', text, flags=re.MULTILINE)
    ends = [m.end() for m in matches]
    pos = max(ends) if len(ends) > 0 else 0
    matches = re.finditer('^(.*)$', text, flags=re.MULTILINE)
    for m in matches:
        if m.start() >= pos:
            line = m.group(1)
            if '*' in line or line.lower() == '{{reflist}}' or line.lower() == '<references/>':
                pos = m.end()
                continue
            if line == '':
                continue
            if line.lower().startswith('{{persondata') or line.lower().startswith('{{authority control') or line.lower().startswith('{{coord') or line.lower().startswith('{{s-start}}'):
                break
            if re.match(r'\[\[Category:', line, flags=re.IGNORECASE):
                break
            if re.match(r'\[\[.*:.*\]\]', line, flags=re.IGNORECASE):
                break
            stop = False
            for template_match in re.finditer(r'\{\{([^}\|]*)(\|.*)?\}\}', line):
                templatename = template_match.group(1)
                if 'DEFAULTSORT:' in templatename or 'DISPLAYTITLE:' in templatename:
                    stop = True
                    break
                if is_navbox(site, get_redirect(site, 'Template:' + templatename)):
                    stop = True
                    break
            if stop:
                break
                
            pos = m.end()
    
    return text[0:pos] + insert_text + text[pos:]

def add_to_external_links(site, text, new_entry):
    external_links_last = True
    if not re.search('== *External links *==', text, flags=re.IGNORECASE):
        insert_text = "\n\n==External links==\n" + new_entry
    else:
        # External links *should* be last section but might not be
        if re.search("== *External links *== *\n(.|\n)*\n==[^=]", text, flags=re.IGNORECASE):
            external_links_last = False
        insert_text = "\n" + new_entry
    
    if external_links_last:
        text = insert_end_of_last_section(site, text, insert_text)
    else:
        text = insert_end_of_not_last_section(text, 'External links', insert_text)
    
    # Ensure blank line after new text (assume doesn't occur elsewhere)
    while not insert_text + "\n\n" in text:
        text = text.replace(insert_text, insert_text + "\n")
    return text

def has_edited_before(page, user):
    for rev in page.revisions(end='20130000000000', prop='user'):
        if rev['user'] == user:
            return True
    return False

artists_cache_path = 'cache/artists.pickle'
if not os.path.isfile(artists_cache_path):
    print 'Artists cache file ' + artists_cache_path + ' not found'
    sys.exit(1)

with open(artists_cache_path, 'r') as f:
    artists = pickle.load(f)

songs_complete_cache_path = 'cache/songs_complete.pickle'
if os.path.isfile(songs_complete_cache_path):
    with open(songs_complete_cache_path, 'r') as f:
        songs_complete = pickle.load(f)
else:
    songs_complete = dict()

# Log in as LyricsBot
site = mwclient.Site('en.wikipedia.org')
config = ConfigParser.RawConfigParser()
config.read('LyricsBot.credentials.txt')
username = config.get('mwclient', 'username')
password = config.get('mwclient', 'password')
site.login(username, password)

jumped = False

for artist in artists:
    artist_name = fix_case(artist['name'])
    artist_article = None
    for suffix in [' (band)',
                   ' (group)',
                   ' (musician)',
                   ' (entertainer)',
                   ' (singer)',
                   ' (artist)',
                   ' (boy band)',
                   ' (rock band)',
                   ' (US band)',
                   ' (U.S. band)',
                   ' (girl group)',
                   ' (American group)',
                   ' (R&B group)',
                   '']:
        if artist_article is None:
            artist_article = get_redirect(site, artist_name + suffix)

    if artist_article is None:
        print 'Could not find article on artist ' + artist['name']
        artist_article = ""
    else:
        print 'Guess at artist article: ' + artist_article
        if is_disambiguation_page(site, artist_article):
            print 'WARNING: ' + artist_article + ' is disambiguation page'

    filename = artist['url']
    cache_path = 'cache/' + filename

    # Extract songs from artist pages
    html = read_file_bz2(cache_path)
    soup = BeautifulSoup(html)
    song_links = [x.find('a') for x in soup.find_all('td', class_='song')]
    songs = [{'url': x['href'][1:], 'title': re.sub(r' Lyrics$', '', x.text.strip())} for x in song_links]

    for song in songs:
        if song['title'] == 'Black Soul Choir':
            jumped = True
        if not jumped:
            continue

        song_result_cache_path = 'cache/' + song['url'] + '.result'
        if songs_complete.has_key(song['url']):
            continue

        title = fix_case(song['title'])
        song_article = None
        song_article_no_suffix = get_redirect(site, title)
        if song_article_no_suffix is not None:
            for suffix in [' (' + artist['name'] + ' song)',
                           ' (' + artist_article + ' song)',
                           ' (' + artist['name'] + ')',
                           ' (' + artist_article + ')',
                           ' (song)']:
                if song_article is None:
                    song_article = get_redirect(site, title + suffix)
                    break
                if song_article is None:
                    song_article = get_redirect(site, 'The ' + title + suffix)
                    break
        if song_article is None:
            song_article = song_article_no_suffix

        if song_article is None:
            print 'Could not find article on song ' + title
        else:
            response = urllib2.urlopen('http://www.metrolyrics.com/' + song['url'])
            html = response.read()
            if 'Our licensing agreement does not allow' in html:
                songs_complete[song['url']] = 0
                with open(songs_complete_cache_path, 'w') as f:
                    pickle.dump(songs_complete, f)
                print 'MetroLyrics does not currently have lyrics of ' + song['title']
                time.sleep(5)
                continue

            print 'Guess at song article: ' + song_article
            if is_disambiguation_page(site, song_article):
                print 'WARNING: ' + song_article + ' is disambiguation page'
            elif not is_song(site, song_article):
                print 'WARNING: Could not verify is song article'
            elif not confirm_song(site, song_article, artist_article, artist_name):
                print 'WARNING: Could not confirm is correct song article'
            else:
                print 'Confirmed is song'
                m = re.search(r'(.*)-lyrics-(.*)\.html', song['url'])
                if not m:
                    print 'ERROR: Can\'t extract artist/title from URL'
                else:
                    title_url = m.group(1)
                    artist_url = m.group(2)
                    page = site.Pages[song_article]
                    if has_edited_before(page, 'LyricsBot'):
                        print "LyricsBot has already edited this page before"
                        songs_complete[song['url']] = 2
                    else:
                        text = page.edit()
                        if not allow_bots(text, 'LyricsBot'):
                            print "LyricsBot forbidden on song page"
                            songs_complete[song['url']] = 3
                        elif '{{MetroLyrics' in text or 'metrolyrics.com/' in text:
                            print "Already contains MetroLyrics link"
                            songs_complete[song['url']] = 4
                        else:
                            text = add_to_external_links(site, text, '* {{MetroLyrics song|' + artist_url + '|' + title_url + '}}<!-- Licensed lyrics provider -->')
                            page.save(text, summary="Add external link to full lyrics from licensed provider (MetroLyrics) - please report incorrect links at [[User talk:Dcoetzee]]")
                            print "Inserted external link in [[" + song_article + "]]"
                            songs_complete[song['url']] = 1
                            with open(songs_complete_cache_path, 'w') as f:
                                pickle.dump(songs_complete, f)
                    with open(songs_complete_cache_path, 'w') as f:
                        pickle.dump(songs_complete, f)

        time.sleep(5)
