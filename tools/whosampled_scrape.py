import requests
from bs4 import BeautifulSoup
from . import direction as direct

class Scraper:
    """A scraper for whosampled
      - handles paging
      direction:
        - items defined in ./direction.py
        - collect *only* samples relevant to direction
        e.g `s = Scraper(direction=direction.contains_sample_of)`
      debug:
        - write logs of each page & be mega verbose about everything
    """
    def __init__(self, direction=None, debug=False):
        # create a session to manage lifetime of self.requests and skip auto-reject from
        # whosampled; seems pretty unfriendly to block self.request's default headers.
        self.debug = debug
        self.direction = direction
        self.base_url = 'https://whosampled.com'
        self.req = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=10)
        self.req.mount('https://', adapter)
        self.req.mount('http://', adapter)
        self.req.headers = {
            "User-Agent":
            "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.119 Safari/537.36"
        }

    def get_whosampled_playlist(self, loaded_playlist, direction=None):
        """ Main endpoint for Scraper
        loaded_playlist:
        - type is <list: dict>
        - [{"track": "School Boy Crush", "artist": "Average White Band"}, ...]
             - Gets link for each song in `loaded_playlist`
             - scrapes corresponding detail page for song
             - parses detail from scrape
        """
        samples = []
        new_playlist = []
        for i in loaded_playlist:
            print(i['track'] + ' by ' + i['artist'][0])
            samples, sampled_by = self.getme_thesamples(i['track'], i['artist'][0])
            if samples:
                new_playlist.append(samples)
        lst = [i for j in new_playlist for i in j] # what the fuck
        return lst

    def getme_thesamples(self, song_title, artist_name):
        """Retrieves sample detail for individual song"""
        link = self.retrieve_song_link(song_title, artist_name)
        if not link:
            return None, None
        samples, sampled_by = self.retrieve_sample_details(song_title, link)
        return samples, sampled_by

    def retrieve_song_link(self, song_title, artist_name=None):
        """queries for song, returns relevant links
           FIXME refinements to how strict this is
             - aka make it find tighter matches at the search level
             - degree of strictness? could be quantified w/ fuzzy match
        """

        query = song_title.replace(' ', '%20')
        if artist_name:
            query = f'{query}%20{artist_name.replace(" ", "%20")}'
        url = f'https://www.whosampled.com/search/tracks/?q={query}'
        r = self.req.get(url)
        content = r.content
        search_page_soup = BeautifulSoup(content, 'html.parser')
        search_results = search_page_soup.findAll(
            'li', attrs={'class': "listEntry"})

        if not search_results:
            return None

        # return first result
        link = [i.a for i in search_results][0].get('href')
        return link

    def retrieve_sample_details(self, song_title, link):
        """ Gets sample details from top-level link

        link (str):
          e.g '/Kenny-Burrell/Midnight-Blue/'

        - 'sampled' -> Was sampled in
        - 'samples' -> Contains samples of

            - relevant pages only exist when # references > 5
            - paging query string can be '?sp=N' or '?cp=N'
            valid pages are:
            - 'sampled' -> Was sampled in
            - 'samples' -> Contains samples of
            - e.g. https://www.whosampled.com/Nas/Halftime/sampled?sp=1
            worth trying next page until 404 is hit as a quick & dirty
            - 'The page you requested cannot be found' (UK-ENG)

          - e.g only parse items in 'Sampled By'
        """
        url = f'{self.base_url}{link}'
        s = self.req.get(url)
        page_detail = s.content
        soup = BeautifulSoup(page_detail, 'html.parser')

        # FIXME findAll('div', attrs={'class': '.sectionHeader'})
        # then list comp -> find_next_sibling('div') on each for content grid
        # allows match on direction (from direction.py)
        # - note; completely speculating
        listed = [i.text for i in soup.findAll('div', attrs={'class': 'list bordered-list'})]

        if not listed:
            return [], []
        # NOTE: order is currently just assuming page renders as contains, was sampled in, remix, cover
        contains_samples_of = self.parse_sample_items(song_title=song_title,
                                                      sample_data=listed[0],
                                                      link=link,
                                                      direction=direct.contains_sample_of)
        if not len(listed) > 2:
            return contains_samples_of, []
        was_sampled_in = self.parse_sample_items(song_title=song_title,
                                                 sample_data=listed[1],
                                                 link=link,
                                                 direction=direct.was_sampled_in)

        return contains_samples_of, was_sampled_in

    def parse_sample_items(self, song_title, sample_data, direction, link, recursing=False):
        """ Gets detail from track summary listing
        """
        raw_samples =  [i.split('\n') for i in list(filter(None, sample_data.split('\t')))][:-1]
        parsed_samples = []
        if len(raw_samples) >= 5 and not recursing:
            parsed_sampled = \
                parsed_samples + self.scrape_paged_content(song_title, direction, link)

        for sample in raw_samples:
            interim = sample[-2].replace('by ', '', 1).split(' (')
            year = interim[1].replace(')', '')
            artist = interim[0]
            parsed_samples.append({
                'query': song_title,
                'direction': direction,
                'type': sample[-7],
                'genre': sample[-6],
                'title': sample[-3],
                'artist':  artist,
                'year': year
            })
        if self.debug: self.log(f'parse_sample_items: {parsed_samples}')
        return parsed_samples

    def scrape_paged_content(self, song_title, direction, link):
        """Heads to scaped"""
        paged_url = f'{self.base_url}{link}{direct.get_paged_content_by_direction(direction=direction)}/'
        soup, samples = self.get_direction_content(
            url=paged_url, song_title=song_title, direction=direction, recursing=True)

        if not soup:
            return samples
        pagination = soup.findAll(
            'div', attrs={'class': "pagination"})
        if not len(pagination) > 0:
            return samples

        # get max page number
        page_link_cont = pagination[0].find_all('span')
        page_links = [item.a.get('href') for item in page_link_cont if item.a is not None]
        last_link_num = int(page_links[-1].split('=')[1]) # maybe 'next'
        potential_max_link_num = int(page_links[-2].split('=')[1]) # maybe max page value

        tracks = []
        for page_number in range(1, max(last_link_num, potential_max_link_num)+1):
            url = f'{paged_url}?cp={page_number}'
            soup, parsed = self.get_direction_content(
                url=url, song_title=song_title, direction=direction, recursing=True)
            tracks = tracks + parsed
        return tracks

    def get_direction_content(self, url, song_title, direction, recursing=False):
        s = self.req.get(url)
        page_detail = s.content
        soup = BeautifulSoup(page_detail, 'html.parser')
        # check if base paged content is 404
        if 'The page you requested cannot be found' in str(soup):
            return None, []

        listed = [i.text for i in soup.findAll('div', attrs={'class': 'list bordered-list'})]
        return soup, self.parse_sample_items(song_title=song_title,
                                             sample_data=listed[0],
                                             direction=direction,
                                             link=None,
                                             recursing=recursing)

    def log(self, message, function=None, page_source=None):
        from time import time
        print(f'''
Message:  {message}
        ''')
        if not page_source:
            return
        file_name = f'{time()}.{song_title}.html'
        with open(file_name, 'w+') as f:
            f.write('<!-- SAMPLE PAGE CONTENT -->\n')
            f.write(str(soup))
            f.write(str(listed))


# test `scrape_page_content` -> throw this oneliner into ipython & see
# from whosampled_scrape import Scraper; s = Scraper(); import direction as d; items = s.scrape_paged_content(direction=d.was_sampled_in, link='https://whosampled.com/nas/halftime')
