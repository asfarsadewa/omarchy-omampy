"""Finding, naming, and ordering local files."""

import os
import tempfile
import unittest

from omampy import library


class ExtensionTests(unittest.TestCase):
    def test_common_music_formats_are_accepted(self):
        for name in ("a.mp3", "a.m4a", "a.ogg", "a.opus", "a.flac", "a.wav", "a.aac"):
            self.assertTrue(library.is_audio_file(name), name)

    def test_the_check_is_case_insensitive(self):
        self.assertTrue(library.is_audio_file("A.MP3"))

    def test_other_files_are_rejected(self):
        for name in ("cover.jpg", "notes.txt", "movie.mkv", "movie.mp4", "noext"):
            self.assertFalse(library.is_audio_file(name), name)


class NaturalKeyTests(unittest.TestCase):
    def test_numbers_sort_as_numbers(self):
        names = ["t10.mp3", "t2.mp3", "t1.mp3"]
        self.assertEqual(sorted(names, key=library.natural_key),
                         ["t1.mp3", "t2.mp3", "t10.mp3"])

    def test_sorting_ignores_case(self):
        self.assertEqual(sorted(["b", "A"], key=library.natural_key), ["A", "b"])

    def test_leading_zeroes_do_not_change_the_order(self):
        self.assertEqual(sorted(["09 x", "10 x"], key=library.natural_key), ["09 x", "10 x"])

    def test_the_key_is_comparable_for_any_pair(self):
        for name in ("", "1", "a", "1a", "a1", "1a1"):
            self.assertIsInstance(library.natural_key(name), tuple)
        self.assertTrue(library.natural_key("1") < library.natural_key("a"))


class NameParsingTests(unittest.TestCase):
    def test_artist_and_title_are_split_on_a_dash(self):
        self.assertEqual(library.parse_track_name("Trio - Da Da Da"), ("Trio", "Da Da Da"))

    def test_en_and_em_dashes_work_too(self):
        self.assertEqual(library.parse_track_name("Trio – Da Da Da"), ("Trio", "Da Da Da"))
        self.assertEqual(library.parse_track_name("Trio — Da Da Da"), ("Trio", "Da Da Da"))

    def test_a_leading_track_number_is_not_an_artist(self):
        self.assertEqual(library.parse_track_name("01 - Da Da Da"), ("", "Da Da Da"))
        self.assertEqual(library.parse_track_name("01. Da Da Da"), ("", "Da Da Da"))

    def test_a_track_number_between_artist_and_title_is_dropped(self):
        self.assertEqual(library.parse_track_name("Trio - 03 - Da Da Da"), ("Trio", "Da Da Da"))

    def test_underscores_are_read_as_spaces(self):
        self.assertEqual(library.parse_track_name("03_Radio_Ga_Ga"), ("", "Radio Ga Ga"))

    def test_a_dash_inside_a_title_is_kept(self):
        self.assertEqual(library.parse_track_name("Trio - Da - Da - Da"),
                         ("Trio", "Da - Da - Da"))

    def test_a_bare_name_is_all_title(self):
        self.assertEqual(library.parse_track_name("untitled"), ("", "untitled"))

    def test_a_name_that_is_only_a_number_survives(self):
        self.assertEqual(library.parse_track_name("12"), ("", "12"))

    def test_an_empty_name_gives_empty_fields(self):
        self.assertEqual(library.parse_track_name(""), ("", ""))
        self.assertEqual(library.parse_track_name("   "), ("", ""))

    def test_a_hyphenated_word_is_not_a_split(self):
        self.assertEqual(library.parse_track_name("Blue-Eyed Soul"), ("", "Blue-Eyed Soul"))


