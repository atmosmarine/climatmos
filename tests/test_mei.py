# ClimAtmos – Ferramentas para análise e visualização de índices climáticos
# Copyright (C) 2025 Atmosmarine
#
# Este programa é software livre; você pode redistribuí-lo e/ou modificá-lo
# sob os termos da Licença Pública Geral GNU, conforme publicada pela
# Free Software Foundation, na versão 3.
#
# Este programa é distribuído na esperança de que seja útil,
# mas SEM QUALQUER GARANTIA; sem mesmo a garantia implícita de
# COMERCIABILIDADE ou ADEQUAÇÃO A UM DETERMINADO PROPÓSITO.
#
# Você deve ter recebido uma cópia da Licença Pública Geral GNU
# junto com este programa; se não, veja <https://www.gnu.org/licenses/>.

# test_mei.py
import os

for _var in [
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
]:
    os.environ.setdefault(_var, "1")

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from src.mei import MEI
from src.atm_tools import validate_config_MEI


def test_validate_config_mei_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_MEI({"MEI_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] MEI_MODO inválido: foo")


def test_validate_config_mei_externo_requer_path_data():
    cfg = {"MEI_MODO": "EXTERNO"}
    with pytest.raises(ValueError) as exc:
        validate_config_MEI(cfg)
    esperado = "[ERRO ARQUIVO CONFIG] Informe MEI_EXTERNO_PATH_DATA ou arquivos individuais (MEI_EXTERNO_*_)."
    assert str(exc.value).endswith(esperado)


def test_validate_config_mei_teste_normaliza_lat_lon():
    cfg = {
        "MEI_MODO": "TESTE",
        "MEI_TESTE_LAT_MIN": "15",
        "MEI_TESTE_LAT_MAX": "-25",
        "MEI_TESTE_LON_MIN": "210",
        "MEI_TESTE_LON_MAX": "140",
        "MEI_TESTE_INICIO": "2000-01",
        "MEI_TESTE_FINAL": "2010-12",
    }
    sanitized = validate_config_MEI(cfg)
    assert sanitized["lat_range"] == (-25.0, 15.0)
    assert sanitized["lon_range"] == (140.0, 210.0)
    assert sanitized["base_series"] == ("2000-01", "2010-12")
    assert sanitized["base_climatology"] == ("1949-12", "1993-12")
    assert sanitized["resolution"] == 0.5


def test_validate_config_mei_teste_inicio_formato_invalido():
    cfg = {
        "MEI_MODO": "TESTE",
        "MEI_TESTE_INICIO": "2000/01",
        "MEI_TESTE_FINAL": "2010-12",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_MEI(cfg)
    esperado = "[ERRO ARQUIVO CONFIG] MEI_TESTE_INICIO e MEI_TESTE_FINAL precisam estar no formato YYYY-MM, YYYY-MM."
    assert str(exc.value).endswith(esperado)


def test_validate_config_mei_externo_resolucao_invalida(tmp_path):
    data_dir = tmp_path / "mei_nc"
    data_dir.mkdir()
    cfg = {
        "MEI_MODO": "EXTERNO",
        "MEI_EXTERNO_PATH_DATA": str(data_dir),
        "MEI_EXTERNO_RESOLUCAO": "-1",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_MEI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] MEI_RESOLUCAO deve ser positivo: -1")


def test_validate_config_mei_externo_paths(tmp_path):
    data_dir = tmp_path / "mei_nc"
    data_dir.mkdir()
    (data_dir / "olr.nc").write_text("dummy", encoding="utf-8")

    cfg = {
        "MEI_MODO": "EXTERNO",
        "MEI_EXTERNO_PATH_RESULTS": str(tmp_path / "out"),
        "MEI_EXTERNO_PATH_DATA": str(data_dir),
        "MEI_EXTERNO_BASE_CLIMATOLOGIA": "1950-12:1993-12",
        "MEI_EXTERNO_INICIO": "1950-12",
        "MEI_EXTERNO_FINAL": "1994-01",
        "MEI_EXTERNO_LAT_MIN": "30",
        "MEI_EXTERNO_LAT_MAX": "-15",
        "MEI_EXTERNO_LON_MIN": "120",
        "MEI_EXTERNO_LON_MAX": "260",
        "MEI_EXTERNO_RESOLUCAO": "1.0",
        "MEI_EXTERNO_PSL_VARS": "slp,sst",
    }

    sanitized = validate_config_MEI(cfg)
    assert sanitized["path_data"] == str(data_dir)
    assert sanitized["resolution"] == pytest.approx(1.0)
    assert sanitized["lat_range"] == (-15.0, 30.0)
    assert sanitized["lon_range"] == (120.0, 260.0)
    assert sanitized["psl_vars"] == ["slp", "sst"]


@pytest.fixture
def mei_teste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "MEI_MODO": "TESTE",
        "MEI_TESTE_PATH_RESULTS": str(tmp_path / "mei_out"),
        "MEI_TESTE_NOME": "Caso Especial",
        "MEI_TESTE_INICIO": "1950-01",
        "MEI_TESTE_FINAL": "1951-12",
        "MEI_TESTE_BASE_CLIMATOLOGIA": "1950-01:1950-12",
        "MEI_TESTE_LAT_MIN": "-30",
        "MEI_TESTE_LAT_MAX": "30",
        "MEI_TESTE_LON_MIN": "100",
        "MEI_TESTE_LON_MAX": "290",
        "MEI_TESTE_RESOLUCAO": "0.5",
    }
    return MEI(cfg)


@pytest.fixture
def mei_externo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "mei_nc"
    data_dir.mkdir()
    cfg = {
        "MEI_MODO": "EXTERNO",
        "MEI_EXTERNO_PATH_RESULTS": str(tmp_path / "mei_ext"),
        "MEI_EXTERNO_PATH_DATA": str(data_dir),
        "MEI_EXTERNO_BASE_CLIMATOLOGIA": "1949-12:1993-12",
        "MEI_EXTERNO_INICIO": "1949-12",
        "MEI_EXTERNO_FINAL": "1993-12",
        "MEI_EXTERNO_LAT_MIN": "-20",
        "MEI_EXTERNO_LAT_MAX": "20",
        "MEI_EXTERNO_LON_MIN": "120",
        "MEI_EXTERNO_LON_MAX": "200",
        "MEI_EXTERNO_RESOLUCAO": "1.0",
    }
    return MEI(cfg)


def test_mei_parse_list_and_slug(mei_teste: MEI):
    assert MEI.parse_list("a, b , ,c") == ["a", "b", "c"]
    assert mei_teste._slug("Região Á") == "RegiãoÁ"


def test_mei_refresh_output_paths_updates(mei_teste: MEI):
    mei_teste.CONFIG["base_series"] = ("2001-01", "2001-02")
    mei_teste._refresh_output_paths()
    assert mei_teste.base_series_tag == "200101_200102"
    assert mei_teste.PATH_MEI_PLOT.name == f"MEI_serie-temporal_CALC_{mei_teste.SUF_EXEC}.png"


def test_mei_parse_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mei = MEI({
        "MEI_MODO": "TESTE",
        "MEI_TESTE_PATH_RESULTS": str(tmp_path / "out"),
        "MEI_TESTE_INICIO": "2000-01",
        "MEI_TESTE_FINAL": "2000-12",
        "MEI_TESTE_BASE_CLIMATOLOGIA": "2000-01:2000-12",
        "MEI_TESTE_LAT_MIN": "-10",
        "MEI_TESTE_LAT_MAX": "10",
        "MEI_TESTE_LON_MIN": "100",
        "MEI_TESTE_LON_MAX": "200",
    })
    parsed = mei._parse_date("2000-05")
    assert parsed.year == 2000 and parsed.month == 5


def test_mei_validate_dates_reference(mei_teste: MEI):
    times = pd.date_range("1950-01-01", "1951-12-01", freq="MS")
    lat = np.array([-10, 0, 10], dtype=float)
    lon = np.array([150, 160], dtype=float)
    data = np.ones((len(times), len(lat), len(lon)))
    ds = xr.Dataset({"olr": (("time", "lat", "lon"), data)}, coords={"time": times, "lat": lat, "lon": lon})

    assert mei_teste._validate_dates(ds) is True


def test_mei_validate_dates_external_adjusts(mei_externo: MEI):
    times = pd.date_range("1950-01-01", periods=6, freq="MS")
    lat = np.array([-15, 0, 15], dtype=float)
    lon = np.array([150, 170], dtype=float)
    data = np.ones((len(times), len(lat), len(lon)))
    ds = xr.Dataset({"sst": (("time", "lat", "lon"), data)}, coords={"time": times, "lat": lat, "lon": lon})

    assert mei_externo._validate_dates(ds) is True
    assert mei_externo.CONFIG["base_climatology"] == ("1950-01", "1950-06")
    assert mei_externo.CONFIG["base_series"] == ("1950-01", "1950-06")
    assert mei_externo.base_series_tag == "195001_195006"


def test_mei_export_format(mei_teste: MEI):
    idx = pd.date_range("2000-12-01", periods=4, freq="MS")
    series = pd.Series([0.1, 0.2, -0.3, 0.4], index=idx)
    table = mei_teste._export_mei_format(series)
    assert list(table.columns) == [
        "DECJAN", "JANFEB", "FEBMAR", "MARAPR", "APRMAY", "MAYJUN",
        "JUNJUL", "JULAUG", "AUGSEP", "SEPOCT", "OCTNOV", "NOVDEC",
    ]
    assert table.loc[2001, "DECJAN"] == pytest.approx(0.1)




def test_mei_prepare_for_pca(mei_teste: MEI):
    times = pd.date_range("2000-01-01", periods=3, freq="MS")
    arr = xr.DataArray(
        np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
        dims=("time", "cluster"),
        coords={"time": times, "cluster": [1, 2]},
    )
    clusters = {"air": arr, "sst": arr * 0.5}
    X = mei_teste._prepare_for_pca(clusters)
    assert X.shape == (3, 4)


def test_mei_run_pca(monkeypatch, mei_teste: MEI):
    class DummyPCA:
        def __init__(self, n_components):
            self.n_components = n_components

        def fit_transform(self, X):
            self.components_ = np.ones((self.n_components, X.shape[1]))
            return np.full((X.shape[0], self.n_components), 0.5)

    import sys
    import types

    stub_decomp = types.ModuleType("sklearn.decomposition")
    stub_decomp.PCA = DummyPCA
    stub_sklearn = types.ModuleType("sklearn")
    stub_sklearn.decomposition = stub_decomp

    monkeypatch.setitem(sys.modules, "sklearn", stub_sklearn)
    monkeypatch.setitem(sys.modules, "sklearn.decomposition", stub_decomp)
    X = np.ones((5, 3))
    pcs, model = mei_teste._run_pca(X)
    assert pcs.shape == (5, 1)
    assert isinstance(model, DummyPCA)


def test_mei_seasonal_standardization(mei_teste: MEI):
    times = pd.date_range("2000-01-01", periods=24, freq="MS")
    year1 = np.arange(12, dtype=float)
    year2 = np.arange(12, dtype=float) + 0.5
    pc = np.concatenate([year1, year2]).reshape(-1, 1)
    standardized = mei_teste._seasonal_standardization(pc, times)
    assert len(standardized) == 24
    assert not standardized.isna().all()
