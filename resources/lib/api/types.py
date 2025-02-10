from dataclasses import dataclass


@dataclass
class Caption:
    label: str
    lang: str
    url: str

    @classmethod
    def from_response(cls, item: dict):
        return cls(label=item["label"], lang=item["language_code"], url=item["url"])


@dataclass
class VideoSearchResult:
    type = "video"
    id: str
    thumbnail_url: str
    heading: str
    channel: str
    channel_id: str
    description: str | None
    view_count: int
    published: int
    duration: int

    @staticmethod
    def extract_thumbnail_url(thumbnails: list[dict]) -> str:
        return (
            next(t for t in thumbnails if t["quality"] == "high") or thumbnails[-1]
        )["url"]

    @classmethod
    def from_response(cls, item: dict):
        thumbnail_url = cls.extract_thumbnail_url(item["videoThumbnails"])
        return cls(
            id=item["videoId"],
            thumbnail_url=thumbnail_url,
            heading=item["title"],
            channel=item["author"],
            channel_id=item["authorId"],
            description=item.get("description"),  # Missing in search results
            view_count=item.get("viewCount", -1),  # Missing for playlists.
            published=item.get("published", 0),
            duration=item["lengthSeconds"],
        )


@dataclass
class ChannelSearchResult:
    type = "channel"
    id: str
    thumbnail_url: str
    heading: str
    description: str | None
    verified: str
    sub_count: int

    @staticmethod
    def extract_thumbnail_url(thumbnails: list[dict]) -> str:
        """
        Grab the highest resolution avatar image
        Usually isn't more than 512x512
        """
        url: str = sorted(thumbnails, key=lambda t: t["height"], reverse=True)[0]["url"]
        return f"https:{url}" if not url.startswith("https://") else url

    @classmethod
    def from_response(cls, item: dict):
        thumbnail_url = cls.extract_thumbnail_url(item["authorThumbnails"])
        return cls(
            id=item["authorId"],
            thumbnail_url=thumbnail_url,
            heading=item["author"],
            description=item.get("description"),
            verified=item["authorVerified"],
            sub_count=item["subCount"],
        )


@dataclass
class PlaylistSearchResult:
    type = "playlist"
    id: str
    thumbnail_url: str
    heading: str
    description: str | None
    author: str
    author_id: str
    author_verified: str
    video_count: str

    @classmethod
    def from_response(cls, item: dict):
        return cls(
            id=item["playlistId"],
            thumbnail_url=item["playlistThumbnail"],
            heading=item["title"],
            description=item.get("description"),
            author=item["author"],
            author_id=item["authorId"],
            author_verified=item["authorVerified"],
            video_count=item["videoCount"],
        )


InvidiousApiResponseType = (
    VideoSearchResult | ChannelSearchResult | PlaylistSearchResult
)
