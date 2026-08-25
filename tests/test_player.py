"""Status folding and console layout."""

import unittest

from omampy import config, library, modes, player, render


def settings(**overrides):
    return config.validate(overrides)


def tracks(count=6):
    return [library.track_from_path("/m/Artist - %02d - Song %d.mp3" % (i + 1, i + 1))
            for i in range(count)]


PLAYING = {"pause": False, "path": "/m/Trio - Da Da Da.mp3", "time-pos": 83.0,
           "duration": 220.0, "playlist-pos": 2, "playlist-count": 9,
           "volume": 68, "mute": False, "metadata": {}}


class RepeatTests(unittest.TestCase):
    def test_repeat_all_loops_the_playlist_only(self):
        self.assertEqual(player.repeat_properties("all"),
                         {"loop-playlist": "inf", "loop-file": "no"})

    def test_repeat_one_loops_the_file_only(self):
        self.assertEqual(player.repeat_properties("one"),
                         {"loop-playlist": "no", "loop-file": "inf"})

    def test_repeat_off_loops_nothing(self):
        self.assertEqual(player.repeat_properties("off"),
                         {"loop-playlist": "no", "loop-file": "no"})

    def test_an_unknown_mode_loops_nothing(self):
        self.assertEqual(player.repeat_properties("sideways")["loop-file"], "no")

    def test_every_configured_mode_is_handled(self):
        for mode in config.REPEAT_MODES:
            self.assertEqual(set(player.repeat_properties(mode)),
                             {"loop-playlist", "loop-file"})


class LaunchArgTests(unittest.TestCase):
    def args(self, **overrides):
        return player.launch_args(settings(**overrides), "/run/s.sock", "GRAPH", "/x.m3u")

    def test_the_binary_comes_first(self):
        self.assertEqual(self.args()[0], "mpv")
        self.assertEqual(player.launch_args(settings(mpv="/opt/mpv"), "/s", "G")[0], "/opt/mpv")

    def test_the_users_own_mpv_config_is_kept_out(self):
        self.assertIn("--no-config", self.args())

    def test_it_runs_headless_and_stays_alive_when_the_playlist_ends(self):
        args = self.args()
        self.assertIn("--no-video", args)
        self.assertIn("--no-terminal", args)
        self.assertIn("--idle=yes", args)

    def test_the_socket_graph_and_playlist_are_all_passed(self):
        args = self.args()
        self.assertIn("--input-ipc-server=/run/s.sock", args)
        self.assertIn("--af=@omampy:lavfi=[GRAPH]", args)
        self.assertIn("--playlist=/x.m3u", args)

    def test_the_playlist_is_omitted_when_there_is_none(self):
        args = player.launch_args(settings(), "/run/s.sock", "GRAPH")
        self.assertFalse(any(a.startswith("--playlist=") for a in args))

    def test_volume_and_repeat_come_from_the_settings(self):
        args = self.args(volume=33, repeat="one")
        self.assertIn("--volume=33", args)
        self.assertIn("--loop-file=inf", args)
        self.assertIn("--loop-playlist=no", args)

    def test_shuffle_is_only_passed_when_it_is_on(self):
        self.assertIn("--shuffle", self.args(shuffle=True))
        self.assertNotIn("--shuffle", self.args(shuffle=False))


