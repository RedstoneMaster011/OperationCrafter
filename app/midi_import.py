"""Small dependency-free Standard MIDI File reader for PC-speaker resources."""

import math
import struct


class MidiImportError(ValueError):
    pass


def _read_variable_length(data, position):
    value = 0
    for _ in range(4):
        if position >= len(data):
            raise MidiImportError("Unexpected end of MIDI variable-length value")
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7f)
        if not byte & 0x80:
            return value, position
    raise MidiImportError("Invalid MIDI variable-length value")


def _parse_track(track_data, track_number):
    position = 0
    tick = 0
    running_status = None
    order = 0
    events = []

    while position < len(track_data):
        delta, position = _read_variable_length(track_data, position)
        tick += delta
        if position >= len(track_data):
            break

        first_data = None
        status_byte = track_data[position]
        if status_byte & 0x80:
            status = status_byte
            position += 1
            if 0x80 <= status <= 0xef:
                running_status = status
            else:
                running_status = None
        else:
            if running_status is None:
                raise MidiImportError("MIDI track uses running status before a status byte")
            status = running_status
            first_data = status_byte
            position += 1

        if status == 0xff:
            if position >= len(track_data):
                raise MidiImportError("Truncated MIDI meta event")
            meta_type = track_data[position]
            position += 1
            length, position = _read_variable_length(track_data, position)
            payload = track_data[position:position + length]
            position += length
            if len(payload) != length:
                raise MidiImportError("Truncated MIDI meta-event payload")
            if meta_type == 0x51 and length == 3:
                tempo = int.from_bytes(payload, "big")
                events.append((tick, track_number, order, "tempo", tempo, 0))
            if meta_type == 0x2f:
                break
            order += 1
            continue

        if status in (0xf0, 0xf7):
            length, position = _read_variable_length(track_data, position)
            position += length
            if position > len(track_data):
                raise MidiImportError("Truncated MIDI system-exclusive event")
            order += 1
            continue

        event_type = status & 0xf0
        channel = status & 0x0f
        data_count = 1 if event_type in (0xc0, 0xd0) else 2
        values = [] if first_data is None else [first_data]
        needed = data_count - len(values)
        if position + needed > len(track_data):
            raise MidiImportError("Truncated MIDI channel event")
        values.extend(track_data[position:position + needed])
        position += needed

        if event_type == 0x90:
            note, velocity = values
            kind = "on" if velocity else "off"
            events.append((tick, track_number, order, kind, note, channel))
        elif event_type == 0x80:
            note = values[0]
            events.append((tick, track_number, order, "off", note, channel))
        order += 1

    return events


def read_midi_events(path):
    """Convert an SMF file to monophonic (frequency, duration_ms) events."""
    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiImportError("This is not a Standard MIDI File")
    header_length = struct.unpack_from(">I", data, 4)[0]
    if header_length < 6 or 8 + header_length > len(data):
        raise MidiImportError("Invalid MIDI header length")
    midi_format, track_count, division = struct.unpack_from(">HHH", data, 8)
    if midi_format not in (0, 1, 2):
        raise MidiImportError(f"Unsupported MIDI format {midi_format}")
    if division & 0x8000:
        raise MidiImportError("SMPTE-time MIDI files are not supported; use PPQN timing")
    if division == 0:
        raise MidiImportError("MIDI timing division cannot be zero")

    position = 8 + header_length
    all_events = []
    parsed_tracks = 0
    while position + 8 <= len(data) and parsed_tracks < track_count:
        chunk_type = data[position:position + 4]
        chunk_length = struct.unpack_from(">I", data, position + 4)[0]
        position += 8
        chunk = data[position:position + chunk_length]
        position += chunk_length
        if len(chunk) != chunk_length:
            raise MidiImportError("Truncated MIDI track")
        if chunk_type == b"MTrk":
            all_events.extend(_parse_track(chunk, parsed_tracks))
            parsed_tracks += 1

    if not all_events:
        raise MidiImportError("The MIDI file contains no playable note events")

    # Tempo events must be applied before note changes at the same tick.
    all_events.sort(key=lambda item: (item[0], 0 if item[3] == "tempo" else 1,
                                      item[1], item[2]))
    tempo_us_per_quarter = 500_000
    previous_tick = 0
    active_notes = {}
    activation_order = 0
    output = []

    index = 0
    while index < len(all_events):
        tick = all_events[index][0]
        delta_ticks = tick - previous_tick
        if delta_ticks > 0:
            duration_ms = max(
                1, round(delta_ticks * tempo_us_per_quarter / division / 1000)
            )
            if active_notes:
                note = max(active_notes.values(), key=lambda value: value[1])[0]
                frequency = max(20, min(20_000, round(440 * math.pow(2, (note - 69) / 12))))
            else:
                frequency = 0
            if output and output[-1][0] == frequency:
                output[-1] = (frequency, min(65_535, output[-1][1] + duration_ms))
            else:
                output.append((frequency, min(65_535, duration_ms)))
        previous_tick = tick

        while index < len(all_events) and all_events[index][0] == tick:
            _, track, _, kind, value, channel = all_events[index]
            if kind == "tempo":
                tempo_us_per_quarter = value
            elif kind == "on":
                activation_order += 1
                active_notes[(track, channel, value)] = (value, activation_order)
            elif kind == "off":
                active_notes.pop((track, channel, value), None)
            index += 1

    playable = [(frequency, duration) for frequency, duration in output if duration > 0]
    if not any(frequency > 0 for frequency, _ in playable):
        raise MidiImportError("The MIDI file does not contain a note with a duration")
    return playable, {
        "format": midi_format,
        "tracks": parsed_tracks,
        "ticks_per_quarter": division,
    }


def midi_events_to_asm(events, symbol, source_name="music.mid"):
    lines = [
        f"; Converted from {source_name} by Operation Crafter",
        "; Each pair is: PC-speaker frequency in Hz, duration in milliseconds",
        f"{symbol}_midi:",
    ]
    for frequency, duration in events:
        lines.append(f"    dw {frequency}, {duration}")
    lines.extend([
        "    dw 0, 0",
        f"{symbol}_midi_event_count equ {len(events)}",
        "",
    ])
    return "\n".join(lines)
