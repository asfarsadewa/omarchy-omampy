"""Block-glyph drawing primitives."""

import unittest

from omampy import render


class WidthTests(unittest.TestCase):
    def test_ascii_counts_one_cell_each(self):
        self.assertEqual(render.display_width("radio"), 5)

    def test_block_and_box_glyphs_are_single_cell(self):
        for text in (render.BLOCKS, render.SHADES, "┌─┐│└┘├┤╞╡╪▼▐▌▔"):
            self.assertEqual(render.display_width(text), len(text))

    def test_wide_glyphs_count_two_cells(self):
        self.assertEqual(render.display_width("東京"), 4)

    def test_combining_marks_take_no_room(self):
        self.assertEqual(render.display_width("é"), 1)

    def test_the_empty_string_is_zero(self):
        self.assertEqual(render.display_width(""), 0)


class TruncateTests(unittest.TestCase):
    def test_text_that_fits_is_untouched(self):
        self.assertEqual(render.truncate("radio", 8), "radio")
        self.assertEqual(render.truncate("radio", 5), "radio")

    def test_longer_text_is_marked_where_it_was_cut(self):
        # The mark is part of the budget, not an addition to it.
        self.assertEqual(render.truncate("shortwave", 5), "shor…")
        self.assertEqual(render.display_width(render.truncate("shortwave", 5)), 5)

    def test_the_result_never_exceeds_the_width(self):
        for width in range(1, 12):
            self.assertLessEqual(render.display_width(render.truncate("shortwave", width)), width)

    def test_wide_glyphs_are_not_split_across_a_cell(self):
        self.assertLessEqual(render.display_width(render.truncate("東京放送", 5)), 5)

    def test_zero_width_produces_nothing(self):
        self.assertEqual(render.truncate("radio", 0), "")


class PadTests(unittest.TestCase):
    def test_padding_reaches_exactly_the_requested_width(self):
        for align in ("left", "right", "center"):
            self.assertEqual(render.display_width(render.pad("am", 9, align)), 9)

    def test_alignment_places_the_text(self):
        self.assertEqual(render.pad("am", 6), "am    ")
        self.assertEqual(render.pad("am", 6, "right"), "    am")
        self.assertEqual(render.pad("am", 6, "center"), "  am  ")

    def test_overlong_text_is_truncated_to_the_width(self):
        self.assertEqual(render.display_width(render.pad("shortwave", 4)), 4)

    def test_wide_glyphs_still_land_on_the_exact_width(self):
        self.assertEqual(render.display_width(render.pad("東京", 9)), 9)


class Clamp01Tests(unittest.TestCase):
    def test_values_inside_the_range_pass_through(self):
        self.assertEqual(render.clamp01(0.42), 0.42)

    def test_values_outside_the_range_are_clamped(self):
        self.assertEqual(render.clamp01(-1), 0.0)
        self.assertEqual(render.clamp01(9), 1.0)

    def test_nonsense_reads_as_zero(self):
        for value in (None, "loud", float("nan"), object()):
            self.assertEqual(render.clamp01(value), 0.0)


class ColumnTests(unittest.TestCase):
    def test_a_column_is_as_tall_as_requested(self):
        self.assertEqual(len(render.column(0.5, 6)), 6)

    def test_zero_is_blank_and_one_is_solid(self):
        self.assertEqual(render.column(0.0, 4), [" "] * 4)
        self.assertEqual(render.column(1.0, 4), ["█"] * 4)

    def test_it_fills_from_the_bottom(self):
        cells = render.column(0.5, 4)
        self.assertEqual(cells[0], " ")
        self.assertEqual(cells[-1], "█")

    def test_partial_cells_use_the_intermediate_glyphs(self):
        cells = render.column(0.1, 1)
        self.assertIn(cells[0], render.BLOCKS)
        self.assertNotEqual(cells[0], " ")
        self.assertNotEqual(cells[0], "█")

    def test_taller_values_never_produce_shorter_columns(self):
        def ink(value):
            return sum(1 for cell in render.column(value, 8) if cell != " ")
        heights = [ink(v / 20) for v in range(21)]
        self.assertEqual(heights, sorted(heights))

    def test_zero_height_is_rejected(self):
        with self.assertRaises(ValueError):
            render.column(0.5, 0)


class SpectrumTests(unittest.TestCase):
    def test_the_grid_is_rectangular(self):
        rows = render.spectrum_rows([0.1, 0.9, 0.5], 5)
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(render.display_width(row), 3)

    def test_no_bars_gives_empty_rows(self):
        self.assertEqual(render.spectrum_rows([], 3), ["", "", ""])

    def test_peaks_are_drawn_above_the_bars(self):
        rows = render.spectrum_rows([0.1], 8, [0.9])
        self.assertIn(render.PEAK_GLYPH, "".join(rows))

    def test_a_peak_never_overwrites_a_bar(self):
        rows = render.spectrum_rows([1.0], 4, [1.0])
        self.assertNotIn(render.PEAK_GLYPH, "".join(rows))

    def test_a_peak_at_zero_draws_nothing(self):
        rows = render.spectrum_rows([0.0], 4, [0.0])
        self.assertEqual("".join(rows).strip(), "")

    def test_extra_peaks_are_ignored(self):
        rows = render.spectrum_rows([0.5], 4, [0.5, 0.9, 0.2])
        for row in rows:
            self.assertEqual(render.display_width(row), 1)


