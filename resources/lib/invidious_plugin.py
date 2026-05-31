import json
import os
import sys
from datetime import datetime
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode

import inputstreamhelper
import invidious_api
import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from infotagger.listitem import ListItemInfoTag

class SearchHistory:
    def __init__(self, history_path: str, depth: int = 10):
        self.history_path = history_path
        self.depth = depth
        d = os.path.dirname(history_path)
        if not os.path.exists(d):
            xbmc.log(f"invidous created state directory {d}.", xbmc.LOGDEBUG)
            os.mkdir(d)

    def push(self, query: str):
        if xbmcvfs.exists(self.history_path):
            with open(self.history_path, "r") as file:
                queries = json.load(file)
        else:
            queries = []
        if query in queries:
            queries.remove(query)
        queries.insert(0, query)
        queries = queries[: self.depth]
        with open(self.history_path, "w+") as file:
            json.dump(queries, file)

    def queries(self):
        if not xbmcvfs.exists(self.history_path):
            return []
        with open(self.history_path, "r") as file:
            return json.load(file)

class InvidiousPlugin:
    INSTANCESURL = "https://api.invidious.io/instances.json?sort_by=type,health"
    def __init__(self, base_url: str, addon_handle: int, args: dict[str, Any]):
        self.base_url = base_url
        self.addon_handle = addon_handle
        self.addon = xbmcaddon.Addon()
        self.args = args
        self.api_client = None
        path = xbmcvfs.translatePath(self.addon.getAddonInfo("profile"))
        self.search_history = SearchHistory(path + "search-history.json", 20)
        settings = self.addon.getSettings()
        self.auto_instance = settings.getBool("auto_instance")
        self.disable_dash = settings.getBool("disable_dash")
        self.show_instance_trending = settings.getBool("show_instance_trending")
        self.show_instance_popular = settings.getBool("show_instance_popular")
        instance_auth = None
        if self.auto_instance or not settings.getString("instance_url"):
            instance_url = self.instance_autodetect()
            self.addon.setSetting("instance_url", instance_url)
        else:
            instance_url = self.addon.getSetting("instance_url")
            if settings.getString("instance_username") and not self.auto_instance:
                instance_auth = {
                    "username": settings.getString("instance_username"),
                    "password": settings.getString("instance_password"),
                }
        if not instance_url:
            return
        xbmc.log(f"invidous using instance {instance_url}.", xbmc.LOGINFO)
        self.api_client = invidious_api.InvidiousAPIClient(instance_url, auth=instance_auth)

    def instance_autodetect(self):
        xbmc.log("invidious picking instance automatically.", xbmc.LOGINFO)
        response = requests.get(self.INSTANCESURL, timeout=5)
        data = response.json()
        for instanceinfo in data:
            instancename, instance = instanceinfo
            if "https" == instance["type"] and instance["api"] is not False and instance["monitor"]["down_since"] is None:
                instance_url = instance["uri"]
                test_video_id = "1l2_uCyBXQ0"
                api_client = invidious_api.InvidiousAPIClient(instance_url)
                try:
                    api_client.fetch_video_information(test_video_id)
                    return instance_url
                except Exception:
                    pass
        xbmc.log("invidious no working https type instance with API support returned from api.invidious.io.", xbmc.LOGWARNING)
        dialog = xbmcgui.Dialog()
        dialog.notification(
            self.addon.getLocalizedString(30012),
            self.addon.getLocalizedString(30013),
            "error",
        )
        return None

    def build_url(self, action, **kwargs):
        if not action:
            raise ValueError("you need to specify an action")
        kwargs["action"] = action
        return self.base_url + "?" + urlencode(kwargs)

    def add_directory_item(self, *args, **kwargs):
        xbmcplugin.addDirectoryItem(self.addon_handle, *args, **kwargs)

    def end_of_directory(self):
        xbmcplugin.endOfDirectory(self.addon_handle)

    def display_search_results(self, results: Iterator[invidious_api.InvidiousApiResponseType]):
        for result in results:
            if result.type not in ["video", "channel", "playlist", "continuation"]:
                raise RuntimeError("unknown result type " + result.type)
            if result.type == "continuation":
                continue


            list_item = xbmcgui.ListItem(result.heading)
            list_item.setArt({"thumb": result.thumbnail_url})
            list_item.setProperty("IsPlayable", "true")
            if isinstance(result, invidious_api.VideoSearchResult):
                datestr = datetime.utcfromtimestamp(result.published).date().isoformat()
                info_tag = ListItemInfoTag(list_item, "video")
                info_tag.set_info(
                    {
                        "title": result.heading,
                        "mediatype": "video",
                        "plot": result.description,
                        "credits": result.author,
                        "date": datestr,
                        "dateadded": datestr,
                        "premiered": datestr,
                        "duration": result.duration,
                    }
                )
                channelUrl = self.build_url("view_channel", channel_id=result.authorId)
                context_menu = [(f'Go To {result.author}', f'Container.Update({channelUrl})')]
                list_item.addContextMenuItems(context_menu)
                url = self.build_url("play_video", video_id=result.id)
                self.add_directory_item(url=url, listitem=list_item)
            elif isinstance(result, invidious_api.ChannelSearchResult):
                url = self.build_url("view_channel", channel_id=result.id)
                info_tag = ListItemInfoTag(list_item, "video")
                info_tag.set_info({"title": result.heading, "plot": result.description})
                self.add_directory_item(url=url, listitem=list_item, isFolder=True)
            elif isinstance(result, invidious_api.PlaylistSearchResult):
                url = self.build_url("view_playlist", playlist_id=result.id)
                if not result.isListed:
                    url = self.build_url("view_user_playlist", playlist_id=result.id)
                self.add_directory_item(url=url, listitem=list_item, isFolder=True)
        actionsWithNextPage = ["user_feed", "view_playlist", "view_channel", "view_user_playlist"]
        action = self.args.get("action", [None])[0]
        channel_id = self.args.get("channel_id", [None])[0]
        playlist_id = self.args.get("playlist_id", [None])[0]
        nextPage = self.get_page_argument() + 1
        if(action in actionsWithNextPage):
            npUrl = self.build_url(action, page=nextPage, channel_id=channel_id, playlist_id=playlist_id)
            list_item = xbmcgui.ListItem(f"Page {nextPage}")
            self.add_directory_item(url=npUrl, listitem=list_item, isFolder=True)
        self.end_of_directory()

    def get_page_argument(self) -> int:
        return int(self.args.get("page", ['1'])[0])

    def display_new_search(self):
        dialog = xbmcgui.Dialog()
        search_input = dialog.input(self.addon.getLocalizedString(30001), type=xbmcgui.INPUT_ALPHANUM)
        self.display_search_result(search_input)

    def display_search_result(self, search_input):
        if len(search_input) == 0:
            return
        self.search_history.push(search_input)
        xbmc.log(f"invidious searching for {search_input}.", xbmc.LOGDEBUG)
        results = self.api_client.search(search_input)
        self.display_search_results(results)

    def display_channel_list(self, channel_id):
        videos = self.api_client.fetch_channel_list(channel_id)
        self.display_search_results(videos)

    def display_playlist_list(self, playlist_id, page: int = 1):
        videos = self.api_client.fetch_playlist_list(playlist_id, page)
        self.display_search_results(videos)

    def display_user_playlist_list(self, playlist_id, page: int = 1):
        videos = self.api_client.fetch_user_playlist_list(playlist_id, page)
        self.display_search_results(videos)

    def play_video(self, id):
        video_info = self.api_client.fetch_video_information(id)
        listitem = None
        if not self.disable_dash and "dashUrl" in video_info:
            is_helper = inputstreamhelper.Helper("mpd")
            if is_helper.check_inputstream():
                url = video_info["dashUrl"]
                listitem = xbmcgui.ListItem(path=url)
                listitem.setProperty("inputstream", is_helper.inputstream_addon)
                listitem.setProperty("inputstream.adaptive.manifest_type", "mpd")
        if listitem is None:
            url = video_info["formatStreams"][-1]["url"]
            listitem = xbmcgui.ListItem(path=url)
        datestr = datetime.utcfromtimestamp(video_info["published"]).date().isoformat()
        info_tag = ListItemInfoTag(listitem, "video")
        info_tag.set_info(
            {
                "title": video_info["title"],
                "mediatype": "video",
                "plot": video_info["description"],
                "credits": video_info["author"],
                "date": datestr,
                "dateadded": datestr,
                "premiered": datestr,
                "duration": str(video_info["lengthSeconds"]),
            }
        )
        if self.addon.getSettingBool("mark_items_watched") and self.api_client.username:
            try:
                self.api_client.mark_watched(id)
            except Exception as e:
                xbmc.log(f"invidious: Failed to mark item watched: {e}", xbmc.LOGERROR)
        if self.addon_handle > -1:
            xbmcplugin.setResolvedUrl(self.addon_handle, succeeded=True, listitem=listitem)
        else:
            xbmc.Player().play(url, listitem)

    def display_main_menu(self):
        def add_list_item(label, path):
            listitem = xbmcgui.ListItem(label, path=path)
            self.add_directory_item(url=self.build_url(path), listitem=listitem, isFolder=True)
        add_list_item(self.addon.getLocalizedString(30001), "search_menu")
        if self.api_client and self.api_client.username:
            add_list_item("Feed", "user_feed")
            add_list_item("Subscriptions", "user_subscriptions")
            add_list_item("My Playlists", "user_playlists")
        if self.show_instance_popular:
            add_list_item(self.addon.getLocalizedString(30020), "popular")
        if self.show_instance_trending:
            add_list_item(self.addon.getLocalizedString(30021), "trending")
        self.end_of_directory()

    def display_search_submenu(self):
        def add_list_item(label, path):
            listitem = xbmcgui.ListItem(label, path=path)
            self.add_directory_item(url=self.build_url(path), listitem=listitem, isFolder=True)
        add_list_item(self.addon.getLocalizedString(30002), "new_search")
        for query in self.search_history.queries():
            url = self.build_url("search", q=query)
            listitem = xbmcgui.ListItem(query, path=query)
            self.add_directory_item(url=url, listitem=listitem, isFolder=True)
        self.end_of_directory()

    def run(self):
        action = self.args.get("action", [None])[0]
        if not self.api_client:
            return
        
        try:
            if not action:
                self.display_main_menu()
            elif action == "search_menu":
                self.display_search_submenu()
            elif action == "new_search":
                self.display_new_search()
            elif action == "search":
                self.display_search_result(self.args["q"][0])
            elif action == "play_video":
                self.play_video(self.args["video_id"][0])
            elif action == "view_channel":
                self.display_channel_list(self.args["channel_id"][0])
            elif action == "view_playlist":
                page = self.get_page_argument()
                self.display_playlist_list(self.args["playlist_id"][0], page)
            elif action == "view_user_playlist":
                page = self.get_page_argument()
                self.display_user_playlist_list(self.args["playlist_id"][0], page)
            elif action == "user_feed":
                self.display_search_results(self.api_client.fetch_feed(self.get_page_argument()))
            elif action == "user_subscriptions":
                self.display_search_results(self.api_client.fetch_subscribed_channels())
            elif action == "user_playlists":
                self.display_search_results(self.api_client.fetch_playlists())
            elif action in ("trending", "popular"):
                self.display_search_results(self.api_client.fetch_special_list(action))
            else:
                raise RuntimeError("unknown action " + action)
        except requests.HTTPError as e:
            dialog = xbmcgui.Dialog()
            dialog.notification(self.addon.getLocalizedString(30003), self.addon.getLocalizedString(30004) + str(e.response.status_code), "error")
        except requests.Timeout:
            dialog = xbmcgui.Dialog()
            dialog.notification(self.addon.getLocalizedString(30005), self.addon.getLocalizedString(30006), "error")

    @classmethod
    def from_argv(cls):
        base_url = sys.argv[0]
        addon_handle = int(sys.argv[1])
        args = parse_qs(sys.argv[2][1:])
        return cls(base_url, addon_handle, args)
