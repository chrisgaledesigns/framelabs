"""Tests for GphotoBackend. Uses mocks -- never touches real hardware.

Requires the optional "gphoto2" package to be importable (it's what
GphotoBackend itself imports), since these tests patch specific
attributes on that module rather than the module as a whole. If it isn't
installed, this whole file is skipped rather than erroring the suite --
matching the "dslr" extra being optional, not a hard dependency.
"""

import pytest

gp = pytest.importorskip("gphoto2")

from unittest.mock import MagicMock, patch  # noqa: E402

from framelabs.camera.camera_interface import CameraError  # noqa: E402
from framelabs.camera.gphoto_backend import GphotoBackend  # noqa: E402

PORT_ADDRESS = "usb:001,004"
MODEL_NAME = "Nikon DSC D850"


def _connected_camera(mock_camera_class, mock_port_info_list_class):
    """Build a GphotoBackend already connect()-ed against a mock camera."""
    mock_camera = MagicMock()
    mock_camera_class.return_value = mock_camera

    mock_port_info_list = MagicMock()
    mock_port_info_list.lookup_path.return_value = 0
    mock_port_info_list_class.return_value = mock_port_info_list

    cam = GphotoBackend(PORT_ADDRESS)
    cam.connect()
    return cam, mock_camera


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_connect_success(mock_camera_class, mock_port_info_list_class):
    mock_camera = MagicMock()
    mock_camera_class.return_value = mock_camera

    mock_port_info_list = MagicMock()
    mock_port_info_list.lookup_path.return_value = 2
    mock_port_info_list_class.return_value = mock_port_info_list

    cam = GphotoBackend(PORT_ADDRESS)
    cam.connect()

    mock_port_info_list.load.assert_called_once()
    mock_port_info_list.lookup_path.assert_called_once_with(PORT_ADDRESS)
    mock_camera.set_port_info.assert_called_once_with(mock_port_info_list[2])
    mock_camera.init.assert_called_once()


@patch("framelabs.camera.gphoto_backend.gp.CameraAbilitiesList")
@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_connect_with_model_name_sets_matching_abilities(
    mock_camera_class, mock_port_info_list_class, mock_abilities_list_class
):
    mock_camera = MagicMock()
    mock_camera_class.return_value = mock_camera

    mock_port_info_list = MagicMock()
    mock_port_info_list.lookup_path.return_value = 0
    mock_port_info_list_class.return_value = mock_port_info_list

    mock_abilities_list = MagicMock()
    mock_abilities_list.lookup_model.return_value = 1
    mock_abilities_list_class.return_value = mock_abilities_list

    cam = GphotoBackend(PORT_ADDRESS, model_name=MODEL_NAME)
    cam.connect()

    mock_abilities_list.load.assert_called_once()
    mock_abilities_list.lookup_model.assert_called_once_with(MODEL_NAME)
    mock_camera.set_abilities.assert_called_once_with(mock_abilities_list[1])


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_connect_without_model_name_skips_abilities(
    mock_camera_class, mock_port_info_list_class
):
    """No model_name means no CameraAbilitiesList lookup -- port info
    alone is enough to connect."""
    mock_camera = MagicMock()
    mock_camera_class.return_value = mock_camera

    mock_port_info_list = MagicMock()
    mock_port_info_list.lookup_path.return_value = 0
    mock_port_info_list_class.return_value = mock_port_info_list

    cam = GphotoBackend(PORT_ADDRESS)
    cam.connect()

    mock_camera.set_abilities.assert_not_called()


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_connect_failure_raises_camera_error(
    mock_camera_class, mock_port_info_list_class
):
    mock_camera = MagicMock()
    mock_camera.init.side_effect = gp.GPhoto2Error(-1)
    mock_camera_class.return_value = mock_camera

    mock_port_info_list = MagicMock()
    mock_port_info_list.lookup_path.return_value = 0
    mock_port_info_list_class.return_value = mock_port_info_list

    cam = GphotoBackend(PORT_ADDRESS)

    with pytest.raises(CameraError):
        cam.connect()


def test_capture_without_connect_raises_camera_error():
    cam = GphotoBackend(PORT_ADDRESS)

    with pytest.raises(CameraError):
        cam.capture()


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_capture_success_returns_bytes(mock_camera_class, mock_port_info_list_class):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)

    mock_file_path = MagicMock()
    mock_file_path.folder = "/store_00010001"
    mock_file_path.name = "capt0001.jpg"
    mock_camera.capture.return_value = mock_file_path

    mock_camera_file = MagicMock()
    mock_camera_file.get_data_and_size.return_value = b"fake-jpeg-bytes"
    mock_camera.file_get.return_value = mock_camera_file

    result = cam.capture()

    mock_camera.file_get.assert_called_once_with(
        "/store_00010001", "capt0001.jpg", gp.GP_FILE_TYPE_NORMAL
    )
    assert isinstance(result, bytes)
    assert result == b"fake-jpeg-bytes"


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_capture_failure_raises_camera_error(
    mock_camera_class, mock_port_info_list_class
):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_camera.capture.side_effect = gp.GPhoto2Error(-1)

    with pytest.raises(CameraError):
        cam.capture()


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_disconnect_releases_camera(mock_camera_class, mock_port_info_list_class):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)

    cam.disconnect()

    mock_camera.exit.assert_called_once()
    assert cam.is_connected() is False


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_disconnect_swallows_errors(mock_camera_class, mock_port_info_list_class):
    """A camera that's already physically gone shouldn't block cleanup."""
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_camera.exit.side_effect = gp.GPhoto2Error(-1)

    cam.disconnect()  # should not raise

    assert cam.is_connected() is False


