import json
from unittest.mock import Mock

import pytest

from pyjs.android.recycler_testing import StaggeredGridSnapshot, _json_float


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_snapshot_rejects_non_json_translation(value):
    with pytest.raises(ValueError, match="finite"):
        _json_float(value)


def test_native_snapshot_export_preserves_unclipped_bounds_and_pending_identity():
    params = Mock()
    params.get_span_index.return_value = 2
    params.is_full_span.return_value = False
    child = Mock()
    child.getLayoutParams.return_value = params
    for method, value in {"getLeft": 403, "getTop": -85, "getRight": 593,
                          "getBottom": 1015, "getTranslationX": 13.5,
                          "getTranslationY": -17.25}.items():
        getattr(child, method).return_value = value
    holder = Mock()
    holder.get_item_id.return_value = 2**60 + 1
    holder.get_binding_adapter_position.return_value = -1
    holder.get_layout_position.return_value = 3
    adapter = Mock()
    adapter.has_stable_ids.return_value = True
    adapter.get_item_count.return_value = 1
    adapter.get_item_id.return_value = 2**60 + 1
    recycler = Mock()
    recycler.getWidth.return_value = 601
    recycler.getHeight.return_value = 400
    recycler.isAnimating.return_value = True
    recycler.hasPendingAdapterUpdates.return_value = True
    recycler.get_adapter.return_value = adapter
    recycler.getChildCount.return_value = 2
    recycler.getChildAt.return_value = child
    recycler.getChildViewHolder.return_value = holder

    def decorate(view, bounds):
        assert view is child
        bounds.left, bounds.top, bounds.right, bounds.bottom = 400, -90, 600, 1024

    recycler.getDecoratedBoundsWithMargins.side_effect = decorate
    payload = json.loads(StaggeredGridSnapshot(recycler).to_json())
    expected_child = {
        "id": str(2**60 + 1), "adapter_position": -1, "layout_position": 3,
        "span": 2, "full_span": False, "bounds": [403, -85, 593, 1015],
        "decorated_bounds": [400, -90, 600, 1024], "translation": [13.5, -17.25],
    }
    assert payload == {
        "version": 1, "coordinates": "recycler-local-pixels", "width": 601,
        "height": 400, "animating": True, "pending_updates": True, "stable_ids": True,
        "order": [str(2**60 + 1)], "children": [expected_child, expected_child],
    }
    recycler.requestLayout.assert_not_called()
