# 動画yaw補正とGeo360View表示整合

更新日: 2026-06-28

この文書は、CubeMap生成時に360動画の正面yawを補正したPOIを
Geo360Viewで表示する際の注意点をまとめます。

POI生成側を含む全体仕様は、`tenkaku_ninja_poi/docs/yaw_front_offset_alignment.md`
を正とします。この文書はQGISプラグイン側の挙動に絞ります。

## 使い分ける角度

| 値 | 用途 |
| --- | --- |
| `target_yaw` | 元MP4の360ビューア上にマーカーを出す角度 |
| `bearing_deg` | 地図上の絶対方位。レーダ、方位線、POI位置に使う |
| `map_bearing_deg` | viewer session内で渡す `bearing_deg` 相当値 |
| `map_target_yaw_to_camera_heading` | 地図方位計算に使ったCubeMap基準yaw |
| `viewer_front_offset_deg` | sessionに保持する、進行方向から元MP4正面までの補正角 |

Detection Checkでは、GPKGの `bearing_deg` と `target_yaw` から
`viewer_front_offset_deg` を復元します。

```text
viewer_front_offset_deg = bearing_deg - trajectory_heading_deg - target_yaw
```

この値により、元MP4の360ビューア視点、QGIS地図上レーダ、Markingの投影が
同じ動画正面補正を共有します。

## レーダ表示

レーダ中心方位は次の式で求めます。

```text
viewer_bearing = trajectory_heading_deg
               + viewer_front_offset_deg
               + yaw_to_camera_heading
```

`viewer_front_offset_deg` がsessionに無い場合だけ、UIの `Offset` をフォールバックとして使います。

Detection POIのターゲットがある場合、レーダはPOIの `map_bearing_deg` を優先して地図上の
絶対方位を復元します。これにより、ビューア用 `target_yaw` がCubeMap補正で変換されていても、
地図上レーダはずれません。

## Marking

手動でダブルクリックしたMarkingは、クリック時点では地図方位を持ちません。
QGIS側がsessionの `viewer_front_offset_deg` を使って `bearing_deg` を計算し、
`Geo360 Markings` へ保存します。

```text
marking_bearing_deg = trajectory_heading_deg
                   + viewer_front_offset_deg
                   + target_yaw_to_camera_heading
```

注意:

- Detection Checkで補正量が復元された後にMarkingすると安全です。
- 補正前に保存済みのMarking geometryは自動更新されません。
- yaw補正を変えた場合、既存Markingは削除して新しくMarkingします。
- `viewer_front_offset_deg` は同一videoのsessionでのみ継承します。別動画へ持ち越しません。

## 症状と原因

| 症状 | 主な原因 |
| --- | --- |
| Detection POIは合うがMarkingがずれる | `viewer_front_offset_deg` がsessionに無い、または古い |
| 360ビューア視点は合うがレーダがずれる | レーダが `bearing_deg` でなく `target_yaw` を使っている |
| QGIS再起動後も直らない | 360 viewerサーバまたはブラウザJSが古いまま残っている |
| 保存済みMarkingがずれ続ける | geometry自体が補正前の方位で保存済み |

## 確認手順

1. Detection Checkで既知地物へ移動する。
2. 360ビューア上の対象マーカーが正しい位置に出ることを確認する。
3. QGIS地図上のレーダ扇形が同じ方向を向くことを確認する。
4. 新しくMarkingをダブルクリックして、地図上の点が期待方向に落ちることを確認する。
5. 保存済みMarkingを見直す場合は、補正後に新規作成した点だけを評価する。
