"""The libavfilter graph builder."""

import unittest

from omampy import chain, modes


class EscapeTests(unittest.TestCase):
    def test_plain_text_is_untouched(self):
        self.assertEqual(chain.escape_value("/home/me/.cache/omampy/bed.wav"),
                         "/home/me/.cache/omampy/bed.wav")

    def test_spaces_survive_unescaped(self):
        self.assertEqual(chain.escape_value("/my music/bed.wav"), "/my music/bed.wav")

    def test_graph_separators_are_escaped(self):
        # A colon is special to both parsers, so it needs two backslashes;
        # the rest are special to the graph parser alone and need one.
        self.assertEqual(chain.escape_value("a:b"), "a\\\\:b")
        self.assertEqual(chain.escape_value("a,b"), "a\\,b")
        self.assertEqual(chain.escape_value("a;b"), "a\\;b")
        self.assertEqual(chain.escape_value("a[b]c"), "a\\[b\\]c")

    def test_escaping_is_applied_innermost_first(self):
        self.assertEqual(chain.escape_value("it's"), "it\\\\'s")
        self.assertEqual(chain.escape_value("a\\b"), "a\\\\\\\\b")


class BandEdgeTests(unittest.TestCase):
    def test_count_is_respected(self):
        for count in (1, 4, 14, 32):
            self.assertEqual(len(chain.band_edges(60, 8000, count)), count)

    def test_lowest_band_opens_down_to_dc(self):
        self.assertEqual(chain.band_edges(100, 4000, 5)[0][0], 0.0)

    def test_bands_are_contiguous(self):
        bands = chain.band_edges(100, 4000, 6)
        for lower, upper in zip(bands, bands[1:]):
            self.assertAlmostEqual(lower[1], upper[0])

    def test_top_edge_is_the_requested_high(self):
        self.assertAlmostEqual(chain.band_edges(100, 4000, 7)[-1][1], 4000)

    def test_spacing_is_logarithmic(self):
        bands = chain.band_edges(100, 3200, 5)
        ratios = [high / low for low, high in bands[1:]]
        for ratio in ratios:
            self.assertAlmostEqual(ratio, ratios[0], places=6)

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            chain.band_edges(100, 4000, 0)
        with self.assertRaises(ValueError):
            chain.band_edges(4000, 100, 4)
        with self.assertRaises(ValueError):
            chain.band_edges(0, 4000, 4)


class RangeAndChannelTests(unittest.TestCase):
    def test_analysis_range_tracks_the_passband(self):
        low, high = chain.analysis_range("sw")
        self.assertEqual(high, modes.MODES["sw"]["band"][1])
        self.assertLess(low, modes.MODES["sw"]["band"][0])

    def test_clean_band_uses_the_full_musical_range(self):
        self.assertEqual(chain.analysis_range("fm"), chain.CLEAN_ANALYSIS_RANGE)

    def test_keep_channels_matches_the_bands_layout(self):
        self.assertEqual(chain.keep_channels("mw"), 1)
        self.assertEqual(chain.keep_channels("fm"), 2)


class IntensityTests(unittest.TestCase):
    def test_values_inside_the_range_pass_through(self):
        self.assertEqual(chain.clamp_intensity(0.42), 0.42)

    def test_values_outside_the_range_are_clamped(self):
        self.assertEqual(chain.clamp_intensity(-3), 0.0)
        self.assertEqual(chain.clamp_intensity(9), 1.0)

    def test_numeric_strings_are_accepted(self):
        self.assertEqual(chain.clamp_intensity("0.5"), 0.5)

    def test_nonsense_is_rejected(self):
        for value in ("loud", None, float("nan")):
            with self.assertRaises(ValueError):
                chain.clamp_intensity(value)


