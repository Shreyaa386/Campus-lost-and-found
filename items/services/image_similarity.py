"""
Image Similarity Service for CampusCare.
Provides modular, explainable visual similarity comparisons between uploaded item images.
Uses Pillow for native color histogram intersection and luminance comparison,
with clean hooks for external AI vision or embedding services.
"""

import math
from io import BytesIO
from PIL import Image


class ImageSimilarityService:
    """
    Compares two item images and produces a similarity score (0.0 to 1.0)
    with human-readable explanation and confidence ratings.
    """

    @classmethod
    def _open_image(cls, image_source):
        """Safely opens an image from file path, FieldFile, or bytes."""
        if not image_source:
            return None
        try:
            if hasattr(image_source, 'path'):
                # Local filesystem path
                return Image.open(image_source.path)
            elif hasattr(image_source, 'file'):
                # Django FieldFile
                image_source.open()
                return Image.open(image_source.file)
            elif isinstance(image_source, str):
                return Image.open(image_source)
            elif isinstance(image_source, (bytes, bytearray)):
                return Image.open(BytesIO(image_source))
            elif isinstance(image_source, Image.Image):
                return image_source
        except Exception:
            return None
        return None

    @classmethod
    def compare_images(cls, image_a_source, image_b_source):
        """
        Compares two images.
        Returns:
            (similarity_score: float [0.0 - 1.0], confidence_label: str, explanation: str)
        """
        img_a = cls._open_image(image_a_source)
        img_b = cls._open_image(image_b_source)

        if not img_a or not img_b:
            return 0.0, "Unavailable", "One or both reports do not have an image to compare."

        try:
            # 1. Normalize images: 64x64 RGB
            thumb_a = img_a.convert('RGB').resize((64, 64), Image.Resampling.BILINEAR)
            thumb_b = img_b.convert('RGB').resize((64, 64), Image.Resampling.BILINEAR)

            # 2. Compute 32-bin color histograms per channel
            bins = 32
            hist_a = []
            hist_b = []
            for channel in range(3):
                ha = thumb_a.split()[channel].histogram()
                hb = thumb_b.split()[channel].histogram()
                # Reduce 256 bins to 32 bins
                bin_size = 256 // bins
                ha_reduced = [sum(ha[i * bin_size:(i + 1) * bin_size]) for i in range(bins)]
                hb_reduced = [sum(hb[i * bin_size:(i + 1) * bin_size]) for i in range(bins)]
                hist_a.extend(ha_reduced)
                hist_b.extend(hb_reduced)

            # 3. Histogram Intersection Similarity
            sum_min = sum(min(a, b) for a, b in zip(hist_a, hist_b))
            sum_total = sum(hist_a)
            histogram_sim = (sum_min / sum_total) if sum_total > 0 else 0.0

            # 4. Luminance & Color Difference
            pixels_a = list(thumb_a.getdata())
            pixels_b = list(thumb_b.getdata())
            total_diff = 0
            for (ra, ga, ba), (rb, gb, bb) in zip(pixels_a, pixels_b):
                diff = abs(ra - rb) + abs(ga - gb) + abs(ba - bb)
                total_diff += diff
            max_possible_diff = 64 * 64 * 255 * 3
            pixel_sim = 1.0 - (total_diff / max_possible_diff)

            # 5. Combined Score (60% histogram + 40% pixel similarity)
            score = max(0.0, min(1.0, (histogram_sim * 0.6) + (pixel_sim * 0.4)))

            # Human-readable confidence and explanation
            if score >= 0.75:
                label = "High Color/Visual Resemblance"
                pct = int(score * 100)
                explanation = f"Color palette and visual tone show high alignment ({pct}% similarity)."
            elif score >= 0.50:
                label = "Moderate Visual Resemblance"
                pct = int(score * 100)
                explanation = f"Noticeable color similarity ({pct}%), though lighting or angles may differ."
            else:
                label = "Low Visual Resemblance"
                pct = int(score * 100)
                explanation = f"Visual colors and tones differ substantially ({pct}% similarity)."

            return round(score, 3), label, explanation

        except Exception as e:
            return 0.0, "Error", f"Image analysis encountered an error: {str(e)}"