class TrackNameTests(unittest.TestCase):
    def test_tags_are_preferred_over_the_filename(self):
        props = {"path": "/m/01 - unknown.mp3",
                 "metadata": {"artist": "Trio", "title": "Da Da Da"}}
        self.assertEqual(player.track_names(props), ("Trio", "Da Da Da"))

    def test_tag_keys_are_matched_whatever_their_case(self):
        props = {"path": "/m/x.mp3", "metadata": {"ARTIST": "Trio", "Title": "Da Da Da"}}
        self.assertEqual(player.track_names(props), ("Trio", "Da Da Da"))

    def test_the_album_artist_stands_in_for_a_missing_artist(self):
        props = {"path": "/m/x.mp3",
                 "metadata": {"album_artist": "Various", "title": "Da Da Da"}}
        self.assertEqual(player.track_names(props), ("Various", "Da Da Da"))

    def test_the_filename_fills_in_what_the_tags_do_not_have(self):
        props = {"path": "/m/Trio - Da Da Da.mp3", "metadata": {}}
        self.assertEqual(player.track_names(props), ("Trio", "Da Da Da"))

    def test_a_partial_tag_set_is_completed_from_the_filename(self):
        props = {"path": "/m/Trio - Da Da Da.mp3", "metadata": {"title": "Tagged"}}
        self.assertEqual(player.track_names(props), ("Trio", "Tagged"))

    def test_empty_tags_do_not_win_over_the_filename(self):
        props = {"path": "/m/Trio - Da Da Da.mp3", "metadata": {"artist": "", "title": None}}
        self.assertEqual(player.track_names(props), ("Trio", "Da Da Da"))

    def test_with_no_path_the_media_title_is_used(self):
        self.assertEqual(player.track_names({"media-title": "Stream"}), ("", "Stream"))

    def test_nothing_at_all_gives_empty_names(self):
        self.assertEqual(player.track_names({}), ("", ""))

    def test_broken_metadata_does_not_raise(self):
        self.assertEqual(player.track_names({"metadata": "nonsense"}), ("", ""))


class StatusTests(unittest.TestCase):
    def test_a_receiver_that_is_down_reports_stopped(self):
        status = player.status_from_props(None, settings())
        self.assertFalse(status["running"])
        self.assertEqual(status["state"], player.STATE_STOPPED)

    def test_playing_is_reported_with_its_track_and_clock(self):
        status = player.status_from_props(PLAYING, settings())
        self.assertEqual(status["state"], player.STATE_PLAYING)
        self.assertEqual(status["display"], "Trio — Da Da Da")
        self.assertEqual(status["position"], 83.0)
        self.assertEqual(status["duration"], 220.0)
        self.assertEqual(status["index"], 2)
        self.assertEqual(status["count"], 9)

    def test_pause_is_reported(self):
        status = player.status_from_props(dict(PLAYING, **{"pause": True}), settings())
        self.assertEqual(status["state"], player.STATE_PAUSED)

    def test_an_idle_receiver_is_not_paused(self):
        status = player.status_from_props({"idle-active": True}, settings())
        self.assertEqual(status["state"], player.STATE_IDLE)

    def test_a_receiver_with_no_file_loaded_is_idle(self):
        self.assertEqual(player.status_from_props({"pause": False}, settings())["state"],
                         player.STATE_IDLE)

    def test_band_details_come_from_the_settings(self):
        status = player.status_from_props(PLAYING, settings(band="sw"))
        self.assertEqual(status["band"], "sw")
        self.assertEqual(status["bandLabel"], "SW")
        self.assertEqual(status["bandTitle"], modes.MODES["sw"]["title"])
        self.assertEqual(status["dialLabel"], modes.dial_label("sw"))

    def test_missing_numbers_do_not_raise(self):
        status = player.status_from_props({"path": "/m/x.mp3", "time-pos": None,
                                           "duration": "nonsense"}, settings())
        self.assertEqual(status["position"], 0.0)
        self.assertEqual(status["duration"], 0.0)

    def test_a_negative_position_is_clamped(self):
        status = player.status_from_props(dict(PLAYING, **{"time-pos": -3}), settings())
        self.assertEqual(status["position"], 0.0)

    def test_the_status_shape_is_the_same_up_or_down(self):
        self.assertEqual(set(player.status_from_props(None, settings())),
                         set(player.status_from_props(PLAYING, settings())))


