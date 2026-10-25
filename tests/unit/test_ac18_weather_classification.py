"""Unit tests for Acceptance Criteria AC-18:
Weather classification boundaries: cloud at 19.9, 20, 49.9, 50, 79.9 and 80 percent;
rain at 2.4, 2.5, 15.5, 15.6, 64.4 and 64.5 mm.
"""

import unittest
from app.domain.remarks import build_weather_remark, classify_rain, classify_sky


class TestAC18WeatherClassification(unittest.TestCase):
    def test_cloud_classification_boundaries(self) -> None:
        """AC-18: cloud at 19.9, 20, 49.9, 50, 79.9 and 80 percent."""
        # below 20% -> Sunny
        self.assertEqual(classify_sky(19.9), "Sunny")

        # 20% to under 50% -> Partly cloudy
        self.assertEqual(classify_sky(20.0), "Partly cloudy")
        self.assertEqual(classify_sky(49.9), "Partly cloudy")

        # 50% to under 80% -> Mostly cloudy
        self.assertEqual(classify_sky(50.0), "Mostly cloudy")
        self.assertEqual(classify_sky(79.9), "Mostly cloudy")

        # 80% or more -> Overcast
        self.assertEqual(classify_sky(80.0), "Overcast")
        self.assertEqual(classify_sky(100.0), "Overcast")

    def test_rain_classification_boundaries(self) -> None:
        """AC-18: rain at 2.4, 2.5, 15.5, 15.6, 64.4 and 64.5 mm."""
        # 0.1 to 2.4 mm -> Drizzle
        self.assertEqual(classify_rain(2.4), "Drizzle")

        # 2.5 to 15.5 mm -> Light rain
        self.assertEqual(classify_rain(2.5), "Light rain")
        self.assertEqual(classify_rain(15.5), "Light rain")

        # 15.6 to 64.4 mm -> Moderate rain
        self.assertEqual(classify_rain(15.6), "Moderate rain")
        self.assertEqual(classify_rain(64.4), "Moderate rain")

        # 64.5 mm or more -> Heavy rain
        self.assertEqual(classify_rain(64.5), "Heavy rain")
        self.assertEqual(classify_rain(100.0), "Heavy rain")

    def test_remark_builder_spec_examples(self) -> None:
        """Verify standard remarks matching Section B7 examples."""
        # 'Sunny, 35°C'
        r1 = build_weather_remark(mean_daytime_cloud_pct=15.0, rain_24h_mm=0.0, max_temp_c=35.0)
        self.assertEqual(r1, "Sunny, 35°C")

        # 'Partly cloudy, 33°C'
        r2 = build_weather_remark(mean_daytime_cloud_pct=35.0, rain_24h_mm=0.0, max_temp_c=33.0)
        self.assertEqual(r2, "Partly cloudy, 33°C")

        # 'Overcast, rain 14 mm, 29°C'
        r3 = build_weather_remark(mean_daytime_cloud_pct=85.0, rain_24h_mm=14.0, max_temp_c=29.0)
        self.assertEqual(r3, "Overcast, rain 14 mm, 29°C")

        # Max length constraint <= 40 chars
        self.assertLessEqual(len(r1), 40)
        self.assertLessEqual(len(r2), 40)
        self.assertLessEqual(len(r3), 40)


if __name__ == "__main__":
    unittest.main()
