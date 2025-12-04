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

# test_pdo.py
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pytest
import urllib.request
import xarray as xr

from src.pdo import PDO
from src.atm_tools import validate_config_PDO


@pytest.fixture
def pdo_teste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(PDO, "_ensure_core_inputs", lambda self: None)
    monkeypatch.setattr(PDO, "_download_nc_with_checks", lambda *args, **kwargs: None)
    cfg = {
        "PDO_MODO": "TESTE",
        "PDO_TESTE_LAT_MIN": 20,
        "PDO_TESTE_LAT_MAX": 70,
        "PDO_TESTE_LON_MIN": 110,
        "PDO_TESTE_LON_MAX": 260,
        "PDO_TESTE_BASE_CLIMA": "1981-01:2010-12",
    }
    return PDO(cfg)


def test_validate_config_pdo_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_PDO({"PDO_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] PDO_MODO inválido: foo")


def test_validate_config_pdo_teste_lat_min_ausente():
    cfg = {"PDO_MODO": "TESTE"}
    with pytest.raises(ValueError) as exc:
        validate_config_PDO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] PDO_TESTE_LAT_MIN não informado.")


def test_validate_config_pdo_teste_lat_faixa_invalida():
    cfg = {
        "PDO_MODO": "TESTE",
        "PDO_TESTE_LAT_MIN": "10",
        "PDO_TESTE_LAT_MAX": "5",
        "PDO_TESTE_LON_MIN": "-180",
        "PDO_TESTE_LON_MAX": "180",
        "PDO_TESTE_BASE_CLIMA": "1981-01:2010-12",
        "PDO_TESTE_FIT_PERIODO": "TOTAL",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_PDO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] Faixa latitudinal inválida: 10.0 ≥ 5.0")


def test_validate_config_pdo_teste_periodo_formato_invalido():
    cfg = {
        "PDO_MODO": "TESTE",
        "PDO_TESTE_LAT_MIN": "-50",
        "PDO_TESTE_LAT_MAX": "50",
        "PDO_TESTE_LON_MIN": "-180",
        "PDO_TESTE_LON_MAX": "180",
        "PDO_TESTE_BASE_CLIMA": "1981-01",  # sem intervalo completo
        "PDO_TESTE_FIT_PERIODO": "1981-01:2010-12",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_PDO(cfg)
    expected = "[ERRO ARQUIVO CONFIG] PDO_TESTE_BASE_CLIMA deve estar no formato AAAA-MM:AAAA-MM, recebido: '1981-01'"
    assert str(exc.value).endswith(expected)


def test_validate_config_pdo_externo_caminho_inexistente(tmp_path):
    missing = tmp_path / "pdo.csv"
    cfg = {"PDO_MODO": "EXTERNO", "PDO_EXTERNO_CAMINHO": str(missing)}
    with pytest.raises(ValueError) as exc:
        validate_config_PDO(cfg)
    expected = f"[ERRO ARQUIVO CONFIG] Arquivo externo PDO não encontrado: {missing}"
    assert str(exc.value).endswith(expected)


def test_validate_config_pdo_externo_base_periodo_normalizado(tmp_path):
    csv_path = tmp_path / "pdo.csv"
    csv_path.write_text("ano;mes;indice\n2000;1;0.1\n", encoding="utf-8")
    cfg = {
        "PDO_MODO": "EXTERNO",
        "PDO_EXTERNO_CAMINHO": str(csv_path),
        "PDO_EXTERNO_FIT_PERIODO": "TOTAL",
        "PDO_EXTERNO_BASE_CLIMA": "1981-01 : 2010-12",
        "PDO_EXTERNO_LAT_MIN": "-10",
        "PDO_EXTERNO_LAT_MAX": "10",
        "PDO_EXTERNO_LON_MIN": "-180",
        "PDO_EXTERNO_LON_MAX": "180",
    }
    validate_config_PDO(cfg)
    assert cfg["PDO_EXTERNO_BASE_CLIMA"] == "1981-01:2010-12"


def test_validate_config_pdo_externo_lat_invalida(tmp_path):
    csv_path = tmp_path / "pdo.csv"
    csv_path.write_text("ano;mes;indice\n2000;1;0.1\n", encoding="utf-8")
    cfg = {
        "PDO_MODO": "EXTERNO",
        "PDO_EXTERNO_CAMINHO": str(csv_path),
        "PDO_EXTERNO_FIT_PERIODO": "TOTAL",
        "PDO_EXTERNO_BASE_CLIMA": "1981-01:2010-12",
        "PDO_EXTERNO_LAT_MIN": "30",
        "PDO_EXTERNO_LAT_MAX": "20",
        "PDO_EXTERNO_LON_MIN": "-180",
        "PDO_EXTERNO_LON_MAX": "180",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_PDO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] Faixa latitudinal externa inválida: 30.0 ≥ 20.0")


def test_validate_config_pdo_teste_ok():
    cfg = {
        "PDO_MODO": "TESTE",
        "PDO_TESTE_LAT_MIN": "-60",
        "PDO_TESTE_LAT_MAX": "65",
        "PDO_TESTE_LON_MIN": "120",
        "PDO_TESTE_LON_MAX": "240",
        "PDO_TESTE_BASE_CLIMA": "1981-01:2010-12",
        "PDO_TESTE_FIT_PERIODO": "NCEI",
    }
    validate_config_PDO(cfg)


def _sample_sst():
    times = pd.date_range("2000-01-01", periods=3, freq="MS")
    lats = np.array([70, 60, 50])
    lons = np.array([350, 10])
    data = np.arange(times.size * lats.size * lons.size, dtype=float).reshape(len(times), len(lats), len(lons))
    return xr.DataArray(data, coords={"time": times, "lat": lats, "lon": lons}, dims=("time", "lat", "lon"))


def test_pdo_to_month_start():
    times = pd.to_datetime(["2000-01-15", "2000-02-20"])
    result = PDO._to_month_start(times)
    assert list(result) == list(pd.to_datetime(["2000-01-01", "2000-02-01"]))


def test_pdo_normalize_lon_and_slice_lat():
    sst = _sample_sst()
    normalized = PDO._normalize_lon(sst)
    assert np.all((normalized.lon.values >= 0) & (normalized.lon.values < 360))
    assert list(normalized.lon.values) == sorted(normalized.lon.values.tolist())

    # lat descending -> slice should swap bounds automatically
    sliced = PDO._slice_lat(normalized, 55, 75)
    assert sliced.lat.min() >= 55 and sliced.lat.max() <= 75


def test_pdo_prepare_region_and_eof(monkeypatch, pdo_teste: PDO):
    sst = _sample_sst()
    normalized = PDO._normalize_lon(sst)

    region = pdo_teste._prepare_region(normalized, lat_min=50, lat_max=70, lon_min=0, lon_max=40)
    assert set(region.dims) == {"time", "lat", "lon"}

    def fake_svd(X, full_matrices=False):
        m, n = X.shape
        size = min(m, n)
        U = np.eye(m)
        S = np.linspace(3.0, 1.0, size)
        Vt = np.eye(n)
        return U, S, Vt

    monkeypatch.setattr(np.linalg, "svd", fake_svd)
    pdo_index, eof_map, variance = pdo_teste._leading_eof(region)
    assert isinstance(pdo_index, pd.Series)
    assert len(pdo_index) == region.time.size
    assert eof_map.dims == ("lat", "lon")
    assert 0.0 <= variance <= 1.0


def test_pdo_leading_eof_flip(monkeypatch, pdo_teste: PDO):
    times = pd.date_range("2000-01-01", periods=4, freq="MS")
    lat = np.array([60, 50])
    lon = np.array([200, 220])
    data = np.arange(4 * 2 * 2, dtype=float).reshape(4, 2, 2)
    region = xr.DataArray(data, coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))

    def fake_svd(X, full_matrices=False):
        m, n = X.shape
        U = np.eye(m)
        S = np.linspace(5.0, 2.0, min(m, n))
        Vt = np.eye(n)
        return U, S, Vt

    monkeypatch.setattr(np.linalg, "svd", fake_svd)
    series, eof_map, explained = pdo_teste._leading_eof(region)
    assert isinstance(series, pd.Series)
    assert explained > 0.0


