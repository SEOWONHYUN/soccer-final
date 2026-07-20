import html
import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 연결 시간과 응답 대기 시간을 따로 지정합니다.
REQUEST_TIMEOUT = (2, 4)
CURRENT_SEASON = "2026/27"
WIKI_SEASON_LABELS = ["2026–27", "2026-27", "2025–26", "2025-26"]

_thread_data = threading.local()


def get_session():
    """재시도 기능이 적용된 requests 세션을 스레드별로 만듭니다."""

    if not hasattr(_thread_data, "session"):
        retry = Retry(
            total=1,
            connect=1,
            read=1,
            status=1,
            backoff_factor=0.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session = requests.Session()
        session.headers.update(HEADERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _thread_data.session = session

    return _thread_data.session


def request_get(url, **kwargs):
    """모든 외부 요청에서 같은 헤더, 재시도, 타임아웃을 사용합니다."""

    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    response = get_session().get(url, **kwargs)
    response.raise_for_status()
    return response


ACCENT_TRANSLATION = str.maketrans({
    "á": "a", "à": "a", "â": "a", "ä": "a", "ã": "a", "å": "a",
    "Á": "a", "À": "a", "Â": "a", "Ä": "a", "Ã": "a", "Å": "a",
    "ç": "c", "Ç": "c",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "É": "e", "È": "e", "Ê": "e", "Ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "Í": "i", "Ì": "i", "Î": "i", "Ï": "i",
    "ñ": "n", "Ñ": "n",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o", "õ": "o", "ø": "o",
    "Ó": "o", "Ò": "o", "Ô": "o", "Ö": "o", "Õ": "o", "Ø": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "Ú": "u", "Ù": "u", "Û": "u", "Ü": "u",
    "ý": "y", "ÿ": "y", "Ý": "y", "ß": "ss",
})


def clean_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_text(text):
    text = str(text or "").translate(ACCENT_TRANSLATION).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return clean_text(text)


LEAGUES = {'EPL': {'name': '프리미어리그', 'url': 'https://www.theguardian.com/football/premierleague/fixtures', 'expected': 380},
 '분데스리가': {'name': '분데스리가', 'url': 'https://www.theguardian.com/football/bundesligafootball/fixtures', 'expected': 306},
 '라리가': {'name': '라리가', 'url': 'https://www.theguardian.com/football/laligafootball/fixtures', 'expected': 380},
 '세리에A': {'name': '세리에 A', 'url': 'https://www.theguardian.com/football/serieafootball/fixtures', 'expected': 380},
 '리그앙': {'name': '리그 1', 'url': 'https://www.theguardian.com/football/ligue1football/fixtures', 'expected': 306}}

RAW_LEAGUE_ALIASES = {'epl': '프리미어리그',
 '프리미어리그': '프리미어리그',
 '프리미어 리그': '프리미어리그',
 'premier league': '프리미어리그',
 'english premier league': '프리미어리그',
 '분데스리가': '분데스리가',
 '분데스 리가': '분데스리가',
 'bundesliga': '분데스리가',
 'german bundesliga': '분데스리가',
 '라리가': '라리가',
 'laliga': '라리가',
 'la liga': '라리가',x
 '세리에a': '세리에 A',
 '세리에 a': '세리에 A',
 'serie a': '세리에 A',
 '리그앙': '리그 1',
 '리그1': '리그 1',
 '리그 1': '리그 1',
 'ligue 1': '리그 1',
 'ligue1': '리그 1'}

LEAGUE_ALIASES = {
    normalize_text(alias): normalize_text(league_name)
    for alias, league_name in RAW_LEAGUE_ALIASES.items()
}

TEAM_DATA = [{'canonical': 'arsenal', 'wiki': 'Arsenal_F.C.', 'aliases': ['아스널', '아스날', 'Arsenal FC']},
 {'canonical': 'aston villa', 'wiki': 'Aston_Villa_F.C.', 'aliases': ['아스톤 빌라', '아스톤빌라', 'Aston Villa FC', 'Villa']},
 {'canonical': 'bournemouth', 'wiki': 'AFC_Bournemouth', 'aliases': ['본머스', 'AFC Bournemouth']},
 {'canonical': 'brentford', 'wiki': 'Brentford_F.C.', 'aliases': ['브렌트퍼드', '브렌트포드', 'Brentford FC']},
 {'canonical': 'brighton',
  'wiki': 'Brighton_&_Hove_Albion_F.C.',
  'aliases': ['브라이턴', '브라이튼', 'Brighton & Hove Albion', 'Brighton and Hove Albion']},
 {'canonical': 'chelsea', 'wiki': 'Chelsea_F.C.', 'aliases': ['첼시', 'Chelsea FC']},
 {'canonical': 'coventry', 'wiki': 'Coventry_City_F.C.', 'aliases': ['코번트리', '코번트리 시티', 'Coventry City']},
 {'canonical': 'crystal palace',
  'wiki': 'Crystal_Palace_F.C.',
  'aliases': ['크리스털 팰리스', '크리스탈 팰리스', '팰리스', 'Crystal Palace FC']},
 {'canonical': 'everton', 'wiki': 'Everton_F.C.', 'aliases': ['에버턴', '에버튼', 'Everton FC']},
 {'canonical': 'fulham', 'wiki': 'Fulham_F.C.', 'aliases': ['풀럼', 'Fulham FC']},
 {'canonical': 'hull', 'wiki': 'Hull_City_A.F.C.', 'aliases': ['헐 시티', '헐시티', 'Hull City', 'Hull City AFC']},
 {'canonical': 'ipswich', 'wiki': 'Ipswich_Town_F.C.', 'aliases': ['입스위치', '입스위치 타운', 'Ipswich Town']},
 {'canonical': 'leeds', 'wiki': 'Leeds_United_F.C.', 'aliases': ['리즈', '리즈 유나이티드', 'Leeds United']},
 {'canonical': 'liverpool', 'wiki': 'Liverpool_F.C.', 'aliases': ['리버풀', 'Liverpool FC']},
 {'canonical': 'manchester city',
  'wiki': 'Manchester_City_F.C.',
  'aliases': ['맨시티', '맨체스터 시티', 'Man City', 'Manchester City FC']},
 {'canonical': 'manchester united',
  'wiki': 'Manchester_United_F.C.',
  'aliases': ['맨유', '맨체스터 유나이티드', 'Man Utd', 'Man United', 'Manchester United FC']},
 {'canonical': 'newcastle', 'wiki': 'Newcastle_United_F.C.', 'aliases': ['뉴캐슬', '뉴캐슬 유나이티드', 'Newcastle United']},
 {'canonical': 'nottingham forest',
  'wiki': 'Nottingham_Forest_F.C.',
  'aliases': ['노팅엄', '노팅엄 포레스트', '노팅엄포레스트', "Nott'm Forest", 'Nottingham Forest FC']},
 {'canonical': 'sunderland', 'wiki': 'Sunderland_A.F.C.', 'aliases': ['선덜랜드', 'Sunderland AFC']},
 {'canonical': 'tottenham',
  'wiki': 'Tottenham_Hotspur_F.C.',
  'aliases': ['토트넘', '토트넘 홋스퍼', '스퍼스', 'Spurs', 'Tottenham Hotspur']},
 {'canonical': 'bayern',
  'wiki': 'FC_Bayern_Munich',
  'aliases': ['바이에른', '바이에른 뮌헨', '바이에른뮌헨', '뮌헨', 'Bayern Munich', 'FC Bayern', 'FC Bayern Munich']},
 {'canonical': 'dortmund', 'wiki': 'Borussia_Dortmund', 'aliases': ['도르트문트', '보루시아 도르트문트', 'BVB', 'Borussia Dortmund']},
 {'canonical': 'rb leipzig',
  'wiki': 'RB_Leipzig',
  'aliases': ['라이프치히', 'RB 라이프치히', 'Leipzig', 'RasenBallsport Leipzig']},
 {'canonical': 'stuttgart', 'wiki': 'VfB_Stuttgart', 'aliases': ['슈투트가르트', 'VfB Stuttgart']},
 {'canonical': 'hoffenheim',
  'wiki': 'TSG_1899_Hoffenheim',
  'aliases': ['호펜하임', 'TSG 호펜하임', 'TSG Hoffenheim', 'TSG 1899 Hoffenheim']},
 {'canonical': 'leverkusen',
  'wiki': 'Bayer_04_Leverkusen',
  'aliases': ['레버쿠젠', '바이어 레버쿠젠', 'Bayer Leverkusen', 'Bayer 04 Leverkusen']},
 {'canonical': 'freiburg', 'wiki': 'SC_Freiburg', 'aliases': ['프라이부르크', 'SC Freiburg']},
 {'canonical': 'eintracht frankfurt',
  'wiki': 'Eintracht_Frankfurt',
  'aliases': ['프랑크푸르트', '아인트라흐트 프랑크푸르트', 'Frankfurt', 'Eintracht Frankfurt']},
 {'canonical': 'augsburg', 'wiki': 'FC_Augsburg', 'aliases': ['아우크스부르크', 'FC Augsburg']},
 {'canonical': 'mainz',
  'wiki': '1._FSV_Mainz_05',
  'aliases': ['마인츠', '마인츠 05', 'Mainz 05', 'FSV Mainz', '1. FSV Mainz 05']},
 {'canonical': 'union berlin',
  'wiki': '1._FC_Union_Berlin',
  'aliases': ['우니온 베를린', '우니온베를린', 'Union Berlin', '1. FC Union Berlin']},
 {'canonical': 'm gladbach',
  'wiki': 'Borussia_Mönchengladbach',
  'aliases': ['묀헨글라트바흐',
              '묀헨글라드바흐',
              '글라트바흐',
              '글라드바흐',
              "M'gladbach",
              'Gladbach',
              'Monchengladbach',
              'Borussia Monchengladbach',
              'Borussia Mönchengladbach']},
 {'canonical': 'hamburg', 'wiki': 'Hamburger_SV', 'aliases': ['함부르크', '함부르크 SV', 'HSV', 'Hamburger SV']},
 {'canonical': 'cologne',
  'wiki': '1._FC_Köln',
  'aliases': ['쾰른', '퀼른', 'FC 쾰른', 'Koln', 'Köln', '1. FC Koln', '1. FC Köln']},
 {'canonical': 'werder bremen',
  'wiki': 'SV_Werder_Bremen',
  'aliases': ['브레멘', '베르더 브레멘', 'Werder Bremen', 'SV Werder Bremen']},
 {'canonical': 'schalke', 'wiki': 'FC_Schalke_04', 'aliases': ['샬케', '샬케 04', 'Schalke 04', 'FC Schalke 04']},
 {'canonical': 'elversberg', 'wiki': 'SV_Elversberg', 'aliases': ['엘버스베르크', '엘버스버그', 'SV Elversberg']},
 {'canonical': 'paderborn',
  'wiki': 'SC_Paderborn_07',
  'aliases': ['파더보른', '파더보른 07', 'SC Paderborn', 'SC Paderborn 07']},
 {'canonical': 'sevilla', 'wiki': 'Sevilla_FC', 'aliases': ['세비야', 'Sevilla FC']},
 {'canonical': 'athletic',
  'wiki': 'Athletic_Bilbao',
  'aliases': ['아틀레틱 빌바오', '아틀레틱 클루브', '빌바오', 'Athletic Bilbao', 'Athletic Club']},
 {'canonical': 'barcelona', 'wiki': 'FC_Barcelona', 'aliases': ['바르셀로나', '바르사', 'FC Barcelona', 'Barca']},
 {'canonical': 'espanyol',
  'wiki': 'RCD_Espanyol',
  'aliases': ['에스파뇰', '에스파놀', 'RCD Espanyol', 'RCD Espanyol de Barcelona']},
 {'canonical': 'real madrid', 'wiki': 'Real_Madrid_CF', 'aliases': ['레알마드리드', '레알 마드리드', '레알', 'Real Madrid CF']},
 {'canonical': 'atletico',
  'wiki': 'Atlético_Madrid',
  'aliases': ['아틀레티코', '아틀레티코 마드리드', 'Atletico Madrid', 'Atlético de Madrid', 'Atletico de Madrid']},
 {'canonical': 'real betis',
  'wiki': 'Real_Betis',
  'aliases': ['레알 베티스', '베티스', 'Real Betis Balompie', 'Real Betis Balompié']},
 {'canonical': 'real sociedad', 'wiki': 'Real_Sociedad', 'aliases': ['레알 소시에다드', '소시에다드']},
 {'canonical': 'malaga', 'wiki': 'Málaga_CF', 'aliases': ['말라가', 'Málaga CF', 'Malaga CF']},
 {'canonical': 'elche', 'wiki': 'Elche_CF', 'aliases': ['엘체', 'Elche CF']},
 {'canonical': 'villarreal', 'wiki': 'Villarreal_CF', 'aliases': ['비야레알', '비야레알 CF', 'Villarreal CF']},
 {'canonical': 'celta',
  'wiki': 'RC_Celta_de_Vigo',
  'aliases': ['셀타', '셀타 비고', 'Celta Vigo', 'RC Celta', 'RC Celta de Vigo']},
 {'canonical': 'rayo', 'wiki': 'Rayo_Vallecano', 'aliases': ['라요', '라요 바예카노', '라요 발레카노', 'Rayo Vallecano']},
 {'canonical': 'getafe', 'wiki': 'Getafe_CF', 'aliases': ['헤타페', 'Getafe CF']},
 {'canonical': 'racing',
  'wiki': 'Racing_de_Santander',
  'aliases': ['라싱', '라싱 산탄데르', 'Racing Santander', 'R. Racing Club', 'Real Racing Club']},
 {'canonical': 'valencia', 'wiki': 'Valencia_CF', 'aliases': ['발렌시아', 'Valencia CF']},
 {'canonical': 'alaves',
  'wiki': 'Deportivo_Alavés',
  'aliases': ['알라베스', '데포르티보 알라베스', 'Alavés', 'Deportivo Alaves', 'Deportivo Alavés']},
 {'canonical': 'osasuna', 'wiki': 'CA_Osasuna', 'aliases': ['오사수나', 'CA Osasuna']},
 {'canonical': 'deportivo',
  'wiki': 'Deportivo_de_La_Coruña',
  'aliases': ['데포르티보', '데포르티보 라코루냐', '라코루냐', 'Deportivo La Coruna', 'Deportivo La Coruña', 'RC Deportivo']},
 {'canonical': 'levante', 'wiki': 'Levante_UD', 'aliases': ['레반테', 'Levante UD']},
 {'canonical': 'inter',
  'wiki': 'Inter_Milan',
  'aliases': ['인터', '인터 밀란', '인터밀란', 'Inter Milan', 'Internazionale', 'FC Internazionale Milano']},
 {'canonical': 'monza', 'wiki': 'AC_Monza', 'aliases': ['몬차', 'AC Monza']},
 {'canonical': 'udinese', 'wiki': 'Udinese_Calcio', 'aliases': ['우디네세', 'Udinese Calcio']},
 {'canonical': 'como', 'wiki': 'Como_1907', 'aliases': ['코모', '코모 1907', 'Como 1907']},
 {'canonical': 'genoa', 'wiki': 'Genoa_CFC', 'aliases': ['제노아', 'Genoa CFC']},
 {'canonical': 'napoli', 'wiki': 'SSC_Napoli', 'aliases': ['나폴리', 'SSC Napoli']},
 {'canonical': 'roma', 'wiki': 'AS_Roma', 'aliases': ['로마', 'AS 로마', 'AS Roma']},
 {'canonical': 'fiorentina', 'wiki': 'ACF_Fiorentina', 'aliases': ['피오렌티나', 'ACF Fiorentina']},
 {'canonical': 'atalanta', 'wiki': 'Atalanta_BC', 'aliases': ['아탈란타', 'Atalanta BC']},
 {'canonical': 'sassuolo', 'wiki': 'US_Sassuolo_Calcio', 'aliases': ['사수올로', 'US Sassuolo', 'Sassuolo Calcio']},
 {'canonical': 'bologna', 'wiki': 'Bologna_FC_1909', 'aliases': ['볼로냐', 'Bologna FC', 'Bologna FC 1909']},
 {'canonical': 'lazio', 'wiki': 'SS_Lazio', 'aliases': ['라치오', 'SS Lazio']},
 {'canonical': 'frosinone', 'wiki': 'Frosinone_Calcio', 'aliases': ['프로시노네', 'Frosinone Calcio']},
 {'canonical': 'juventus', 'wiki': 'Juventus_FC', 'aliases': ['유벤투스', '유베', 'Juventus FC']},
 {'canonical': 'parma', 'wiki': 'Parma_Calcio_1913', 'aliases': ['파르마', 'Parma Calcio', 'Parma Calcio 1913']},
 {'canonical': 'cagliari', 'wiki': 'Cagliari_Calcio', 'aliases': ['칼리아리', 'Cagliari Calcio']},
 {'canonical': 'torino', 'wiki': 'Torino_FC', 'aliases': ['토리노', 'Torino FC']},
 {'canonical': 'milan', 'wiki': 'AC_Milan', 'aliases': ['AC 밀란', 'AC밀란', '밀란', 'AC Milan']},
 {'canonical': 'venezia', 'wiki': 'Venezia_FC', 'aliases': ['베네치아', 'Venezia FC']},
 {'canonical': 'lecce', 'wiki': 'US_Lecce', 'aliases': ['레체', 'US Lecce']},
 {'canonical': 'angers', 'wiki': 'Angers_SCO', 'aliases': ['앙제', 'Angers SCO']},
 {'canonical': 'auxerre', 'wiki': 'AJ_Auxerre', 'aliases': ['오세르', 'AJ Auxerre']},
 {'canonical': 'monaco', 'wiki': 'AS_Monaco_FC', 'aliases': ['모나코', 'AS Monaco', 'AS Monaco FC']},
 {'canonical': 'brest',
  'wiki': 'Stade_Brestois_29',
  'aliases': ['브레스트', '스타드 브레스트', 'Stade Brestois', 'Stade Brestois 29']},
 {'canonical': 'lorient', 'wiki': 'FC_Lorient', 'aliases': ['로리앙', 'FC Lorient']},
 {'canonical': 'le havre', 'wiki': 'Le_Havre_AC', 'aliases': ['르아브르', '르 아브르', 'Le Havre AC']},
 {'canonical': 'lille', 'wiki': 'Lille_OSC', 'aliases': ['릴', 'LOSC', 'Lille OSC']},
 {'canonical': 'nice', 'wiki': 'OGC_Nice', 'aliases': ['니스', 'OGC Nice']},
 {'canonical': 'lyon', 'wiki': 'Olympique_Lyonnais', 'aliases': ['리옹', '올랭피크 리옹', 'OL', 'Olympique Lyonnais']},
 {'canonical': 'marseille',
  'wiki': 'Olympique_de_Marseille',
  'aliases': ['마르세유', '올랭피크 마르세유', 'OM', 'Olympique Marseille', 'Olympique de Marseille']},
 {'canonical': 'paris fc', 'wiki': 'Paris_FC', 'aliases': ['파리 FC', '파리FC', 'Paris Football Club']},
 {'canonical': 'paris saint germain',
  'wiki': 'Paris_Saint-Germain_F.C.',
  'aliases': ['파리 생제르맹',
              '파리생제르맹',
              '생제르맹',
              'PSG',
              'Paris Saint-Germain',
              'Paris Saint Germain',
              'Paris Saint-Germain FC']},
 {'canonical': 'lens', 'wiki': 'RC_Lens', 'aliases': ['랑스', 'RC Lens']},
 {'canonical': 'rennes',
  'wiki': 'Stade_Rennais_F.C.',
  'aliases': ['렌', '렌느', '스타드 렌', 'Stade Rennais', 'Stade Rennais FC']},
 {'canonical': 'strasbourg',
  'wiki': 'RC_Strasbourg_Alsace',
  'aliases': ['스트라스부르', 'RC Strasbourg', 'RC Strasbourg Alsace']},
 {'canonical': 'toulouse', 'wiki': 'Toulouse_FC', 'aliases': ['툴루즈', 'Toulouse FC']},
 {'canonical': 'le mans', 'wiki': 'Le_Mans_FC', 'aliases': ['르망', '르 망', 'Le Mans FC']},
 {'canonical': 'troyes', 'wiki': 'ES_Troyes_AC', 'aliases': ['트루아', '트루아 AC', 'ESTAC', 'ESTAC Troyes', 'ES Troyes AC']}]

TEAM_ALIASES = {}
WIKI_PAGES = {}
TEAM_SUGGESTIONS = []

for team in TEAM_DATA:
    canonical = normalize_text(team["canonical"])
    WIKI_PAGES[canonical] = team["wiki"]

    for alias in [team["canonical"]] + team["aliases"]:
        TEAM_ALIASES[normalize_text(alias)] = canonical

    if team["aliases"]:
        TEAM_SUGGESTIONS.append(team["aliases"][0])
    TEAM_SUGGESTIONS.append(team["canonical"].title())

TEAM_SUGGESTIONS = sorted(set(TEAM_SUGGESTIONS))

# Guardian에서 A Bilbao처럼 줄여 쓰는 팀명도 연결합니다.
TEAM_TOKEN_ALIASES = {}
_token_owners = {}
for alias, canonical in TEAM_ALIASES.items():
    for token in alias.split():
        if len(token) < 5:
            continue
        _token_owners.setdefault(token, set()).add(canonical)
for token, owners in _token_owners.items():
    if len(owners) == 1:
        TEAM_TOKEN_ALIASES[token] = next(iter(owners))

DATE_PATTERN = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"\d{1,2}\s+[A-Za-z]+\s+20\d{2}$"
)
TIME_PATTERN = re.compile(r"^(\d{1,2}[:.]\d{2})(?:\s+[A-Z]{2,5})?$")
POSITION_WORDS = {
    "gk", "df", "mf", "fw", "goalkeeper", "defender", "midfielder", "forward"
}
BAD_IMAGE_WORDS = {
    "logo", "crest", "badge", "flag", "signature", "autograph", "kit", "shirt",
    "jersey", "stadium", "supporters", "fans", "trophy", "statue", "mural",
    "squad", "team photo", "lineup", "line up", "group photo", "poster", "banner",
}


def get_soup(url, params=None):
    response = request_get(url, params=params)
    return BeautifulSoup(response.text, "html.parser"), response.url


# ------------------------------------------------------------------
# The Guardian 경기 일정
# ------------------------------------------------------------------

def next_token(tokens, start):
    index = start
    while index < len(tokens):
        token = clean_text(tokens[index])
        if token.lower() not in {"", "image"}:
            return token, index
        index += 1
    return "", len(tokens)


def parse_schedule(soup, league_name, source_url):
    tokens = [clean_text(text) for text in soup.stripped_strings if clean_text(text)]
    games = []
    used_games = set()
    current_date = ""
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if DATE_PATTERN.fullmatch(token):
            current_date = token
            index += 1
            continue

        time_match = TIME_PATTERN.fullmatch(token)
        is_tbc = token.upper() in {"TBC", "TBD"}

        if current_date and (time_match or is_tbc):
            home_team, home_index = next_token(tokens, index + 1)
            versus, versus_index = next_token(tokens, home_index + 1)
            away_team, away_index = next_token(tokens, versus_index + 1)

            if home_team and versus.lower() == "v" and away_team:
                game_key = (current_date, home_team, away_team)
                if game_key not in used_games:
                    used_games.add(game_key)
                    game_time = token
                    if time_match:
                        game_time = time_match.group(1).replace(".", ":")
                    games.append({
                        "league": league_name,
                        "season": CURRENT_SEASON,
                        "date": current_date,
                        "time": game_time,
                        "home_team": home_team,
                        "away_team": away_team,
                        "source_url": source_url,
                    })
                index = away_index + 1
                continue

        index += 1

    return games


def search_schedule(league_key):
    league = LEAGUES[league_key]
    try:
        soup, real_url = get_soup(league["url"])
        games = parse_schedule(soup, league["name"], real_url)
        return games, real_url, ""
    except (requests.RequestException, ValueError) as error:
        print(league["name"], "일정 수집 실패:", error)
        return [], league["url"], str(error)


def collect_all_games():
    all_games = []
    status = {}
    collected = {}

    with ThreadPoolExecutor(max_workers=len(LEAGUES)) as executor:
        future_map = {
            executor.submit(search_schedule, league_key): league_key
            for league_key in LEAGUES
        }
        for future in as_completed(future_map):
            league_key = future_map[future]
            try:
                collected[league_key] = future.result()
            except Exception as error:
                collected[league_key] = ([], LEAGUES[league_key]["url"], str(error))

    for league_key in LEAGUES:
        games, source_url, error = collected.get(
            league_key, ([], LEAGUES[league_key]["url"], "수집 결과 없음")
        )
        all_games.extend(games)
        status[league_key] = {
            "league": LEAGUES[league_key]["name"],
            "count": len(games),
            "expected": LEAGUES[league_key]["expected"],
            "source_url": source_url,
            "error": error,
        }

    return all_games, status


def change_keyword(keyword):
    search_word = normalize_text(keyword)
    if search_word in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[search_word]
    if search_word in TEAM_ALIASES:
        return TEAM_ALIASES[search_word]
    return search_word


def search_games(all_games, keyword):
    if normalize_text(keyword) in {"전체", "all"}:
        return all_games

    search_word = change_keyword(keyword)
    results = []
    for game in all_games:
        fields = [game["league"], game["home_team"], game["away_team"]]
        if any(search_word in normalize_text(value) for value in fields):
            results.append(game)
    return results


# ------------------------------------------------------------------
# Google News / Bing News RSS
# ------------------------------------------------------------------

def make_news_query(keyword):
    search_word = normalize_text(keyword)
    if search_word in {"전체", "all"}:
        return "European football"
    if search_word in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[search_word] + " football"
    if search_word in TEAM_ALIASES:
        return TEAM_ALIASES[search_word] + " football"
    return clean_text(keyword) + " football"


def _valid_http_url(value):
    if not value:
        return ""
    value = html.unescape(clean_text(value))
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def _description_links(description):
    if not description:
        return []
    soup = BeautifulSoup(html.unescape(description), "html.parser")
    return [_valid_http_url(a.get("href", "")) for a in soup.find_all("a", href=True)]


def _extract_item_link(item, query):
    candidates = [
        item.findtext("link", default=""),
        item.findtext("guid", default=""),
    ]

    candidates.extend(_description_links(item.findtext("description", default="")))

    source_tag = item.find("source")
    if source_tag is not None:
        candidates.append(source_tag.get("url", ""))

    for candidate in candidates:
        url = _valid_http_url(candidate)
        if not url:
            continue
        parsed = urlparse(url)
        query_values = parse_qs(parsed.query)
        for key in ("url", "u", "target"):
            if key in query_values:
                direct = _valid_http_url(query_values[key][0])
                if direct:
                    return direct
        return url

    return "https://news.google.com/search?q=" + quote(query)


def parse_news_feed(content, query, limit=10):
    root = ET.fromstring(content)
    results = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title", default=""))
        if not title:
            continue
        source_tag = item.find("source")
        source = clean_text(source_tag.text if source_tag is not None else "")
        published = clean_text(item.findtext("pubDate", default=""))
        link = _extract_item_link(item, query)
        results.append({
            "title": title,
            "link": link,
            "published": published,
            "source": source or "News",
        })
        if len(results) >= limit:
            break

    return results


def _news_feed_requests(query):
    return [
        (
            "https://news.google.com/rss/search",
            {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
        ),
        (
            "https://www.bing.com/news/search",
            {"q": query, "format": "rss", "setlang": "ko-kr"},
        ),
        (
            "https://news.google.com/rss/search",
            {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        ),
    ]


def search_news(keyword, limit=10):
    query = make_news_query(keyword)
    collected = []
    used = set()

    for url, params in _news_feed_requests(query):
        try:
            response = request_get(
                url,
                params=params,
                headers={
                    **HEADERS,
                    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                },
            )
            items = parse_news_feed(response.content, query, limit=limit)
        except (requests.RequestException, ET.ParseError, ValueError) as error:
            print("뉴스 피드 수집 실패:", url, error)
            continue

        for article in items:
            key = normalize_text(article["title"])
            if not key or key in used:
                continue
            used.add(key)
            collected.append(article)
            if len(collected) >= limit:
                return collected

    return collected


# ------------------------------------------------------------------
# Wikipedia 팀 문서와 선수단
# ------------------------------------------------------------------

def empty_squad(message):
    return {
        "team_name": "",
        "players": [],
        "source_url": "",
        "logo_url": "",
        "message": message,
    }


def resolve_team_name(keyword):
    search_word = normalize_text(keyword)
    if search_word in TEAM_ALIASES:
        return TEAM_ALIASES[search_word]
    if search_word in WIKI_PAGES:
        return search_word
    for canonical in sorted(WIKI_PAGES, key=len, reverse=True):
        if canonical in search_word:
            return canonical
    candidates = {
        TEAM_TOKEN_ALIASES[token]
        for token in search_word.split()
        if token in TEAM_TOKEN_ALIASES
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return search_word


def _wiki_page_url(title):
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()._-&–")


def _wiki_search_titles(query, limit=8):
    response = request_get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "list": "search",
            "srsearch": query,
            "srnamespace": 0,
            "srlimit": limit,
        },
    )
    return response.json().get("query", {}).get("search", [])


def _score_team_title(title, snippet, search_word):
    normalized_title = normalize_text(title)
    normalized_snippet = normalize_text(BeautifulSoup(snippet or "", "html.parser").get_text(" "))
    tokens = [token for token in normalize_text(search_word).split() if len(token) > 2]
    score = 0
    score += sum(4 for token in tokens if token in normalized_title)
    score += sum(1 for token in tokens if token in normalized_snippet)
    if "football club" in normalized_snippet or "association football club" in normalized_snippet:
        score += 5
    if any(word in normalized_title for word in ["women", "reserve", "academy", "youth", "season"]):
        score -= 6
    return score


def find_wikipedia_page(keyword):
    search_word = resolve_team_name(keyword)
    if search_word in WIKI_PAGES:
        return get_soup(_wiki_page_url(WIKI_PAGES[search_word]))

    results = _wiki_search_titles(search_word + " football club", limit=8)
    if not results:
        raise ValueError("팀 문서를 찾지 못했습니다.")
    best = max(results, key=lambda item: _score_team_title(
        item.get("title", ""), item.get("snippet", ""), search_word
    ))
    return get_soup(_wiki_page_url(best.get("title", "")))


def get_team_logo(soup):
    for image in soup.select("table.infobox img, .infobox img"):
        alt = normalize_text(image.get("alt", ""))
        if any(word in alt for word in ["flag", "kit", "jersey", "shirt", "map"]):
            continue
        image_url = image.get("src") or image.get("data-src") or ""
        if image_url.startswith("//"):
            image_url = "https:" + image_url
        elif image_url.startswith("/"):
            image_url = urljoin("https://en.wikipedia.org", image_url)
        if _valid_http_url(image_url):
            return image_url
    return ""


def get_nationality(cell):
    image = cell.find("img")
    if image is not None:
        nationality = image.get("alt") or image.get("title") or ""
        if nationality:
            return clean_text(nationality)
    return clean_text(cell.get_text(" ", strip=True))


def get_player_info(cell):
    links = cell.find_all("a", href=True)
    for link in reversed(links):
        name = clean_text(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if not name or not href.startswith("/wiki/") or "new" in link.get("class", []):
            continue
        title = unquote(href.split("/wiki/", 1)[1]).replace("_", " ")
        if ":" in title:
            continue
        return {
            "name": name,
            "wiki_title": title,
            "profile_url": urljoin("https://en.wikipedia.org", href),
        }
    return {
        "name": clean_text(cell.get_text(" ", strip=True)),
        "wiki_title": "",
        "profile_url": "",
    }


def _make_player(number_cell, position_cell, nation_cell, player_cell):
    position = clean_text(position_cell.get_text(" ", strip=True))
    if normalize_text(position) not in POSITION_WORDS:
        return None
    player_info = get_player_info(player_cell)
    name = clean_text(player_info["name"])
    name = re.sub(r"\s*\((captain|vice-captain|on loan).*?\)\s*$", "", name, flags=re.I)
    if not name or normalize_text(name) == "player":
        return None
    return {
        "number": clean_text(number_cell.get_text(" ", strip=True)) or "-",
        "position": position or "-",
        "nationality": get_nationality(nation_cell) or "-",
        "name": name,
        "wiki_title": player_info["wiki_title"],
        "profile_url": player_info["profile_url"],
        "image_url": "",
    }


def _players_from_row(row):
    cells = row.find_all(["td", "th"], recursive=False)
    players = []
    for index, cell in enumerate(cells):
        if normalize_text(cell.get_text(" ", strip=True)) not in POSITION_WORDS:
            continue
        if index < 1 or index + 2 >= len(cells):
            continue
        player = _make_player(cells[index - 1], cell, cells[index + 1], cells[index + 2])
        if player:
            players.append(player)
    return players


def parse_squad(soup):
    players = []
    used_names = set()

    for table in soup.select("table"):
        table_text = normalize_text(table.get_text(" ", strip=True))
        if "player" not in table_text or not any(pos in table_text.split() for pos in ["gk", "df", "mf", "fw"]):
            continue

        table_players = []
        for row in table.select("tr"):
            table_players.extend(_players_from_row(row))

        if not table_players:
            continue

        for player in table_players:
            key = normalize_text(player["name"])
            if key and key not in used_names:
                used_names.add(key)
                players.append(player)

        if len(players) >= 15:
            break

    return players[:32]


def _merge_players(original, extra):
    result = list(original)
    used = {normalize_text(player["name"]) for player in result}
    for player in extra:
        key = normalize_text(player["name"])
        if key and key not in used:
            used.add(key)
            result.append(player)
    return result[:32]


def _season_page_players(team_name):
    for season_label in WIKI_SEASON_LABELS:
        query = f'"{season_label}" "{team_name}" season'
        try:
            results = _wiki_search_titles(query, limit=5)
        except (requests.RequestException, ValueError):
            continue

        for item in results:
            title = item.get("title", "")
            normalized = normalize_text(title)
            if "season" not in normalized:
                continue
            try:
                soup, _ = get_soup(_wiki_page_url(title))
                players = parse_squad(soup)
            except (requests.RequestException, ValueError):
                continue
            if players:
                return players
    return []


# ------------------------------------------------------------------
# Wikipedia / Wikidata / Commons 선수 사진
# ------------------------------------------------------------------

def _change_api_title(title, title_map):
    changed = title
    for _ in range(4):
        if changed not in title_map:
            break
        changed = title_map[changed]
    return changed


def request_page_data(titles):
    if not titles:
        return {}, {}

    response = request_get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "pageimages|pageprops|info",
            "piprop": "thumbnail|original",
            "pithumbsize": 420,
            "pilicense": "any",
            "ppprop": "wikibase_item",
            "inprop": "url",
            "redirects": 1,
            "titles": "|".join(titles[:50]),
        },
    )
    query = response.json().get("query", {})
    title_map = {}
    for group in ("normalized", "redirects"):
        for item in query.get(group, []):
            old = item.get("from", "")
            new = item.get("to", "")
            if old and new:
                title_map[old] = new

    page_map = {}
    for page in query.get("pages", []):
        title = page.get("title", "")
        if not title:
            continue
        page_map[title] = {
            "image_url": page.get("thumbnail", {}).get("source", "")
                         or page.get("original", {}).get("source", ""),
            "profile_url": page.get("fullurl", ""),
            "wikidata_id": page.get("pageprops", {}).get("wikibase_item", ""),
        }
    return page_map, title_map


def _commons_urls(file_names):
    if not file_names:
        return {}
    titles = ["File:" + name for name in file_names]
    response = request_get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 500,
            "titles": "|".join(titles[:50]),
        },
    )
    result = {}
    for page in response.json().get("query", {}).get("pages", []):
        image_info = (page.get("imageinfo") or [{}])[0]
        url = image_info.get("thumburl") or image_info.get("url") or ""
        file_title = page.get("title", "").replace("File:", "", 1)
        if file_title and url:
            result[file_title] = url
    return result


