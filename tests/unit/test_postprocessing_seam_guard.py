#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Focused AST fixtures for the post-processing execution seam guard."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_postprocessing_seam.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_postprocessing_seam", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _tree(guard, monkeypatch, tmp_path, source, rel="comicarr/app/leaf.py"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "SCAN_GLOBS", ("comicarr/**/*.py",))
    return path


def test_real_tree_passes(guard):
    assert guard.main() == 0


@pytest.mark.parametrize(
    "source",
    [
        "from comicarr.postprocessor import PostProcessor\nPostProcessor('n', 'f')\n",
        "from comicarr.postprocessor import PostProcessor as PP\nPP('n', 'f')\n",
        "from comicarr import process\nprocess.Process('n', 'f').post_process()\n",
        "import comicarr.process as legacy\nlegacy.Process('n', 'f').post_process()\n",
        "import comicarr\ncomicarr.process.Process('n', 'f').post_process()\n",
        "import comicarr as c\nc.process.Process('n', 'f').post_process()\n",
        "from ..process import Process\nProcess('n', 'f').post_process()\n",
        "def run():\n    from comicarr.postprocessor import PostProcessor\n    return PostProcessor('n', 'f')\n",
    ],
)
def test_direct_legacy_construction_is_rejected(guard, monkeypatch, tmp_path, source):
    _tree(guard, monkeypatch, tmp_path, source)
    assert guard.main() == 1


@pytest.mark.parametrize(
    "source",
    [
        "from comicarr.postprocessor import PostProcessor\nname = PostProcessor.__name__\n",
        "from comicarr import process\nname = process.Process.__name__\n",
        "import subprocess\nsubprocess.run(['true'])\n",
        "class Process:\n    pass\nProcess()\n",
        "from comicarr.app.metadata import Process\nProcess()\n",
    ],
)
def test_imports_and_unrelated_process_names_are_accepted(guard, monkeypatch, tmp_path, source):
    _tree(guard, monkeypatch, tmp_path, source)
    assert guard.main() == 0


def test_arbitrary_process_variable_is_not_assumed_to_be_legacy(guard, monkeypatch, tmp_path):
    source = "process = factory()\nprocess('n', 'f')\npostprocessor = factory()\npostprocessor('n', 'f')\n"
    _tree(guard, monkeypatch, tmp_path, source)
    assert guard.main() == 0


def test_same_file_legacy_constructor_is_rejected(guard, monkeypatch, tmp_path):
    source = "class PostProcessor:\n    pass\nPostProcessor('n', 'f')\n"
    _tree(guard, monkeypatch, tmp_path, source, rel="comicarr/postprocessor.py")
    assert guard.main() == 1


def test_owned_implementation_files_may_construct_legacy_processors(guard, monkeypatch, tmp_path):
    source = "from comicarr.postprocessor import PostProcessor\nPostProcessor('n', 'f')\n"
    _tree(guard, monkeypatch, tmp_path, source, rel="comicarr/app/downloads/postprocessing.py")
    assert guard.main() == 0

    _tree(guard, monkeypatch, tmp_path, source, rel="comicarr/process.py")
    assert guard.main() == 0


def test_unparseable_source_fails_closed(guard, monkeypatch, tmp_path, capsys):
    _tree(guard, monkeypatch, tmp_path, "def broken(:\n")
    assert guard.main() == 1
    assert "Could not parse" in capsys.readouterr().err