class DownsampleTests(unittest.TestCase):
    def test_it_produces_exactly_the_requested_number_of_buckets(self):
        for count in (1, 3, 7, 20):
            self.assertEqual(len(render.downsample([0.1] * 14, count)), count)

    def test_it_keeps_the_loudest_value_in_each_bucket(self):
        self.assertEqual(render.downsample([0.1, 0.9, 0.2, 0.3], 2), [0.9, 0.3])

    def test_an_empty_input_gives_silence(self):
        self.assertEqual(render.downsample([], 4), [0.0] * 4)

    def test_upsampling_repeats_rather_than_dropping(self):
        self.assertEqual(render.downsample([0.5], 3), [0.5, 0.5, 0.5])

    def test_values_are_clamped(self):
        self.assertEqual(render.downsample([5.0, -5.0], 2), [1.0, 0.0])

    def test_zero_buckets_is_rejected(self):
        with self.assertRaises(ValueError):
            render.downsample([0.5], 0)


class MeterRowTests(unittest.TestCase):
    def test_the_row_is_exactly_the_requested_width(self):
        for value in (0.0, 0.33, 1.0):
            self.assertEqual(render.display_width(render.meter_row(value, 10)), 10)

    def test_the_ends_are_empty_and_full(self):
        self.assertEqual(render.meter_row(0.0, 4), "░░░░")
        self.assertEqual(render.meter_row(1.0, 4), "████")

    def test_a_zero_width_row_is_empty(self):
        self.assertEqual(render.meter_row(0.5, 0), "")

    def test_a_negative_width_is_rejected(self):
        with self.assertRaises(ValueError):
            render.meter_row(0.5, -1)


class ShadedRowTests(unittest.TestCase):
    def test_the_row_is_exactly_the_requested_width(self):
        self.assertEqual(render.display_width(render.shaded_row(0.42, 12)), 12)

    def test_it_fills_from_the_left(self):
        row = render.shaded_row(0.5, 8)
        self.assertEqual(row[0], "█")
        self.assertEqual(row[-1], " ")

    def test_the_empty_glyph_is_configurable(self):
        self.assertTrue(render.shaded_row(0.0, 4, empty="·").endswith("····"))

    def test_full_scale_is_solid(self):
        self.assertEqual(render.shaded_row(1.0, 5), "█████")


class FormatTimeTests(unittest.TestCase):
    def test_minutes_and_seconds(self):
        self.assertEqual(render.fmt_time(0), "0:00")
        self.assertEqual(render.fmt_time(9), "0:09")
        self.assertEqual(render.fmt_time(83), "1:23")
        self.assertEqual(render.fmt_time(599), "9:59")

    def test_an_hour_adds_a_field(self):
        self.assertEqual(render.fmt_time(3600), "1:00:00")
        self.assertEqual(render.fmt_time(3661), "1:01:01")

    def test_fractions_are_truncated_not_rounded_up(self):
        self.assertEqual(render.fmt_time(59.9), "0:59")

    def test_unknown_durations_read_as_dashes(self):
        for value in (None, -1, "soon", float("nan"), float("inf")):
            self.assertEqual(render.fmt_time(value), "--:--")


class ProgressBarTests(unittest.TestCase):
    def test_the_bar_is_exactly_the_requested_width(self):
        for position in (0, 50, 100, 240):
            self.assertEqual(render.display_width(render.progress_bar(position, 200, 20)), 20)

    def test_the_playhead_starts_at_the_left_and_ends_at_the_right(self):
        self.assertTrue(render.progress_bar(0, 200, 10).startswith("▌"))
        self.assertTrue(render.progress_bar(200, 200, 10).endswith("▌"))

    def test_an_unknown_duration_leaves_the_playhead_at_the_start(self):
        self.assertTrue(render.progress_bar(30, 0, 10).startswith("▌"))
        self.assertTrue(render.progress_bar(30, None, 10).startswith("▌"))

    def test_position_past_the_end_stays_inside_the_bar(self):
        self.assertEqual(render.display_width(render.progress_bar(900, 200, 12)), 12)

    def test_too_narrow_a_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            render.progress_bar(1, 2, 2)