def _wikidata_images(wikidata_ids):
    ids = [item for item in dict.fromkeys(wikidata_ids) if item]
    if not ids:
        return {}
    response = request_get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(ids[:50]),
            "props": "claims",
        },
    )
    entity_to_file = {}
    for entity_id, entity in response.json().get("entities", {}).items():
        claims = entity.get("claims", {}).get("P18", [])
        if not claims:
            continue
        value = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if isinstance(value, str) and value:
            entity_to_file[entity_id] = value
    file_urls = _commons_urls(list(entity_to_file.values()))
    return {
        entity_id: file_urls.get(file_name, "")
        for entity_id, file_name in entity_to_file.items()
    }


def _bad_image_title(title):
    normalized = normalize_text(title)
    return any(word in normalized for word in BAD_IMAGE_WORDS)


def _score_player_result(title, snippet, player_name, team_name):
    normalized_title = normalize_text(title)
    normalized_snippet = normalize_text(BeautifulSoup(snippet or "", "html.parser").get_text(" "))
    player_tokens = [token for token in normalize_text(player_name).split() if len(token) > 1]
    team_tokens = [token for token in normalize_text(team_name).split() if len(token) > 3]
    score = 0
    score += sum(5 for token in player_tokens if token in normalized_title)
    score += sum(2 for token in player_tokens if token in normalized_snippet)
    score += sum(1 for token in team_tokens if token in normalized_snippet)
    if "footballer" in normalized_snippet or "football player" in normalized_snippet:
        score += 5
    if any(word in normalized_title for word in ["disambiguation", "list of", "season"]):
        score -= 10
    return score