class PlaylistWindowTests(unittest.TestCase):
    def test_an_empty_playlist_shows_nothing(self):
        self.assertEqual(player.playlist_window([], 0, 5), [])

    def test_a_short_playlist_is_shown_whole(self):
        self.assertEqual(len(player.playlist_window(tracks(3), 0, 5)), 3)

    def test_the_window_is_capped_at_the_requested_rows(self):
        self.assertEqual(len(player.playlist_window(tracks(20), 10, 5)), 5)

    def test_the_current_track_is_always_visible(self):
        for index in range(20):
            window = player.playlist_window(tracks(20), index, 5)
            self.assertTrue(any(entry["current"] for entry in window), index)

    def test_exactly_one_entry_is_current(self):
        window = player.playlist_window(tracks(20), 7, 5)
        self.assertEqual(sum(1 for entry in window if entry["current"]), 1)

    def test_the_window_stays_inside_the_playlist(self):
        for index in (-5, 0, 19, 99):
            for entry in player.playlist_window(tracks(20), index, 5):
                self.assertGreaterEqual(entry["index"], 0)
                self.assertLess(entry["index"], 20)

    def test_the_start_and_end_of_the_playlist_still_fill_the_window(self):
        self.assertEqual(len(player.playlist_window(tracks(20), 0, 5)), 5)
        self.assertEqual(len(player.playlist_window(tracks(20), 19, 5)), 5)

    def test_numbers_are_one_based(self):
        self.assertEqual(player.playlist_window(tracks(3), 0, 3)[0]["number"], 1)

    def test_zero_rows_is_rejected(self):
        with self.assertRaises(ValueError):
            player.playlist_window(tracks(3), 0, 0)


class TrackLineTests(unittest.TestCase):
    def test_the_line_is_exactly_the_requested_width(self):
        entry = {"number": 3, "display": "Trio — Da Da Da", "current": False}
        self.assertEqual(render.display_width(player.track_line(entry, 30)), 30)

    def test_the_current_track_is_marked(self):
        entry = {"number": 3, "display": "x", "current": True}
        self.assertTrue(player.track_line(entry, 20).startswith("▶"))

    def test_other_tracks_are_not(self):
        entry = {"number": 3, "display": "x", "current": False}
        self.assertFalse(player.track_line(entry, 20).startswith("▶"))

    def test_a_long_title_does_not_widen_the_line(self):
        entry = {"number": 3, "display": "x" * 200, "current": False}
        self.assertEqual(render.display_width(player.track_line(entry, 24)), 24)


