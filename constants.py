"""プラグイン全体で使う固定値。"""

PLUGIN_TITLE = "Geo360View"

LATITUDE_FIELDS = ("lat", "latitude", "gps_lat", "y", "緯度")
LONGITUDE_FIELDS = ("lon", "lng", "longitude", "gps_lon", "gps_lng", "x", "経度")
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