def _search_wikipedia_player(player_name, team_name):
    queries = [
        f'"{player_name}" footballer "{team_name}"',
        f'"{player_name}" association football player',
    ]
    candidates = []
    for query in queries:
        try:
            candidates.extend(_wiki_search_titles(query, limit=8))
        except (requests.RequestException, ValueError):
            continue
    if not candidates:
        return {"image_url": "", "profile_url": "", "wiki_title": ""}

    candidates.sort(
        key=lambda item: _score_player_result(
            item.get("title", ""), item.get("snippet", ""), player_name, team_name
        ),
        reverse=True,
    )
    titles = [item.get("title", "") for item in candidates[:6] if item.get("title")]
    page_map, title_map = request_page_data(titles)
    for title in titles:
        final_title = _change_api_title(title, title_map)
        data = page_map.get(final_title, {})
        if data.get("image_url"):
            return {
                "image_url": data["image_url"],
                "profile_url": data.get("profile_url", ""),
                "wiki_title": final_title,
            }
    return {"image_url": "", "profile_url": "", "wiki_title": ""}


def _search_commons_player(player_name, team_name):
    query = f'"{player_name}" football'
    if team_name:
        query += " " + team_name
    response = request_get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 500,
        },
    )
    pages = response.json().get("query", {}).get("pages", [])
    name_tokens = [token for token in normalize_text(player_name).split() if len(token) > 1]
    scored = []
    for page in pages:
        title = page.get("title", "")
        if _bad_image_title(title):
            continue
        normalized_title = normalize_text(title)
        score = sum(4 for token in name_tokens if token in normalized_title)
        if score == 0:
            continue
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url") or ""
        if url:
            scored.append((score, url))
    if not scored:
        return ""
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1]


