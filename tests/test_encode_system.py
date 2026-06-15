import unittest

from app import OUTPUT_DIR, output_path
from encode_system import EncodeConfig, build_ffmpeg_command, estimate_encode_minutes, expected_size_mb, safe_output_name


class EncodeSystemTests(unittest.TestCase):
    def test_estimate_public_faster_than_private(self):
        public_eta = estimate_encode_minutes(20, "public", "medium")
        private_eta = estimate_encode_minutes(20, "private", "medium")
        self.assertLess(public_eta, private_eta)

    def test_two_pass_command_has_pass_flag(self):
        cfg = EncodeConfig(input_source="input.mp4", output_file="out.mp4", duration_minutes=20, mode="two_pass")
        pass1 = build_ffmpeg_command(cfg, pass_no=1)
        pass2 = build_ffmpeg_command(cfg, pass_no=2)
        self.assertIn("-pass", pass1)
        self.assertIn("1", pass1)
        self.assertIn("-pass", pass2)
        self.assertIn("2", pass2)
        self.assertEqual(pass2[-1], "out.mp4")

    def test_expected_size_positive(self):
        size = expected_size_mb(20, "crf", 4, 128, 23)
        self.assertGreater(size, 0)

    def test_safe_output_name(self):
        self.assertEqual(safe_output_name("../../bad?.mp4"), "bad.mp4")
        self.assertEqual(safe_output_name(""), "encoded.mp4")

    def test_output_path_stays_in_outputs(self):
        target = output_path("../../bad?.mp4")
        self.assertTrue(str(target).startswith(str(OUTPUT_DIR)))
        self.assertEqual(target.name, "bad.mp4")


if __name__ == "__main__":
    unittest.main()
