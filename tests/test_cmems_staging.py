import ast
from pathlib import Path

import pytest

from scripts.run_marine_simulation import stage_cmems_forcing


SCRIPTS = Path(__file__).parents[1] / "scripts"
MARINE_ENTRYPOINTS = (
    SCRIPTS / "run_marine_simulation.py",
    SCRIPTS / "prepare_croco_forcing.py",
    SCRIPTS / "submit_gcp_batch_simulation.py",
)


def _import_bindings(node):
    if isinstance(node, ast.Import):
        return {
            alias.asname or alias.name.split(".")[0]
            for alias in node.names
        }
    if isinstance(node, ast.ImportFrom):
        return {
            alias.asname or alias.name
            for alias in node.names
            if alias.name != "*"
        }
    return set()


def _module_import_bindings(tree):
    bindings = set()

    def visit(node):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        bindings.update(_import_bindings(node))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return bindings


def _function_local_imports(function):
    imports = []

    def visit(node):
        if node is not function and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        for name in _import_bindings(node):
            imports.append((name, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(function)
    return imports


@pytest.mark.parametrize("script", MARINE_ENTRYPOINTS, ids=lambda path: path.name)
def test_function_local_imports_do_not_shadow_module_imports(script: Path):
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    module_bindings = _module_import_bindings(tree)
    offenders = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        for name, lineno in _function_local_imports(function):
            if name in module_bindings:
                offenders.append((function.name, lineno, name))
    assert offenders == []


def test_stage_cmems_forcing_copies_nonempty_artifact(tmp_path: Path):
    import xarray as xr
    inputs_dir = tmp_path / "inputs"
    croco_work = tmp_path / "outputs" / "croco_alboran_1km"
    inputs_dir.mkdir()
    croco_work.mkdir(parents=True)
    staged = inputs_dir / "cmems_ocean_forcing.nc"
    
    ds = xr.Dataset(
        {v: (("time", "depth", "latitude", "longitude"), [[[[1.0]]]]) for v in ("uo", "vo", "thetao", "so", "zos")},
        coords={"time": [0], "depth": [0], "latitude": [0], "longitude": [0]}
    )
    ds.to_netcdf(staged)

    destination = stage_cmems_forcing(staged, croco_work)

    assert destination == croco_work / "cmems_ocean_forcing.nc"
    assert destination.exists() and destination.stat().st_size > 0


def test_stage_cmems_forcing_rejects_empty_artifact(tmp_path: Path):
    staged = tmp_path / "cmems_ocean_forcing.nc"
    staged.touch()
    croco_work = tmp_path / "croco_alboran_1km"
    croco_work.mkdir()

    with pytest.raises(ValueError, match="Pre-staged CMEMS forcing is empty"):
        stage_cmems_forcing(staged, croco_work)
