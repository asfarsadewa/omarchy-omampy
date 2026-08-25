"""Turning astats readings into bar heights."""

import unittest

from omampy import meter


def metadata(*levels, start=1):
    return {"lavfi.astats.%d.RMS_level" % (start + i): "%f" % value
            for i, value in enumerate(levels)}


class ToDbTests(unittest.TestCase):
    def test_numbers_and_numeric_strings_agree(self):
        self.assertEqual(meter.to_db("-31.5"), -31.5)
        self.assertEqual(meter.to_db(-31.5), -31.5)

    def test_every_spelling_of_silence_reads_as_silence(self):
        for value in ("-inf", "-INF", "-Infinity", float("-inf"), "nan", "", "n/a"):
            self.assertEqual(meter.to_db(value), meter.SILENT)


class ParseTests(unittest.TestCase):
    def test_rms_readings_are_collected_by_channel(self):
        self.assertEqual(meter.parse_channels(metadata(-10.0, -20.0)),
                         {1: -10.0, 2: -20.0})

    def test_other_astats_measurements_are_ignored(self):
        payload = metadata(-10.0)
        payload["lavfi.astats.1.Peak_level"] = "-3.0"
        payload["lavfi.astats.Overall.Bit_depth4"] = "16"
        self.assertEqual(meter.parse_channels(payload), {1: -10.0})

    def test_a_missing_or_malformed_payload_is_empty(self):
        for payload in (None, {}, "", [], 7):
            self.assertEqual(meter.parse_channels(payload), {})


class SplitLevelTests(unittest.TestCase):
    def test_mono_keeps_one_channel_for_the_signal(self):
        signal, bands = meter.split_levels(metadata(-10.0, -20.0, -30.0), 2, 1)
        self.assertEqual(signal, -10.0)
        self.assertEqual(bands, [-20.0, -30.0])

    def test_stereo_keeps_two_and_reports_the_louder(self):
        signal, bands = meter.split_levels(metadata(-18.0, -12.0, -30.0), 1, 2)
        self.assertEqual(signal, -12.0)
        self.assertEqual(bands, [-30.0])

    def test_missing_channels_read_as_silence(self):
        signal, bands = meter.split_levels(metadata(-10.0), 3, 1)
        self.assertEqual(signal, -10.0)
        self.assertEqual(bands, [meter.SILENT] * 3)

    def test_an_empty_payload_is_all_silence(self):
        signal, bands = meter.split_levels({}, 2, 1)
        self.assertEqual(signal, meter.SILENT)
        self.assertEqual(bands, [meter.SILENT, meter.SILENT])

    def test_band_count_is_always_honoured(self):
        for count in (1, 5, 14, 32):
            _, bands = meter.split_levels(metadata(*([-20.0] * 40)), count, 1)
            self.assertEqual(len(bands), count)

    def test_bad_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            meter.split_levels({}, 0, 1)
        with self.assertRaises(ValueError):
            meter.split_levels({}, 4, 0)


class TiltTests(unittest.TestCase):
    def test_the_ramp_runs_from_nothing_to_the_full_amount(self):
        gains = meter.tilt_gains(5, 12.0)
        self.assertEqual(gains[0], 0.0)
        self.assertEqual(gains[-1], 12.0)

    def test_the_ramp_is_monotonic(self):
        gains = meter.tilt_gains(8)
        self.assertEqual(gains, sorted(gains))

    def test_a_single_band_gets_no_tilt(self):
        self.assertEqual(meter.tilt_gains(1), [0.0])

    def test_zero_bands_is_an_error(self):
        with self.assertRaises(ValueError):
            meter.tilt_gains(0)


