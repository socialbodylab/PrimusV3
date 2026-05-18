"""
effects.py — Color utilities, effect functions, and grid transforms.
"""

import math
import random


# ======================================================================
#  COLOR UTILITIES
# ======================================================================

def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def hsv_to_rgb(h, s, v):
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t_ = v * (1.0 - (1.0 - f) * s)
    r, g, b = [
        (v, t_, p), (q, v, p), (p, v, t_),
        (p, q, v), (t_, p, v), (v, p, q),
    ][i % 6]
    return (int(r * 255), int(g * 255), int(b * 255))


def random_color_between(c1, c2):
    return lerp_color(c1, c2, random.random())


def normalize_brightness(value, default=1.0):
    try:
        brightness = float(value)
    except (TypeError, ValueError):
        brightness = default
    if not math.isfinite(brightness):
        brightness = default
    return max(0.0, min(1.0, brightness))


def scale_pixels(pixels, brightness):
    factor = normalize_brightness(brightness)
    result = []
    for pixel in pixels:
        result.append(tuple(
            max(0, min(255, int(channel * factor)))
            for channel in pixel[:3]
        ))
    return result


def blend_pixels(pixels_a, pixels_b, factor):
    """Per-pixel blend: result = a*(1-factor) + b*factor. Lists must be same length."""
    result = []
    for i in range(min(len(pixels_a), len(pixels_b))):
        a = pixels_a[i]
        b = pixels_b[i]
        result.append(lerp_color(a, b, factor))
    return result


def _smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _hash_unit(*values):
    h = 2166136261
    for value in values:
        h ^= int(value) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 3266489917) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 0xFFFFFFFF


def _value_noise_2d(x, y, seed=0):
    x0 = math.floor(x)
    y0 = math.floor(y)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = _smoothstep(x - x0)
    fy = _smoothstep(y - y0)
    a = _lerp(_hash_unit(x0, y0, seed), _hash_unit(x1, y0, seed), fx)
    b = _lerp(_hash_unit(x0, y1, seed), _hash_unit(x1, y1, seed), fx)
    return _lerp(a, b, fy)


def _fractal_noise_2d(x, y, seed=0, octaves=3):
    total = 0.0
    amplitude = 1.0
    frequency = 1.0
    normalizer = 0.0
    for octave in range(octaves):
        total += _value_noise_2d(x * frequency, y * frequency,
                                 seed + octave * 101) * amplitude
        normalizer += amplitude
        frequency *= 2.0
        amplitude *= 0.5
    return total / max(normalizer, 0.001)


# ======================================================================
#  ANIMATION FACTOR
# ======================================================================

def compute_anim_factor(scaled_t, playback, duration=5.0):
    rate = 1.0 / max(duration, 0.1)
    if playback == "once":
        return min(scaled_t * rate, 1.0)
    elif playback == "boomerang":
        cyc = (scaled_t * rate) % 2.0
        return cyc if cyc <= 1.0 else 2.0 - cyc
    else:
        return (scaled_t * rate) % 1.0


# ======================================================================
#  EFFECT FUNCTIONS
# ======================================================================

def fx_none(count, **kw):
    return [(0, 0, 0)] * count


def fx_solid(count, start_color, **kw):
    return [start_color] * count


def fx_pulse(count, t, start_color, end_color, duration=5.0, **kw):
    rate = math.tau / max(duration, 0.1)
    f = (math.sin(t * rate) + 1.0) / 2.0
    c = lerp_color(start_color, end_color, f)
    return [c] * count


def fx_linear(count, anim_factor, start_color, end_color,
              grid=None, angle=0, **kw):
    pixels = []
    if grid:
        cols, rows = grid
        rad = math.radians(angle)
        ax, ay = math.cos(rad), math.sin(rad)
        ox = math.cos(anim_factor * math.tau) * 0.2
        oy = math.sin(anim_factor * math.tau) * 0.2
        for idx in range(count):
            x, y = idx % cols, idx // cols
            nx = x / max(cols - 1, 1) - 0.5
            ny = y / max(rows - 1, 1) - 0.5
            dot = (nx + ox) * ax + (ny + oy) * ay
            pixels.append(lerp_color(start_color, end_color,
                                     max(0.0, min(1.0, dot + 0.5))))
    else:
        for i in range(count):
            pos = i / max(count - 1, 1)
            shifted = (pos + anim_factor) % 1.0
            pixels.append(lerp_color(start_color, end_color, shifted))
    return pixels


