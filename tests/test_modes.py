"""Band table and band-switch behaviour."""

import unittest

from omampy import modes


class NormalizeTests(unittest.TestCase):
    def test_canonical_names_pass_through(self):
        for name in modes.ORDER:
            self.assertEqual(modes.normalize(name), name)

    def test_case_and_spacing_are_ignored(self):
        self.assertEqual(modes.normalize("  SW "), "sw")
        self.assertEqual(modes.normalize("Long Wave"), "lw")
        self.assertEqual(modes.normalize("long-wave"), "lw")

    def test_aliases_resolve(self):
        self.assertEqual(modes.normalize("am"), "mw")
        self.assertEqual(modes.normalize("shortwave"), "sw")
        self.assertEqual(modes.normalize("bypass"), "fm")
        self.assertEqual(modes.normalize("clean"), "fm")

    def test_unknown_name_names_the_alternatives(self):
        with self.assertRaises(modes.UnknownMode) as caught:
            modes.normalize("vhf")
        for name in modes.ORDER:
            self.assertIn(name, str(caught.exception))

    def test_empty_and_none_are_rejected(self):
        for value in ("", None, "   "):
            with self.assertRaises(modes.UnknownMode):
                modes.normalize(value)


class TableTests(unittest.TestCase):
    REQUIRED = ("label", "title", "dial_khz", "dial_unit", "band", "mono", "rate",
                "drive", "tilt_db", "tilt_hz", "fade_depth", "fade_rate",
                "hiss", "crackle_rate", "hum_hz", "hum")

    def test_every_band_is_fully_specified(self):
        self.assertEqual(set(modes.MODES), set(modes.ORDER))
        for name, spec in modes.MODES.items():
            for key in self.REQUIRED:
                self.assertIn(key, spec, "%s is missing %s" % (name, key))

    def test_passbands_are_ordered_and_positive(self):
        for name, spec in modes.MODES.items():
            if spec["band"] is None:
                continue
            low, high = spec["band"]
            self.assertGreater(low, 0, name)
            self.assertGreater(high, low, name)

    def test_a_mono_band_declares_a_rate(self):
        for name, spec in modes.MODES.items():
            if spec["mono"]:
                self.assertIsInstance(spec["rate"], int, name)
                self.assertGreater(spec["rate"], 0, name)

    def test_shortwave_is_narrower_and_noisier_than_medium_wave(self):
        mw, sw = modes.MODES["mw"], modes.MODES["sw"]
        self.assertGreater(mw["band"][1] - mw["band"][0], sw["band"][1] - sw["band"][0])
        self.assertGreater(sw["hiss"], mw["hiss"])
        self.assertGreater(sw["crackle_rate"], mw["crackle_rate"])
        self.assertGreater(sw["fade_depth"], mw["fade_depth"])

    def test_only_long_wave_hums(self):
        for name, spec in modes.MODES.items():
            if name == "lw":
                self.assertGreater(spec["hum"], 0)
                self.assertGreater(spec["hum_hz"], 0)
            else:
                self.assertEqual(spec["hum"], 0)

    def test_fm_is_the_only_clean_band(self):
        self.assertTrue(modes.is_clean("fm"))
        for name in modes.ORDER:
            if name != "fm":
                self.assertFalse(modes.is_clean(name), name)

    def test_default_band_is_on_the_switch(self):
        self.assertIn(modes.DEFAULT_MODE, modes.ORDER)


class CycleTests(unittest.TestCase):
    def test_forward_wraps(self):
        self.assertEqual(modes.cycle("mw"), "sw")
        self.assertEqual(modes.cycle(modes.ORDER[-1]), modes.ORDER[0])

    def test_backward_wraps(self):
        self.assertEqual(modes.cycle("mw", -1), modes.ORDER[-1])

    def test_a_full_lap_returns_to_the_start(self):
        name = "sw"
        for _ in range(len(modes.ORDER)):
            name = modes.cycle(name)
        self.assertEqual(name, "sw")

    def test_cycle_accepts_aliases(self):
        self.assertEqual(modes.cycle("AM"), "sw")


class DialLabelTests(unittest.TestCase):
    def test_medium_wave_reads_in_kilohertz(self):
        self.assertEqual(modes.dial_label("mw"), "1080 kHz")

    def test_shortwave_reads_in_megahertz(self):
        self.assertEqual(modes.dial_label("sw"), "9.75 MHz")

    def test_long_wave_reads_in_kilohertz(self):
        self.assertEqual(modes.dial_label("lw"), "198 kHz")

    def test_fm_reads_in_megahertz(self):
        self.assertEqual(modes.dial_label("fm"), "98.5 MHz")


if __name__ == "__main__":
    unittest.main()
