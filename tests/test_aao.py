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

# test_aao.py
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from src.aao import AAO
from src.atm_tools import validate_config_AAO


def test_validate_config_aao_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_AAO({"AAO_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_MODO inválido: FOO")


def test_validate_config_aao_teste_nivel_invalido():
    cfg = {"AAO_MODO": "TESTE", "AAO_TESTE_NIVEL_Z": "abc"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_TESTE_NIVEL_Z inválido: abc")


def test_validate_config_aao_teste_base_invalida():
    cfg = {"AAO_MODO": "TESTE", "AAO_TESTE_BASE_CLIMA": "2000-01:1999-12"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_TESTE_BASE_CLIMA inválido: 2000-01:1999-12")


def test_validate_config_aao_base_periodo_inconsistente():
    cfg = {"AAO_BASE_START": "2020-01-01", "AAO_BASE_END": "2010-01-01"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    expected = "[ERRO ARQUIVO CONFIG] AAO_BASE_END (2010-01-01) deve ser posterior a AAO_BASE_START (2020-01-01)."
    assert str(exc.value).endswith(expected)


def test_validate_config_aao_level_nao_positivo():
    cfg = {"AAO_LEVEL_HPA": "-10"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_LEVEL_HPA deve ser positivo: -10")


def test_validate_config_aao_include_20s_invalido():
    cfg = {"AAO_INCLUDE_20S": "talvez"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_INCLUDE_20S inválido: talvez")


def test_validate_config_aao_ddof_negativo():
    cfg = {"AAO_STD_DDOF": "-1"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_STD_DDOF deve ser >= 0: -1")


def test_validate_config_aao_externo_caminho_obrigatorio():
    cfg = {"AAO_MODO": "EXTERNO", "AAO_EXTERNO_CAMINHO": ""}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    expected = "[ERRO ARQUIVO CONFIG] AAO_EXTERNO_CAMINHO obrigatório no modo EXTERNO."
    assert str(exc.value).endswith(expected)


def test_validate_config_aao_externo_caminho_inexistente(tmp_path):
    missing = tmp_path / "dados.nc"
    cfg = {"AAO_MODO": "EXTERNO", "AAO_EXTERNO_CAMINHO": str(missing)}
    with pytest.raises(FileNotFoundError) as exc:
        validate_config_AAO(cfg)
    expected = f"[ERRO ARQUIVO CONFIG] Arquivo indicado em AAO_EXTERNO_CAMINHO não encontrado: {missing}"
    assert str(exc.value).endswith(expected)


def test_validate_config_aao_externo_inicio_invalido():
    cfg = {"AAO_MODO": "EXTERNO", "AAO_EXTERNO_CAMINHO": __file__, "AAO_EXTERNO_INICIO": "foo"}
    with pytest.raises(ValueError) as exc:
        validate_config_AAO(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] AAO_EXTERNO_INICIO inválido: foo")


def test_aao_parse_helpers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    aao = AAO({
        "AAO_MODO": "TESTE",
        "AAO_TESTE_NIVEL_Z": "700",
        "AAO_TESTE_LAT_MAX": "-30",
        "AAO_TESTE_BASE_CLIMA": "1980-01:1990-12",
    })

    assert AAO._slug("Áreas 123!") == "Areas_123"
    assert AAO._parse_bool("Sim") is True
    assert AAO._parse_bool("no") is False
    assert AAO._parse_int("08", default=5, min_val=3) == 8
    assert AAO._parse_int("2", default=5, min_val=3) == 5
    assert AAO._parse_float("3,14", default=0.0) == pytest.approx(3.14)
    assert AAO._parse_str_list("a,b; c") == ["a", "b", "c"]
    assert AAO._parse_tuple("10,20", (0.0, 1.0)) == (10.0, 20.0)
    assert AAO._parse_float_tuple("1.5,2.5", (0.0, 1.0)) == (1.5, 2.5)

    custom_dir = tmp_path / "custom"
    path = aao._resolve_dir("AAO_OUTDIR", custom_dir)
    assert path == custom_dir


@pytest.fixture
def aao_teste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "AAO_MODO": "TESTE",
        "AAO_TESTE_NOME": "Caso",
        "AAO_TESTE_NIVEL_Z": "700",
        "AAO_TESTE_LAT_MAX": "-25",
        "AAO_TESTE_BASE_CLIMA": "1980-01:1990-12",
        "AAO_BASE_START": "1980-01-01",
        "AAO_BASE_END": "1990-12-31",
    }
    return AAO(cfg)


def test_aao_init_outputs_dirs(aao_teste: AAO):
    assert aao_teste.out_dir.exists()
    assert aao_teste.tab_dir == aao_teste.out_dir
    assert aao_teste.level_hpa == 700
    assert aao_teste.lat_max == pytest.approx(-25.0)


def test_aao_lat_weights():
    weights = AAO._lat_weights_sqrtcos([-90, -60, 0, 60, 90])
    assert weights[0] == pytest.approx(0.0, abs=1e-6)
    assert weights[2] == pytest.approx(1.0, abs=1e-6)


def test_aao_robust_sel_lat(aao_teste: AAO):
    times = pd.date_range("2000-01-01", periods=3, freq="MS")
    lat = np.array([-40, -30, -20, -10])
    lon = np.array([0, 10])
    data = np.arange(len(times) * len(lat) * len(lon)).reshape(len(times), len(lat), len(lon))
    da = xr.DataArray(data, coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))
    subset = AAO._robust_sel_lat(da, lat_max=-25.0, include_20S=False)
    assert subset.sizes["lat"] == 2


def test_aao_build_base_mask():
    times = pd.date_range("2000-01-01", periods=4, freq="MS")
    lat = np.array([-30, -20])
    lon = np.array([0, 10])
    data = np.ones((len(times), len(lat), len(lon)))
    da = xr.DataArray(data, coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))
    mask = AAO._build_base_mask(da)
    assert mask.all()


def test_aao_compute_loading_eof1(monkeypatch):
    times = pd.date_range("2000-01-01", periods=5, freq="MS")
    lat = np.array([-40, -30])
    lon = np.array([0, 10])
    data = np.random.rand(len(times), len(lat), len(lon))
    da = xr.DataArray(data, coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))

    def fake_svd(X, full_matrices=False):
        m, n = X.shape
        size = min(m, n)
        U = np.eye(m)
        S = np.linspace(3.0, 1.0, size)
        Vt = np.eye(n)
        return U, S, Vt

    monkeypatch.setattr(np.linalg, "svd", fake_svd)
    eof1, pc1, s1, var_exp, mask = AAO._compute_loading_eof1(da)
    assert isinstance(eof1, xr.DataArray)
    assert pc1.size == len(times)
    assert 0.0 <= var_exp <= 1.0
    assert mask.all()


def test_aao_project_pc1():
    times = pd.date_range("2000-01-01", periods=3, freq="MS")
    lat = np.array([-40, -30])
    lon = np.array([0, 10])
    base = xr.DataArray(np.random.rand(len(times), len(lat), len(lon)), coords={"time": times, "lat": lat, "lon": lon}, dims=("time", "lat", "lon"))
    eof1 = base.isel(time=0)
    mask = AAO._build_base_mask(base)
    pc = AAO._project_pc1(base, eof1, mask)
    assert isinstance(pc, xr.DataArray)
    assert pc.dims == ("time",)


def test_aao_standardize_base():
    times = pd.date_range("2000-01-01", periods=6, freq="MS")
    pc = xr.DataArray(np.arange(6, dtype=float), coords={"time": times}, dims=("time",))
    std_pc, mu, sd = AAO._standardize_base(pc, times[0], times[-1], ddof=0)
    assert pytest.approx(mu) == np.mean(pc.values)
    assert pytest.approx(sd) == np.std(pc.values, ddof=0)
    assert std_pc.mean().round(7) == 0.0
