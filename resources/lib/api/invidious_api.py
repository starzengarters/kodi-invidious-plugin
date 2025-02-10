import time
from typing import Iterator

import requests
import xbmc
import xbmcaddon

from .types import (
    Caption,
    ChannelSearchResult,
    InvidiousApiSearchResponseType,
    PlaylistSearchResult,
    VideoInfoResult,
    VideoSearchResult,
)


class InvidiousAPIClient:
    instance_url: str
    session: requests.Session
    addon: xbmcaddon.Addon
    authenticated: bool
    username: str | None
    password: str | None

    def __init__(self, instance_url: str, auth: None | dict[str, str] = None):
        self.instance_url = instance_url.rstrip("/")
        self.session = requests.Session()
        self.authenticated = False
        self.username, self.password = None, None
        if auth:
            self.username = auth["username"]
            self.password = auth["password"]

    @property
    def base_url(self) -> str:
        return self.instance_url + "/api/v1/"

    def _login(self) -> None:
        if not self.username:
            raise
        login_response = self.session.post(
            self.instance_url + "/login",
            data={
                "email": self.username,
                "password": self.password,
                "action": "signin",
            },
        )

        login_response.raise_for_status()

        if login_response.ok:
            self.authenticated = True

    def _make_get_request(
        self, path: str, params: None | dict[str, str] = None
    ) -> requests.Response:
        assembled_url = self.base_url + path

        xbmc.log(
            f"invidious ========== request {assembled_url} with {params} started ==========",
            xbmc.LOGDEBUG,
        )
        start = time.time()
        response = self.session.get(assembled_url, params=params, timeout=5)
        end = time.time()
        xbmc.log(
            f"invidious ========== request finished in {end - start}s ==========",
            xbmc.LOGDEBUG,
        )

        if response.status_code > 300:
            xbmc.log(
                f"invidious API request {assembled_url} with {params} failed with HTTP status {response.status_code}: {response.reason}.",
                xbmc.LOGWARNING,
            )
        response.raise_for_status()

        return response

    def _parse_list_response(
        self, response: requests.models.Response
    ) -> Iterator[InvidiousApiSearchResponseType]:
        if not response or not response.content:
            raise StopIteration()
        data = response.json()

        # If a channel or playlist is opened, the videos are packaged
        # in a dict entry "videos".
        if "videos" in data:
            data = data["videos"]

        for item in data:
            # Playlist videos do not have the 'type' attribute
            match item.get("type"):
                case "video" | "shortVideo" | None:
                    yield VideoSearchResult.from_response(item)

                case "channel":
                    yield ChannelSearchResult.from_response(item)

                case "playlist":
                    yield PlaylistSearchResult.from_response(item)

                case _:
                    xbmc.log(
                        f'invidious received search result item with unknown response type {item["type"]}.',
                        xbmc.LOGWARNING,
                    )

    def get_caption_url(self, caption: Caption) -> str:
        return f"{self.instance_url}{caption.url}"

    def search(self, *terms):
        params = {
            "q": " ".join(terms),
            "sort_by": "upload_date",
        }

        response = self._make_get_request("search", params)

        return self._parse_list_response(response)

    def fetch_video_information(self, video_id) -> VideoInfoResult:
        response = self._make_get_request(f"videos/{video_id}")
        data = response.json()
        return VideoInfoResult.from_response(data)

    def fetch_channel_list(self, channel_id):
        response = self._make_get_request(f"channels/{channel_id}/videos")

        return self._parse_list_response(response)

    def fetch_playlist_list(self, playlist_id):
        response = self._make_get_request(f"playlists/{playlist_id}")

        return self._parse_list_response(response)

    def fetch_special_list(self, special_list_name: str):
        response = self._make_get_request(special_list_name)

        return self._parse_list_response(response)

    def fetch_feed(self) -> Iterator[VideoSearchResult]:
        if not self.authenticated:
            self._login()
        response = self._make_get_request("auth/feed")

        for result in self._parse_list_response(response):
            if isinstance(result, VideoSearchResult):
                yield result

    def fetch_subscribed_channels(self) -> Iterator[ChannelSearchResult]:
        if not self.authenticated:
            self._login()
        subscriptions_response = self._make_get_request("auth/subscriptions")

        data = subscriptions_response.json()
        for author in data:
            yield self.fetch_channel_info(author["authorId"])

    def fetch_channel_info(self, channel_id: str) -> ChannelSearchResult:
        response = self._make_get_request(f"channels/{channel_id}")

        data = response.json()
        return ChannelSearchResult.from_response(data)

    def subscribe(self, channel_id: str) -> None:
        if not self.authenticated:
            self._login()
        reponse = self.session.post(f"{self.base_url}auth/subscriptions/{channel_id}")
        if reponse.ok:
            return None
        raise

    def unsubscribe(self, channel_id: str) -> None:
        if not self.authenticated:
            self._login()
        response = self.session.delete(
            f"{self.base_url}auth/subscriptions/{channel_id}"
        )
        if response.ok:
            return None
        raise

    def mark_watched(self, video_id: str) -> None:
        if not self.authenticated:
            self._login()
        reponse = self.session.post(f"{self.base_url}auth/history/{video_id}")
        if reponse.ok:
            return None
        raise
