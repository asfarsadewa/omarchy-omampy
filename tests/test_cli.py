"""The command surface, run against an isolated environment and no mpv."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from omampy import cli, config, library


@contextlib.contextmanager
def captured():
    """Run with stdout and stderr collected."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


class CliTestCase(unittest.TestCase):
    """Points every XDG directory at a throwaway tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.music = os.path.join(self.root, "music")
        os.makedirs(self.music)
        self.env = {
            "XDG_CONFIG_HOME": os.path.join(self.root, "config"),
            "XDG_CACHE_HOME": os.path.join(self.root, "cache"),
            "XDG_STATE_HOME": os.path.join(self.root, "state"),
            "XDG_RUNTIME_DIR": os.path.join(self.root, "run"),
            "HOME": self.root,
        }
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_config({"library": [self.music]})

    def write_config(self, settings):
        paths = config.paths_from_env(self.env)
        os.makedirs(paths.config_dir, exist_ok=True)
        with open(paths.config_file, "w", encoding="utf-8") as handle:
            json.dump(settings, handle)

    def add_track(self, name):
        path = os.path.join(self.music, name)
        with open(path, "wb") as handle:
            handle.write(b"\0" * 16)
        return path

    def run_cli(self, *argv):
        with captured() as (out, err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = cli.build_parser()

    def parse(self, *argv):
        return self.parser.parse_args(list(argv))

    def test_every_command_has_a_handler(self):
        for command in ("start", "stop", "scan", "toggle", "pause", "resume", "next",
                        "prev", "play", "seek", "volume", "band", "intensity",
                        "repeat", "shuffle", "status", "watch", "chain", "bed", "doctor"):
            args = self.parse(command) if command != "seek" else self.parse(command, "5")
            self.assertTrue(callable(args.handler), command)

    def test_a_command_is_required(self):
        with self.assertRaises(SystemExit):
            with captured():
                self.parse()

    def test_an_unknown_command_is_rejected(self):
        with self.assertRaises(SystemExit):
            with captured():
                self.parse("explode")

    def test_transport_commands_carry_a_null_index(self):
        self.assertIsNone(self.parse("toggle").index)

    def test_play_takes_an_optional_index(self):
        self.assertIsNone(self.parse("play").index)
        self.assertEqual(self.parse("play", "4").index, 4)

    def test_seek_defaults_to_relative(self):
        self.assertFalse(self.parse("seek", "-10").absolute)
        self.assertTrue(self.parse("seek", "10", "--absolute").absolute)

    def test_volume_and_intensity_take_signed_text(self):
        self.assertEqual(self.parse("volume", "+5").value, "+5")
        self.assertEqual(self.parse("intensity", "-0.1").value, "-0.1")

    def test_repeat_only_accepts_known_modes(self):
        self.assertEqual(self.parse("repeat", "one").mode, "one")
        with self.assertRaises(SystemExit):
            with captured():
                self.parse("repeat", "sometimes")

    def test_watch_has_sensible_defaults(self):
        args = self.parse("watch")
        self.assertGreater(args.hz, 0)
        self.assertGreater(args.width, 0)
        self.assertEqual(args.duration, 0.0)


class SessionTests(CliTestCase):
    def test_settings_come_from_the_config_file(self):
        self.write_config({"library": [self.music], "band": "sw", "volume": 33})
        session = cli.Session()
        self.assertEqual(session.settings["band"], "sw")
        self.assertEqual(session.settings["volume"], 33)

    def test_saved_state_wins_over_the_config_file(self):
        self.write_config({"library": [self.music], "band": "sw"})
        cli.Session().persist(band="lw")
        self.assertEqual(cli.Session().settings["band"], "lw")

    def test_persisting_one_setting_leaves_the_others_alone(self):
        self.write_config({"library": [self.music], "band": "sw", "intensity": 0.9})
        cli.Session().persist(band="lw")
        reopened = cli.Session()
        self.assertEqual(reopened.settings["band"], "lw")
        self.assertEqual(reopened.settings["intensity"], 0.9)

    def test_only_touched_keys_are_written_to_state(self):
        cli.Session().persist(band="lw")
        with open(cli.Session().paths.state_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"band": "lw"})

    def test_persisted_values_are_validated(self):
        cli.Session().persist(intensity=99)
        self.assertEqual(cli.Session().settings["intensity"], 1.0)

    def test_a_broken_config_file_is_survivable(self):
        paths = config.paths_from_env(self.env)
        with open(paths.config_file, "w", encoding="utf-8") as handle:
            handle.write("{oh no")
        session = cli.Session()
        self.assertEqual(session.settings["band"], config.DEFAULTS["band"])
        self.assertTrue(session.warnings)

    def test_reload_picks_up_a_change_made_by_another_process(self):
        session = cli.Session()
        self.assertEqual(session.settings["band"], config.DEFAULTS["band"])
        cli.Session().persist(band="lw")
        self.assertEqual(session.reload()["band"], "lw")

    def test_stamps_change_when_a_settings_file_is_written(self):
        session = cli.Session()
        before = session.stamps()
        session.persist(band="lw")
        self.assertNotEqual(session.stamps(), before)

    def test_stamps_are_steady_when_nothing_is_written(self):
        session = cli.Session()
        self.assertEqual(session.stamps(), session.stamps())

    def test_stamps_cope_with_files_that_do_not_exist_yet(self):
        self.assertEqual(len(cli.Session().stamps()), 2)

    def test_tracks_come_back_from_the_written_playlist(self):
        self.add_track("Trio - Da Da Da.mp3")
        self.run_cli("scan")
        self.assertEqual([t.title for t in cli.Session().tracks()], ["Da Da Da"])


class ScanCommandTests(CliTestCase):
    def test_scanning_reports_what_it_found(self):
        self.add_track("a.mp3")
        self.add_track("b.mp3")
        code, out, _ = self.run_cli("scan")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("2 tracks", out)

    def test_scanning_writes_a_playlist_mpv_can_load(self):
        path = self.add_track("a.mp3")
        self.run_cli("scan")
        self.assertEqual(library.read_m3u(cli.Session().paths.playlist_file), [path])

    def test_an_empty_library_says_so_without_failing(self):
        code, out, _ = self.run_cli("scan")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("nothing to play", out)

    def test_json_output_is_machine_readable(self):
        self.add_track("Trio - Da Da Da.mp3")
        _, out, _ = self.run_cli("scan", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tracks"][0]["display"], "Trio — Da Da Da")

    def test_directories_can_be_given_on_the_command_line(self):
        other = os.path.join(self.root, "other")
        os.makedirs(other)
        with open(os.path.join(other, "z.mp3"), "wb") as handle:
            handle.write(b"\0")
        _, out, _ = self.run_cli("scan", other)
        self.assertIn("1 track", out)

    def test_shuffle_reorders_a_long_library_reproducibly(self):
        for i in range(30):
            self.add_track("t%02d.mp3" % i)
        self.run_cli("scan")
        ordered = library.read_m3u(cli.Session().paths.playlist_file)
        self.run_cli("shuffle", "on")
        shuffled = library.read_m3u(cli.Session().paths.playlist_file)
        self.assertNotEqual(ordered, shuffled)
        self.assertEqual(sorted(ordered), sorted(shuffled))


class ChainCommandTests(CliTestCase):
    def test_it_prints_a_connected_graph(self):
        code, out, _ = self.run_cli("chain", "--band", "sw")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(out.strip().startswith("[in]"))
        self.assertTrue(out.strip().endswith("[out]"))

    def test_the_af_flag_wraps_it_for_mpv(self):
        _, out, _ = self.run_cli("chain", "--af", "--no-bed")
        self.assertTrue(out.strip().startswith("@omampy:lavfi=["))

    def test_the_probe_can_be_left_out(self):
        _, out, _ = self.run_cli("chain", "--no-meter", "--no-bed")
        self.assertNotIn("astats", out)

    def test_the_bed_can_be_left_out(self):
        _, out, _ = self.run_cli("chain", "--no-bed")
        self.assertNotIn("amovie", out)

    def test_an_unknown_band_is_a_usage_error(self):
        code, _, err = self.run_cli("chain", "--band", "vhf")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("vhf", err)

    def test_the_band_defaults_to_the_current_setting(self):
        self.write_config({"library": [self.music], "band": "lw"})
        _, out, _ = self.run_cli("chain", "--no-bed", "--no-meter")
        self.assertIn("highpass=f=150", out)


class BedCommandTests(CliTestCase):
    def test_it_generates_a_bed_and_prints_where_it_went(self):
        code, out, _ = self.run_cli("bed", "--band", "sw", "--intensity", "0.5")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(os.path.isfile(out.strip()))

    def test_a_clean_band_has_no_bed_to_make(self):
        code, out, _ = self.run_cli("bed", "--band", "fm")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no static", out)


class OfflineCommandTests(CliTestCase):
    """Everything that has to behave when the receiver is not running."""

    def test_status_says_the_receiver_is_down(self):
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("off air", out)

    def test_status_json_is_still_well_formed(self):
        _, out, _ = self.run_cli("status", "--json")
        payload = json.loads(out)
        self.assertFalse(payload["running"])
        self.assertEqual(payload["state"], "stopped")

    def test_status_can_still_draw_the_console(self):
        _, out, _ = self.run_cli("status", "--ascii", "--width", "40")
        lines = out.strip("\n").split("\n")
        self.assertTrue(lines[0].startswith("┌"))
        self.assertTrue(lines[-1].startswith("└"))

    def test_stopping_a_stopped_receiver_is_not_an_error(self):
        code, out, _ = self.run_cli("stop")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("already off air", out)

    def test_transport_commands_report_that_nothing_is_listening(self):
        for command in ("toggle", "pause", "resume", "next", "prev", "play"):
            code, _, err = self.run_cli(command)
            self.assertEqual(code, cli.EXIT_UNAVAILABLE, command)
            self.assertIn("not running", err, command)

    def test_seeking_reports_that_nothing_is_listening(self):
        code, _, _ = self.run_cli("seek", "10")
        self.assertEqual(code, cli.EXIT_UNAVAILABLE)

    def test_the_band_can_still_be_changed_for_next_time(self):
        code, out, _ = self.run_cli("band", "lw")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Long wave", out)
        self.assertEqual(cli.Session().settings["band"], "lw")

    def test_the_band_switch_can_be_stepped(self):
        self.write_config({"library": [self.music], "band": "mw"})
        self.run_cli("band", "--next")
        self.assertEqual(cli.Session().settings["band"], "sw")
        self.run_cli("band", "--prev")
        self.assertEqual(cli.Session().settings["band"], "mw")

    def test_the_band_with_no_argument_reports_the_current_one(self):
        self.write_config({"library": [self.music], "band": "sw"})
        _, out, _ = self.run_cli("band")
        self.assertEqual(out.strip(), "sw")

    def test_an_unknown_band_is_a_usage_error(self):
        code, _, err = self.run_cli("band", "vhf")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("vhf", err)

    def test_intensity_is_remembered_and_clamped(self):
        self.run_cli("intensity", "0.42")
        self.assertAlmostEqual(cli.Session().settings["intensity"], 0.42)
        self.run_cli("intensity", "9")
        self.assertEqual(cli.Session().settings["intensity"], 1.0)

    def test_intensity_accepts_a_relative_step(self):
        self.run_cli("intensity", "0.5")
        self.run_cli("intensity", "+0.2")
        self.assertAlmostEqual(cli.Session().settings["intensity"], 0.7)

    def test_a_non_numeric_intensity_is_a_usage_error(self):
        code, _, err = self.run_cli("intensity", "loud")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("0..1", err)

    def test_an_absolute_volume_is_remembered_for_next_time(self):
        code, _, _ = self.run_cli("volume", "55")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(cli.Session().settings["volume"], 55)

    def test_a_non_numeric_volume_is_a_usage_error(self):
        code, _, err = self.run_cli("volume", "loud")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("number", err)

    def test_repeat_can_be_read_set_and_cycled(self):
        _, out, _ = self.run_cli("repeat")
        self.assertEqual(out.strip(), config.DEFAULTS["repeat"])
        self.run_cli("repeat", "one")
        self.assertEqual(cli.Session().settings["repeat"], "one")
        self.run_cli("repeat", "--cycle")
        self.assertNotEqual(cli.Session().settings["repeat"], "one")

    def test_shuffle_toggles_when_given_no_argument(self):
        before = cli.Session().settings["shuffle"]
        self.run_cli("shuffle")
        self.assertNotEqual(cli.Session().settings["shuffle"], before)

    def test_watch_still_streams_frames_with_nothing_to_play(self):
        code, out, _ = self.run_cli("watch", "--hz", "30", "--duration", "0.12")
        self.assertEqual(code, cli.EXIT_OK)
        lines = [line for line in out.strip().split("\n") if line]
        self.assertTrue(lines)
        frame = json.loads(lines[0])
        self.assertEqual(frame["status"]["state"], "stopped")
        self.assertIn("lines", frame)
        self.assertIn("levels", frame)

    def test_watch_notices_a_band_change_made_while_it_is_streaming(self):
        """The console is drawn by a stream that outlives every command.

        A band change is written by a separate one-shot process, so a stream
        that read its settings once would keep drawing the old band while the
        audio played the new one.
        """
        import subprocess
        import sys as _sys

        self.write_config({"library": [self.music], "band": "mw"})
        proc = subprocess.Popen(
            [_sys.executable, "-m", "omampy", "watch", "--hz", "30", "--duration", "1.2"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ), text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__))))
        time.sleep(0.4)
        cli.Session().persist(band="lw")
        out, err = proc.communicate(timeout=20)

        frames = [json.loads(line) for line in out.splitlines() if line.strip()]
        self.assertTrue(frames, "watch produced no frames: %s" % err)
        bands = [f["status"]["band"] for f in frames]
        self.assertEqual(bands[0], "mw", "should start on the configured band")
        self.assertEqual(bands[-1], "lw", "should follow the change: %s" % bands)
        self.assertIn("▐LW▌", frames[-1]["bandSwitch"])

    def test_doctor_reports_a_missing_mpv_as_a_failure(self):
        with mock.patch("shutil.which", return_value=None):
            code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, cli.EXIT_UNAVAILABLE)
        self.assertIn("MISSING", out)

    def test_doctor_passes_when_everything_is_in_place(self):
        with mock.patch("shutil.which", return_value="/usr/bin/mpv"):
            code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("playlist", out)

    def test_starting_without_mpv_installed_explains_itself(self):
        with mock.patch("shutil.which", return_value=None):
            code, _, err = self.run_cli("start")
        self.assertEqual(code, cli.EXIT_UNAVAILABLE)
        self.assertIn("mpv", err)


if __name__ == "__main__":
    unittest.main()