class SignalFilterTests(unittest.TestCase):
    def test_clean_band_adds_nothing(self):
        self.assertEqual(chain.signal_filters("fm", 1.0), [])

    def test_radio_bands_downmix_and_resample(self):
        filters = chain.signal_filters("mw", 0.5)
        self.assertTrue(filters[0].startswith("aresample=22050"))
        self.assertIn("channel_layouts=mono", filters[1])

    def test_the_passband_uses_the_full_stage_count(self):
        filters = chain.signal_filters("sw", 0.5)
        low, high = modes.MODES["sw"]["band"]
        self.assertEqual(filters.count("highpass=f=%g:p=2" % low), chain.BAND_STAGES)
        self.assertEqual(filters.count("lowpass=f=%g:p=2" % high), chain.BAND_STAGES)

    def test_fade_scales_with_intensity(self):
        def depth(intensity):
            for item in chain.signal_filters("sw", intensity):
                if item.startswith("tremolo"):
                    return float(item.split("d=")[1])
            return 0.0
        self.assertGreater(depth(1.0), depth(0.5))
        self.assertGreater(depth(0.5), 0.0)

    def test_zero_intensity_removes_the_fade_but_keeps_the_passband(self):
        filters = chain.signal_filters("sw", 0.0)
        self.assertFalse(any(f.startswith("tremolo") for f in filters))
        self.assertTrue(any(f.startswith("highpass") for f in filters))

    def test_saturation_is_present_only_where_the_band_drives(self):
        self.assertTrue(any(f.startswith("asoftclip") for f in chain.signal_filters("sw", 0.5)))
        self.assertFalse(any(f.startswith("asoftclip") for f in chain.signal_filters("fm", 0.5)))


class BedWeightTests(unittest.TestCase):
    def test_weight_rises_with_intensity(self):
        self.assertGreater(chain.bed_weight("sw", 1.0), chain.bed_weight("sw", 0.4))

    def test_zero_intensity_silences_the_bed(self):
        self.assertEqual(chain.bed_weight("sw", 0.0), 0.0)

    def test_clean_band_never_gets_a_bed(self):
        self.assertEqual(chain.bed_weight("fm", 1.0), 0.0)

    def test_weight_never_exceeds_the_signal(self):
        self.assertLess(chain.bed_weight("sw", 1.0), 1.0)


class ProbeTests(unittest.TestCase):
    def test_probe_measures_signal_and_every_band(self):
        bands = chain.band_edges(60, 8000, 6)
        graph = chain.probe_graph("body", "out", bands, 1)
        self.assertIn("amerge=inputs=7", graph)
        self.assertIn("pan=mono|c0=c0", graph)
        self.assertIn("measure_perchannel=RMS_level", graph)

    def test_stereo_probe_keeps_both_channels(self):
        graph = chain.probe_graph("body", "out", chain.band_edges(60, 8000, 3), 2)
        self.assertIn("amerge=inputs=4", graph)
        self.assertIn("pan=stereo|c0=c0|c1=c1", graph)

    def test_lowest_branch_has_no_highpass(self):
        graph = chain.probe_graph("body", "out", chain.band_edges(60, 8000, 3), 1)
        first = [part for part in graph.split(";") if part.startswith("[pb0]")][0]
        self.assertNotIn("highpass", first)

    def test_every_branch_is_format_pinned_before_the_merge(self):
        bands = chain.band_edges(60, 8000, 5)
        graph = chain.probe_graph("body", "out", bands, 1)
        self.assertEqual(graph.count("aformat=" + chain.PROBE_FORMAT), len(bands))

    def test_bad_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            chain.probe_graph("body", "out", [], 1)
        with self.assertRaises(ValueError):
            chain.probe_graph("body", "out", chain.band_edges(60, 8000, 2), 3)