def fx_constrainbow(count, dt, speed, playback,
                    start_color, end_color, state, **kw):
    while len(state) < count:
        state.append({
            "cur": random_color_between(start_color, end_color),
            "nxt": random_color_between(start_color, end_color),
            "prg": random.random(),
        })
    inc = dt * 0.3 * speed
    pixels = []
    for i in range(count):
        s = state[i]
        s["prg"] += inc
        # Handle reverse direction (negative dt from boomerang)
        while s["prg"] < 0.0:
            s["nxt"] = s["cur"]
            s["cur"] = random_color_between(start_color, end_color)
            s["prg"] += 1.0
        if playback == "boomerang":
            cp = (s["prg"] * 2.0) % 2.0
            f = cp if cp < 1.0 else 2.0 - cp
            pixels.append(lerp_color(s["cur"], s["nxt"], f))
            if s["prg"] >= 1.0:
                s["cur"] = s["nxt"]
                s["nxt"] = random_color_between(start_color, end_color)
                s["prg"] = 0.0
        elif playback == "once":
            s["prg"] = min(s["prg"], 1.0)
            pixels.append(lerp_color(s["cur"], s["nxt"], s["prg"]))
        else:
            if s["prg"] >= 1.0:
                s["cur"] = s["nxt"]
                s["nxt"] = random_color_between(start_color, end_color)
                s["prg"] = 0.0
            pixels.append(lerp_color(s["cur"], s["nxt"], s["prg"]))
    return pixels


def fx_rainbow(count, t, grid=None, duration=5.0, **kw):
    rate = 1.0 / max(duration, 0.1)
    pixels = []
    if grid:
        cols, rows = grid
        for idx in range(count):
            x, y = idx % cols, idx // cols
            offset = (x / cols + y / rows) * 0.5
            hue = (t * rate + offset) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
    else:
        for i in range(count):
            pos = i / max(count - 1, 1)
            hue = (pos + t * rate) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
    return pixels


def fx_radial(count, t, anim_factor, start_color, end_color,
              grid=None, duration=5.0, **kw):
    if not grid:
        rate = math.tau / max(duration, 0.1)
        f = (math.sin(t * rate) + 1.0) / 2.0
        return [lerp_color(start_color, end_color, f)] * count
    cols, rows = grid
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    max_dist = math.hypot(cx, cy)
    pixels = []
    for idx in range(count):
        x, y = idx % cols, idx // cols
        dist = math.hypot(x - cx, y - cy) / max(max_dist, 0.001)
        shifted = (dist + anim_factor) % 1.0
        pixels.append(lerp_color(start_color, end_color, shifted))
    return pixels


def fx_spiral(count, t, anim_factor, start_color, end_color,
              grid=None, duration=5.0, **kw):
    if not grid:
        rate = 1.0 / max(duration, 0.1)
        pixels = []
        for i in range(count):
            pos = i / max(count - 1, 1)
            hue = (pos + t * rate) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
        return pixels
    cols, rows = grid
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    max_dist = math.hypot(cx, cy)
    pixels = []
    for idx in range(count):
        x, y = idx % cols, idx // cols
        angle = math.atan2(y - cy, x - cx) / math.tau + 0.5
        dist = math.hypot(x - cx, y - cy) / max(max_dist, 0.001)
        spiral_val = (angle + dist * 2.0 + anim_factor) % 1.0
        pixels.append(lerp_color(start_color, end_color, spiral_val))
    return pixels


def fx_knight_rider(count, t, start_color, end_color,
                    highlight_width=5, duration=5.0, **kw):
    if count <= 1:
        return [list(start_color)] * count
    hw = max(int(highlight_width), 1)
    radius = hw * count / 30.0
    rate = 2.0 / max(duration, 0.1)
    cyc = (t * rate) % 2.0
    pos = cyc if cyc <= 1.0 else 2.0 - cyc
    center = pos * (count - 1)
    pixels = []
    for i in range(count):
        dist = abs(i - center)
        if dist < radius:
            f = 1.0 - (dist / radius)
            pixels.append(lerp_color(end_color, start_color, f))
        else:
            pixels.append(end_color)
    return pixels


