<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.40.12-Bratislava" styleCategories="Symbology">
  <renderer-v2 symbollevels="0" forceraster="0" attr="semantic_class" referencescale="-1" type="categorizedSymbol" enableorderby="0">
    <categories>
      <category value="01_UnevenRail" render="true" uuid="{ce540c12-d770-43e0-ae32-b9ee535df96e}" label="01_レール偏摩耗" type="string" symbol="0"/>
      <category value="02_JointDip" render="true" uuid="{9ece82f6-6477-4d91-b5ba-fbffe0d02f7d}" label="02_継ぎ目落ち（遊間）" type="string" symbol="1"/>
      <category value="03_GluedInsulatedRail" render="true" uuid="{1126b9fc-01d9-4f17-89ab-b4073f2e13f7}" label="03_接着絶縁レール" type="string" symbol="2"/>
      <category value="04_RailReinforcementPlate" render="true" uuid="{a1acaf0b-eccc-41af-b075-e352a5cd6078}" label="04_レール補強板" type="string" symbol="3"/>
      <category value="05_unused" render="true" uuid="{59fe0feb-c8db-4472-843d-4a69b17726db}" label="05_unused" type="string" symbol="4"/>
      <category value="06_Grass" render="true" uuid="{6f3ae95e-5ea3-48a0-83aa-1960d8c7166c}" label="06_草繁茂" type="string" symbol="5"/>
      <category value="11_SleeperDamage" render="true" uuid="{a4dc96ed-27e9-435b-9478-f38330c2c963}" label="11_枕木損傷" type="string" symbol="6"/>
      <category value="12_Efflorescence" render="true" uuid="{6a3ed746-f18c-46da-a32b-79af7bb56d63}" label="12_エフロ" type="string" symbol="7"/>
      <category value="13_JointLoss" render="true" uuid="{0832c8af-8026-4ff8-8545-72b0def34a35}" label="13_締結器（欠損、故障）" type="string" symbol="8"/>
      <category value="14_DetachedPad" render="true" uuid="{568bd3e3-3a01-4789-87e9-d20b93b261e3}" label="14_パッド外れ" type="string" symbol="9"/>
      <category value="15_RailBond" render="true" uuid="{e7ae36a5-a1ef-4d9f-9a15-83233c3f9324}" label="15_レールボンド" type="string" symbol="10"/>
      <category value="21_ConcreteDamage" render="true" uuid="{4498aa21-f30f-4528-91fe-9101c9a285ec}" label="21_コンクリート損傷" type="string" symbol="11"/>
      <category value="22_CrossingPanel" render="true" uuid="{034fa546-3675-40c5-93e4-4f6433477fb5}" label="22_踏切保護版破損" type="string" symbol="12"/>
      <category value="23_Packing" render="true" uuid="{c56a7b63-52b4-4a88-a50d-8f67d7506a71}" label="23_パッキン損傷" type="string" symbol="13"/>
      <category value="24_WaterPooling" render="true" uuid="{6ba52eb4-9ad6-42cc-b3b2-0c127c655369}" label="24_滞水" type="string" symbol="14"/>
      <category value="25_MudPumping" render="true" uuid="{9ed070c0-402d-4166-8a7f-4ebe03352724}" label="25_噴泥" type="string" symbol="15"/>
      <category value="26_Ballast" render="true" uuid="{e9cd0f84-a932-4326-9a22-72ab261d9ef1}" label="26_バラスト" type="string" symbol="16"/>
    </categories>
    <symbols>
      <symbol name="0" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{a5416b07-6694-4b0f-adf4-4f40233805c4}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="90" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="255,0,0,255,rgb:1,0,0,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="line" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="194,201,209,255,hsv:0.58938888888888885,0.0690928511482414,0.81930266269932095,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer pass="0" enabled="1" locked="0" id="{95c91a89-b7dc-4be3-b1e2-4dab9a242720}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="255,0,0,255,rgb:1,0,0,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="line" type="QString"/>
            <Option name="offset" value="0.79999999999999982,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="194,201,209,255,hsv:0.58938888888888885,0.0690928511482414,0.81930266269932095,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="2" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="1" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{58499615-6f9c-4d48-bdfa-7597b9811ba8}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="90" type="QString"/>
            <Option name="color" value="240,2,2,255,hsv:0,0.99372854200045779,0.9402609292744335,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iZW50cmFuY2UtYWx0MSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB3aWR0aD0iMTUiIGhlaWdodD0iMTUiIHZpZXdCb3g9IjAgMCAxNSAxNSI+CiAgPHBhdGggZmlsbD0icGFyYW0oZmlsbCkgIzAwMCIgZmlsbC1vcGFjaXR5PSJwYXJhbShmaWxsLW9wYWNpdHkpIiBzdHJva2U9InBhcmFtKG91dGxpbmUpICNmZmYiIHN0cm9rZS13aWR0aD0icGFyYW0ob3V0bGluZS13aWR0aCkgMCIgc3Ryb2tlLW9wYWNpdHk9InBhcmFtKG91dGxpbmUtb3BhY2l0eSkiIGQ9Ik02LjU1NCw5LjYzOWEuNS41LDAsMCwwLC43MDcuNzA3TDkuOTI4LDcuNjY5YS4yNS4yNSwwLDAsMCwwLS4zNTRoMEw3LjI2MSw0LjYzOWEuNS41LDAsMCwwLS43MDcuNzA3TDguMiw3SDEuNWEuNS41LDAsMCwwLDAsMUg4LjJaTTEyLDFINS41YS41LjUsMCwwLDAsMCwxaDZhLjUuNSwwLDAsMSwuNS41djEwYS41LjUsMCwwLDEtLjUuNUg1LjI1YS41LjUsMCwwLDAsMCwxSDEyYTEsMSwwLDAsMCwxLTFWMkExLDEsMCwwLDAsMTIsMVoiLz4KPC9zdmc+" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="10" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{b2dbbdc6-b5f9-40e4-97b7-e1bf88122fae}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="152,19,19,255,hsv:0,0.87640192263675898,0.59713130388342106,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iY2FzdGxlLUpQIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNSIgaGVpZ2h0PSIxNSIgdmlld0JveD0iMCAwIDE1IDE1Ij4KICA8cGF0aCBmaWxsPSJwYXJhbShmaWxsKSAjMDAwIiBmaWxsLW9wYWNpdHk9InBhcmFtKGZpbGwtb3BhY2l0eSkiIHN0cm9rZT0icGFyYW0ob3V0bGluZSkgI2ZmZiIgc3Ryb2tlLXdpZHRoPSJwYXJhbShvdXRsaW5lLXdpZHRoKSAwIiBzdHJva2Utb3BhY2l0eT0icGFyYW0ob3V0bGluZS1vcGFjaXR5KSIgZD0iTTEyLjUsMTIuNzVhMSwxLDAsMCwxLTEtLjk5OTVWNy4yNUgxMGExLDEsMCwwLDEtMS0xdi0ySDZ2MmExLDEsMCwwLDEtMSwxSDMuNXY0LjVhMSwxLDAsMCwxLTIsMFY2LjI1YTEsMSwwLDAsMSwxLTFINHYtMmExLDEsMCwwLDEsMS0xaDVhMSwxLDAsMCwxLDEsMXYyaDEuNWExLDEsMCwwLDEsMSwxdjUuNWExLDEsMCwwLDEtLjk5OTUsMVoiLz4KPC9zdmc+" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="11" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{d58e30aa-a8b6-47ee-9de9-692039c69526}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="180" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="255,0,0,255,rgb:1,0,0,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="arrowhead" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="228,11,11,255,hsv:0,0.95367360952162972,0.89282063019760438,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0.3" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="2.625" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
        <layer pass="0" enabled="1" locked="0" id="{7653a92a-d60b-4c0d-ab61-a88e7f234d5d}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="90" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="255,0,0,255,rgb:1,0,0,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="line" type="QString"/>
            <Option name="offset" value="0.00000000000000007,1.99999999999999867" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="228,11,11,255,hsv:0,0.95367360952162972,0.89282063019760438,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0.3" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="12" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{2c411c94-4e64-4d04-aaec-1e06070a9abc}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="174,91,24,255,hsv:0.07455555555555556,0.86283665217059591,0.68235294117647061,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJidWlsZGluZyIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB3aWR0aD0iMTUiIGhlaWdodD0iMTUiIHZpZXdCb3g9IjAgMCAxNSAxNSI+CiAgPHBhdGggZmlsbD0icGFyYW0oZmlsbCkgIzAwMCIgZmlsbC1vcGFjaXR5PSJwYXJhbShmaWxsLW9wYWNpdHkpIiBzdHJva2U9InBhcmFtKG91dGxpbmUpICNmZmYiIHN0cm9rZS13aWR0aD0icGFyYW0ob3V0bGluZS13aWR0aCkgMCIgc3Ryb2tlLW9wYWNpdHk9InBhcmFtKG91dGxpbmUtb3BhY2l0eSkiIGQ9Ik0zLDJ2MTFoNXYtM2gzdjNoMVYySDN6IE03LDEySDR2LTJoM1YxMnogTTcsOUg0VjdoM1Y5eiBNNyw2SDRWNGgzVjZ6IE0xMSw5SDhWN2gzVjl6IE0xMSw2SDhWNGgzVjZ6Ii8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="7" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="13" force_rhr="0" frame_rate="10" alpha="0.9" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{5ffd92e6-8161-4fb1-8c60-c8d1e0a04c1a}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="226,24,24,255,hsv:0,0.89333943694209206,0.88738841840238036,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJibG9vZC1iYW5rIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNSIgaGVpZ2h0PSIxNSIgdmlld0JveD0iMCAwIDE1IDE1Ij4KICA8cGF0aCBmaWxsPSJwYXJhbShmaWxsKSAjMDAwIiBmaWxsLW9wYWNpdHk9InBhcmFtKGZpbGwtb3BhY2l0eSkiIHN0cm9rZT0icGFyYW0ob3V0bGluZSkgI2ZmZiIgc3Ryb2tlLXdpZHRoPSJwYXJhbShvdXRsaW5lLXdpZHRoKSAwIiBzdHJva2Utb3BhY2l0eT0icGFyYW0ob3V0bGluZS1vcGFjaXR5KSIgZD0iTTExLjIsNy4xTDExLjIsNy4xTDcuNSwyTDMuOCw3LjFoMEMzLjMsNy44LDMsOC43LDMsOS42QzMsMTIsNSwxNCw3LjUsMTRjMCwwLDAsMCwwLDBDMTAsMTQsMTIsMTIsMTIsOS42YzAsMCwwLDAsMCwwJiN4QTsmI3g5O0MxMiw4LjcsMTEuNyw3LjgsMTEuMiw3LjF6IE0xMCwxMEg4djJIN3YtMkg1VjloMlY3aDF2MmgyVjEweiIvPgo8L3N2Zz4=" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4.8" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="14" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{ea6504b6-2dda-4fe8-96d9-b4ac54e9bbe9}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="14,46,242,255,hsv:0.6433888888888889,0.94297703517204545,0.94789044022278168,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJ3YXRlciIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB3aWR0aD0iMTUiIGhlaWdodD0iMTUiIHZpZXdCb3g9IjAgMCAxNSAxNSI+CiAgPHBhdGggZmlsbD0icGFyYW0oZmlsbCkgIzAwMCIgZmlsbC1vcGFjaXR5PSJwYXJhbShmaWxsLW9wYWNpdHkpIiBzdHJva2U9InBhcmFtKG91dGxpbmUpICNmZmYiIHN0cm9rZS13aWR0aD0icGFyYW0ob3V0bGluZS13aWR0aCkgMCIgc3Ryb2tlLW9wYWNpdHk9InBhcmFtKG91dGxpbmUtb3BhY2l0eSkiIGQ9Ik03LjQ5LDE1QzQuNTI4OCwxNC44MjcsMi4xNjc2LDEyLjQ2MTUsMiw5LjVDMiw2LjYsNi4yNSwxLjY2LDcuNDksMGMxLjI0LDEuNjYsNSw2LjU5LDUsOS40OVMxMC4xNywxNSw3LjQ5LDE1eiIvPgo8L3N2Zz4=" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="15" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{b504d93a-c8c0-4d9e-b093-28f41b46bd53}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="0,0,0,255,rgb:0,0,0,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIGlkPSJlbGV2YXRvciIgd2lkdGg9IjE1IiBoZWlnaHQ9IjE1IiB2aWV3Qm94PSIwIDAgMTUgMTUiPgogIDxwYXRoIGZpbGw9InBhcmFtKGZpbGwpICMwMDAiIGZpbGwtb3BhY2l0eT0icGFyYW0oZmlsbC1vcGFjaXR5KSIgc3Ryb2tlPSJwYXJhbShvdXRsaW5lKSAjZmZmIiBzdHJva2Utd2lkdGg9InBhcmFtKG91dGxpbmUtd2lkdGgpIDAiIHN0cm9rZS1vcGFjaXR5PSJwYXJhbShvdXRsaW5lLW9wYWNpdHkpIiBkPSJNMTEsMUg0QTEsMSwwLDAsMCwzLDJWMTNhMSwxLDAsMCwwLDEsMWg3YTEsMSwwLDAsMCwxLTFWMkExLDEsMCwwLDAsMTEsMVpNNy41LDEyLjVsLTItNGg0Wm0tMi02LDItNCwyLDRaIi8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4.8" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="16" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{48c79508-fcc1-43c9-a232-49299af17015}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="194,201,209,255,hsv:0.58938888888888885,0.0690928511482414,0.81930266269932095,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0ibGFuZG1hcmstSlAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgd2lkdGg9IjE1IiBoZWlnaHQ9IjE1IiB2aWV3Qm94PSIwIDAgMTUgMTUiPgogIDxwYXRoIGZpbGw9InBhcmFtKGZpbGwpICMwMDAiIGZpbGwtb3BhY2l0eT0icGFyYW0oZmlsbC1vcGFjaXR5KSIgc3Ryb2tlPSJwYXJhbShvdXRsaW5lKSAjZmZmIiBzdHJva2Utd2lkdGg9InBhcmFtKG91dGxpbmUtd2lkdGgpIDAiIHN0cm9rZS1vcGFjaXR5PSJwYXJhbShvdXRsaW5lLW9wYWNpdHkpIiBkPSJNOS41LDQuNWEyLDIsMCwxLDEtMi0yQTIsMiwwLDAsMSw5LjUsNC41Wm0tNiw0YTIsMiwwLDEsMCwyLDJBMiwyLDAsMCwwLDMuNSw4LjVabTgsMGEyLDIsMCwxLDAsMiwyQTIsMiwwLDAsMCwxMS41LDguNVoiLz4KPC9zdmc+" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="5" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="2" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{3eaf632f-0cd3-4be2-926c-ae6a91802d4f}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="0,0,0,255,rgb:0,0,0,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJzaGVsdGVyIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNSIgaGVpZ2h0PSIxNSIgdmlld0JveD0iMCAwIDE1IDE1Ij4KICA8cGF0aCBmaWxsPSJwYXJhbShmaWxsKSAjMDAwIiBmaWxsLW9wYWNpdHk9InBhcmFtKGZpbGwtb3BhY2l0eSkiIHN0cm9rZT0icGFyYW0ob3V0bGluZSkgI2ZmZiIgc3Ryb2tlLXdpZHRoPSJwYXJhbShvdXRsaW5lLXdpZHRoKSAwIiBzdHJva2Utb3BhY2l0eT0icGFyYW0ob3V0bGluZS1vcGFjaXR5KSIgZD0iTTQsN3Y1aDkuNXYySDJsMCwwbDAsMFY3Ljc4TDEsOC4xNlY2bDEzLTV2Mi4xNEw0LDd6Ii8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="3" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{1766e53f-9417-4624-a36c-8e505d19be83}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="0,0,0,255,rgb:0,0,0,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJidWlsZGluZy1hbHQxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNSIgaGVpZ2h0PSIxNSIgdmlld0JveD0iMCAwIDE1IDE1Ij4KICA8cGF0aCBmaWxsPSJwYXJhbShmaWxsKSAjMDAwIiBmaWxsLW9wYWNpdHk9InBhcmFtKGZpbGwtb3BhY2l0eSkiIHN0cm9rZT0icGFyYW0ob3V0bGluZSkgI2ZmZiIgc3Ryb2tlLXdpZHRoPSJwYXJhbShvdXRsaW5lLXdpZHRoKSAwIiBzdHJva2Utb3BhY2l0eT0icGFyYW0ob3V0bGluZS1vcGFjaXR5KSIgZD0iTTExLDEzLjV2LTlDMTEsNC4yLDEwLjgsNCwxMC41LDRIOVYxTDUsMi4xdjExLjRIMlYxNGgxMXYtMC41SDExeiBNNywxMy41VjNoMXYxMC41SDd6Ii8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="4" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{68d3ec84-f698-441d-9bca-ca8e7a2e0cd3}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="65,220,220,255,hsv:0.5,0.70588235294117652,0.86274509803921573,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="circle" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="35,35,35,255,rgb:0.13725490196078433,0.13725490196078433,0.13725490196078433,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="2" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="5" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{c000da69-4260-4524-aabf-759855f5c462}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="86,242,13,255,hsv:0.28055555555555556,0.94634927901121535,0.95071335927367051,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJ3ZXRsYW5kIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNSIgaGVpZ2h0PSIxNSIgdmlld0JveD0iMCAwIDE1IDE1Ij4KICA8cGF0aCBmaWxsPSJwYXJhbShmaWxsKSAjMDAwIiBmaWxsLW9wYWNpdHk9InBhcmFtKGZpbGwtb3BhY2l0eSkiIHN0cm9rZT0icGFyYW0ob3V0bGluZSkgI2ZmZiIgc3Ryb2tlLXdpZHRoPSJwYXJhbShvdXRsaW5lLXdpZHRoKSAwIiBzdHJva2Utb3BhY2l0eT0icGFyYW0ob3V0bGluZS1vcGFjaXR5KSIgZD0iTTEuNDgsNC41QzEuOTA1LDQuMTQ2NywyLjQ0ODMsMy45NjgsMyw0YzEuMjI3My0wLjA4NjksMi4zMTU0LDAuNzgzNiwyLjUsMmwwLjc4LDQuNjhjLTAuNjM5NC0wLjI4OTMtMS4zNzU5LTAuMjcwOS0yLDAuMDUmI3hBOyYjeDk7TDMuNDgsNkMzLjE4NzQsNS4xMzQ3LDIuMzkyNiw0LjUzODcsMS40OCw0LjV6IE03LjQ4LDExLjI0YzAuMzgxNi0wLjMwNzYsMC44MjUtMC41MjkzLDEuMy0wLjY1TDEwLDMmI3hBOyYjeDk7YzAuMjkyNi0wLjg2NTMsMS4wODc0LTEuNDYxMywyLTEuNWMtMC40MTk4LTAuMzQ4NS0wLjk1NS0wLjUyNjktMS41LTAuNUM5LjI3MjcsMC45MTMxLDguMTg0NiwxLjc4MzYsOCwzbC0xLjMsNy43OSYjeEE7JiN4OTtDNi45Nzg2LDEwLjkwNTIsNy4yNDA4LDExLjA1NjUsNy40OCwxMS4yNHogTTExLjgsMTAuNzRMMTEuOCwxMC43NGMwLjE1NjUtMC4xMjc3LDAuMzIzOC0wLjI0MTQsMC41LTAuMzRMMTMsNiYjeEE7JiN4OTtjMC4yOTI2LTAuODY1MywxLjA4NzQtMS40NjEzLDItMS41Yy0wLjQxOTgtMC4zNDg1LTAuOTU1LTAuNTI2OS0xLjUtMC41Yy0xLjIyNzMtMC4wODY5LTIuMzE1NCwwLjc4MzYtMi41LDJsLTAuNjcsNCYjeEE7JiN4OTtDMTAuODczMSwxMC4xMjMsMTEuMzc3OCwxMC4zNzcsMTEuOCwxMC43NHogTTE0LDEyTDE0LDEyYy0wLjQzNDYtMC4wMS0wLjg1NzksMC4xMzk0LTEuMTksMC40MmwtMC40NywwLjQxJiN4QTsmI3g5O2MtMC4yODQ3LDAuMjU0Ni0wLjcxNTMsMC4yNTQ2LTEsMGMtMC4xNS0wLjEyLTAuMjktMC4yNi0wLjQ0LTAuMzljLTAuNzA3Ni0wLjU5NjgtMS43NDI0LTAuNTk2OC0yLjQ1LDAmI3hBOyYjeDk7Yy0wLjE2LDAuMTMtMC4zMSwwLjI4LTAuNDcsMC40MWMtMC4yODQ3LDAuMjU0Ni0wLjcxNTMsMC4yNTQ2LTEsMGMtMC4xNi0wLjEzLTAuMzEtMC4yOC0wLjQ3LTAuNDEmI3hBOyYjeDk7Yy0wLjcwNTktMC41OTEyLTEuNzM0MS0wLjU5MTItMi40NCwwYy0wLjE1LDAuMTMtMC4yOSwwLjI3LTAuNDQsMC4zOWMtMC4wODkyLDAuMDcxNS0wLjE5MDksMC4xMjU4LTAuMywwLjE2JiN4QTsmI3g5O2MtMC4yOTIyLDAuMDY1Mi0wLjU5NjktMC4wMzAxLTAuOC0wLjI1Yy0wLjI0NzUtMC4yMTQtMC41MTE3LTAuNDA3OS0wLjc5LTAuNThDMS41MzM2LDEyLjA0MjEsMS4yOTc0LDExLjk4NjUsMS4wNiwxMkgxJiN4QTsmI3g5O2MtMC4yNzYxLDAtMC41LDAuMjIzOS0wLjUsMC41UzAuNzIzOSwxMywxLDEzbDAsMGMwLjI0NiwwLjAxNDUsMC40NzYyLDAuMTI2LDAuNjQsMC4zMUwyLDEzLjU3JiN4QTsmI3g5O2MwLjY3MTcsMC41NSwxLjYzMDgsMC41NzQ3LDIuMzMsMC4wNmMwLjE5LTAuMTQsMC4zNi0wLjMyLDAuNTUtMC40N2MwLjI4NDctMC4yNTQ2LDAuNzE1My0wLjI1NDYsMSwwbDAuMzksMC4zNSYjeEE7JiN4OTtjMC42OTM3LDAuNjE4OSwxLjczMjIsMC42NDg0LDIuNDYsMC4wN2MwLjE1LTAuMTEsMC4yNy0wLjI1LDAuNDItMC4zN2MwLjI5NzYtMC4zMDM4LDAuNzg1MS0wLjMwODcsMS4wODg5LTAuMDExMSYjeEE7JiN4OTtjMC4wMDM3LDAuMDAzNywwLjAwNzQsMC4wMDc0LDAuMDExMSwwLjAxMTFsMC4zOSwwLjM1YzAuNDg2NiwwLjQxMjQsMS4xNDg1LDAuNTUxNiwxLjc2LDAuMzdjMC4zODI1LTAuMTAzNiwwLjcyODYtMC4zMTEzLDEtMC42JiN4QTsmI3g5O2MwLjE1NDktMC4xNzcyLDAuMzY3NC0wLjI5NCwwLjYtMC4zM2wwLDBjMC4yNzYxLDAsMC41LTAuMjIzOSwwLjUtMC41UzE0LjI3NjEsMTIsMTQsMTJ6Ii8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="6" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{42f6121a-9ec8-46a5-b0bf-7658a6cd7c0c}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="247,171,9,255,hsv:0.11372222222222222,0.96278324559395745,0.96690318150606547,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIGlkPSJjYXV0aW9uIiB3aWR0aD0iMTUiIGhlaWdodD0iMTUiIHZpZXdCb3g9IjAgMCAxNSAxNSI+CiAgPHBhdGggZmlsbD0icGFyYW0oZmlsbCkgIzAwMCIgZmlsbC1vcGFjaXR5PSJwYXJhbShmaWxsLW9wYWNpdHkpIiBzdHJva2U9InBhcmFtKG91dGxpbmUpICNmZmYiIHN0cm9rZS13aWR0aD0icGFyYW0ob3V0bGluZS13aWR0aCkgMCIgc3Ryb2tlLW9wYWNpdHk9InBhcmFtKG91dGxpbmUtb3BhY2l0eSkiIGQ9Ik0xNC45LDEzLjRMOC41LDAuNmMtMC40LTAuOC0xLjUtMC44LTEuOSwwTDAuMSwxMy40Yy0wLjQsMC43LDAuMiwxLjYsMSwxLjZoMTIuOEMxNC43LDE1LDE1LjIsMTQuMSwxNC45LDEzLjR6IE03LjUsMTMmI3hBOyYjeDk7QzYuNywxMyw2LDEyLjMsNiwxMS41UzYuNiwxMCw3LjUsMTBTOSwxMC43LDksMTEuNUM5LDEyLjQsOC4zLDEzLDcuNSwxM3ogTTguNSw5aC0yTDYsNS41QzYsNS4yLDYuMiw1LDYuNSw1aDJDOC44LDUsOSw1LjIsOSw1LjUmI3hBOyYjeDk7TDguNSw5eiIvPgo8L3N2Zz4=" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="7" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{db36eaca-1b27-4889-ac7f-4b26f3b2a48d}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="0,0,0,0,rgb:0,0,0,0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="miter" type="QString"/>
            <Option name="name" value="asterisk_fill" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="0,0,0,255,rgb:0,0,0,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0.2" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="4" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="8" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{683b9f88-61ef-4253-8d64-4d448baf9c51}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="0,0,0,255,rgb:0,0,0,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB2ZXJzaW9uPSIxLjEiIGlkPSJkYW5nZXIiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgd2lkdGg9IjE1IiBoZWlnaHQ9IjE1IiB2aWV3Qm94PSIwIDAgMTUgMTUiPgogIDxwYXRoIGZpbGw9InBhcmFtKGZpbGwpICMwMDAiIGZpbGwtb3BhY2l0eT0icGFyYW0oZmlsbC1vcGFjaXR5KSIgc3Ryb2tlPSJwYXJhbShvdXRsaW5lKSAjZmZmIiBzdHJva2Utd2lkdGg9InBhcmFtKG91dGxpbmUtd2lkdGgpIDAiIHN0cm9rZS1vcGFjaXR5PSJwYXJhbShvdXRsaW5lLW9wYWNpdHkpIiBkPSJNMTMuOTQsMTQuNjhjLTAuMDc0OSwwLjE5NC0wLjI2MiwwLjMyMTUtMC40NywwLjMyYy0wLjA1OTUsMC4wMTA3LTAuMTIwNSwwLjAxMDctMC4xOCwwTDcuNSwxMi41NkwxLjcsMTUmI3hBOyYjeDk7Yy0wLjI1NzIsMC4xMDA1LTAuNTQ3Mi0wLjAyNjYtMC42NDc2LTAuMjgzOEMxLjA1MTYsMTQuNzE0MSwxLjA1MDgsMTQuNzEyMSwxLjA1LDE0LjcxYy0wLjEyOTEtMC4yNDQxLTAuMDM1OC0wLjU0NjcsMC4yMDg0LTAuNjc1NyYjeEE7JiN4OTtDMS4yODQ1LDE0LjAyMDUsMS4zMTE4LDE0LjAwOSwxLjM0LDE0bDQuODUtMmwtNC44NS0yQzEuMDc1OCw5LjkxOTcsMC45MjY3LDkuNjQwNCwxLjAwNyw5LjM3NjJzMC4zNTk2LTAuNDEzMywwLjYyMzgtMC4zMzMmI3hBOyYjeDk7QzEuNjU0NSw5LjA1MDQsMS42Nzc2LDkuMDU5NCwxLjcsOS4wN2w1LjgsMi40MWw1LjgtMi40MWMwLjI0OTQtMC4xMTg1LDAuNTQ3Ny0wLjAxMjQsMC42NjYyLDAuMjM3JiN4QTsmI3g5O2MwLjExODUsMC4yNDk0LDAuMDEyNCwwLjU0NzctMC4yMzcsMC42NjYyQzEzLjcwNjgsOS45ODM5LDEzLjY4MzcsOS45OTI4LDEzLjY2LDEwTDguOCwxMmw0Ljg1LDImI3hBOyYjeDk7YzAuMjYwNywwLjA5MSwwLjM5ODMsMC4zNzYxLDAuMzA3NCwwLjYzNjhDMTMuOTUyMywxNC42NTE1LDEzLjk0NjUsMTQuNjY1OSwxMy45NCwxNC42OHogTTEyLDQuMjN2MC40NSYjeEE7JiN4OTtjLTAuMDAyMSwwLjIxMjktMC4wNzIyLDAuNDE5Ni0wLjIsMC41OUMxMS4yNDE0LDUuODg4MywxMC42Mzk5LDYuNDY2NCwxMCw3djEuMTZjMC4wMDE1LDAuMjA4LTAuMTI2LDAuMzk1MS0wLjMyLDAuNDdMNy41Miw5LjUmI3hBOyYjeDk7SDcuNDVMNS4yOCw4LjYzQzUuMTAxNiw4LjU0MjgsNC45OTE3LDguMzU4NCw1LDguMTZWN0M0LjM1MjgsNi40Njc1LDMuNzQ0Niw1Ljg4OTMsMy4xOCw1LjI3QzMuMDU5Myw1LjA5NzIsMi45OTYzLDQuODkwNywzLDQuNjgmI3hBOyYjeDk7VjQuMjNDMy4xNjY5LDIuMDExNyw0Ljg5NzQsMC4yMzA3LDcuMTEsMGgwLjM2bDAsMGgwLjM5QzEwLjA4NjIsMC4yMTMxLDExLjgzNDgsMS45OTk3LDEyLDQuMjN6IE02LDRjMC0wLjU1MjMtMC40NDc3LTEtMS0xJiN4QTsmI3g5O1M0LDMuNDQ3Nyw0LDRzMC40NDc3LDEsMSwxUzYsNC41NTIzLDYsNHogTTcsN2MwLTAuMjc2MS0wLjIyMzktMC41LTAuNS0wLjVTNiw2LjcyMzksNiw3djAuNUM2LDcuNzc2MSw2LjIyMzksOCw2LjUsOCYjeEE7JiN4OTtTNyw3Ljc3NjEsNyw3LjVWN3ogTTksN2MwLTAuMjc2MS0wLjIyMzktMC41LTAuNS0wLjVTOCw2LjcyMzksOCw3djAuNUM4LDcuNzc2MSw4LjIyMzksOCw4LjUsOFM5LDcuNzc2MSw5LDcuNVY3eiBNMTEsNCYjeEE7JiN4OTtjMC0wLjU1MjMtMC40NDc3LTEtMS0xUzksMy40NDc3LDksNHMwLjQ0NzcsMSwxLDFTMTEsNC41NTIzLDExLDR6Ii8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="5" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol name="9" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{ebfb2042-f1e9-4e2e-9e10-17f127b3a70f}" class="SvgMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="color" value="212,23,23,255,hsv:0,0.89329365987640197,0.83331044480048833,1" type="QString"/>
            <Option name="fixedAspectRatio" value="0" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="name" value="base64:PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iMTUiIGhlaWdodD0iMTUiIHZpZXdCb3g9IjAgMCAxNSAxNSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBpZD0iZGlhbW9uZCI+CiAgPHBhdGggZmlsbD0icGFyYW0oZmlsbCkgIzAwMCIgZmlsbC1vcGFjaXR5PSJwYXJhbShmaWxsLW9wYWNpdHkpIiBzdHJva2U9InBhcmFtKG91dGxpbmUpICNmZmYiIHN0cm9rZS13aWR0aD0icGFyYW0ob3V0bGluZS13aWR0aCkgMCIgc3Ryb2tlLW9wYWNpdHk9InBhcmFtKG91dGxpbmUtb3BhY2l0eSkiIGQ9Ik03LjAzNzE1IDEuMjAxNDdMMi4xMjU0MiA2LjdDMi4wNDk2MiA2Ljc4MzkzIDIuMDA1NjggNi44OTAwNSAyLjAwMDUxIDdDMS45OTUzNSA3LjEwOTk0IDIuMDI5MjUgNy4yMTAxMyAyLjA5Njg5IDcuM0w3LjAwNjUgMTMuNzYwMUM3LjA2MjMzIDEzLjgzNDMgNy4xMzYyOSAxMy44OTQ3IDcuMjIyMTYgMTMuOTM2NUM3LjMwODAzIDEzLjk3ODIgNy40MDMzMSAxNCA3LjUgMTRDNy41OTY2OSAxNCA3LjY5MTk3IDEzLjk3ODIgNy43Nzc4NCAxMy45MzY1QzcuODYzNzEgMTMuODk0NyA3LjkzNzY2IDEzLjgzNDMgNy45OTM1IDEzLjc2MDFMMTIuOTAzMSA3LjNDMTIuOTcwNyA3LjIxMDEzIDEzLjAwNDcgNy4xMDk5NCAxMi45OTk1IDdDMTIuOTk0MyA2Ljg5MDA1IDEyLjk1MDQgNi43ODM5MyAxMi44NzQ2IDYuN0w3Ljk2Mjg1IDEuMjAxNDdDNy45MDU5MSAxLjEzODMzIDcuODM1MDEgMS4wODc2MSA3Ljc1NTA4IDEuMDUyODJDNy42NzUxNCAxLjAxODAyIDcuNTg4MSAxIDcuNSAxQzcuNDExOSAxIDcuMzI0ODYgMS4wMTgwMiA3LjI0NDkyIDEuMDUyODJDNy4xNjQ5OSAxLjA4NzYxIDcuMDk0MDkgMS4xMzgzMyA3LjAzNzE1IDEuMjAxNDdaIi8+Cjwvc3ZnPg==" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="255,255,255,255,rgb:1,1,1,1" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="parameters"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="5" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </symbols>
    <rotation/>
    <sizescale/>
    <data-defined-properties>
      <Option type="Map">
        <Option name="name" value="" type="QString"/>
        <Option name="properties"/>
        <Option name="type" value="collection" type="QString"/>
      </Option>
    </data-defined-properties>
  </renderer-v2>
  <selection mode="Default">
    <selectionColor invalid="1"/>
    <selectionSymbol>
      <symbol name="" force_rhr="0" frame_rate="10" alpha="1" is_animated="0" clip_to_extent="1" type="marker">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" value="" type="QString"/>
            <Option name="properties"/>
            <Option name="type" value="collection" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" enabled="1" locked="0" id="{d4e394d9-a2d4-4507-a338-62df4a96a9c8}" class="SimpleMarker">
          <Option type="Map">
            <Option name="angle" value="0" type="QString"/>
            <Option name="cap_style" value="square" type="QString"/>
            <Option name="color" value="255,0,0,255,rgb:1,0,0,1" type="QString"/>
            <Option name="horizontal_anchor_point" value="1" type="QString"/>
            <Option name="joinstyle" value="bevel" type="QString"/>
            <Option name="name" value="circle" type="QString"/>
            <Option name="offset" value="0,0" type="QString"/>
            <Option name="offset_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="offset_unit" value="MM" type="QString"/>
            <Option name="outline_color" value="35,35,35,255,rgb:0.13725490196078433,0.13725490196078433,0.13725490196078433,1" type="QString"/>
            <Option name="outline_style" value="solid" type="QString"/>
            <Option name="outline_width" value="0" type="QString"/>
            <Option name="outline_width_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="outline_width_unit" value="MM" type="QString"/>
            <Option name="scale_method" value="diameter" type="QString"/>
            <Option name="size" value="2" type="QString"/>
            <Option name="size_map_unit_scale" value="3x:0,0,0,0,0,0" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
            <Option name="vertical_anchor_point" value="1" type="QString"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" value="" type="QString"/>
              <Option name="properties"/>
              <Option name="type" value="collection" type="QString"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </selectionSymbol>
  </selection>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>0</layerGeometryType>
</qgis>
