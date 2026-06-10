from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "src-tauri" / "icons"


def draw_icon(size: int = 1024) -> Image.Image:
    scale = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(v * scale) for v in values)

    draw.rounded_rectangle(box((18, 34, 238, 218)), radius=round(42 * scale), fill=(79, 70, 229, 255))
    draw.rounded_rectangle(box((42, 62, 214, 96)), radius=round(14 * scale), fill=(129, 140, 248, 255))
    draw.rounded_rectangle(box((42, 112, 214, 184)), radius=round(20 * scale), fill=(255, 255, 255, 235))
    draw.rounded_rectangle(box((62, 132, 112, 164)), radius=round(10 * scale), fill=(79, 70, 229, 255))
    draw.rounded_rectangle(box((128, 132, 194, 164)), radius=round(10 * scale), fill=(99, 102, 241, 190))
    return img


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    png = draw_icon()
    png.save(ICONS_DIR / "icon.png")
    png.save(
        ICONS_DIR / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    png.save(
        ICONS_DIR / "icon.icns",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )
    print(f"Generated icons in {ICONS_DIR}")


if __name__ == "__main__":
    main()