class DbToUnitTests(unittest.TestCase):
    def test_the_ends_of_the_window_map_to_the_ends_of_the_range(self):
        self.assertEqual(meter.db_to_unit(meter.DB_FLOOR), 0.0)
        self.assertEqual(meter.db_to_unit(meter.DB_CEIL), 1.0)

    def test_the_middle_maps_to_the_middle(self):
        middle = (meter.DB_FLOOR + meter.DB_CEIL) / 2
        self.assertAlmostEqual(meter.db_to_unit(middle), 0.5)

    def test_values_beyond_the_window_are_clamped(self):
        self.assertEqual(meter.db_to_unit(-200.0), 0.0)
        self.assertEqual(meter.db_to_unit(20.0), 1.0)

    def test_silence_is_zero(self):
        self.assertEqual(meter.db_to_unit(meter.SILENT), 0.0)

    def test_an_inverted_window_is_rejected(self):
        with self.assertRaises(ValueError):
            meter.db_to_unit(-30.0, floor=-10.0, ceil=-60.0)


class NormalizeTests(unittest.TestCase):
    def test_output_length_matches_input_length(self):
        self.assertEqual(len(meter.normalize([-30.0] * 7)), 7)

    def test_every_value_lands_inside_the_range(self):
        for value in meter.normalize([-100.0, -40.0, -20.0, 0.0]):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_the_tilt_lifts_higher_bands(self):
        flat = meter.normalize([-40.0] * 4)
        self.assertLess(flat[0], flat[-1])

    def test_no_tilt_leaves_a_flat_reading_flat(self):
        flat = meter.normalize([-40.0] * 4, tilt_db=0.0)
        self.assertEqual(len(set(flat)), 1)

    def test_an_empty_frame_produces_nothing(self):
        self.assertEqual(meter.normalize([]), [])


class SmootherTests(unittest.TestCase):
    def test_it_starts_silent(self):
        self.assertEqual(meter.Smoother(4).values, [0.0] * 4)

    def test_it_rises_toward_the_target_without_overshooting(self):
        smoother = meter.Smoother(1, attack=0.5, decay=0.1)
        self.assertAlmostEqual(smoother.update([1.0])[0], 0.5)
        self.assertAlmostEqual(smoother.update([1.0])[0], 0.75)

    def test_it_rises_faster_than_it_falls(self):
        rising = meter.Smoother(1)
        falling = meter.Smoother(1)
        falling.values = [1.0]
        self.assertGreater(rising.update([1.0])[0], 1.0 - falling.update([0.0])[0])

    def test_it_settles_to_exactly_zero(self):
        smoother = meter.Smoother(2)
        smoother.values = [1.0, 1.0]
        for _ in range(400):
            smoother.silence()
        self.assertEqual(smoother.values, [0.0, 0.0])

    def test_peaks_hold_above_the_bars_and_then_fall(self):
        smoother = meter.Smoother(1, attack=1.0, decay=1.0, peak_decay=0.1)
        smoother.update([1.0])
        self.assertEqual(smoother.peaks, [1.0])
        smoother.update([0.0])
        self.assertAlmostEqual(smoother.peaks[0], 0.9)

    def test_a_peak_never_falls_below_its_bar(self):
        smoother = meter.Smoother(1, attack=1.0, decay=1.0, peak_decay=1.0)
        smoother.update([0.5])
        smoother.update([0.5])
        self.assertGreaterEqual(smoother.peaks[0], smoother.values[0])

    def test_targets_outside_the_range_are_clamped(self):
        smoother = meter.Smoother(1, attack=1.0, decay=1.0)
        self.assertEqual(smoother.update([5.0]), [1.0])
        self.assertEqual(smoother.update([-5.0]), [0.0])

    def test_a_short_frame_is_padded_with_silence(self):
        smoother = meter.Smoother(3, attack=1.0)
        self.assertEqual(smoother.update([1.0]), [1.0, 0.0, 0.0])

    def test_bad_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            meter.Smoother(0)
        with self.assertRaises(ValueError):
            meter.Smoother(4, attack=2.0)
        with self.assertRaises(ValueError):
            meter.Smoother(4, decay=-1.0)


if __name__ == "__main__":
    unittest.main()
