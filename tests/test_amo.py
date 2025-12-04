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

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from src.amo import AMO
from src.atm_tools import validate_config_AMO


def test_validate_config_amo_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_AMO({"AMO_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AMO_MODO inválido: FOO")


def test_validate_config_amo_teste_base_invalida():
    cfg = {
        "AMO_MODO": "TESTE",
        "AMO_TESTE_BASE_CLIMA": "xpto",
        "AMO_TESTE_LAT_MIN": 0,
        "AMO_TESTE_LAT_MAX": 10,
        "AMO_TESTE_LON_MIN": -70,
        "AMO_TESTE_LON_MAX": -10,
        "AMO_TESTE_INICIO": "2000-01-01",
        "AMO_TESTE_FINAL": "2001-01-01",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_AMO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AMO_TESTE_BASE_CLIMA inválido: xpto")


def test_validate_config_amo_teste_lat_invalida():
    cfg = {
        "AMO_MODO": "TESTE",
        "AMO_TESTE_BASE_CLIMA": "1981-01:2010-12",
        "AMO_TESTE_LAT_MIN": "abc",
        "AMO_TESTE_LAT_MAX": 20,
        "AMO_TESTE_LON_MIN": -60,
        "AMO_TESTE_LON_MAX": -10,
        "AMO_TESTE_INICIO": "2000-01-01",
        "AMO_TESTE_FINAL": "2001-01-01",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_AMO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AMO_TESTE_LAT_MIN inválido: abc")


def test_validate_config_amo_teste_periodo_invalido():
    cfg = {
        "AMO_MODO": "TESTE",
        "AMO_TESTE_BASE_CLIMA": "1981-01:2010-12",
        "AMO_TESTE_LAT_MIN": -40,
        "AMO_TESTE_LAT_MAX": 60,
        "AMO_TESTE_LON_MIN": -80,
        "AMO_TESTE_LON_MAX": 0,
        "AMO_TESTE_INICIO": "2020-01-01",
        "AMO_TESTE_FINAL": "2010-01-01",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_AMO(cfg)
    expected = "[ERRO ARQUIVO CONFIG] AMO_TESTE_INICIO/FINAL inválidos: 2020-01-01 00:00:00, 2010-01-01 00:00:00"
    assert str(exc.value).endswith(expected)


def test_validate_config_amo_externo_arquivo_inexistente():
    cfg = {"AMO_MODO": "EXTERNO", "AMO_EXTERNO_CAMINHO": "nao_existe.csv"}
    with pytest.raises(ValueError) as exc:
        validate_config_AMO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] Arquivo externo AMO não encontrado: nao_existe.csv")


def test_validate_config_amo_externo_colunas_invalidas(tmp_path):
    csv_path = tmp_path / "amo.csv"
    csv_path.write_text("ano;mes;valor\n2000;1;1.0\n", encoding="utf-8")
    cfg = {"AMO_MODO": "EXTERNO", "AMO_EXTERNO_CAMINHO": str(csv_path)}

    with pytest.raises(ValueError) as exc:
        validate_config_AMO(cfg)
    msg = str(exc.value)
    assert "[ERRO ARQUIVO CONFIG] Arquivo externo AMO deve conter colunas" in msg
    for col in ["ano", "mes", "tsm"]:
        assert col in msg
    assert "['ano', 'mes', 'valor']" in msg


def test_validate_config_amo_externo_ok(tmp_path):
    csv_path = tmp_path / "amo.csv"
    csv_path.write_text("ano;mes;tsm\n2000;1;25.0\n", encoding="utf-8")
    cfg = {"AMO_MODO": "EXTERNO", "AMO_EXTERNO_CAMINHO": str(csv_path)}
    validate_config_AMO(cfg)

@pytest.fixture
def amo_teste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "AMO_MODO": "TESTE",
        "AMO_TESTE_BASE_CLIMA": "1981-01:2010-12",
        "AMO_TESTE_LAT_MIN": -40,
        "AMO_TESTE_LAT_MAX": 60,
        "AMO_TESTE_LON_MIN": -80,
        "AMO_TESTE_LON_MAX": 0,
        "AMO_TESTE_INICIO": "2000-01-01",
        "AMO_TESTE_FINAL": "2001-01-01",
        "AMO_TESTE_TSM": "ERSSTv5",
        "DATA_DIR": str(tmp_path / "data"),
        "OUT_DIR": str(tmp_path / "out"),
    }
    return AMO(cfg)


def test_amo_helper_methods(amo_teste: AMO):
    assert amo_teste._parse_base_years("1981-01:2010-12") == (1981, 2010)
    assert amo_teste._parse_base_years("1981-2010") == (1981, 2010)
    assert amo_teste._format_baseline((pd.Timestamp("1981-01-01"), pd.Timestamp("2010-12-31"))) == "1981-2010"

    with pytest.raises(ValueError):
        amo_teste._as_bool_ext("talvez", label="AMO_TOGGLE")


def test_amo_strip_and_numeric_parsing(amo_teste: AMO):
    assert amo_teste._strip_comment("5.0 # anot") == "5.0"
    assert amo_teste._as_float("1,23") == pytest.approx(1.23)
    assert amo_teste._as_float("bad", default=2.5) == pytest.approx(2.5)
    dt = amo_teste._as_date("2001-05-15")
    assert dt.year == 2001 and dt.month == 5
    assert amo_teste._parse_base("1971-2000") == (1971, 2000)


def test_amo_normalize_lon_and_subset(amo_teste: AMO):
    lon = xr.DataArray(np.array([0, 90, 270, 350]), dims=("lon",))
    norm = amo_teste._normalize_lon(lon)
    assert norm.values.tolist() == [0.0, 90.0, -90.0, -10.0]

    data = xr.Dataset({
        "sst": (("time", "lat", "lon"), np.arange(2 * 3 * 4).reshape(2, 3, 4))
    }, coords={
        "time": pd.date_range("2000-01-01", periods=2, freq="MS"),
        "lat": np.array([-50, -10, 20]),
        "lon": np.array([280, 300, 310, 320]),
    })

    amo_teste.lon_min, amo_teste.lon_max = -70.0, -40.0
    amo_teste.lat_min, amo_teste.lat_max = -40.0, 30.0
    subset, lon_name, lat_name = amo_teste._subset_region(data)
    assert lon_name == "lon"
    assert lat_name == "lat"
    assert subset.sizes["lon"] == 3
    assert subset.sizes["lat"] == 2


def test_amo_to_csv_table(amo_teste: AMO):
    idx = pd.date_range("2000-01-01", periods=3, freq="MS")
    series = pd.Series([0.1, 0.2, 0.3], index=idx)
    table = amo_teste._to_csv_table(series)
    assert list(table.columns) == ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
    assert table.loc[2000, "JAN"] == pytest.approx(0.1)


def test_amo_area_weighted_mean(amo_teste: AMO):
    lat = np.array([-30, 0, 30])
    lon = np.array([-40, -20])
    data = xr.DataArray(np.ones((len(lat), len(lon))), coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))
    mean = amo_teste._area_weighted_mean(data, "lon", "lat")
    assert mean.item() == pytest.approx(1.0)


def test_amo_detrend_pd(amo_teste: AMO, monkeypatch):
    idx = pd.date_range("2000-01-01", periods=10, freq="MS")
    vals = pd.Series(np.linspace(1, 5, len(idx)), index=idx)

    def fake_polyfit(x, y, deg):
        assert deg == 1
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        slope = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
        intercept = y.mean() - slope * x.mean()
        return np.array([slope, intercept])

    monkeypatch.setattr(np, "polyfit", fake_polyfit)

    detrended = amo_teste._detrend_pd(vals)
    x = np.arange(len(detrended), dtype=float)
    y = detrended.values
    slope = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
    assert abs(slope) < 1e-10


def test_amo_to_psl_text(amo_teste: AMO):
    idx = pd.date_range("2000-01-01", periods=2, freq="MS")
    series = pd.Series([0.5, -0.2], index=idx)
    text = amo_teste._to_psl_text(series, "TITULO")
    lines = text.splitlines()
    assert lines[0] == "TITULO"
    assert any("2000" in line for line in lines[2:])


def test_amo_series_to_year12_df(amo_teste: AMO):
    idx = pd.date_range("1999-12-01", periods=3, freq="MS")
    s = pd.Series([0.0, 1.0, 2.0], index=idx)
    table = amo_teste._series_to_year12_df(s, y0=1999, y1=2000)
    assert table.index.min() == 1999
    assert table.loc[2000, 2] == pytest.approx(2.0)


def test_amo_align_monthly_index(amo_teste: AMO):
    idx = pd.to_datetime(["2000-01-15", "2000-02-28"])
    s = pd.Series([1.0, 2.0], index=idx)
    aligned = amo_teste._align_monthly_index(s)
    assert list(aligned.index) == list(pd.to_datetime(["2000-01-01", "2000-02-01"]))


def test_amo_slug(amo_teste: AMO):
    assert amo_teste._slug("Nome Teste!") == "NomeTeste"