def fx_chase(count, anim_factor, start_color, end_color,
             chase_origin="start", grid=None, angle=0, **kw):
    if grid:
        cols, rows = grid
        rad = math.radians(angle)
        ax, ay = math.cos(rad), math.sin(rad)
        pixels = []
        for idx in range(count):
            x, y = idx % cols, idx // cols
            nx = x / max(cols - 1, 1) - 0.5
            ny = y / max(rows - 1, 1) - 0.5
            if chase_origin == "center":
                proj = abs(nx * ax + ny * ay) * 2.0
            elif chase_origin == "end":
                proj = 1.0 - (nx * ax + ny * ay + 0.5)
            else:
                proj = nx * ax + ny * ay + 0.5
            pixels.append(list(end_color) if proj <= anim_factor
                          else list(start_color))
        return pixels
    else:
        if chase_origin == "center":
            mid = count / 2.0
            fill = anim_factor * mid
            return [list(end_color) if abs(i - mid + 0.5) <= fill
                    else list(start_color) for i in range(count)]
        elif chase_origin == "end":
            wi = math.floor(anim_factor * count)
            return [list(end_color) if i >= count - wi
                    else list(start_color) for i in range(count)]
        else:
            wi = math.floor(anim_factor * count)
            return [list(end_color) if i < wi
                    else list(start_color) for i in range(count)]


def fx_noise(count, t, start_color, end_color, anim_factor=0.0,
             grid=None, **kw):
    pixels = []
    phase = anim_factor * math.tau
    drift_x = math.cos(phase) * 1.4
    drift_y = math.sin(phase) * 1.4
    if grid:
        cols, rows = grid
        scale = 2.8
        for idx in range(count):
            x, y = idx % cols, idx // cols
            nx = x / max(cols - 1, 1) * scale + drift_x
            ny = y / max(rows - 1, 1) * scale + drift_y
            n = _fractal_noise_2d(nx, ny, seed=73, octaves=3)
            pixels.append(lerp_color(start_color, end_color, n))
    else:
        scale = 4.0
        time_y = t * 0.45
        for i in range(count):
            x = i / max(count - 1, 1) * scale + drift_x
            n = _fractal_noise_2d(x, time_y + drift_y, seed=73, octaves=3)
            pixels.append(lerp_color(start_color, end_color, n))
    return pixels


def fx_static_noise(count, t, start_color, end_color, grid=None, **kw):
    frame = math.floor(t * 18.0)
    pixels = []
    for i in range(count):
        n = _hash_unit(i, frame, 197)
        pixels.append(lerp_color(start_color, end_color, n))
    return pixels


def fx_sparkle_noise(count, t, start_color, end_color, grid=None, **kw):
    if count <= 0:
        return []
    frame = math.floor(t * 12.0)
    primary = int(_hash_unit(frame, 509) * count) % count
    pixels = []
    for i in range(count):
        trigger = _hash_unit(i, frame, 311)
        previous = _hash_unit(i, frame - 1, 311)
        intensity = 0.0
        if i == primary:
            intensity = 1.0
        elif trigger > 0.88:
            intensity = 0.45 + _hash_unit(i, frame, 719) * 0.55
        elif previous > 0.93:
            intensity = 0.25
        pixels.append(lerp_color(start_color, end_color, intensity))
    return pixels


# ======================================================================
#  GRID PIXEL REORDERING
# ======================================================================

def apply_serpentine(pixels, cols, rows):
    out = list(pixels)
    for r in range(rows):
        if r % 2 == 1:
            start = r * cols
            end = start + cols
            out[start:end] = out[start:end][::-1]
    return out


def apply_grid_rotation(pixels, cols, rows, rotation):
    if rotation == 0:
        return pixels
    grid_2d = []
    for r in range(rows):
        grid_2d.append(pixels[r * cols:(r + 1) * cols])
    if rotation == 90:
        rotated = []
        for c in range(cols):
            row = [grid_2d[rows - 1 - r][c] for r in range(rows)]
            rotated.append(row)
    elif rotation == 180:
        rotated = [row[::-1] for row in reversed(grid_2d)]
    elif rotation == 270:
        rotated = []
        for c in range(cols - 1, -1, -1):
            row = [grid_2d[r][c] for r in range(rows)]
            rotated.append(row)
    else:
        return pixels
    out = []
    for row in rotated:
        out.extend(row)
    return out


# ======================================================================
#  EFFECTS REGISTRY
# ======================================================================

EFFECTS = {
    "none":         fx_none,
    "solid":        fx_solid,
    "pulse":        fx_pulse,
    "linear":       fx_linear,
    "constrainbow": fx_constrainbow,
    "rainbow":      fx_rainbow,
    "noise":        fx_noise,
    "static_noise": fx_static_noise,
    "sparkle_noise": fx_sparkle_noise,
    "knight_rider": fx_knight_rider,
    "chase":        fx_chase,
    "radial":       fx_radial,
    "spiral":       fx_spiral,
}