def test_pdo_prepare_region_empty(tmp_path):
    sst = _sample_sst()
    normalized = PDO._normalize_lon(sst)
    with pytest.raises(ValueError):
        PDO.__new__(PDO)._prepare_region(normalized, lat_min=-10, lat_max=-5, lon_min=100, lon_max=120)


def test_pdo_leading_eof_flip(monkeypatch, pdo_teste: PDO):
    times = pd.date_range("2000-01-01", periods=4, freq="MS")
    lat = np.array([60, 50])
    lon = np.array([200, 220])
    data = np.arange(4 * 2 * 2, dtype=float).reshape(4, 2, 2)
    region = xr.DataArray(data, coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))

    def fake_svd(X, full_matrices=False):
        m, n = X.shape
        U = np.eye(m)
        S = np.linspace(5.0, 2.0, min(m, n))
        Vt = np.eye(n)
        return U, S, Vt

    monkeypatch.setattr(np.linalg, "svd", fake_svd)
    series, eof_map, explained = pdo_teste._leading_eof(region)
    assert isinstance(series, pd.Series)
    assert explained > 0.0


def test_pdo_http_head(monkeypatch, pdo_teste: PDO):
    class DummyResponse:
        def __init__(self, headers):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=60):
        assert isinstance(req, urllib.request.Request)
        return DummyResponse({"Last-Modified": "Wed, 01 Jan 2020 00:00:00 GMT"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    headers = PDO._http_head("https://example.com")
    assert "Last-Modified" in headers


def test_pdo_read_ncei_offline(tmp_path, monkeypatch, pdo_teste: PDO):
    dummy_txt = "2010    0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1.0 1.1 1.2"
    cache = pdo_teste.NCEI_CACHE
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(dummy_txt, encoding="utf-8")

    def fake_urlopen(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    series = pdo_teste.read_ncei_official("https://example.com/pdo.dat")
    assert isinstance(series, pd.Series)
    assert not series.empty