def test_is_connected_without_connect_returns_false():
    cam = GphotoBackend(PORT_ADDRESS)

    assert cam.is_connected() is False


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_is_connected_true_when_summary_succeeds(
    mock_camera_class, mock_port_info_list_class
):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_camera.get_summary.return_value = MagicMock()

    assert cam.is_connected() is True


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_is_connected_false_when_summary_fails(
    mock_camera_class, mock_port_info_list_class
):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_camera.get_summary.side_effect = gp.GPhoto2Error(-1)

    assert cam.is_connected() is False


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_read_preview_frame_without_live_view_raises_camera_error(
    mock_camera_class, mock_port_info_list_class
):
    cam, _ = _connected_camera(mock_camera_class, mock_port_info_list_class)

    with pytest.raises(CameraError):
        cam.read_preview_frame()


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_read_preview_frame_success_returns_bytes(
    mock_camera_class, mock_port_info_list_class
):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)

    mock_camera_file = MagicMock()
    mock_camera_file.get_data_and_size.return_value = b"fake-preview-bytes"
    mock_camera.capture_preview.return_value = mock_camera_file

    cam.start_live_view()
    result = cam.read_preview_frame()

    assert isinstance(result, bytes)
    assert result == b"fake-preview-bytes"


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_read_preview_frame_after_stop_live_view_raises_camera_error(
    mock_camera_class, mock_port_info_list_class
):
    cam, _ = _connected_camera(mock_camera_class, mock_port_info_list_class)

    cam.start_live_view()
    cam.stop_live_view()

    with pytest.raises(CameraError):
        cam.read_preview_frame()


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_set_iso_writes_config(mock_camera_class, mock_port_info_list_class):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_config = MagicMock()
    mock_widget = MagicMock()
    mock_config.get_child_by_name.return_value = mock_widget
    mock_camera.get_config.return_value = mock_config

    cam.set_iso(400)

    mock_config.get_child_by_name.assert_called_once_with("iso")
    mock_widget.set_value.assert_called_once_with("400")
    mock_camera.set_config.assert_called_once_with(mock_config)


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_set_shutter_writes_config(mock_camera_class, mock_port_info_list_class):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_config = MagicMock()
    mock_widget = MagicMock()
    mock_config.get_child_by_name.return_value = mock_widget
    mock_camera.get_config.return_value = mock_config

    cam.set_shutter("1/250")

    mock_config.get_child_by_name.assert_called_once_with("shutterspeed")
    mock_widget.set_value.assert_called_once_with("1/250")


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_set_aperture_writes_config(mock_camera_class, mock_port_info_list_class):
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_config = MagicMock()
    mock_widget = MagicMock()
    mock_config.get_child_by_name.return_value = mock_widget
    mock_camera.get_config.return_value = mock_config

    cam.set_aperture("f/8")

    mock_config.get_child_by_name.assert_called_once_with("aperture")
    mock_widget.set_value.assert_called_once_with("f/8")


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_set_iso_on_unsupported_widget_does_not_raise(
    mock_camera_class, mock_port_info_list_class
):
    """Bodies that don't expose a given widget should warn, not crash --
    matching WebcamBackend's forgiving contract for these setters."""
    cam, mock_camera = _connected_camera(mock_camera_class, mock_port_info_list_class)
    mock_camera.get_config.side_effect = gp.GPhoto2Error(-1)

    cam.set_iso(100)  # should not raise


@patch("framelabs.camera.gphoto_backend.gp.PortInfoList")
@patch("framelabs.camera.gphoto_backend.gp.Camera")
def test_get_metadata_uses_model_name_when_available(
    mock_camera_class, mock_port_info_list_class
):
    cam, _ = _connected_camera(mock_camera_class, mock_port_info_list_class)
    cam._model_name = MODEL_NAME

    metadata = cam.get_metadata()

    assert metadata.camera_id == PORT_ADDRESS
    assert metadata.display_name == MODEL_NAME
    assert metadata.backend_type == "gphoto"


def test_get_metadata_falls_back_to_port_address_without_model_name():
    cam = GphotoBackend(PORT_ADDRESS)

    metadata = cam.get_metadata()

    assert PORT_ADDRESS in metadata.display_name
    assert metadata.backend_type == "gphoto"