class ConsoleTests(unittest.TestCase):
    def build(self, status=None, width=46, height=8, **kwargs):
        status = status or player.status_from_props(PLAYING, settings(band="sw"))
        values = kwargs.pop("values", [0.5] * 14)
        return player.console(status, values, tracks=tracks(), width=width,
                              height=height, **kwargs)

    def test_every_drawn_line_is_exactly_the_console_width(self):
        for width in (30, 46, 72):
            for line in self.build(width=width)["lines"]:
                self.assertEqual(render.display_width(line), width, width)

    def test_the_spectrum_is_as_tall_as_requested(self):
        self.assertEqual(len(self.build(height=12)["spectrum"]), 12)

    def test_the_spectrum_is_as_wide_as_the_band_count(self):
        drawn = self.build(values=[0.5] * 9)
        for row in drawn["spectrum"]:
            self.assertEqual(render.display_width(row), 9)

    def test_the_selected_band_is_marked_on_the_switch(self):
        self.assertIn("▐SW▌", self.build()["bandSwitch"])

    def test_the_frequency_readout_is_on_the_dial(self):
        self.assertIn("9.75 MHz", self.build()["dial"])

    def test_the_now_playing_line_carries_the_track(self):
        self.assertIn("Trio", self.build()["nowPlaying"])

    def test_the_transport_shows_elapsed_and_total(self):
        drawn = self.build()
        self.assertEqual(drawn["elapsed"], "1:23")
        self.assertEqual(drawn["total"], "3:40")
        self.assertIn("1:23", drawn["transport"])

    def test_the_status_tag_follows_the_state(self):
        for state, tag in player.STATUS_TAGS.items():
            status = dict(player.status_from_props(PLAYING, settings()), state=state)
            self.assertEqual(player.console(status, [0.5] * 14)["statusTag"], tag)

    def test_a_stopped_receiver_still_draws_a_console(self):
        status = player.status_from_props(None, settings())
        drawn = player.console(status, [0.0] * 14, width=40)
        self.assertTrue(drawn["lines"])
        for line in drawn["lines"]:
            self.assertEqual(render.display_width(line), 40)

    def test_an_empty_playlist_drops_the_track_list(self):
        status = player.status_from_props(PLAYING, settings())
        self.assertEqual(player.console(status, [0.5] * 14, tracks=[])["playlist"], [])

    def test_peaks_are_optional(self):
        status = player.status_from_props(PLAYING, settings())
        self.assertTrue(player.console(status, [0.5] * 14, [0.9] * 14)["spectrum"])

    def test_the_marquee_offset_changes_a_long_title(self):
        long_title = dict(player.status_from_props(PLAYING, settings()),
                          display="a very long station identifier indeed, quite long")
        first = player.console(long_title, [0.5] * 14, width=30)["nowPlaying"]
        later = player.console(long_title, [0.5] * 14, width=30, offset=5)["nowPlaying"]
        self.assertNotEqual(first, later)

    def test_a_console_narrower_than_the_minimum_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build(width=10)

    def test_the_frame_carries_both_pieces_and_a_drawing(self):
        drawn = self.build()
        for key in ("rows", "top", "bottom", "lines", "spectrum", "mini", "bandSwitch",
                    "dial", "signal", "intensity", "nowPlaying", "transport",
                    "playlist", "statusTag", "inner"):
            self.assertIn(key, drawn)

    def test_every_row_is_padded_to_the_inner_width(self):
        drawn = self.build(width=52)
        self.assertEqual(drawn["inner"], 50)
        for row in drawn["rows"]:
            self.assertEqual(render.display_width(row["text"]), 50, row["kind"])

    def test_the_rows_reassemble_into_the_drawing(self):
        drawn = self.build()
        self.assertEqual(len(drawn["lines"]), len(drawn["rows"]) + 2)
        for row, line in zip(drawn["rows"], drawn["lines"][1:-1]):
            self.assertEqual(line, "│" + row["text"] + "│")

    def test_every_row_is_tagged_with_a_known_kind(self):
        known = {player.ROW_BLANK, player.ROW_SPECTRUM, player.ROW_BAND, player.ROW_DIAL,
                 player.ROW_METER, player.ROW_NOW, player.ROW_TRANSPORT, player.ROW_TRACK}
        for row in self.build()["rows"]:
            self.assertIn(row["kind"], known)

    def test_the_spectrum_is_centred_in_a_wider_console(self):
        rows = [r for r in self.build(width=60, values=[1.0] * 14)["rows"]
                if r["kind"] == player.ROW_SPECTRUM]
        text = rows[-1]["text"]
        self.assertTrue(text.startswith(" "))
        self.assertTrue(text.endswith(" "))
        left = len(text) - len(text.lstrip(" "))
        right = len(text) - len(text.rstrip(" "))
        self.assertLessEqual(abs(left - right), 1)

    def test_there_is_one_spectrum_row_per_requested_height(self):
        rows = self.build(height=6)["rows"]
        self.assertEqual(sum(1 for row in rows if row["kind"] == player.ROW_SPECTRUM), 6)

    def test_track_rows_carry_their_playlist_index(self):
        for row in self.build()["rows"]:
            if row["kind"] == player.ROW_TRACK:
                self.assertIsInstance(row["index"], int)
                self.assertIsInstance(row["current"], bool)

    def test_exactly_one_track_row_is_current(self):
        rows = [r for r in self.build()["rows"] if r["kind"] == player.ROW_TRACK]
        self.assertEqual(sum(1 for row in rows if row["current"]), 1)

    def test_the_miniature_spectrum_is_one_row_of_fixed_width(self):
        mini = self.build()["mini"]
        self.assertEqual(render.display_width(mini), player.MINI_COLUMNS)
        self.assertNotIn("\n", mini)

    def test_the_top_and_bottom_close_the_frame(self):
        drawn = self.build()
        self.assertTrue(drawn["top"].startswith("┌") and drawn["top"].endswith("┐"))
        self.assertTrue(drawn["bottom"].startswith("└") and drawn["bottom"].endswith("┘"))


if __name__ == "__main__":
    unittest.main()
