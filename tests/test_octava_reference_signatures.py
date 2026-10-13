"""Exercise the production reference reader without starting Studio services."""
import ast
from pathlib import Path
import re
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('extension,payload,mime', [
    ('.png', b'\x89PNG\r\n\x1a\n' + b'fixture', 'image/png'),
    ('.jpeg', b'\xff\xd8\xff' + b'fixture', 'image/jpeg'),
    ('.webp', b'RIFF\x00\x00\x00\x00WEBPfixture', 'image/webp'),
    ('.png', b'\\x89PNG\\r\\n\\x1a\\n', None),
    ('.jpg', b'\\xff\\xd8\\xff', None),
])
def test_reference_reader_binary_signatures(tmp_path, monkeypatch, extension, payload, mime):
    source = Path(__file__).resolve().parents[1] / 'local_agent' / 'studio_server.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == '_asset_reference_image')
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {'Path': Path, 're': re, 'StudioStore': object,
                 'StudioError': ValueError, 'approved_bytes': lambda _: None}
    exec(compile(module, str(source), 'exec'), namespace)
    project = tmp_path / 'story'
    image = project / 'assets' / ('reference' + extension)
    image.parent.mkdir(parents=True)
    image.write_bytes(payload)
    registry = types.ModuleType('local_agent.asset_registry')
    registry.read_asset_registry = lambda *_: {
        'prop.test': {'path': 'assets/' + image.name}}
    monkeypatch.setitem(sys.modules, 'local_agent.asset_registry', registry)
    store = SimpleNamespace(root=tmp_path, project='story', workspace=tmp_path)
    result = namespace['_asset_reference_image'](store, 'prop.test')
    assert result == ((payload, mime) if mime else None)
