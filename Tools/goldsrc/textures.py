"""PNG -> 8-битный BMP с палитрой (формат, который жрёт studiomdl/GoldSrc).

Только stdlib: PNG распаковывается через zlib, палитра строится медианным
разрезанием, BMP пишется как 256-цветный без RLE.
"""

from __future__ import annotations

import struct
import zlib


# ---------------------------------------------------------------- PNG


def read_png_rgba(path):
    """Возвращает (width, height, bytearray RGBA). Поддержка 8-бит RGB/RGBA."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "не PNG"

    pos = 8
    ihdr = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif ctype == b"IDAT":
            idat += payload
        elif ctype == b"IEND":
            break
        pos += 12 + length

    width, height, depth, color_type, comp, filt, interlace = ihdr
    assert depth == 8 and interlace == 0, "поддерживается только 8-бит без интерлейса"
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    raw = zlib.decompress(bytes(idat))

    stride = width * channels
    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        f = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if f == 1:      # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif f == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:    # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:    # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        prev = line

        o = y * width * 4
        if channels == 4:
            out[o:o + width * 4] = line
        elif channels == 3:
            for x in range(width):
                out[o + x * 4:o + x * 4 + 3] = line[x * 3:x * 3 + 3]
                out[o + x * 4 + 3] = 255
        elif channels == 1:
            for x in range(width):
                v = line[x]
                out[o + x * 4:o + x * 4 + 4] = bytes((v, v, v, 255))
        else:  # gray+alpha
            for x in range(width):
                v = line[x * 2]
                out[o + x * 4:o + x * 4 + 4] = bytes((v, v, v, line[x * 2 + 1]))
    return width, height, out


def downscale_rgba(w, h, rgba, factor):
    """Простое усреднение factor x factor."""
    nw, nh = w // factor, h // factor
    out = bytearray(nw * nh * 4)
    f2 = factor * factor
    for y in range(nh):
        for x in range(nw):
            r = g = b = a = 0
            for dy in range(factor):
                row = ((y * factor + dy) * w + x * factor) * 4
                for dx in range(factor):
                    i = row + dx * 4
                    r += rgba[i]
                    g += rgba[i + 1]
                    b += rgba[i + 2]
                    a += rgba[i + 3]
            o = (y * nw + x) * 4
            out[o] = r // f2
            out[o + 1] = g // f2
            out[o + 2] = b // f2
            out[o + 3] = a // f2
    return nw, nh, out


# ------------------------------------------------------------- палитра


def median_cut(pixels, max_colors=256):
    """pixels: список (r, g, b). Возвращает палитру [(r,g,b)] и индексы."""
    if not pixels:
        return [(0, 0, 0)], []

    boxes = [list(range(len(pixels)))]
    while len(boxes) < max_colors:
        # берём самый «длинный» бокс
        best, best_range, best_ch = -1, -1, 0
        for bi, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for ch in range(3):
                vals = [pixels[i][ch] for i in box]
                rng = max(vals) - min(vals)
                if rng > best_range:
                    best, best_range, best_ch = bi, rng, ch
        if best < 0 or best_range == 0:
            break
        box = boxes.pop(best)
        box.sort(key=lambda i: pixels[i][best_ch])
        mid = len(box) // 2
        boxes.append(box[:mid])
        boxes.append(box[mid:])

    palette = []
    for box in boxes:
        n = len(box)
        palette.append((sum(pixels[i][0] for i in box) // n,
                        sum(pixels[i][1] for i in box) // n,
                        sum(pixels[i][2] for i in box) // n))
    return palette, boxes


def quantize(rgba, w, h, max_colors=256):
    """Возвращает (palette, indices) для RGBA-буфера 8-бит."""
    # берём каждый N-й пиксель для обучения палитры
    step = max(1, (w * h) // 60000)
    samples = []
    for i in range(0, w * h, step):
        o = i * 4
        samples.append((rgba[o], rgba[o + 1], rgba[o + 2]))
    palette, boxes = median_cut(samples, max_colors)

    # карта цвет -> индекс палитры через кэш, ближайший цвет
    cache = {}
    idx = bytearray(w * h)
    pal = palette
    for i in range(w * h):
        o = i * 4
        key = (rgba[o], rgba[o + 1], rgba[o + 2])
        v = cache.get(key)
        if v is None:
            r, g, b = key
            best, bd = 0, 1 << 30
            for pi, (pr, pg, pb) in enumerate(pal):
                d = (pr - r) * (pr - r) + (pg - g) * (pg - g) + (pb - b) * (pb - b)
                if d < bd:
                    best, bd = pi, d
            v = best
            cache[key] = v
        idx[i] = v
    return pal, idx


# ---------------------------------------------------------------- BMP


def write_bmp8(path, w, h, palette, indices):
    """8-битный BMP (BI_RGB, снизу вверх), 256 цветов."""
    pal = list(palette) + [(0, 0, 0)] * (256 - len(palette))
    palette_bytes = bytearray()
    for r, g, b in pal[:256]:
        palette_bytes += bytes((b, g, r, 0))

    row_size = (w + 3) & ~3
    pixel_bytes = bytearray()
    for y in range(h - 1, -1, -1):     # BMP хранится снизу вверх
        row = indices[y * w:(y + 1) * w]
        pixel_bytes += bytes(row)
        pixel_bytes += b"\x00" * (row_size - w)

    offset = 14 + 40 + len(palette_bytes)
    size = offset + len(pixel_bytes)
    header = b"BM" + struct.pack("<IHHI", size, 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 8, 0, len(pixel_bytes),
                       2835, 2835, 256, 0)
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(info)
        fh.write(bytes(palette_bytes))
        fh.write(bytes(pixel_bytes))


def png_to_bmp8(src, dst, size=None, max_colors=256, report=print):
    w, h, rgba = read_png_rgba(src)
    if size and size < w:
        factor = max(1, w // size)
        w, h, rgba = downscale_rgba(w, h, rgba, factor)
    pal, idx = quantize(rgba, w, h, max_colors)
    write_bmp8(dst, w, h, pal, idx)
    report(f"  {src} -> {dst} ({w}x{h}, {len(pal)} цветов)")
    return w, h