@lru_cache(maxsize=512)
def search_player_photo(player_name, team_name="", wiki_title="", skip_primary=False):
    """정확한 문서 → Wikidata → 이름 검색 → Commons 순서로 사진을 찾습니다."""

    title = clean_text(wiki_title) or clean_text(player_name)
    if title and not skip_primary:
        try:
            page_map, title_map = request_page_data([title])
            final_title = _change_api_title(title, title_map)
            data = page_map.get(final_title, {})
            if data.get("image_url"):
                return data["image_url"]
            wikidata_id = data.get("wikidata_id", "")
            if wikidata_id:
                wikidata_images = _wikidata_images([wikidata_id])
                if wikidata_images.get(wikidata_id):
                    return wikidata_images[wikidata_id]
        except (requests.RequestException, ValueError):
            pass

    try:
        result = _search_wikipedia_player(player_name, team_name)
        if result.get("image_url"):
            return result["image_url"]
    except (requests.RequestException, ValueError):
        pass

    try:
        return _search_commons_player(player_name, team_name)
    except (requests.RequestException, ValueError):
        return ""


def add_player_images(players, team_name=""):
    """
    선수 사진을 빠르게 가져옵니다.

    모든 선수 문서 제목을 Wikipedia API에 한 번만 전달하고,
    pageimages 결과만 사용합니다. 검색 화면이 뜨기 전에
    선수별 Wikidata·Commons 추가 검색을 하지 않습니다.
    """
    if not players:
        return players

    request_titles = []
    for player in players[:32]:
        title = player.get("wiki_title") or player.get("name", "")
        if title and title not in request_titles:
            request_titles.append(title)

    try:
        page_map, title_map = request_page_data(request_titles)
    except (requests.RequestException, ValueError) as error:
        print("선수 사진 일괄 수집 실패:", error)
        return players

    for player in players:
        requested_title = player.get("wiki_title") or player.get("name", "")
        final_title = _change_api_title(requested_title, title_map)
        data = page_map.get(final_title, {})

        if data.get("image_url"):
            player["image_url"] = data["image_url"]

        if not player.get("profile_url") and data.get("profile_url"):
            player["profile_url"] = data["profile_url"]

    return players


