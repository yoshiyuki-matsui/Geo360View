"""Frame-layer replacement regressions without a QGIS installation."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def load_methods(namespace):
    path = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"addLayer", "removePreviousFrameLayers"}
    methods = [node for owner in tree.body if isinstance(owner, ast.ClassDef)
               for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=[ast.ClassDef(name="UnderTest", bases=[], keywords=[],
                                         body=methods, decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["UnderTest"]()


class FrameLayerReplacementTests(unittest.TestCase):
    def setUp(self):
        self.layers = {}
        self.events = []
        self.project = Mock()
        self.project.mapLayer.side_effect = self.layers.get
        self.project.addMapLayer.side_effect = lambda layer: self.events.append("add") or layer
        self.project.removeMapLayers.side_effect = lambda ids: self.events.append("remove")
        self.provider = Mock()
        self.provider.addFeatures.return_value = (True, [])
        self.new_layer = Mock()
        self.new_layer.id.return_value = "new"
        self.new_layer.dataProvider.return_value = self.provider
        namespace = {"QgsProject": SimpleNamespace(instance=lambda: self.project),
                     "QgsVectorLayer": Mock(return_value=self.new_layer),
                     "QgsField": Mock(), "QgsFeature": Mock(),
                     "QgsGeometry": Mock(), "QgsPointXY": Mock(),
                     "_to_qdatetime": lambda value: value}
        for name in ("INT", "DATETIME", "DOUBLE", "STRING"):
            namespace["QT_FIELD_" + name] = name
        self.target = load_methods(namespace)
        self.target.created_layer_ids = []
        self.target.frame_layer_id = None
        self.target.frame_click_tool = None
        self.target.save_on_exit_layer_ids = set()
        self.target.loaded_layer_feature_counts = {}
        self.target.isFrameReferenceLayer = lambda layer: layer.is_frame
        self.target.deactivateClickMode = Mock()
        self.target.process_button = Mock()
        self.target.progress_bar = Mock()
        self.target.session_closing = False
        self.target.resolveKpMatches = lambda rows: ([None] * len(rows), 0, None)
        self.target.processFrameShiftValue = lambda: 0
        for name in ("createLayerSpatialIndex", "markLayerSaveOnExit", "notifyInfo",
                     "notifyWarning", "exportFrameData", "showError"):
            setattr(self.target, name, Mock())

    def add_old(self, layer_id, name="Video GPX Points", is_frame=True, tracked=True):
        layer = SimpleNamespace(id=lambda: layer_id, name=lambda: name, is_frame=is_frame)
        self.layers[layer_id] = layer
        if tracked:
            self.target.created_layer_ids.append(layer_id)
            self.target.save_on_exit_layer_ids.add(layer_id)
            self.target.loaded_layer_feature_counts[layer_id] = 10
        return layer

    def test_success_removes_all_previous_frames_and_keeps_other_layers(self):
        old = self.add_old("old")
        self.add_old("older")
        self.add_old("poi", "User POIs", False)
        self.add_old("marking", "Markings", False)
        self.add_old("unrelated", tracked=False)
        self.target.frame_layer_id = "old"
        self.target.frame_click_tool = SimpleNamespace(layer=old)
        self.target.addLayer([(1, 1, None, 35, 137)])
        self.assertEqual(self.events, ["add", "remove"])
        self.assertEqual(set(self.project.removeMapLayers.call_args.args[0]), {"old", "older"})
        self.assertEqual(self.target.created_layer_ids, ["poi", "marking", "new"])
        self.assertEqual(self.target.frame_layer_id, "new")
        self.assertEqual(self.target.save_on_exit_layer_ids, {"poi", "marking"})
        self.assertEqual(self.target.loaded_layer_feature_counts, {"poi": 10, "marking": 10})
        self.target.deactivateClickMode.assert_called_once_with(show_message=False)

    def test_renamed_restored_frame_is_removed_and_unrelated_click_tool_is_kept(self):
        self.add_old("restored", "Renamed frame layer")
        self.target.frame_layer_id = "restored"
        other = self.add_old("poi", "User POIs", False)
        self.target.frame_click_tool = SimpleNamespace(layer=other)
        self.target.removePreviousFrameLayers()
        self.project.removeMapLayers.assert_called_once_with(["restored"])
        self.target.deactivateClickMode.assert_not_called()

    def test_empty_result_and_closing_session_keep_previous_layer(self):
        self.add_old("old")
        self.target.frame_layer_id = "old"
        self.target.addLayer([])
        self.target.session_closing = True
        self.target.addLayer([(1, 1, None, 35, 137)])
        self.project.removeMapLayers.assert_not_called()
        self.assertEqual(self.target.frame_layer_id, "old")

    def test_feature_or_project_add_failure_keeps_previous_layer(self):
        for failure in ("features", "project"):
            with self.subTest(failure=failure):
                self.setUp()
                self.add_old("old")
                self.target.frame_layer_id = "old"
                if failure == "features":
                    self.provider.addFeatures.return_value = (False, [])
                else:
                    self.project.addMapLayer.side_effect = lambda layer: None
                self.target.addLayer([(1, 1, None, 35, 137)])
                self.project.removeMapLayers.assert_not_called()
                self.assertEqual(self.target.frame_layer_id, "old")
                self.target.showError.assert_called_once()

    def test_first_run_and_manually_removed_previous_layer(self):
        self.target.created_layer_ids = ["missing"]
        self.target.frame_layer_id = "missing"
        self.target.addLayer([(1, 1, None, 35, 137)])
        self.project.removeMapLayers.assert_not_called()
        self.assertEqual(self.target.frame_layer_id, "new")


if __name__ == "__main__":
    unittest.main()
