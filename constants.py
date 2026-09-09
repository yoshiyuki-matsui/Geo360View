"""プラグイン全体で使う固定値。"""

PLUGIN_TITLE = "Geo360View"

LATITUDE_FIELDS = ("lat", "latitude", "gps_lat", "y", "緯度")
LONGITUDE_FIELDS = ("lon", "lng", "longitude", "gps_lon", "gps_lng", "x", "経度")
REFERENCE_ID_FIELDS = (
    "reference_id", "ref_id", "id", "asset_id", "facility_id",
    "pole_id", "参照点ID", "施設ID", "電柱番号",
)
REFERENCE_LABEL_FIELDS = (
    "reference_label", "label", "reference_name", "name",
    "kp", "kilopost", "kilo_post", "reference", "ref", "point",
    "facility_name", "bridge_name", "pole", "bridge",
    "測点", "キロポスト", "参照点", "施設名", "高架橋名",
)
KP_FIELDS = (
    "kp", "kilopost", "kilo_post",
    "reference", "reference_id", "ref", "ref_id",
    "name", "id", "point", "asset_id", "facility_id",
    "pole", "pole_id", "bridge", "bridge_name",
    "測点", "キロポスト", "参照点", "参照点ID", "施設ID", "施設名", "電柱番号", "高架橋名",
)

FRAMES_CSV_SUFFIX = "_frames.csv"
MATCHED_FRAMES_CSV_SUFFIX = "_matched_frames.csv"
NAVIGATION_JSON_SUFFIX = "_navigation.json"

FRAME_IMAGE_FOLDER_SIZE = 1000
