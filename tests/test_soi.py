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

# test_soi.py
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import urllib.request

from src.atm_tools import validate_config_SOI
from src.soi import SOI


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def soi_ref(tmp_cwd):
    return SOI({"SOI_MODO": "REFERENCIA"})


def test_parse_base_range_corrige_formato(soi_ref: SOI):
    base = soi_ref._parse_base_range("1981/01a2010/12", metodo="CPC_PADRONIZADO")
    assert base == ("1981-01-01", "2010-12-31")

    default_cru = soi_ref._parse_base_range("", metodo="CRU")
    assert default_cru == ("1951-01-01", "1980-12-31")


def test_read_slp_csv_basico(soi_ref: SOI, tmp_cwd: Path):
    csv_path = tmp_cwd / "slp.csv"
    csv_path.write_text("ano;mes;slp\n2000;1;1010.1\n2000;2;1005.4\n", encoding="utf-8")

    serie = soi_ref._read_slp_csv(str(csv_path))
    assert list(serie.index) == [pd.Timestamp("2000-01-01"), pd.Timestamp("2000-02-01")]
    assert np.allclose(serie.values, [1010.1, 1005.4])


def test_monthly_standardize_pairwise(soi_ref: SOI):
    dates = pd.date_range("2000-01-01", periods=24, freq="MS")
    serie = pd.Series(np.arange(24, dtype=float), index=dates)

    res = soi_ref._monthly_standardize(serie, "2000-01-01", "2001-12-31", ddof_month=0)

    assert res.loc["2000-01-01"] == pytest.approx(-1.0)
    assert res.loc["2001-01-01"] == pytest.approx(1.0)
    assert res.loc["2000-02-01"] == pytest.approx(-1.0)


def test_monthly_anomaly(soi_ref: SOI):
    dates = pd.date_range("2000-01-01", periods=24, freq="MS")
    serie = pd.Series(np.arange(24, dtype=float), index=dates)

    res = soi_ref._monthly_anomaly(serie, "2000-01-01", "2001-12-31")

    assert res.loc["2000-01-01"] == pytest.approx(-6.0)
    assert res.loc["2001-01-01"] == pytest.approx(6.0)
    assert res.loc["2000-06-01"] == pytest.approx(-6.0)


def test_compute_cru_soi_expected_values():
    dates = pd.date_range("2000-01-01", periods=24, freq="MS")
    base = pd.Series(np.linspace(1000.0, 1023.0, len(dates)), index=dates)
    perturb = np.sin(np.linspace(0, 3 * np.pi, len(dates)))
    tah_slp = base + perturb
    dar_slp = base - perturb

    soi_cru = SOI._compute_cru_soi(tah_slp, dar_slp, base="2000-01:2001-12")

    base_start, base_end = "2000-01-01", "2001-12-31"

    base_tah = tah_slp.loc[base_start:base_end]
    mu_tah = base_tah.groupby(base_tah.index.month).mean()
    sd_tah = base_tah.groupby(base_tah.index.month).std(ddof=1)
    z_tah = (tah_slp.values - mu_tah.reindex(tah_slp.index.month).values) / sd_tah.reindex(tah_slp.index.month).values

    base_dar = dar_slp.loc[base_start:base_end]
    mu_dar = base_dar.groupby(base_dar.index.month).mean()
    sd_dar = base_dar.groupby(base_dar.index.month).std(ddof=1)
    z_dar = (dar_slp.values - mu_dar.reindex(dar_slp.index.month).values) / sd_dar.reindex(dar_slp.index.month).values

    diff = pd.Series(z_tah - z_dar, index=dates)
    sub = diff.loc[base_start:base_end]
    sd2 = sub.groupby(sub.index.month).std(ddof=1)
    expected = diff / sd2.reindex(diff.index.month).values
    expected = expected.rename("SOI_CRU_calc")

    pd.testing.assert_series_equal(soi_cru, expected)


def test_parse_cru_slp_converte_decimos():
    txt = "2000 10100 10200 10300 10400 10500 10600 10700 10800 10900 11000 11100 -990"
    serie = SOI._parse_cru_slp(txt)

    assert serie.loc[pd.Timestamp("2000-01-01")] == pytest.approx(1010.0)
    assert np.isnan(serie.loc[pd.Timestamp("2000-12-01")])


