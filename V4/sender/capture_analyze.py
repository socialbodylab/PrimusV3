"""capture_analyze.py — Rolling flicker diagnostics from captured Art-Net events."""

import time
from collections import defaultdict

import capture_store
from capture_setup import device_label, universe_for_ip

_WINDOW_SECONDS = 5.0


def _sequence_gap(prev_seq, new_seq):
    if prev_seq is None or new_seq is None:
        return 0
    if new_seq == 0 or prev_seq == 0:
        return 0
    expected = (prev_seq % 255) + 1
    if new_seq == expected:
        return 0
    if new_seq > prev_seq:
        return new_seq - prev_seq - 1
    return (255 - prev_seq) + new_seq


def analyze_events(entries=None, show_setup=None):
    entries = entries if entries is not None else capture_store.get_events(since_id=0)
    if show_setup is None:
        status = capture_store.status()
        session = status.get("session") or {}
        show_setup = session.get("show_setup") or {}
    else:
        session = capture_store.status().get("session") or {}
    capture_mode = session.get("mode", "")
    capture_device_ip = session.get("device_ip", "")
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    sources = set()
    universes = defaultdict(int)
    opcode_counts = defaultdict(int)
    recent_rates = defaultdict(int)
    per_device = defaultdict(lambda: {
        "packets": 0,
        "universe": None,
        "expected_universe": None,
        "wrong_universe_packets": 0,
        "recent_rate": 0.0,
    })
    deltas = []
    sequence_gaps = 0
    sequence_repeats = 0
    last_seq = {}
    wrong_universe_total = 0
    unexpected_universes = set()

    expected_by_ip = {
        item.get("ip"): item.get("universe")
        for item in show_setup.get("devices", [])
        if item.get("ip")
    }
    expected_by_universe = {
        item.get("universe"): item.get("ip")
        for item in show_setup.get("devices", [])
        if item.get("universe") is not None
    }

    for entry in entries:
        ts = entry.get("ts") or 0
        src = entry.get("src") or ""
        dst = entry.get("dst") or ""
        opcode_name = entry.get("opcode_name") or "unknown"
        universe = entry.get("universe")
        sequence = entry.get("sequence")
        expected_universe = entry.get("expected_universe")
        if expected_universe is None and dst:
            expected_universe = universe_for_ip(show_setup, dst)

        if src:
            sources.add(src)
        opcode_counts[opcode_name] += 1
        if universe is not None:
            universes[universe] += 1
            if ts >= window_start:
                recent_rates[universe] += 1
            if expected_by_universe and universe not in expected_by_universe:
                unexpected_universes.add(universe)

        if dst:
            bucket = per_device[dst]
            bucket["packets"] += 1
            bucket["expected_universe"] = expected_universe
            if universe is not None:
                bucket["universe"] = universe
                if expected_universe is not None and universe != expected_universe:
                    bucket["wrong_universe_packets"] += 1
                    wrong_universe_total += 1
            if ts >= window_start:
                bucket["recent_rate"] += 1

        if entry.get("opcode") == 0x5000 and universe is not None:
            key = (src, universe)
            prev = last_seq.get(key)
            if prev is not None:
                if sequence == prev:
                    sequence_repeats += 1
                else:
                    sequence_gaps += _sequence_gap(prev, sequence)
            last_seq[key] = sequence

        delta = entry.get("delta_ms")
        if delta is not None and entry.get("opcode") == 0x5000:
            deltas.append(float(delta))

    device_stats = []
    for item in show_setup.get("devices", []):
        ip = item.get("ip")
        if not ip:
            continue
        bucket = per_device.get(ip, {})
        device_stats.append({
            "ip": ip,
            "label": item.get("label") or device_label(show_setup, ip),
            "expected_universe": item.get("universe"),
            "packets": bucket.get("packets", 0),
            "seen_universe": bucket.get("universe"),
            "wrong_universe_packets": bucket.get("wrong_universe_packets", 0),
            "packets_per_second": round(bucket.get("recent_rate", 0) / _WINDOW_SECONDS, 2),
        })

    anomalies = []
    if show_setup.get("layout") == "per_device_universe":
        for stat in device_stats:
            if stat["packets"] and stat["seen_universe"] is not None:
                if stat["seen_universe"] != stat["expected_universe"]:
                    anomalies.append({
                        "level": "warning",
                        "code": "wrong_universe",
                        "message": (
                            f"{stat['label']} ({stat['ip']}): expected universe "
                            f"{stat['expected_universe']}, saw {stat['seen_universe']}"
                        ),
                    })
            if stat["packets"] == 0 and entries:
                if capture_mode == "sniff" or stat["ip"] == capture_device_ip:
                    anomalies.append({
                    "level": "info",
                    "code": "device_silent",
                    "message": f"No packets for {stat['label']} ({stat['ip']}, U{stat['expected_universe']})",
                })
    if unexpected_universes:
        anomalies.append({
            "level": "warning",
            "code": "unexpected_universe",
            "message": f"Universes not in show setup: {', '.join(str(u) for u in sorted(unexpected_universes))}",
        })
    if wrong_universe_total > 0:
        anomalies.append({
            "level": "warning",
            "code": "wrong_universe_total",
            "message": f"ArtDmx packets on wrong universe: {wrong_universe_total}",
        })
    if len(sources) > 1:
        anomalies.append({
            "level": "warning",
            "code": "multiple_sources",
            "message": f"Multiple Art-Net sources detected: {', '.join(sorted(sources))}",
        })
    if sequence_gaps > 0:
        anomalies.append({
            "level": "warning",
            "code": "sequence_gaps",
            "message": f"ArtDmx sequence gaps detected: {sequence_gaps}",
        })
    if sequence_repeats > 5:
        anomalies.append({
            "level": "info",
            "code": "sequence_repeats",
            "message": f"Repeated ArtDmx sequence numbers: {sequence_repeats}",
        })

    jitter = {}
    if deltas:
        sorted_deltas = sorted(deltas)
        p95_index = max(0, int(len(sorted_deltas) * 0.95) - 1)
        avg = sum(deltas) / len(deltas)
        jitter = {
            "avg_ms": round(avg, 2),
            "max_ms": round(max(deltas), 2),
            "p95_ms": round(sorted_deltas[p95_index], 2),
            "sample_count": len(deltas),
        }
        if avg < 10:
            anomalies.append({
                "level": "warning",
                "code": "burst_rate",
                "message": f"Very fast ArtDmx pacing (avg {avg:.1f} ms between packets)",
            })
        elif avg > 80:
            anomalies.append({
                "level": "info",
                "code": "slow_rate",
                "message": f"Slow ArtDmx pacing (avg {avg:.1f} ms between packets)",
            })
        if jitter["p95_ms"] > 100:
            anomalies.append({
                "level": "warning",
                "code": "high_jitter",
                "message": f"High inter-packet jitter (p95 {jitter['p95_ms']:.1f} ms)",
            })

    for universe, count in recent_rates.items():
        rate = count / _WINDOW_SECONDS
        if rate > 60:
            anomalies.append({
                "level": "warning",
                "code": "high_packet_rate",
                "message": f"Universe {universe}: {rate:.1f} pkt/s (>{60}/s)",
            })

    return {
        "packet_count": len(entries),
        "sources": sorted(sources),
        "universes": dict(sorted(universes.items())),
        "devices": device_stats,
        "wrong_universe_packets": wrong_universe_total,
        "packets_per_second": {
            str(u): round(c / _WINDOW_SECONDS, 2)
            for u, c in sorted(recent_rates.items())
        },
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "sequence_gaps": sequence_gaps,
        "sequence_repeats": sequence_repeats,
        "jitter": jitter,
        "anomalies": anomalies,
        "window_seconds": _WINDOW_SECONDS,
        "show_setup": show_setup,
    }


def summary_report():
    status = capture_store.status()
    session = status.get("session") or {}
    show_setup = session.get("show_setup") or {}
    stats = analyze_events(show_setup=show_setup)
    return {
        "generated_at": time.time(),
        "session": session,
        "stats": stats,
    }
