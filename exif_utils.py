import struct

from .constants import PLUGIN_TITLE


def _exif_ascii(value):
    return str(value or "").encode("ascii", "replace") + b"\x00"


def _decimal_to_dms_rationals(value):
    value = abs(float(value))
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return [
        (degrees, 1),
        (minutes, 1),
        (round(seconds * 1000000), 1000000),
    ]


def _minimal_exif_payload(tags, gps=None):
    entries = []
    data = bytearray()

    def add_ascii(tag, value):
        value_bytes = _exif_ascii(value)
        entries.append((tag, 2, len(value_bytes), value_bytes))

    def add_long(tag, value):
        entries.append((tag, 4, 1, struct.pack("<I", value)))

    add_ascii(0x010E, tags.get("description", ""))  # ImageDescription
    add_ascii(0x0131, tags.get("software", f"{PLUGIN_TITLE} QGIS plugin"))  # Software
    add_ascii(0x0132, tags.get("datetime", ""))  # DateTime
    if gps:
        add_long(0x8825, 0)  # GPSInfoIFDPointer; offset is filled after IFD0 sizing.
    entries.sort(key=lambda item: item[0])

    ifd_offset = 8
    data_offset = ifd_offset + 2 + len(entries) * 12 + 4
    gps_entries = _gps_ifd_entries(gps) if gps else []
    if gps_entries:
        data_offset += 2 + len(gps_entries) * 12 + 4
    ifd = bytearray()
    ifd.extend(struct.pack("<H", len(entries)))

    for tag, field_type, count, value_bytes in entries:
        if tag == 0x8825:
            gps_ifd_offset = ifd_offset + 2 + len(entries) * 12 + 4
            packed_value = struct.pack("<I", gps_ifd_offset)
            ifd.extend(struct.pack("<HHI", tag, field_type, count))
            ifd.extend(packed_value)
            continue

        if len(value_bytes) <= 4:
            packed_value = value_bytes.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value_bytes)
        ifd.extend(struct.pack("<HHI", tag, field_type, count))
        ifd.extend(packed_value)

    ifd.extend(struct.pack("<I", 0))
    gps_ifd = _pack_gps_ifd(gps_entries, data_offset, data) if gps_entries else b""
    tiff = b"II*\x00" + struct.pack("<I", ifd_offset) + bytes(ifd) + gps_ifd + bytes(data)
    return b"Exif\x00\x00" + tiff


def _gps_ifd_entries(gps):
    lat = float(gps["lat"])
    lon = float(gps["lon"])
    return [
        (0x0001, 2, 2, _exif_ascii("N" if lat >= 0 else "S")),
        (0x0002, 5, 3, _decimal_to_dms_rationals(lat)),
        (0x0003, 2, 2, _exif_ascii("E" if lon >= 0 else "W")),
        (0x0004, 5, 3, _decimal_to_dms_rationals(lon)),
        (0x0012, 2, 7, _exif_ascii("WGS-84")),
    ]


def _pack_gps_ifd(entries, data_offset, data):
    gps_ifd = bytearray()
    gps_ifd.extend(struct.pack("<H", len(entries)))

    for tag, field_type, count, value in entries:
        if field_type == 5:
            packed_value = struct.pack("<I", data_offset + len(data))
            for numerator, denominator in value:
                data.extend(struct.pack("<II", numerator, denominator))
        elif len(value) <= 4:
            packed_value = value.ljust(4, b"\x00")
        else:
            packed_value = struct.pack("<I", data_offset + len(data))
            data.extend(value)

        gps_ifd.extend(struct.pack("<HHI", tag, field_type, count))
        gps_ifd.extend(packed_value)

    gps_ifd.extend(struct.pack("<I", 0))
    return bytes(gps_ifd)


def _insert_exif(jpeg_bytes, exif_payload):
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        return jpeg_bytes
    segment_length = len(exif_payload) + 2
    if segment_length > 65535:
        return jpeg_bytes
    return (
        jpeg_bytes[:2]
        + b"\xff\xe1"
        + struct.pack(">H", segment_length)
        + exif_payload
        + jpeg_bytes[2:]
    )
