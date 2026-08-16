"""Synthetic face generation for face-matching tests.

Faces are drawn procedurally rather than shipping photographs, so no real
person's biometric data enters the repository.

YuNet is trained on photographs and ignores flat cartoon drawings entirely, so
these use vertical gradient shading, shaded features, and a slight blur — that
is enough to be detected reliably (~0.90 detector score).
"""

from __future__ import annotations

import io


def draw_face(
    *,
    seed: int = 0,
    size: int = 480,
    blur: float = 2.0,
) -> bytes:
    """Render a detectable frontal face.

    `seed` varies head width, feature spacing, skin tone, and mouth shape so
    different seeds yield faces SFace scores as different people.
    """
    from PIL import Image, ImageDraw, ImageFilter

    # Derive geometry from the seed, staying within plausible face proportions.
    half_w = 70 + (seed % 4) * 9
    half_h = 100 + (seed % 3) * 10
    eye_dx = 30 + (seed % 5) * 4
    eye_y_off = -46 + (seed % 4) * 7
    mouth_half = 26 + (seed % 6) * 9
    tone_shift = (seed % 5) * 16

    scale = size / 480.0
    cx = cy = size // 2

    image = Image.new("RGB", (size, size), (208, 206, 202))
    draw = ImageDraw.Draw(image)

    # Head: vertical gradient, which is what makes it read as a photo.
    top = int(cy - half_h * scale)
    height = int(2 * half_h * scale)
    for row in range(height):
        t = row / max(height, 1)
        colour = (
            max(0, int(246 - 45 * t) - tone_shift),
            max(0, int(212 - 45 * t) - tone_shift),
            max(0, int(188 - 40 * t) - tone_shift),
        )
        # Ellipse half-width at this row.
        norm = (row - height / 2) / (height / 2)
        if abs(norm) >= 1:
            continue
        width = int(half_w * scale * (1 - norm * norm) ** 0.5)
        if width > 0:
            draw.line([(cx - width, top + row), (cx + width, top + row)], fill=colour)

    ex = int(eye_dx * scale)
    ey = int(cy + eye_y_off * scale)

    for dx in (-ex, ex):
        # Sclera, iris, pupil, then a brow above.
        draw.ellipse(
            [cx + dx - int(19 * scale), ey - int(11 * scale),
             cx + dx + int(19 * scale), ey + int(11 * scale)],
            fill=(250, 250, 250),
        )
        draw.ellipse(
            [cx + dx - int(9 * scale), ey - int(9 * scale),
             cx + dx + int(9 * scale), ey + int(9 * scale)],
            fill=(48, 36, 30),
        )
        draw.ellipse(
            [cx + dx - int(4 * scale), ey - int(4 * scale),
             cx + dx + int(4 * scale), ey + int(4 * scale)],
            fill=(12, 12, 12),
        )
        draw.arc(
            [cx + dx - int(22 * scale), ey - int(30 * scale),
             cx + dx + int(22 * scale), ey - int(2 * scale)],
            200, 340, fill=(92, 66, 50), width=max(2, int(5 * scale)),
        )

    # Nose
    draw.polygon(
        [
            (cx, cy - int(18 * scale)),
            (cx - int(13 * scale), cy + int(22 * scale)),
            (cx + int(13 * scale), cy + int(22 * scale)),
        ],
        fill=(max(0, 216 - tone_shift), max(0, 182 - tone_shift), max(0, 156 - tone_shift)),
    )
    draw.line(
        [(cx - int(13 * scale), cy + int(22 * scale)),
         (cx + int(13 * scale), cy + int(22 * scale))],
        fill=(178, 144, 124), width=max(2, int(3 * scale)),
    )

    # Mouth
    draw.arc(
        [cx - int(mouth_half * scale), cy + int(38 * scale),
         cx + int(mouth_half * scale), cy + int(78 * scale)],
        10, 170, fill=(152, 82, 82), width=max(3, int(7 * scale)),
    )

    image = image.filter(ImageFilter.GaussianBlur(blur))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