class TrackTests(unittest.TestCase):
    def test_a_track_is_built_from_the_filename_alone(self):
        track = library.track_from_path("/music/Trio - Da Da Da.mp3", 1234)
        self.assertEqual(track.artist, "Trio")
        self.assertEqual(track.title, "Da Da Da")
        self.assertEqual(track.ext, ".mp3")
        self.assertEqual(track.size, 1234)

    def test_display_joins_artist_and_title(self):
        self.assertEqual(library.track_from_path("/m/Trio - Da Da Da.mp3").display,
                         "Trio — Da Da Da")

    def test_display_falls_back_to_the_title_alone(self):
        self.assertEqual(library.track_from_path("/m/untitled.mp3").display, "untitled")

    def test_an_unparseable_name_still_produces_a_title(self):
        self.assertTrue(library.track_from_path("/m/....mp3").title)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def write(self, *parts, content=b"x"):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_it_finds_audio_and_ignores_everything_else(self):
        self.write("a.mp3")
        self.write("cover.jpg")
        self.write("notes.txt")
        found = library.scan([self.root])
        self.assertEqual([os.path.basename(t.path) for t in found], ["a.mp3"])

    def test_it_recurses_by_default(self):
        self.write("album", "b.mp3")
        self.assertEqual(len(library.scan([self.root])), 1)

    def test_recursion_can_be_turned_off(self):
        self.write("album", "b.mp3")
        self.write("top.mp3")
        found = library.scan([self.root], recursive=False)
        self.assertEqual([os.path.basename(t.path) for t in found], ["top.mp3"])

    def test_results_are_in_natural_order(self):
        for name in ("10 ten.mp3", "2 two.mp3", "1 one.mp3"):
            self.write(name)
        found = library.scan([self.root])
        self.assertEqual([os.path.basename(t.path) for t in found],
                         ["1 one.mp3", "2 two.mp3", "10 ten.mp3"])

    def test_hidden_files_and_directories_are_skipped(self):
        self.write(".hidden.mp3")
        self.write(".cache", "c.mp3")
        self.assertEqual(library.scan([self.root]), [])

    def test_the_same_file_reached_twice_appears_once(self):
        self.write("a.mp3")
        self.assertEqual(len(library.scan([self.root, self.root])), 1)

    def test_a_missing_directory_is_skipped_quietly(self):
        self.write("a.mp3")
        found = library.scan([os.path.join(self.root, "nope"), self.root])
        self.assertEqual(len(found), 1)

    def test_scanning_nothing_gives_nothing(self):
        self.assertEqual(library.scan([]), [])

    def test_the_limit_caps_the_result(self):
        for i in range(6):
            self.write("t%d.mp3" % i)
        self.assertEqual(len(library.scan([self.root], limit=3)), 3)

    def test_sizes_are_recorded(self):
        self.write("a.mp3", content=b"1234567")
        self.assertEqual(library.scan([self.root])[0].size, 7)

    def test_a_user_path_is_expanded(self):
        self.assertEqual(library.scan(["~/definitely-not-a-real-music-dir"]), [])


class OrderingTests(unittest.TestCase):
    def tracks(self, count=8):
        return [library.track_from_path("/m/%02d - t.mp3" % i) for i in range(count)]

    def test_a_shuffle_is_reproducible_from_its_seed(self):
        source = self.tracks()
        self.assertEqual(library.shuffled(source, 7), library.shuffled(source, 7))

    def test_different_seeds_deal_differently(self):
        source = self.tracks(24)
        self.assertNotEqual(library.shuffled(source, 1), library.shuffled(source, 2))

    def test_a_shuffle_keeps_every_track(self):
        source = self.tracks()
        self.assertEqual(sorted(library.shuffled(source, 3)), sorted(source))

    def test_sorting_is_stable_and_natural(self):
        source = [library.track_from_path(p) for p in ("/m/b10.mp3", "/m/b2.mp3")]
        self.assertEqual([t.path for t in library.sort_tracks(source)],
                         ["/m/b2.mp3", "/m/b10.mp3"])


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "playlist.m3u")

    def test_the_playlist_declares_itself_extended(self):
        self.assertEqual(library.m3u_lines([])[0], "#EXTM3U")

    def test_each_track_gets_a_label_and_a_path(self):
        track = library.track_from_path("/m/Trio - Da Da Da.mp3")
        self.assertEqual(library.m3u_lines([track])[1:],
                         ["#EXTINF:-1,Trio — Da Da Da", "/m/Trio - Da Da Da.mp3"])

    def test_newlines_in_a_label_cannot_break_the_format(self):
        track = library.Track("/m/x.mp3", "A\nB", "C\rD", ".mp3", 0)
        lines = library.m3u_lines([track])
        self.assertEqual(len(lines), 3)

    def test_paths_survive_a_write_and_read(self):
        tracks = [library.track_from_path(p)
                  for p in ("/m/a b.mp3", "/m/Trio - Da Da Da.mp3", "/m/东京.mp3")]
        library.write_m3u(self.path, tracks)
        self.assertEqual(library.read_m3u(self.path), [t.path for t in tracks])

    def test_writing_leaves_no_partial_file_behind(self):
        library.write_m3u(self.path, [])
        self.assertEqual(os.listdir(self.tmp.name), ["playlist.m3u"])

    def test_writing_creates_the_directory(self):
        nested = os.path.join(self.tmp.name, "a", "b", "playlist.m3u")
        library.write_m3u(nested, [])
        self.assertTrue(os.path.isfile(nested))

    def test_reading_a_missing_playlist_gives_nothing(self):
        self.assertEqual(library.read_m3u(os.path.join(self.tmp.name, "nope.m3u")), [])

    def test_an_empty_playlist_round_trips(self):
        library.write_m3u(self.path, [])
        self.assertEqual(library.read_m3u(self.path), [])


if __name__ == "__main__":
    unittest.main()
