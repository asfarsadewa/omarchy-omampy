"""Paths and settings validation."""

import json
import os
import tempfile
import unittest

from omampy import config


class PathTests(unittest.TestCase):
    ENV = {"XDG_CONFIG_HOME": "/x/config", "XDG_CACHE_HOME": "/x/cache",
           "XDG_STATE_HOME": "/x/state", "XDG_RUNTIME_DIR": "/run/user/1000"}

    def test_xdg_variables_are_honoured(self):
        paths = config.paths_from_env(self.ENV, uid=1000)
        self.assertEqual(paths.config_dir, "/x/config/omampy")
        self.assertEqual(paths.cache_dir, "/x/cache/omampy")
        self.assertEqual(paths.state_dir, "/x/state/omampy")
        self.assertEqual(paths.runtime_dir, "/run/user/1000/omampy")

    def test_files_live_under_their_directories(self):
        paths = config.paths_from_env(self.ENV, uid=1000)
        self.assertEqual(paths.config_file, "/x/config/omampy/config.json")
        self.assertEqual(paths.state_file, "/x/state/omampy/state.json")
        self.assertEqual(paths.playlist_file, "/x/state/omampy/playlist.m3u")
        self.assertEqual(paths.socket_file, "/run/user/1000/omampy/mpv.sock")

    def test_missing_variables_fall_back_to_the_documented_defaults(self):
        paths = config.paths_from_env({"HOME": "/home/me"}, uid=1000)
        self.assertTrue(paths.config_dir.endswith("/.config/omampy"))
        self.assertTrue(paths.cache_dir.endswith("/.cache/omampy"))

    def test_without_a_runtime_dir_the_socket_joins_the_cache(self):
        paths = config.paths_from_env({"XDG_CACHE_HOME": "/x/cache"}, uid=1000)
        self.assertEqual(paths.runtime_dir, "/x/cache/omampy")

    def test_relative_variables_are_ignored(self):
        paths = config.paths_from_env({"XDG_CONFIG_HOME": "relative/path", "HOME": "/home/me"})
        self.assertTrue(os.path.isabs(paths.config_dir))


class SocketLimitTests(unittest.TestCase):
    def test_a_short_directory_fits(self):
        self.assertTrue(config.socket_path_fits("/run/user/1000/omampy"))

    def test_a_very_deep_directory_does_not(self):
        self.assertFalse(config.socket_path_fits("/" + "d" * 200))

    def test_a_deep_runtime_dir_moves_the_socket_somewhere_short(self):
        deep = "/" + "d" * 200
        paths = config.paths_from_env({"XDG_RUNTIME_DIR": deep}, uid=1000)
        self.assertEqual(paths.runtime_dir, config.short_runtime_dir(1000))
        self.assertTrue(config.socket_path_fits(paths.runtime_dir))

    def test_the_short_directory_is_per_user(self):
        self.assertNotEqual(config.short_runtime_dir(1000), config.short_runtime_dir(1001))


class FilterSafetyTests(unittest.TestCase):
    def test_ordinary_paths_are_safe(self):
        for path in ("/home/me/.cache/omampy", "/home/my music/.cache", "/x:y/z"):
            self.assertTrue(config.filter_safe(path), path)

    def test_quotes_and_backslashes_are_not(self):
        self.assertFalse(config.filter_safe("/home/o'brien/.cache"))
        self.assertFalse(config.filter_safe("/home/a\\b/.cache"))

    def test_beds_normally_live_in_the_cache(self):
        paths = config.paths_from_env({"XDG_CACHE_HOME": "/x/cache",
                                       "XDG_RUNTIME_DIR": "/run/user/1000"}, uid=1000)
        self.assertEqual(paths.bed_dir, "/x/cache/omampy")

    def test_an_unsafe_cache_pushes_beds_to_the_runtime_dir(self):
        paths = config.paths_from_env({"XDG_CACHE_HOME": "/home/o'brien/.cache",
                                       "XDG_RUNTIME_DIR": "/run/user/1000"}, uid=1000)
        self.assertEqual(paths.bed_dir, "/run/user/1000/omampy")
        self.assertTrue(config.filter_safe(paths.bed_dir))

    def test_an_unsafe_runtime_dir_is_replaced(self):
        paths = config.paths_from_env({"XDG_RUNTIME_DIR": "/run/o'brien"}, uid=1000)
        self.assertTrue(config.filter_safe(paths.runtime_dir))


