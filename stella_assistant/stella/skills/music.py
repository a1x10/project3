"""Музыка: Яндекс Музыка (треки, артисты, альбомы, плейлисты, «Моя волна», жанры, подкасты, аудиокниги,
лайки/дизлайки), интернет-радио, подкасты из любых RSS, локальная музыка и аудиокниги с запоминанием места
(например, MP3 из Литрес)."""
from __future__ import annotations

import random
import re
import threading
import time
from pathlib import Path

from ..audio.player import Track
from ..nlp.text import best_match, clean
from .base import Reply, Skill, intent

AUDIO_EXT = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".m4b", ".aac", ".wav", ".wma"}
GENRES = {
    "рок": "genre:rock", "поп": "genre:pop", "джаз": "genre:jazz", "классик": "genre:classicalmusic",
    "электрон": "genre:electronics", "рэп": "genre:rap", "хип": "genre:rap", "метал": "genre:metal",
    "инди": "genre:indie", "блюз": "genre:blues", "регги": "genre:reggae", "шансон": "genre:shanson",
    "детск": "genre:children", "саундтрек": "genre:soundtrack", "кантри": "genre:country", "фолк": "genre:folk",
    "панк": "genre:punk", "диско": "genre:disco", "лаунж": "genre:lounge", "эстрад": "genre:estrada",
}
MOODS = {"спокойн": "mood:calm", "весел": "mood:happy", "грустн": "mood:sad", "энергичн": "mood:energetic",
         "для сна": "activity:fall-asleep", "для работы": "activity:work-background",
         "для тренировк": "activity:workout", "для вечеринк": "activity:party", "для дороги": "activity:road-trip"}


def natural_key(p: Path):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", p.name)]