class BuildGraphTests(unittest.TestCase):
    def test_every_band_produces_a_connected_graph(self):
        for band in modes.ORDER:
            graph = chain.build_graph(band, 0.7, bed_path="/tmp/bed.wav", meter_bands=8)
            self.assertTrue(graph.startswith("[in]"), band)
            self.assertTrue(graph.endswith("[out]"), band)
            self.assertNotIn(";;", graph, band)

    def test_pad_labels_are_produced_before_they_are_consumed(self):
        graph = chain.build_graph("mw", 0.7, bed_path="/tmp/bed.wav", meter_bands=4)
        produced = set()
        for section in graph.split(";"):
            head = section[: section.index("]") + 1] if section.startswith("[") else ""
            for label in _labels(head):
                if label != "in":
                    self.assertIn(label, produced, "%s used before it is produced" % label)
            for label in _labels(section[len(head):]):
                produced.add(label)

    def test_bed_is_included_only_when_it_can_be_heard(self):
        with_bed = chain.build_graph("mw", 0.8, bed_path="/tmp/bed.wav", meter_bands=0)
        self.assertIn("amovie=/tmp/bed.wav", with_bed)
        self.assertIn("amix=inputs=2", with_bed)
        self.assertNotIn("amovie", chain.build_graph("mw", 0.0, bed_path="/tmp/bed.wav",
                                                     meter_bands=0))
        self.assertNotIn("amovie", chain.build_graph("mw", 0.8, bed_path=None, meter_bands=0))
        self.assertNotIn("amovie", chain.build_graph("fm", 1.0, bed_path="/tmp/bed.wav",
                                                     meter_bands=0))

    def test_every_radio_band_rides_gain_whatever_the_intensity(self):
        # A receiver has AGC whether or not there is static on the band, and
        # a consistent level is what makes the metering window calibratable.
        for intensity in (0.0, 0.5, 1.0):
            for bed in ("/tmp/b.wav", None):
                graph = chain.build_graph("mw", intensity, bed_path=bed, meter_bands=0)
                self.assertIn("acompressor", graph)
                self.assertIn("alimiter", graph)

    def test_the_clean_band_never_rides_gain(self):
        self.assertNotIn("alimiter", chain.build_graph("fm", 1.0, meter_bands=0))
        self.assertEqual(chain.levelling_filters("fm"), [])

    def test_levelling_comes_after_the_static_is_mixed_in(self):
        graph = chain.build_graph("sw", 0.8, bed_path="/tmp/b.wav", meter_bands=0)
        self.assertLess(graph.index("amix"), graph.index("acompressor"))
        self.assertLess(graph.index("acompressor"), graph.index("alimiter"))

    def test_meter_bands_control_the_probe_width(self):
        graph = chain.build_graph("sw", 0.5, meter_bands=11)
        self.assertIn("asplit=11", graph)
        self.assertIn("amerge=inputs=12", graph)

    def test_zero_meter_bands_removes_the_probe(self):
        graph = chain.build_graph("sw", 0.5, meter_bands=0)
        for marker in ("astats", "amerge", "asplit=2[keep]"):
            self.assertNotIn(marker, graph)

    def test_clean_band_with_no_probe_is_a_pass_through(self):
        self.assertEqual(chain.build_graph("fm", 1.0, meter_bands=0), "[in]anull[out]")

    def test_clean_band_can_still_be_metered(self):
        graph = chain.build_graph("fm", 1.0, meter_bands=5)
        self.assertIn("amerge=inputs=6", graph)
        self.assertIn("pan=stereo", graph)

    def test_paths_with_separators_are_escaped_into_the_graph(self):
        graph = chain.build_graph("mw", 1.0, bed_path="/tmp/a:b/bed,1.wav", meter_bands=0)
        self.assertIn("amovie=/tmp/a\\\\:b/bed\\,1.wav", graph)

    def test_intensity_is_clamped_rather_than_rejected(self):
        self.assertEqual(chain.build_graph("sw", 5.0, meter_bands=0),
                         chain.build_graph("sw", 1.0, meter_bands=0))

    def test_af_argument_carries_the_stable_label(self):
        self.assertEqual(chain.af_argument("[in]anull[out]"),
                         "@omampy:lavfi=[[in]anull[out]]")


def _labels(text: str) -> list[str]:
    """Every `[pad]` name in a fragment of graph text."""
    out = []
    depth = 0
    current = ""
    for ch in text:
        if ch == "[":
            depth = 1
            current = ""
        elif ch == "]" and depth:
            depth = 0
            out.append(current)
        elif depth:
            current += ch
    return out


if __name__ == "__main__":
    unittest.main()
