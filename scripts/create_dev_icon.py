"""Windows resource build'i için bağımlılıksız, basit geliştirme simgesi."""
from pathlib import Path
import struct

size = 32
pixels = bytearray()
for row in range(size):
    y = size - 1 - row  # DIB bottom-up
    for x in range(size):
        foreground = 6 <= y <= 25 and (6 <= x <= 9 or 22 <= x <= 25 or abs(x - (7 + (y - 6) * 0.85)) < 2)
        r, g, b = (211, 229, 250) if foreground else (19, 25, 33)
        pixels.extend((b, g, r, 255))
mask = bytes(4 * size)
bitmap = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels + mask
icon = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(bitmap), 22) + bitmap
target = Path(__file__).resolve().parents[1] / "apps/desktop/src-tauri/icons/icon.ico"
target.parent.mkdir(exist_ok=True)
target.write_bytes(icon)
print("Geliştirme ICO kaynağı oluşturuldu.")