class Music(Skill):
    name = "music"

    def __init__(self, a):
        super().__init__(a)
        self._ym = None
        self._ym_lock = threading.Lock()
        self.station = None
        self.station_batch = None
        self.current_radio = None
        a.player.position_saver = self._save_book_position

    # ------------------------------------------------------- Яндекс Музыка --
    def ym(self):
        token = self.cfg.get("yandex_music.token")
        if not token:
            return None
        with self._ym_lock:
            if self._ym is None:
                try:
                    from yandex_music import Client
                    from yandex_music.utils.request import Request
                    self._ym = Client(token, request=Request(timeout=15)).init()
                    self.log.info("Яндекс Музыка: вошли как %s", getattr(self._ym.me.account, "login", "?"))
                except Exception as e:
                    self.log.error("Яндекс Музыка недоступна: %s", e)
                    return None
            return self._ym

    @staticmethod
    def _direct_link(track) -> str:
        infos = track.get_download_info(get_direct_links=True)
        mp3 = [i for i in infos if i.codec == "mp3"] or infos
        best = max(mp3, key=lambda i: i.bitrate_in_kbps)
        return best.direct_link

    def _ym_track(self, t, source="yandex") -> Track:
        return Track(title=t.title or "без названия", artist=", ".join(t.artists_name() or []),
                     resolver=lambda tr=t: self._direct_link(tr), source=source, id=str(t.track_id or t.id),
                     meta={"duration": (t.duration_ms or 0) / 1000})

    def _station_tracks(self, station: str) -> list[Track]:
        client = self.ym()
        last = self.a.player.current()
        queue = last.id if last and last.source == "yandex" else None
        res = client.rotor_station_tracks(station, queue=queue) if queue else client.rotor_station_tracks(station)
        if not res:
            return []
        self.station_batch = res.batch_id
        return [self._ym_track(s.track) for s in res.sequence if s.track]

    def play_station(self, station: str, title: str) -> Reply:
        client = self.ym()
        if not client:
            return self._no_yandex()
        tracks = self._station_tracks(station)
        if not tracks:
            return Reply("Не получилось запустить волну.", emotion="sadness")
        self.station = station
        try:
            client.rotor_station_feedback_radio_started(station, "stella", self.station_batch)
        except Exception:
            pass
        self.a.player.play(tracks, mode="station", refill=lambda: self._station_tracks(station))
        return Reply(f"Включаю {title}.", emotion="joy", intensity=0.7)

    def _no_yandex(self) -> Reply:
        return Reply("Для Яндекс Музыки нужен токен в настройках (yandex_music.token). А пока могу включить радио — "
                     "скажи «включи радио».", emotion="sadness", intensity=0.6)

    def search_and_play(self, query: str, kind: str = "all") -> Reply | None:
        client = self.ym()
        if not client:
            return None
        res = client.search(query, type_=kind if kind != "all" else "all")
        if not res:
            return Reply(f"Не нашла «{query}».", emotion="sadness")
        if kind == "track" or (kind == "all" and res.best and res.best.type == "track"):
            items = res.tracks.results if res.tracks else []
            if not items and res.best:
                items = [res.best.result]
            if not items:
                return Reply(f"Не нашла песню «{query}».", emotion="sadness")
            first = items[0]
            tracks = [self._ym_track(first)]
            # дальше — похожее: волна по треку
            station = f"track:{first.id}"
            self.a.player.play(tracks, refill=lambda: self._station_tracks(station))
            return Reply(f"Включаю: {tracks[0].display()}.", emotion="joy", intensity=0.6)
        best_type = res.best.type if res.best else None
        if kind in ("all", "artist") and (best_type == "artist" or kind == "artist"):
            artist = res.best.result if best_type == "artist" else (res.artists.results[0] if res.artists else None)
            if artist is None:
                return Reply(f"Не нашла исполнителя «{query}».", emotion="sadness")
            at = client.artists_tracks(artist.id, page_size=50)
            tracks = [self._ym_track(t) for t in (at.tracks if at else []) if t.available is not False]
            if not tracks:
                return Reply("У этого исполнителя нет доступных треков.", emotion="sadness")
            self.a.player.play(tracks, refill=lambda: self._station_tracks(f"artist:{artist.id}"))
            return Reply(f"Включаю {artist.name}.", emotion="joy", intensity=0.7)
        if kind in ("all", "album") and (best_type == "album" or kind == "album"):
            album = res.best.result if best_type == "album" else (res.albums.results[0] if res.albums else None)
            if album is None:
                return Reply(f"Не нашла альбом «{query}».", emotion="sadness")
            return self._play_album(album.id, f"альбом «{album.title}»")
        if kind in ("all", "playlist") and (best_type == "playlist" or kind == "playlist"):
            pl = res.best.result if best_type == "playlist" else (res.playlists.results[0] if res.playlists else None)
            if pl is None:
                return Reply(f"Не нашла плейлист «{query}».", emotion="sadness")
            return self._play_playlist(pl)
        if kind == "podcast":
            pods = res.podcasts.results if res.podcasts else []
            if not pods:
                return None
            return self._play_album(pods[0].id, f"подкаст «{pods[0].title}»", newest_first=True, source="podcast")
        return Reply(f"Не нашла «{query}».", emotion="sadness")

    def _play_album(self, album_id, title: str, newest_first: bool = False, source: str = "yandex") -> Reply:
        album = self.ym().albums_with_tracks(album_id)
        tracks = [t for vol in (album.volumes or []) for t in vol]
        if newest_first:
            tracks = list(reversed(tracks)) if tracks and getattr(album, "sort_order", "") == "asc" else tracks
        if not tracks:
            return Reply("Тут пусто.", emotion="sadness")
        self.a.player.play([self._ym_track(t, source) for t in tracks])
        return Reply(f"Включаю {title}.", emotion="joy", intensity=0.6)

    def _play_playlist(self, pl, shuffle: bool = False) -> Reply:
        shorts = pl.fetch_tracks()
        tracks = []
        for ts in shorts[:200]:
            t = ts.track or ts.fetch_track()
            if t:
                tracks.append(self._ym_track(t))
        if shuffle:
            random.shuffle(tracks)
        if not tracks:
            return Reply("Плейлист пустой.", emotion="sadness")
        self.a.player.play(tracks)
        return Reply(f"Включаю плейлист «{pl.title}».", emotion="joy", intensity=0.6)

    def play_likes(self) -> Reply:
        client = self.ym()
        if not client:
            likes = self.a.memory.likes()
            return Reply("Без Яндекс Музыки я храню только названия понравившихся песен." if likes else
                         "Пока нет понравившихся песен.")
        lst = client.users_likes_tracks()
        ids = lst.tracks_ids[:100] if lst else []
        if not ids:
            return Reply("В «Мне нравится» пока пусто.", emotion="sadness")
        tracks = [self._ym_track(t) for t in client.tracks(ids)]
        random.shuffle(tracks)
        self.a.player.play(tracks)
        return Reply("Включаю твои любимые песни!", emotion="love", intensity=0.6)

    # -------------------------------------------------------------- радио --
    def find_radio(self, name: str):
        stations: dict = self.cfg.get("music.radio") or {}
        if stations:
            hit, score = best_match(name, list(stations.items()), key=lambda kv: kv[0], threshold=0.55)
            if hit:
                return hit[0], hit[1]
        for host in ("all.api.radio-browser.info", "de1.api.radio-browser.info", "de2.api.radio-browser.info"):
            try:
                data = self.a.get_json(f"https://{host}/json/stations/search",
                                       params={"name": name, "order": "clickcount", "reverse": "true", "limit": 8,
                                               "hidebroken": "true"}, timeout=8, retries=0)
                for st in data:
                    url = st.get("url_resolved") or st.get("url")
                    if url:
                        try:  # просьба сервиса: отмечать прослушивание
                            self.a.http.get(f"https://{host}/json/url/{st['stationuuid']}", timeout=3)
                        except Exception:
                            pass
                        return st["name"].strip(), url
                return None
            except Exception as e:
                self.log.info("radio-browser %s: %s", host, e)
        return None

    def play_radio(self, name: str) -> Reply:
        name = name.strip() or "Европа Плюс"
        found = self.find_radio(name)
        if not found:
            return Reply(f"Не нашла радиостанцию «{name}».", emotion="sadness")
        title, url = found
        self.current_radio = title
        self.a.player.play([Track(title=title, url=url, source="radio")], mode="radio")
        return Reply(f"Включаю радио {title}.", emotion="joy", intensity=0.6)

    # ----------------------------------------------------------- подкасты --
    def play_podcast(self, name: str) -> Reply:
        podcasts: dict = self.cfg.get("music.podcasts") or {}
        feed = None
        title = name
        if podcasts:
            hit, _ = best_match(name, list(podcasts.items()), key=lambda kv: kv[0], threshold=0.5)
            if hit:
                title, feed = hit
        if not feed and self.ym():
            r = self.search_and_play(name, "podcast")
            if r:
                return r
        if not feed:
            try:
                d = self.a.get_json("https://itunes.apple.com/search",
                                    params={"term": name, "media": "podcast", "country": "ru", "limit": 3})
                res = [x for x in d.get("results", []) if x.get("feedUrl")]
                if res:
                    feed, title = res[0]["feedUrl"], res[0].get("collectionName", name)
            except Exception as e:
                self.log.warning("iTunes: %s", e)
        if not feed:
            return Reply(f"Не нашла подкаст «{name}».", emotion="sadness")
        episodes = self._feed_episodes(feed)
        if not episodes:
            return Reply("В этом подкасте не нашла выпусков.", emotion="sadness")
        tracks = [Track(title=ep_title, artist=title, url=url, source="podcast") for ep_title, url in episodes]
        self.a.player.play(tracks)
        return Reply(f"Включаю подкаст «{title}», последний выпуск: {episodes[0][0]}.", emotion="joy", intensity=0.5)

    def _feed_episodes(self, feed: str, limit: int = 20) -> list[tuple[str, str]]:
        """Читаем только начало ленты (большие RSS весят десятки мегабайт)."""
        try:
            with self.a.http.get(feed, timeout=15, stream=True) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_content(65536):
                    data += chunk
                    if data.count(b"</item>") >= limit or len(data) > 4_000_000:
                        break
        except Exception as e:
            self.log.warning("RSS %s: %s", feed, e)
            return []
        text = data.decode("utf-8", "ignore")
        out = []
        for item in re.findall(r"<item\b.*?</item>", text, flags=re.S)[:limit]:
            m_url = re.search(r"<enclosure[^>]+url=[\"']([^\"']+)[\"']", item)
            m_title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, flags=re.S)
            if m_url:
                out.append((re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else "выпуск",
                            m_url.group(1).replace("&amp;", "&")))
        return out

    # ----------------------------------------------------- локальные файлы --
    def _local_files(self, root: Path) -> list[Path]:
        if not root.exists():
            return []
        return sorted((p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT), key=natural_key)

    def play_local(self, query: str = "") -> Reply:
        root = self.cfg.path_of("music.music_dir", "~/Music")
        files = self._local_files(root)
        if not files:
            return Reply("В папке с музыкой пусто.", emotion="sadness")
        if query:
            hit = [f for f in files if clean(query) in clean(str(f.relative_to(root)))]
            files = hit or files
        random.shuffle(files)
        self.a.player.play([Track(title=f.stem, url=str(f), source="local") for f in files[:300]])
        return Reply("Включаю музыку с диска.", emotion="joy", intensity=0.5)

    # -------------------------------------------------------- аудиокниги --
    def _books(self) -> list[Path]:
        root = self.cfg.path_of("music.audiobooks_dir", "~/Audiobooks")
        if not root.exists():
            return []
        books = [p for p in root.iterdir() if p.is_dir() and self._local_files(p)]
        books += [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT]
        return books

    def _save_book_position(self, track: Track, pos: float):
        book = track.meta.get("book")
        if not book:
            return
        idx = track.meta.get("index", 0)
        if pos < 0:  # глава дослушана — следующая
            self.a.memory.kv_set(f"book:{book}", {"index": idx + 1, "pos": 0, "ts": time.time()})
        else:
            self.a.memory.kv_set(f"book:{book}", {"index": idx, "pos": max(0.0, pos - 3), "ts": time.time()})
        self.a.memory.kv_set("book:last", book)

    def play_book(self, query: str | None) -> Reply:
        books = self._books()
        if query:
            hit, _ = best_match(query, books, key=lambda p: p.stem.replace("_", " "), threshold=0.45)
            if not hit:
                if self.ym():  # аудиокниги есть и в Яндекс Музыке (как альбомы)
                    r = self.search_and_play(query, "album")
                    if r:
                        return r
                return Reply(f"Не нашла книгу «{query}». Положи MP3 в папку аудиокниг.", emotion="sadness")
            book = hit
        else:
            last = self.a.memory.kv_get("book:last")
            book = next((b for b in books if str(b) == last), None) or (books[0] if books else None)
            if book is None:
                return Reply("Аудиокниг пока нет. Скопируй их в папку " +
                             str(self.cfg.path_of("music.audiobooks_dir", "~/Audiobooks")) + ".", emotion="sadness")
        files = self._local_files(book) if book.is_dir() else [book]
        state = self.a.memory.kv_get(f"book:{book}", {"index": 0, "pos": 0})
        start = min(state.get("index", 0), len(files) - 1)
        tracks = []
        for i, f in enumerate(files):
            tr = Track(title=f.stem, artist=book.stem, url=str(f), source="audiobook", meta={"book": str(book), "index": i})
            if i == start:
                tr.start = float(state.get("pos", 0))
            tracks.append(tr)
        self.a.memory.kv_set("book:last", str(book))
        self.a.player.play(tracks, start_index=start)
        where = " с того места, где остановились" if state.get("pos") or start else ""
        return Reply(f"Включаю книгу «{book.stem}»{where}.", emotion="joy", intensity=0.5)

    # ---------------------------------------------------------- по умолчанию --
    def play_default(self, quiet_start: bool = False) -> Reply:
        if self.ym():
            return self.play_station("user:onyourwave", "Мою волну")
        if self._local_files(self.cfg.path_of("music.music_dir", "~/Music")):
            return self.play_local()
        return self.play_radio(next(iter((self.cfg.get("music.radio") or {"Европа Плюс": ""}).keys())))

    # --------------------------------------------------------------- команды --
    @intent(r"\b(?:включи|поставь|играй|сыграй|запусти|врубай|вруби|хочу послушать|давай послушаем|проиграй|"
            r"заведи)\s+(.+)$", priority=45, fun=True)
    def play(self, ctx):
        what = ctx.raw_group(1)
        what = re.sub(r"^(?:мне|пожалуйста|нам)\s+", "", what).strip()
        if re.search(r"\b(?:свет|лампу|лампочку|телевизор|чайник|кондиционер|пылесос|розетку|обогреватель|"
                     r"увлажнитель|сценарий|режим|будильник|таймер|радионян\w*|звук|мультирум)\b", what):
            return None  # это умный дом / другие навыки
        try:
            return self._play_what(what)
        except Exception as e:
            self.log.exception("музыка")
            return Reply(f"Не получилось включить: {e}", emotion="sadness")

    def _play_what(self, what: str) -> Reply | None:
        w = what
        if re.fullmatch(r"(?:музык\w*|что(?:-| )?нибудь|какую-нибудь музыку|песни|песню|музон|музычку|"
                        r"мою волну|моя волна|волну|рекомендации|что-то послушать)", w):
            return self.play_default()
        if re.search(r"\b(?:мои лайки|любим\w+ (?:песни|треки|музыку)|мне нравится|избранное|мою музыку|мои треки)\b", w):
            return self.play_likes() if self.ym() else self.play_local()
        m = re.match(r"(?:радио|радиостанцию)\s*(.*)$", w)
        if m:
            return self.play_radio(m.group(1))
        m = re.match(r"(?:подкаст|подкасты|выпуск подкаста)\s*(.*)$", w)
        if m:
            return self.play_podcast(m.group(1) or "новости")
        m = re.match(r"(?:аудиокниг\w*|книг\w*)\s*(.*)$", w)
        if m:
            return self.play_book(m.group(1) or None)
        m = re.match(r"(?:плейлист)\s+(.+)$", w)
        if m:
            client = self.ym()
            if not client:
                return self._no_yandex()
            own = client.users_playlists_list()
            hit, _ = best_match(m.group(1), own, key=lambda p: p.title, threshold=0.5)
            return self._play_playlist(hit) if hit else self.search_and_play(m.group(1), "playlist")
        m = re.match(r"(?:альбом)\s+(.+)$", w)
        if m:
            return self.search_and_play(m.group(1), "album") or self._no_yandex()
        m = re.match(r"(?:песню|трек|композицию)\s+(.+)$", w)
        if m:
            return self.search_and_play(m.group(1), "track") or self.play_local(m.group(1))
        m = re.match(r"(?:локальную музыку|музыку с диска|музыку с флешки)$", w)
        if m:
            return self.play_local()
        for stem, station in MOODS.items():
            if stem in w and re.search(r"музык|песн|что-нибудь|плейлист", w):
                return self.play_station(station, f"музыку {stem}") if self.ym() else self.play_local()
        for stem, station in GENRES.items():
            if re.search(rf"\b{stem}\w*", w) and len(w.split()) <= 3:
                return self.play_station(station, w) if self.ym() else self.play_radio(w)
        m = re.match(r"(?:музыку|песни|треки)\s+(.+)$", w)
        if m:
            w = m.group(1)
        if self.ym():
            return self.search_and_play(w, "all")
        return self.play_local(w) if self._local_files(self.cfg.path_of("music.music_dir", "~/Music")) \
            else self._no_yandex()

    @intent(r"^(?:продолжи|продолжай|возобнови)\s+(?:слушать\s+)?(?:аудиокниг\w*|книг\w*)", priority=47)
    def resume_book(self, ctx):
        return self.play_book(None)

    @intent(r"^(?:пауза|поставь на паузу|на паузу|останови музыку|выключи музыку|стоп музыка|музыку стоп|"
            r"выключи радио|выключи подкаст|выключи книгу|хватит музыки)$", priority=80)
    def pause(self, ctx):
        if self.a.player.is_active():
            self.a.player.pause()
        return Reply("", speak=False)

    @intent(r"^(?:продолжи|продолжай|играй дальше|сними с паузы|включи обратно|продолжи музыку|продолжить|"
            r"играй|включи музыку обратно|снять с паузы)$", priority=79)
    def resume(self, ctx):
        if self.a.player.resume():
            return Reply("", speak=False)
        return self.play_default()

    @intent(r"^(?:дальше|следующ\w*(?: трек| песн\w*)?|переключи\w*(?: песню| трек)?|другую(?: песню)?|пропусти|"
            r"скип|давай следующую|некст)$", priority=78)
    def next(self, ctx):
        if not self.a.player.is_active():
            return None
        if self.station and self.ym():
            cur = self.a.player.current()
            try:
                self.ym().rotor_station_feedback_skip(self.station, cur.id, self.a.player.position() or 0,
                                                      self.station_batch)
            except Exception:
                pass
        self.a.player.next()
        return Reply("", speak=False)

    @intent(r"^(?:предыдущ\w*(?: трек| песн\w*)?|назад|прошл\w* (?:трек|песн\w*)|верни (?:прошлую|предыдущую)\w*(?: песню)?)$",
            priority=78)
    def prev(self, ctx):
        if not self.a.player.is_active():
            return None
        self.a.player.prev()
        return Reply("", speak=False)

    @intent(r"\bперемотай\b.*?(\d+)?\s*(секунд\w*|минут\w*)?\s*(вперед|назад)?", priority=77)
    def seek(self, ctx):
        n = ctx.norm
        m = re.search(r"(\d+)\s*(секунд|минут)", n)
        sec = int(m.group(1)) * (60 if m.group(2).startswith("минут") else 1) if m else 30
        if "назад" in n:
            sec = -sec
        self.a.player.seek(sec)
        return Reply("", speak=False)

    @intent(r"\bперемешай\b|\bвразнобой\b|\bв случайном порядке\b", priority=76)
    def shuffle(self, ctx):
        p = self.a.player
        if not p.queue:
            return None
        rest = p.queue[p.index + 1:]
        random.shuffle(rest)
        p.queue = p.queue[: p.index + 1] + rest
        return Reply("Перемешала.", emotion="joy", intensity=0.4)

    @intent(r"\b(?:что (?:сейчас |это )?(?:играет|за песня|за трек|звучит|за музыка)|как называется (?:эта )?(?:песня|трек)|"
            r"кто (?:это )?поет|кто исполня\w*)\b", priority=74)
    def now_playing(self, ctx):
        p = self.a.player
        cur = p.current()
        if not (cur and p.is_playing()):
            return None  # не наша музыка — пусть узнает Shazam
        if cur.source == "radio":
            title = p.stream_title()
            if title and re.search(r"\.(?:mp3|aac|aacp|ogg|opus|m3u8?|pls)$|^https?://", title.lower()):
                title = None  # это имя файла потока, а не песня
            if title and title != cur.title:
                return Reply(f"Сейчас на радио {cur.title} играет {title}.", emotion="interest", intensity=0.5)
            return Reply(f"Играет радио {cur.title}.")
        if cur.source == "audiobook":
            return Reply(f"Аудиокнига «{cur.artist}», {cur.title}.")
        return Reply(f"Сейчас играет {cur.display()}.", emotion="interest", intensity=0.5)

    @intent(r"^(?:лайк|мне нравится|нравится|класс(?:ная песня)?|отличная песня|ставлю лайк|поставь лайк|"
            r"запомни эту песню|добавь в избранное|супер песня|люблю эту песню)$", priority=75)
    def like(self, ctx):
        cur = self.a.player.current()
        if not cur:
            return None
        if cur.source == "yandex" and self.ym():
            try:
                self.ym().users_likes_tracks_add(cur.id)
            except Exception as e:
                self.log.warning("лайк: %s", e)
        self.a.memory.like_set(cur.id or cur.title, cur.display(), 1)
        return Reply("Поставила лайк! Буду включать похожее.", emotion="love", intensity=0.7)

    @intent(r"^(?:дизлайк|не нравится|мне не нравится|плохая песня|не включай (?:больше|ее|это)|убери эту песню|"
            r"поставь дизлайк|фу|отстой)$", priority=75)
    def dislike(self, ctx):
        cur = self.a.player.current()
        if not cur:
            return None
        if cur.source == "yandex" and self.ym():
            try:
                self.ym().users_dislikes_tracks_add(cur.id)
            except Exception as e:
                self.log.warning("дизлайк: %s", e)
        self.a.memory.like_set(cur.id or cur.title, cur.display(), -1)
        self.a.player.next()
        return Reply("Поняла, больше не включу.", emotion="contempt", intensity=0.5)

    @intent(r"\bсделай (?:музыку|радио|звук музыки) (тише|громче)\b|\b(тише|громче) музыку\b", priority=73)
    def music_volume(self, ctx):
        louder = "громче" in ctx.norm
        p = self.a.player
        p.set_volume(p.volume + (15 if louder else -15))
        return Reply("", speak=False)
