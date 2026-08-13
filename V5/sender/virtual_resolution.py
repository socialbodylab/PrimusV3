"""Virtual resolution helpers for Art-Net transport downsampling."""


def default_virtual_pixels(output_type, physical_count):
    """Return the default virtual pixel count for an output type."""
    physical = int(physical_count or 0)
    if physical <= 0:
        return 0
    if output_type == "small_grid":
        return 1
    return physical


def resolve_virtual_pixels(output_dict, output_type=None, physical_count=None):
    """Resolve stored or default virtual pixel count for a device output."""
    if output_type is None:
        output_type = output_dict.get("type", "none")
    if physical_count is None:
        physical_count = int(output_dict.get("count") or 0)
    physical = int(physical_count or 0)
    if physical <= 0 or output_type == "none":
        return 0
    stored = output_dict.get("virtual_pixels")
    if stored is None:
        return default_virtual_pixels(output_type, physical)
    virtual = int(stored)
    if virtual < 1:
        virtual = 1
    if virtual > physical:
        virtual = physical
    return virtual


def virtual_percent_to_count(physical_count, virtual_percent):
    """Convert a 1-100 percent to a virtual pixel count."""
    physical = int(physical_count or 0)
    if physical <= 0:
        return 0
    percent = max(1, min(100, int(virtual_percent)))
    return max(1, round(physical * percent / 100))


def downsample_pixels(pixels, virtual_count):
    """Average physical pixels into virtual buckets for Art-Net transport."""
    physical = len(pixels)
    virtual = int(virtual_count or 0)
    if physical <= 0 or virtual <= 0:
        return []
    if virtual >= physical:
        return [tuple(int(channel) & 0xFF for channel in px[:3]) for px in pixels]

    out = []
    for v in range(virtual):
        start = (v * physical) // virtual
        end = ((v + 1) * physical) // virtual
        if end <= start:
            end = min(start + 1, physical)
        bucket = pixels[start:end]
        if not bucket:
            out.append((0, 0, 0))
            continue
        r = sum(px[0] for px in bucket)
        g = sum(px[1] for px in bucket)
        b = sum(px[2] for px in bucket)
        count = len(bucket)
        out.append((r // count, g // count, b // count))
    return out


def pack_rgb_pixels(pixels):
    """Pack RGB tuples into raw bytes."""
    buf = bytearray()
    for px in pixels:
        buf.extend((int(px[0]) & 0xFF, int(px[1]) & 0xFF, int(px[2]) & 0xFF))
    return bytes(buf)


def transport_rgb_bytes(output_dict, rgb_bytes=None, pixels=None):
    """Downsample to virtual resolution and return packed RGB bytes."""
    physical = int(output_dict.get("count") or 0)
    if physical <= 0:
        return b""

    virtual = resolve_virtual_pixels(output_dict)
    if virtual <= 0:
        return b""

    if pixels is None:
        if not rgb_bytes:
            return bytes(virtual * 3)
        step = 3
        pixels = [
            (rgb_bytes[i], rgb_bytes[i + 1], rgb_bytes[i + 2])
            for i in range(0, min(len(rgb_bytes), physical * step), step)
        ]
    else:
        # Same normalization as the byte path: truncate to the output's
        # physical count and zero-pad short frames, so a look rendered at a
        # different resolution still fills (and blanks) every physical LED.
        pixels = list(pixels[:physical])
    while len(pixels) < physical:
        pixels.append((0, 0, 0))

    transport_pixels = downsample_pixels(pixels, virtual)
    return pack_rgb_pixels(transport_pixels)