def test_validate_config_soi_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_SOI({"SOI_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] SOI_MODO inválido: FOO")


def test_validate_config_soi_teste_base_invalida():
    cfg = {"SOI_MODO": "TESTE", "SOI_TESTE_BASE_CLIMA": "xpto", "SOI_TESTE_METODO": "CRU"}
    with pytest.raises(ValueError) as exc:
        validate_config_SOI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] SOI_TESTE_BASE_CLIMA inválido: xpto")


def test_validate_config_soi_teste_metodo_invalido():
    cfg = {"SOI_MODO": "TESTE", "SOI_TESTE_BASE_CLIMA": "1981-01:2010-12", "SOI_TESTE_METODO": "foo"}
    with pytest.raises(ValueError) as exc:
        validate_config_SOI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] SOI_TESTE_METODO inválido: foo")


def test_validate_config_soi_externo_base_invalida():
    cfg = {"SOI_MODO": "EXTERNO", "SOI_EXTERNO_BASE_CLIMA": "xpto"}
    with pytest.raises(ValueError) as exc:
        validate_config_SOI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] SOI_EXTERNO_BASE_CLIMA inválido: xpto")


def test_validate_config_soi_externo_arquivo_inexistente(tmp_path):
    cfg = {
        "SOI_MODO": "EXTERNO",
        "SOI_EXTERNO_BASE_CLIMA": "1981-01:2010-12",
        "SOI_EXTERNO_TAHITI": str(tmp_path / "tah.csv"),
        "SOI_EXTERNO_DARWIN": str(tmp_path / "dar.csv"),
    }
    with pytest.raises(ValueError) as exc:
        validate_config_SOI(cfg)
    missing = tmp_path / "tah.csv"
    msg = str(exc.value)
    assert "[ERRO ARQUIVO CONFIG] Arquivo SOI_EXTERNO_TAHITI não encontrado:" in msg
    assert str(missing) in msg


def test_validate_config_soi_externo_colunas_invalidas(tmp_path):
    tah_csv = tmp_path / "tah.csv"
    dar_csv = tmp_path / "dar.csv"
    tah_csv.write_text("ano;mes;valor\n2000;1;1\n", encoding="utf-8")
    dar_csv.write_text("ano;mes;slp\n2000;1;1010\n", encoding="utf-8")
    cfg = {
        "SOI_MODO": "EXTERNO",
        "SOI_EXTERNO_BASE_CLIMA": "1981-01:2010-12",
        "SOI_EXTERNO_TAHITI": str(tah_csv),
        "SOI_EXTERNO_DARWIN": str(dar_csv),
    }
    with pytest.raises(ValueError) as exc:
        validate_config_SOI(cfg)
    msg = str(exc.value)
    assert "[ERRO ARQUIVO CONFIG] Arquivo SOI_EXTERNO_TAHITI deve conter colunas" in msg
    assert "ano" in msg and "mes" in msg and "slp" in msg
    assert "valor" in msg


def test_validate_config_soi_externo_ok(tmp_path):
    tah_csv = tmp_path / "tah.csv"
    dar_csv = tmp_path / "dar.csv"
    tah_csv.write_text("ano;mes;slp\n2000;1;1010\n", encoding="utf-8")
    dar_csv.write_text("ano;mes;slp\n2000;1;1008\n", encoding="utf-8")
    cfg = {
        "SOI_MODO": "EXTERNO",
        "SOI_EXTERNO_BASE_CLIMA": "1981-01:2010-12",
        "SOI_EXTERNO_TAHITI": str(tah_csv),
        "SOI_EXTERNO_DARWIN": str(dar_csv),
    }
    validate_config_SOI(cfg)


def test_soi_strip_and_upper():
    assert SOI._strip_inline_comment("valor # coment") == "valor"
    assert SOI._upper_unaccent("não") == "NAO"


