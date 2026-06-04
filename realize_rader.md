
---

# 📘 **QGIS レーダ機能：実寸仕様（最終版）**

## 1. **レーダは “絶対距離” と “動的距離” を分離して扱う**

### ● **絶対距離（固定）**
- GUI でユーザが指定する「範囲円（例：5m）」は  
  **地図上に描く固定距離の同心円** として扱う。
- 推奨：**5m と 10m の二重同心円**  
  → ユーザはこの 2 本を基準に距離を外挿できる。

### ● **動的距離（可変）**
- レーダ扇形の奥行きは **直近の移動量（実寸）** を使う。
- 進行方向の推定と同じ区間（±10フレーム）を使う。

---

# 2. **進行方向（heading）の算出方法**

### ● direction が GPX に無い場合が多いため、以下の方法で推定する：

1. 対象フレーム index を i とする  
2. `i - 10` と `i + 10` のフレームの lat/lon を取得  
3. それぞれを **平面直角座標（または canvas CRS）に変換**  
4. ベクトルを計算  
   \[
   dx = x_2 - x_1,\quad dy = y_2 - y_1
   \]
5. 北=0°、時計回りの角度として  
   \[
   heading = (\text{atan2}(dx, dy) \cdot 180/\pi + 360) \% 360
   \]

### ● 特徴
- ±10フレーム ≒ 0.6秒  
- 時速40km/h ≒ 11.1m/s → 約7mの区間  
- ノイズが平均化され、安定した heading が得られる

---

# 3. **レーダ扇形の奥行き（距離）の算出方法**

### ● ±10フレームの移動距離を実寸で求める：

\[
distance = \sqrt{dx^2 + dy^2}
\]

### ● レーダの奥行きはこの距離をベースにする：

```python
radius_m = distance_m * radar_scale  # radar_scale は UI で調整可能
```

### ● 特徴
- 速度が速い → レーダが伸びる  
- 停止中 → レーダが短くなる  
- 実世界の挙動と一致する“生きたレーダ”になる

---

# 4. **レーダの向き（viewerBearing）の決定**

### ● viewerBearing = 進行方向 + yaw（相対角度）

1. yaw はビューアの yaw_to_camera_heading を使用  
2. yaw を GIS の方位系に変換  
   \[
   gis\_yaw = (90 - yaw) \% 360
   \]
3. 最終的な視線方向  
   \[
   bearing = (heading + gis\_yaw) \% 360
   \]

---

# 5. **同心円（絶対距離）の描画**

### ● 5m 円
```python
circle_5m = [destinationPoint(lat, lon, angle, 5.0) for angle in range(0, 361, 8)]
```

### ● 10m 円
```python
circle_10m = [destinationPoint(lat, lon, angle, 10.0) for angle in range(0, 361, 8)]
```

### ● 特徴
- 地図の縮尺と常に一致  
- レーダの距離感を直感的に把握できる  
- 5m と 10m の 2 本だけで十分

---

# 6. **レーダ扇形の描画**

- 扇形の中心角：  
  \[
  bearing \pm \frac{FOV}{2}
  \]
- 扇形の奥行き：  
  **radius_m（動的距離）**

---

# 7. **この仕様のメリット**

- heading が常に安定（GPX の direction 欠損に強い）
- レーダの奥行きが実世界の速度と同期
- 同心円で距離感が明確
- FOV は扇形の広がりだけに使うため役割が明確
- UI と数学モデルが完全に一致する

---

# 📦 **まとめ**

> この仕様に基づいて、QGIS プラグインのレーダ機能を修正してください。  
> 主な変更点は以下の通りです：
>
> 1. heading は GPX の direction ではなく、±10フレームの位置から推定する  
> 2. レーダ扇形の奥行きは ±10フレームの移動距離（実寸）を使う  
> 3. GUI の範囲円（5m・10m）は絶対距離の同心円として描画する  
> 4. viewerBearing = heading + yaw（yaw は GIS 方位系に変換）  
> 5. FOV は扇形の広がりにのみ使用する  
>
> これにより、レーダが実世界の距離と速度に同期し、距離感が明確になります。


---

# 📘 **レーダ heading / 距離のフォールバック仕様（最終版）**

## 🎯 フォールバックが必要になるケースは 2 つ

1. **GNSS の軌跡が暴れている（方向が不連続）**  
2. **移動量が規定以下（ほぼ停止 or ノイズ）**

この 2 つを検出して、  
**heading と radius を前回値で維持**するのが最も自然で破綻しない。

---

# 1. **GNSS 軌跡が暴れている場合の検出**

### ✔ 条件：前後 ±10 フレームの heading が急変している

```python
abs(heading_now - heading_prev) > heading_jump_threshold
```

推奨値：

- `heading_jump_threshold = 45°`  
  → 0.6 秒で 45° 以上の方向転換は通常ありえない  
  → GNSS の暴れと判断できる

### ✔ 対応：前回の heading を維持

```python
if heading_is_unstable:
    heading = heading_prev
```

---

# 2. **移動量が規定以下の場合の検出**

### ✔ 条件：±10 フレームの移動距離が小さすぎる

```python
distance_m < min_distance_threshold
```

推奨値：

- `min_distance_threshold = 0.5m`  
  → 0.6 秒で 0.5m 未満は「停止 or ノイズ」

### ✔ 対応：  
- heading → **前回値を維持**  
- radius → **0 にせず、最小値を設定**

```python
radius_m = min_radius  # 例: 1.0m
```

理由：  
完全ゼロにするとレーダが消えて UI が不安定に見えるため。

---

# 3. **フォールバックの最終ロジック**

```python
heading = computed_heading
radius_m = computed_distance

if heading_is_unstable or distance_is_too_small:
    heading = heading_prev
    radius_m = max(radius_m, min_radius)
```

---

# 4. **これで何が実現するか**

- GNSS が暴れてもレーダが飛び跳ねない  
- 停止中でもレーダが自然に見える  
- heading が常に滑らかで安定  
- 実寸レーダの「速度連動性」は維持  
- 同心円（5m/10m）との整合性も崩れない

---

# 📦 ** 追加：フォールバック仕様**

> レーダ heading / 距離の計算に以下のフォールバック処理を追加してください：
>
> **1. heading の急変検出**  
> - ±10 フレームで算出した heading が前回値から 45° 以上変化した場合  
> → GNSS の暴れと判断し、heading は前回値を維持する
>
> **2. 移動量が小さすぎる場合**  
> - ±10 フレームの移動距離が 0.5m 未満の場合  
> → 停止 or ノイズと判断  
> → heading は前回値を維持  
> → radius は最小値（例: 1m）を設定
>
> **3. 通常時**  
> - heading = ±10 フレームのベクトル方向  
> - radius = ±10 フレームの移動距離 × スケール
>
> この処理により、GNSS の乱れや停止時でもレーダが安定し、実寸距離ベースの挙動を維持できます。

---

