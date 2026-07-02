from importlib import resources, util


def test_transport_matters_import_namespace_replaces_manicure() -> None:
    assert util.find_spec("transport_matters") is not None
    assert util.find_spec("manicure") is None


def test_transport_matters_module_entrypoints_exist() -> None:
    assert util.find_spec("transport_matters.__main__") is not None
    assert util.find_spec("transport_matters.cli.__main__") is not None


def test_embedded_web_bundle_resource_target_uses_transport_matters_package() -> None:
    web_index = resources.files("transport_matters").joinpath("www/index.html")
    canvas_index = resources.files("transport_matters").joinpath("canvas/index.html")

    assert str(web_index).endswith("transport_matters/www/index.html")
    assert str(canvas_index).endswith("transport_matters/canvas/index.html")
