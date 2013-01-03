#!/usr/bin/python
# All rights to this work waived under the Creative Commons Zero Waiver
# (CC0, http://creativecommons.org/publicdomain/zero/1.0/).

import sys
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

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

def write_file(path, contents):
    with open(path, 'w') as f:
        f.write(contents)

def get_page_filename(initial_letter, pagenum):
    if pagenum == 1:
        return 'artists-' + initial_letter + '.html'
    else:
        return 'artists-' + initial_letter + '-' + str(pagenum) + '.html'

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

def confirm_song(site, title, artist):
    page = site.Pages[title]
    text = page.edit()
    m = re.search(r'\| *Artist * = *\[\[([^\|\]]*)(\|.*)?\]\]', text, flags=re.IGNORECASE)
    if m:
        return artist == m.group(1).strip()
    m = re.search(r'\| *Artist * = *(.*)', text, flags=re.IGNORECASE)
    if m:
        return artist.lower() == m.group(1).strip().lower()
    return False

def fix_case(title):
    for word in ['on', 'in', 'at', 'for', 'to', 'from', 'a', 'the']:
        title = title.replace(word.capitalize(), word.lower())
    return title

def is_navbox(site, title):
    page = site.Pages[title]
    text = page.edit().lower()
    return '{{navbox' in text or 'navigational boxes|' in text or 'navigational boxes]]' in text or 'list-linking templates|' in text or 'list-linking templates]]' in text

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
    if not re.search('== *External links *==', text, flags=re.IGNORECASE):
        insert_text = "\n\n==External links==\n" + new_entry
    else:
        insert_text = "\n" + new_entry
    
    text = insert_end_of_last_section(site, text, insert_text)
    # Ensure blank line after new text (assume doesn't occur elsewhere)
    while not insert_text + "\n\n" in text:
        text = text.replace(insert_text, insert_text + "\n")
    return text

artists_cache_path = 'cache/artists.pickle'
if not os.path.isfile(artists_cache_path):
    print 'Artists cache file ' + artists_cache_path + ' not found'
    sys.exit(1)

with open(artists_cache_path, 'r') as f:
    artists = pickle.load(f)

# Log in as LyricsBot
site = mwclient.Site('en.wikipedia.org')
config = ConfigParser.RawConfigParser()
config.read('LyricsBot.credentials.txt')
username = config.get('mwclient', 'username')
password = config.get('mwclient', 'password')
site.login(username, password)

for artist in artists:
    artist_name = fix_case(artist['name'])
    artist_article = get_redirect(site, artist_name)
    if artist_article is None:
        print 'Could not find article on artist ' + artist['name']
    else:
        print 'Guess at artist article: ' + artist_article
        if is_disambiguation_page(site, artist_article):
            print 'WARNING: ' + artist_article + ' is disambiguation page'

    filename = artist['url']
    cache_path = 'cache/' + filename

    # Extract songs from artist pages
    html = read_file(cache_path)
    soup = BeautifulSoup(html)
    song_links = [x.find('a') for x in soup.find_all('td', class_='song')]
    songs = [{'url': x['href'][1:], 'title': re.sub(r' Lyrics$', '', x.text.strip())} for x in song_links]

    for song in songs:
        song_result_cache_path = 'cache/' + song['url'] + '.result'
        if os.path.isfile(song_result_cache_path):
            continue

        response = urllib2.urlopen('http://www.metrolyrics.com/' + song['url'])
        html = response.read()
        if 'Our licensing agreement does not allow' in html:
            write_file(song_result_cache_path, '0')
            print 'MetroLyrics does not currently have lyrics of ' + song['title']
            time.sleep(5)
            continue

        title = fix_case(song['title'])
        song_article = None
        for suffix in [' (' + artist['name'] + ' song)',
                       ' (' + artist_article + ' song)',
                       ' (' + artist['name'] + ')',
                       ' (' + artist_article + ')',
                       ' (song)',
                       '']:
            if song_article is None:
                song_article = get_redirect(site, title + suffix)
            if song_article is None:
                song_article = get_redirect(site, 'The ' + title + suffix)

        if song_article is None:
            print 'Could not find article on song ' + title
        else:
            print 'Guess at song article: ' + song_article
            if is_disambiguation_page(site, song_article):
                print 'WARNING: ' + song_article + ' is disambiguation page'
            elif not is_song(site, song_article):
                print 'WARNING: Could not verify is song article'
            elif not confirm_song(site, song_article, artist_article):
                print 'WARNING: Could not confirm is correct song article'
            else:
                print 'Confirmed is song'
                m = re.search(r'(.*)-lyrics-(.*)\.html', song['url'])
                if not m:
                    print 'ERROR: Can\'t extract artist/title from URL'
                else:
                    title_url = m.group(1)
                    artist_url = m.group(2)
                    template_page = site.Pages['Template:Lyrics/' + song_article]
                    if not template_page.exists:
                        template_page.edit()
                        text = '* {{MetroLyrics song|' + artist_url + '|' + title_url + '}}'
                        template_page.save(text, summary="Create with link to full lyrics at MetroLyrics")
                        print "Saved template page " + template_page.name + " with text: " + text
                        page = site.Pages[song_article]
                        text = page.edit()
                        if not allow_bots(text, 'LyricsBot'):
                            print "LyricsBot forbidden on song page"
                        else:
                            text = add_to_external_links(site, text, '{{' + template_page.page_title + '}}')
                        page.save(text, summary="Add external link to full lyrics from legal provider")
                        print "Inserted external link in [[" + song_article + "]]"
                        write_file(song_result_cache_path, '1')
                        sys.exit(0)

        time.sleep(5)