class MarqueeTests(unittest.TestCase):
    def test_short_text_is_padded_and_does_not_move(self):
        first = render.marquee("radio", 12, 0)
        self.assertEqual(first, render.marquee("radio", 12, 7))
        self.assertEqual(render.display_width(first), 12)

    def test_long_text_is_windowed_to_the_width(self):
        for offset in range(0, 40):
            window = render.marquee("a very long station identifier", 10, offset)
            self.assertEqual(render.display_width(window), 10)

    def test_the_window_moves_with_the_offset(self):
        text = "a very long station identifier"
        self.assertNotEqual(render.marquee(text, 10, 0), render.marquee(text, 10, 3))

    def test_scrolling_wraps_around(self):
        text = "a very long station identifier"
        loop = len(text + "   ·   ")
        self.assertEqual(render.marquee(text, 10, 0), render.marquee(text, 10, loop))

    def test_zero_width_produces_nothing(self):
        self.assertEqual(render.marquee("radio", 0, 0), "")


class DialTests(unittest.TestCase):
    def test_the_scale_is_exactly_the_requested_width(self):
        for width in (5, 12, 30):
            self.assertEqual(render.display_width(render.dial(0.5, width)), width)

    def test_the_scale_has_ends(self):
        scale = render.dial(0.5, 20)
        self.assertEqual(scale[0], "╞")
        self.assertEqual(scale[-1], "╡")

    def test_the_pointer_moves_with_the_position(self):
        self.assertEqual(render.dial(0.0, 21).index("▼"), 0)
        self.assertEqual(render.dial(1.0, 21).index("▼"), 20)
        self.assertEqual(render.dial(0.5, 21).index("▼"), 10)

    def test_there_is_exactly_one_pointer(self):
        self.assertEqual(render.dial(0.3, 25).count("▼"), 1)

    def test_too_narrow_a_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            render.dial(0.5, 4)


class BandSwitchTests(unittest.TestCase):
    def test_the_selected_band_is_the_marked_one(self):
        row = render.band_switch("sw", ["mw", "sw", "lw"])
        self.assertIn("▐SW▌", row)
        self.assertNotIn("▐MW▌", row)

    def test_every_band_appears(self):
        row = render.band_switch("mw", ["mw", "sw", "lw", "fm"])
        for label in ("MW", "SW", "LW", "FM"):
            self.assertIn(label, row)

    def test_labels_can_be_supplied(self):
        row = render.band_switch("a", ["a", "b"], {"a": "AM", "b": "FM"})
        self.assertIn("▐AM▌", row)

    def test_selection_does_not_change_the_width(self):
        first = render.band_switch("mw", ["mw", "sw"])
        second = render.band_switch("sw", ["mw", "sw"])
        self.assertEqual(render.display_width(first), render.display_width(second))


class SignalGlyphTests(unittest.TestCase):
    def test_the_readout_is_exactly_the_requested_length(self):
        self.assertEqual(render.display_width(render.signal_glyphs(0.5, 5)), 5)

    def test_no_signal_is_all_dots(self):
        self.assertEqual(render.signal_glyphs(0.0, 4), "····")

    def test_full_signal_lights_every_step(self):
        self.assertNotIn("·", render.signal_glyphs(1.0, 4))

    def test_more_signal_lights_more_steps(self):
        weak = render.signal_glyphs(0.2, 5).count("·")
        strong = render.signal_glyphs(0.8, 5).count("·")
        self.assertGreater(weak, strong)

    def test_zero_steps_is_rejected(self):
        with self.assertRaises(ValueError):
            render.signal_glyphs(0.5, 0)


class RuleAndBoxTests(unittest.TestCase):
    def test_a_rule_is_exactly_the_requested_width(self):
        self.assertEqual(render.display_width(render.rule(20)), 20)
        self.assertEqual(render.display_width(render.rule(20, label="TAPE")), 20)

    def test_a_rule_label_appears_inside_it(self):
        self.assertIn("TAPE", render.rule(20, label="TAPE"))

    def test_a_box_is_rectangular(self):
        lines = render.box(["one", "two"], 20)
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(render.display_width(line), 20)

    def test_a_box_has_corners_and_sides(self):
        lines = render.box(["x"], 12)
        self.assertTrue(lines[0].startswith("┌") and lines[0].endswith("┐"))
        self.assertTrue(lines[1].startswith("│") and lines[1].endswith("│"))
        self.assertTrue(lines[-1].startswith("└") and lines[-1].endswith("┘"))

    def test_the_title_and_status_both_sit_on_the_top_edge(self):
        top = render.box(["x"], 40, title="OMAMPY", status="ON AIR")[0]
        self.assertIn("OMAMPY", top)
        self.assertIn("ON AIR", top)
        self.assertLess(top.index("OMAMPY"), top.index("ON AIR"))

    def test_overlong_content_does_not_break_the_frame(self):
        lines = render.box(["x" * 200], 24, title="A" * 50, status="B" * 50)
        for line in lines:
            self.assertEqual(render.display_width(line), 24)

    def test_a_box_with_no_content_is_still_closed(self):
        lines = render.box([], 10)
        self.assertEqual(len(lines), 2)

    def test_too_narrow_a_box_is_rejected(self):
        with self.assertRaises(ValueError):
            render.box(["x"], 3)


if __name__ == "__main__":
    unittest.main()