@lru_cache(maxsize=256)
def search_team_logo(team_name):
    try:
        soup, _ = find_wikipedia_page(team_name)
        logo_url = get_team_logo(soup)
        if logo_url:
            return logo_url

        canonical = resolve_team_name(team_name)
        title = WIKI_PAGES.get(canonical, team_name)
        page_map, title_map = request_page_data([title])
        final_title = _change_api_title(title, title_map)
        return page_map.get(final_title, {}).get("image_url", "")
    except (requests.RequestException, ValueError):
        return ""


def search_team_squad(keyword):
    search_word = normalize_text(keyword)
    if search_word in {"전체", "all"} or search_word in LEAGUE_ALIASES:
        return empty_squad("리그명 검색에는 팀 스쿼드가 표시되지 않습니다.")

    try:
        soup, source_url = find_wikipedia_page(keyword)
        title_tag = soup.select_one("h1")
        team_name = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else keyword
        logo_url = get_team_logo(soup)
        players = parse_squad(soup)

        # 팀 기본 문서에서 선수를 찾았다면 바로 사용합니다.
        # 기존처럼 15명 미만일 때 시즌 문서를 여러 번 검색하지 않습니다.
        if not players:
            players = _season_page_players(team_name)

        players = add_player_images(players, team_name)

        if not players:
            return {
                "team_name": team_name,
                "players": [],
                "source_url": source_url,
                "logo_url": logo_url,
                "message": "Wikipedia 문서는 찾았지만 선수단 표를 찾지 못했습니다.",
            }

        return {
            "team_name": team_name,
            "players": players,
            "source_url": source_url,
            "logo_url": logo_url,
            "message": "",
        }
    except (requests.RequestException, ValueError) as error:
        print("스쿼드 수집 실패:", error)
        return empty_squad("팀 문서 또는 선수단 정보를 가져오지 못했습니다.")
