from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsSpatialIndex,
)

from .common import _find_field, _open_csv_dict_reader, _parse_float
from .constants import KP_FIELDS, LATITUDE_FIELDS, LONGITUDE_FIELDS


def _read_kp_csv(path):
    handle, reader = _open_csv_dict_reader(path)
    with handle:
        fieldnames = reader.fieldnames or []
        lat_field = _find_field(fieldnames, LATITUDE_FIELDS)
        lon_field = _find_field(fieldnames, LONGITUDE_FIELDS)
        kp_field = _find_field(fieldnames, KP_FIELDS)

        if not lat_field or not lon_field:
            raise ValueError(
                "KP CSV must contain latitude/longitude columns "
                f"(fields: {', '.join(fieldnames)})"
            )

        rows = []
        for index, row in enumerate(reader, start=1):
            lat = _parse_float(row.get(lat_field))
            lon = _parse_float(row.get(lon_field))
            if lat is None or lon is None:
                continue

            kp_value = row.get(kp_field) if kp_field else None
            kp_value = str(kp_value).strip() if kp_value not in (None, "") else str(index)
            rows.append({
                "kp": kp_value,
                "lat": lat,
                "lon": lon,
                "point": QgsPointXY(lon, lat),
            })

    if not rows:
        raise ValueError("KP CSV did not contain valid latitude/longitude rows.")

    return rows


def build_kp_matches(rows, kp_file, tolerance_m):
    matches = [None] * len(rows)
    if not kp_file:
        return matches, 0

    kp_rows = _read_kp_csv(kp_file)
    index = QgsSpatialIndex()
    kp_by_id = {}
    for kp_id, kp in enumerate(kp_rows):
        feat = QgsFeature()
        feat.setId(kp_id)
        feat.setGeometry(QgsGeometry.fromPointXY(kp["point"]))
        index.addFeature(feat)
        kp_by_id[kp_id] = kp

    distance = QgsDistanceArea()
    distance.setSourceCrs(
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext()
    )
    distance.setEllipsoid("WGS84")

    match_count = 0
    for row_index, (frame_num, source_frame, time, lat, lon) in enumerate(rows):
        original_point = QgsPointXY(lon, lat)
        nearest_ids = index.nearestNeighbor(original_point, 1)
        if not nearest_ids:
            continue

        kp = kp_by_id.get(nearest_ids[0])
        if kp is None:
            continue

        distance_m = distance.measureLine(original_point, kp["point"])
        if distance_m > tolerance_m:
            continue

        matches[row_index] = {
            "kp": kp["kp"],
            "distance_m": distance_m,
            "lat": kp["lat"],
            "lon": kp["lon"],
        }
        match_count += 1

    return matches, match_count
