"""The synthesised static: determinism, shape, and file output."""

import math
import os
import struct
import tempfile
import unittest
import wave

from omampy import noisebed


class QuantizeTests(unittest.TestCase):
    def test_values_snap_to_the_cache_grid(self):
        self.assertEqual(noisebed.quantize_intensity(0.64), 0.6)
        self.assertEqual(noisebed.quantize_intensity(0.66), 0.7)
        self.assertEqual(noisebed.quantize_intensity(0.7), 0.7)

    def test_a_value_exactly_between_steps_rounds_up(self):
        self.assertEqual(noisebed.quantize_intensity(0.65), 0.7)
        self.assertEqual(noisebed.quantize_intensity(0.75), 0.8)

    def test_out_of_range_values_are_clamped(self):
        self.assertEqual(noisebed.quantize_intensity(-1), 0.0)
        self.assertEqual(noisebed.quantize_intensity(4), 1.0)

    def test_the_grid_has_the_advertised_number_of_steps(self):
        distinct = {noisebed.quantize_intensity(i / 100.0) for i in range(101)}
        self.assertEqual(len(distinct), noisebed.INTENSITY_STEPS + 1)


class FilterTests(unittest.TestCase):
    def test_lowpass_removes_the_fastest_alternation(self):
        signal = [1.0 if i % 2 == 0 else -1.0 for i in range(2000)]
        noisebed._one_pole_lowpass(signal, 22050, 300.0)
        self.assertLess(max(abs(v) for v in signal[500:]), 0.2)

    def test_highpass_removes_a_constant_offset(self):
        signal = [1.0] * 2000
        noisebed._one_pole_highpass(signal, 22050, 500.0)
        self.assertLess(abs(signal[-1]), 0.05)

    def test_a_cutoff_of_zero_is_a_no_op(self):
        signal = [0.3, -0.7, 0.1]
        noisebed._one_pole_highpass(signal, 22050, 0.0)
        self.assertEqual(signal, [0.3, -0.7, 0.1])

    def test_normalize_scales_the_loudest_sample_to_the_peak(self):
        signal = [0.1, -0.25, 0.05]
        noisebed._normalize(signal, 0.9)
        self.assertAlmostEqual(max(abs(v) for v in signal), 0.9)

    def test_normalize_leaves_silence_alone(self):
        signal = [0.0, 0.0]
        noisebed._normalize(signal, 0.9)
        self.assertEqual(signal, [0.0, 0.0])


class CrossfadeTests(unittest.TestCase):
    def test_the_buffer_shortens_by_the_fade_length(self):
        faded = noisebed._loop_crossfade([0.5] * 1000, 100)
        self.assertEqual(len(faded), 900)

    def test_constant_energy_is_preserved_across_the_seam(self):
        faded = noisebed._loop_crossfade([1.0] * 1000, 100)
        for value in faded[:100]:
            self.assertAlmostEqual(value, math.sin(math.pi / 4) + math.cos(math.pi / 4),
                                   delta=0.5)

    def test_a_buffer_too_short_to_fade_is_returned_intact(self):
        signal = [0.1, 0.2, 0.3]
        self.assertEqual(noisebed._loop_crossfade(signal, 10), signal)
        self.assertEqual(noisebed._loop_crossfade(signal, 0), signal)


class SeamlessFrequencyTests(unittest.TestCase):
    def test_a_whole_number_of_cycles_is_left_alone(self):
        self.assertAlmostEqual(noisebed.seamless_frequency(50.0, 12.0), 50.0)

    def test_the_result_always_closes_its_last_cycle(self):
        for seconds in (11.75, 7.3, 12.0):
            hz = noisebed.seamless_frequency(50.0, seconds)
            self.assertAlmostEqual(hz * seconds, round(hz * seconds), places=9)

    def test_the_nudge_is_small(self):
        self.assertAlmostEqual(noisebed.seamless_frequency(50.0, 11.75), 50.0, delta=0.2)

    def test_degenerate_inputs_give_no_hum(self):
        self.assertEqual(noisebed.seamless_frequency(0, 12), 0.0)
        self.assertEqual(noisebed.seamless_frequency(50, 0), 0.0)