class ValidateTests(unittest.TestCase):
    def test_no_input_gives_the_defaults(self):
        self.assertEqual(config.validate(None), config.validate({}))
        self.assertEqual(config.validate({})["band"], config.DEFAULTS["band"])

    def test_the_defaults_are_not_shared_between_calls(self):
        first = config.validate({})
        first["library"].append("/tmp")
        self.assertNotIn("/tmp", config.validate({})["library"])

    def test_known_values_are_kept(self):
        settings = config.validate({"volume": 42, "shuffle": True, "repeat": "one"})
        self.assertEqual(settings["volume"], 42)
        self.assertTrue(settings["shuffle"])
        self.assertEqual(settings["repeat"], "one")

    def test_unknown_keys_are_dropped_with_a_warning(self):
        warnings = []
        settings = config.validate({"nope": 1}, warnings)
        self.assertNotIn("nope", settings)
        self.assertTrue(any("nope" in w for w in warnings))

    def test_a_band_alias_is_resolved(self):
        self.assertEqual(config.validate({"band": "Shortwave"})["band"], "sw")

    def test_an_unknown_band_falls_back_and_warns(self):
        warnings = []
        settings = config.validate({"band": "vhf"}, warnings)
        self.assertEqual(settings["band"], config.DEFAULTS["band"])
        self.assertTrue(warnings)

    def test_intensity_is_clamped(self):
        self.assertEqual(config.validate({"intensity": 9})["intensity"], 1.0)
        self.assertEqual(config.validate({"intensity": -2})["intensity"], 0.0)

    def test_a_non_numeric_intensity_warns_and_falls_back(self):
        warnings = []
        settings = config.validate({"intensity": "loud"}, warnings)
        self.assertEqual(settings["intensity"], config.DEFAULTS["intensity"])
        self.assertTrue(warnings)

    def test_volume_is_clamped_to_the_allowed_range(self):
        self.assertEqual(config.validate({"volume": 999})["volume"], config.MAX_VOLUME)
        self.assertEqual(config.validate({"volume": -5})["volume"], 0)

    def test_a_single_library_path_is_accepted_as_a_string(self):
        self.assertEqual(config.validate({"library": "~/Tunes"})["library"], ["~/Tunes"])

    def test_an_empty_library_falls_back_to_the_default(self):
        self.assertEqual(config.validate({"library": []})["library"], config.DEFAULTS["library"])

    def test_a_library_that_is_not_a_list_warns(self):
        warnings = []
        config.validate({"library": 7}, warnings)
        self.assertTrue(warnings)

    def test_an_unknown_repeat_mode_warns_and_falls_back(self):
        warnings = []
        self.assertEqual(config.validate({"repeat": "sometimes"}, warnings)["repeat"],
                         config.DEFAULTS["repeat"])
        self.assertTrue(warnings)

    def test_meter_dimensions_are_clamped(self):
        self.assertEqual(config.validate({"meter_bands": 1})["meter_bands"],
                         config.MIN_METER_BANDS)
        self.assertEqual(config.validate({"meter_bands": 999})["meter_bands"],
                         config.MAX_METER_BANDS)
        self.assertEqual(config.validate({"meter_height": 999})["meter_height"],
                         config.MAX_METER_HEIGHT)

    def test_an_empty_mpv_name_falls_back(self):
        self.assertEqual(config.validate({"mpv": "  "})["mpv"], config.DEFAULTS["mpv"])

    def test_a_non_object_warns_and_gives_defaults(self):
        warnings = []
        self.assertEqual(config.validate("nonsense", warnings), config.validate(None))
        self.assertTrue(warnings)

    def test_every_default_survives_validation_unchanged(self):
        self.assertEqual(config.validate(dict(config.DEFAULTS)), config.validate(None))


class LoadSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(config.load(self.path), config.validate(None))

    def test_settings_survive_a_save_and_load(self):
        config.save(self.path, {"band": "sw", "volume": 33})
        loaded = config.load(self.path)
        self.assertEqual(loaded["band"], "sw")
        self.assertEqual(loaded["volume"], 33)

    def test_saving_keeps_only_recognised_keys(self):
        config.save(self.path, {"band": "sw", "secret": 1})
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"band": "sw"})

    def test_saving_creates_the_directory(self):
        nested = os.path.join(self.tmp.name, "a", "b", "config.json")
        config.save(nested, {"volume": 10})
        self.assertTrue(os.path.isfile(nested))

    def test_saving_leaves_no_partial_file_behind(self):
        config.save(self.path, {"volume": 10})
        self.assertEqual(os.listdir(self.tmp.name), ["config.json"])

    def test_broken_json_warns_and_gives_defaults(self):
        self.write("{not json")
        warnings = []
        self.assertEqual(config.load(self.path, warnings), config.validate(None))
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