def test_soi_series_to_year12_df(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    soi = SOI({})
    idx = pd.date_range("2000-01-01", periods=3, freq="MS")
    serie = pd.Series([0.1, 0.2, 0.3], index=idx)
    df = soi._series_to_year12_df(serie, y0=2000, y1=2000, ndigits=1)
    assert df.loc[2000, 1] == 0.1
    assert df.loc[2000, 3] == 0.3


def test_soi_resolve_base_interval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    soi_ref = SOI({})
    assert soi_ref._resolve_base_interval("CRU") == ("1951-01-01", "1980-12-31")
    assert soi_ref._resolve_base_interval("CPC") == (SOI.CPC_BASE_START, SOI.CPC_BASE_END)

    soi_test = SOI({
        "SOI_MODO": "TESTE",
        "SOI_TESTE_BASE_CLIMA": "1990-01:1991-12",
        "SOI_TESTE_METODO": "CRU",
    })
    assert soi_test._resolve_base_interval("CRU") == ("1990-01-01", "1991-12-31")


def test_soi_last_suffix_and_series_to_year12(soi_ref: SOI):
    idx1 = pd.to_datetime(["1999-12-01", "2000-01-01"])
    idx2 = pd.to_datetime(["2001-02-01"])
    suffix = soi_ref._last_suffix(pd.Series([1, 2], index=idx1), pd.Series([3], index=idx2))
    assert suffix == "200102"


def test_soi_parse_matrix_and_collect():
    txt = "2000 1.0 2.0 3.0 4.0 5.0 6.0 7.0 8.0 9.0 10.0 11.0 12.0"
    series = SOI._parse_matrix(txt, use_float=True, missing_to_nan=-99)
    assert series.index[0] == pd.Timestamp("2000-01-01")
    assert series.iloc[0] == pytest.approx(1.0)

    lines = [
        "HEADER SECTION",
        "Tahiti Sea Level Press",
        "YEAR    JAN    FEB",
        "2000    1.0    2.0",
        "2001    3.0    4.0",
        "END BLOCK",
    ]
    block = SOI._collect_after_anchor(lines, 1)
    assert "2000" in block and "2001" in block


def test_soi_extract_station_blocks():
    header = "YEAR JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC"
    months = " ".join(f"{1.0 + i:.1f}" for i in range(12))
    anoms = " ".join(f"{0.1 + 0.1*i:.1f}" for i in range(12))
    sample_std = (
        "TAHITI SEA LEVEL PRESS\n"
        "STANDARDIZED DATA\n"
        f"{header}\n"
        f"2000 {months}\n"
        f"2001 {months}\n"
        "TAHITI SEA LEVEL PRESS\n"
        "ANOMALY DATA\n"
        f"{header}\n"
        f"2000 {anoms}\n"
        f"2001 {anoms}\n"
    )
    std = SOI._extract_station_std(sample_std, "Tahiti")
    assert std.index[0] == pd.Timestamp("2000-01-01")
    anom = SOI._extract_station_anom(sample_std, "Tahiti")
    assert anom.loc[pd.Timestamp("2000-01-01")] == pytest.approx(0.1)

    slp_vals = " ".join(str(1000 + i) for i in range(1, 13))
    sample_slp = (
        "TAHITI SEA LEVEL PRESS\n"
        f"{header}\n"
        f"2000 {slp_vals}\n"
        f"2001 {slp_vals}\n"
    )
    slp = SOI._extract_station_slp(sample_slp, "Tahiti")
    assert slp.iloc[0] == pytest.approx(1001)


def test_soi_extract_diff_blocks():
    std_vals = " ".join(f"{0.5 + 0.1*i:.1f}" for i in range(12))
    anom_vals = " ".join(f"{0.1 + 0.1*i:.1f}" for i in range(12))
    header = "YEAR JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC"
    soi_text = (
        "(STAND TAHITI - STAND DARWIN) SEA LEVEL PRESS\n"
        "STANDARDIZED DATA\n"
        f"{header}\n"
        f"2000 {std_vals}\n"
        f"2001 {std_vals}\n"
        "(STAND TAHITI - STAND DARWIN) SEA LEVEL PRESS ANOMALY\n"
        f"{header}\n"
        f"2000 {anom_vals}\n"
        f"2001 {anom_vals}\n"
    )
    std = SOI._extract_diff_std(soi_text)
    assert not std.empty and std.iloc[0] == pytest.approx(0.5)
    anom = SOI._extract_diff_anom(soi_text)
    assert anom.loc[pd.Timestamp("2000-01-01")] == pytest.approx(0.1)


def test_soi_get_text_and_safe_text(tmp_cwd, monkeypatch):
    tmp_file = tmp_cwd / "local.txt"
    tmp_file.write_text("conteudo local", encoding="utf-8")
    soi = SOI({"SOI_MODO": "REFERENCIA"})
    assert soi._get_text(str(tmp_file)) == "conteudo local"

    class DummyResponse:
        def __init__(self, data):
            self._data = data.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._data

    def fake_urlopen(url):
        return DummyResponse("remoto")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    remote_txt = soi._get_text("https://example.com/data")
    assert remote_txt == "remoto"

    monkeypatch.setattr(SOI, "_get_text", lambda self, src: "")
    assert soi._safe_text("https://example.com/indisponivel", "teste") == ""