class GenerateTests(unittest.TestCase):
    SECONDS = 1.0
    RATE = 8000

    def bed(self, band="sw", intensity=0.7, **kwargs):
        kwargs.setdefault("seconds", self.SECONDS)
        kwargs.setdefault("rate", self.RATE)
        return noisebed.generate(band, intensity, **kwargs)

    def test_the_same_inputs_always_give_the_same_bed(self):
        self.assertEqual(self.bed(), self.bed())

    def test_a_different_seed_gives_a_different_bed(self):
        self.assertNotEqual(self.bed(), self.bed(seed=99))

    def test_a_different_band_gives_a_different_bed(self):
        self.assertNotEqual(self.bed("sw"), self.bed("mw"))

    def test_a_different_intensity_gives_a_different_bed(self):
        self.assertNotEqual(self.bed(intensity=0.2), self.bed(intensity=0.9))

    def test_intensities_inside_one_grid_step_share_a_bed(self):
        self.assertEqual(self.bed(intensity=0.70), self.bed(intensity=0.72))

    def test_a_clean_band_has_no_static(self):
        self.assertEqual(self.bed("fm", 1.0), [])

    def test_zero_intensity_has_no_static(self):
        self.assertEqual(self.bed("sw", 0.0), [])

    def test_the_bed_is_shortened_by_the_loop_crossfade(self):
        expected = int(round(self.SECONDS * self.RATE)) - int(round(
            noisebed.LOOP_FADE_SECONDS * self.RATE))
        self.assertEqual(len(self.bed()), expected)

    def test_the_bed_is_peak_normalised(self):
        self.assertAlmostEqual(max(abs(v) for v in self.bed()), noisebed.PEAK, places=6)

    def test_the_bed_stays_inside_the_sample_range(self):
        self.assertTrue(all(-1.0 < v < 1.0 for v in self.bed()))

    def test_more_intensity_means_more_crackle(self):
        def spikes(intensity):
            samples = self.bed("sw", intensity)
            if not samples:
                return 0
            rms = math.sqrt(sum(v * v for v in samples) / len(samples))
            return sum(1 for v in samples if abs(v) > rms * 4)
        self.assertGreater(spikes(1.0), spikes(0.2))

    def test_long_wave_carries_its_hum(self):
        # The hum is a strong periodic component; medium wave has none, so
        # long wave's bed should correlate with itself one hum period later.
        samples = self.bed("lw", 1.0)
        period = int(round(self.RATE / 50.0))
        def correlation(values):
            pairs = list(zip(values, values[period:]))
            return sum(a * b for a, b in pairs) / max(1, len(pairs))
        self.assertGreater(correlation(samples), correlation(self.bed("mw", 1.0)))

    def test_a_zero_length_request_is_empty(self):
        self.assertEqual(self.bed(seconds=0.0), [])


class Pcm16Tests(unittest.TestCase):
    def test_values_map_to_the_full_range(self):
        pcm = noisebed.to_pcm16([0.0, 1.0, -1.0, 0.5])
        self.assertEqual(list(pcm), [0, 32767, -32767, 16383])

    def test_out_of_range_values_are_clipped_not_wrapped(self):
        pcm = noisebed.to_pcm16([4.0, -4.0])
        self.assertEqual(list(pcm), [32767, -32767])


class FilenameTests(unittest.TestCase):
    def test_the_name_is_stable_for_the_same_settings(self):
        self.assertEqual(noisebed.bed_filename("sw", 0.7), noisebed.bed_filename("sw", 0.7))

    def test_the_name_carries_the_band(self):
        self.assertTrue(noisebed.bed_filename("sw", 0.7).startswith("bed-sw-"))
        self.assertTrue(noisebed.bed_filename("mw", 0.7).startswith("bed-mw-"))

    def test_different_settings_get_different_names(self):
        names = {
            noisebed.bed_filename("sw", 0.7),
            noisebed.bed_filename("sw", 0.2),
            noisebed.bed_filename("sw", 0.7, seed=1),
            noisebed.bed_filename("mw", 0.7),
        }
        self.assertEqual(len(names), 4)

    def test_intensities_inside_one_grid_step_share_a_name(self):
        self.assertEqual(noisebed.bed_filename("sw", 0.70), noisebed.bed_filename("sw", 0.73))

    def test_the_name_is_a_safe_filename(self):
        name = noisebed.bed_filename("sw", 0.7)
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".wav"))


class WriteAndEnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_written_audio_reads_back_identically(self):
        samples = [0.0, 0.5, -0.5, 0.9]
        path = noisebed.write_wav(os.path.join(self.tmp.name, "b.wav"), samples, 8000)
        with wave.open(path, "rb") as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(handle.getsampwidth(), 2)
            self.assertEqual(handle.getframerate(), 8000)
            raw = handle.readframes(handle.getnframes())
        values = struct.unpack("<%dh" % len(samples), raw)
        self.assertEqual(list(values), list(noisebed.to_pcm16(samples)))

    def test_writing_leaves_no_partial_file_behind(self):
        noisebed.write_wav(os.path.join(self.tmp.name, "b.wav"), [0.1], 8000)
        self.assertEqual(os.listdir(self.tmp.name), ["b.wav"])

    def test_ensure_creates_the_bed_once_and_then_reuses_it(self):
        first = noisebed.ensure(self.tmp.name, "sw", 0.7, seconds=0.2, rate=8000)
        stamp = os.stat(first).st_mtime_ns
        second = noisebed.ensure(self.tmp.name, "sw", 0.7, seconds=0.2, rate=8000)
        self.assertEqual(first, second)
        self.assertEqual(os.stat(second).st_mtime_ns, stamp)

    def test_ensure_makes_a_directory_that_is_not_there_yet(self):
        target = os.path.join(self.tmp.name, "nested", "deeper")
        path = noisebed.ensure(target, "mw", 0.5, seconds=0.2, rate=8000)
        self.assertTrue(os.path.isfile(path))

    def test_ensure_returns_nothing_for_a_band_with_no_static(self):
        self.assertIsNone(noisebed.ensure(self.tmp.name, "fm", 1.0))
        self.assertIsNone(noisebed.ensure(self.tmp.name, "sw", 0.0))

    def test_a_truncated_cache_file_is_regenerated(self):
        path = noisebed.ensure(self.tmp.name, "sw", 0.7, seconds=0.2, rate=8000)
        with open(path, "wb") as handle:
            handle.write(b"")
        again = noisebed.ensure(self.tmp.name, "sw", 0.7, seconds=0.2, rate=8000)
        self.assertGreater(os.path.getsize(again), 44)


if __name__ == "__main__":
    unittest.main()
