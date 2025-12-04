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

# test_oni.py
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.atm_tools import validate_config_ONI
from src.oni import ONI


# -----------------------
# Fixtures e utilidades
# -----------------------
@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """
    Isola diretórios de saída (ONI/* e data/*) dentro de um tmp para não sujar o projeto.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def oni_teste(tmp_cwd):
    """
    Instância em modo TESTE para facilitar asserts de paths sem baixar nada.
    """
    return ONI({
        "ONI_MODO": "TESTE",
        "ONI_TESTE_NOME": "meu_experimento",
        "ONI_TESTE_LAT_MIN": -5,
        "ONI_TESTE_LAT_MAX": 5,
        "ONI_TESTE_LON_MIN": -170,
        "ONI_TESTE_LON_MAX": -120,
        "ONI_TESTE_ANO_INICIO": 1950,
    })


# -----------------------
# Helpers básicos
# -----------------------
def test_helpers_parse_basicos(oni_teste: ONI, capsys):
    assert oni_teste._strip_comment("12.3 # note") == "12.3"
    assert oni_teste._as_float("3,14") == pytest.approx(3.14)
    assert oni_teste._as_float("x", default=7.5) == 7.5
    assert oni_teste._as_int("10") == 10
    assert oni_teste._as_int("10.7") == 10
    assert oni_teste._as_int("foo", default=9) == 9
    assert oni_teste._slug("ab c/?") == "abc"

    oni_teste.cfg["LAT_TEST"] = "95"
    lat = oni_teste._safe_float_cfg("LAT_TEST", 0.0, kind="latitude")
    assert lat == pytest.approx(90.0)

    oni_teste.cfg["LON_TEST"] = "200"
    lon = oni_teste._safe_float_cfg("LON_TEST", 0.0, normalize_lon=True)
    assert -180.0 <= lon <= 180.0

    oni_teste.cfg["ANO_TEST"] = "19490"
    ano = oni_teste._safe_int_cfg("ANO_TEST", 1950, min_val=1850, max_val=2024)
    assert ano == 1949

    logs = capsys.readouterr().out
    assert "LAT_TEST=95.0" in logs
    assert "LON_TEST=200.0" in logs
    assert "ANO_TEST=19490" in logs


# -----------------------
# __init__ e pastas/paths
# -----------------------
def test_construcao_paths_modo_teste(tmp_cwd):
    oni = ONI({
        "ONI_MODO": "TESTE",
        "ONI_TESTE_NOME": "X_Y-Z!",
        "ONI_TESTE_LAT_MIN": -5,
        "ONI_TESTE_LAT_MAX": 5,
        "ONI_TESTE_LON_MIN": -170,
        "ONI_TESTE_LON_MAX": -120,
        "ONI_TESTE_ANO_INICIO": 1950,
    })
    # OUT_DIR deve incluir slug seguro
    assert "TESTE_X_Y-Z" in str(oni.OUT_DIR)
    # Diretórios resolvidos para o modo TESTE
    assert oni.OUT_DIR.exists()
    assert oni.OUT_DIR_tables == oni.OUT_DIR
    assert oni.OUT_DIR_figs == oni.OUT_DIR
    assert oni.OUT_DIR_valida == oni.OUT_DIR
    # CSV padrão para a série mensal TOTAL
    assert oni.csv_sst_path.name.startswith("ONI_TSM-media-nino34_")
    assert oni.csv_sst_path.suffix == ".csv"
    assert oni.csv_sst_path.parent == oni.OUT_DIR_tables


def test_construcao_paths_modo_referencia(tmp_cwd):
    oni = ONI({"ONI_MODO": "REFERENCIA"})
    assert oni.OUT_DIR == Path("outputs/ONI/REFERENCIA")
    assert oni.OUT_DIR_tables == oni.OUT_DIR_figs == oni.OUT_DIR_valida == oni.OUT_DIR


def test_construcao_paths_modo_externo(tmp_cwd):
    externo_csv = tmp_cwd / "oni_externo.csv"
    externo_csv.write_text("ano;mes;tsm\n2020;1;25.0\n", encoding="utf-8")
    oni = ONI({
        "ONI_MODO": "EXTERNO",
        "ONI_EXTERNO_CAMINHO_TSM": str(externo_csv),
        "ONI_EXTERNO_TSM": "ERSSTv5-CUSTOM",
    })
    assert "EXTERNO_ERSSTv5-CUSTOM" in str(oni.OUT_DIR)
    assert oni.OUT_DIR == Path("outputs/ONI/EXTERNO_ERSSTv5-CUSTOM")


# -----------------------
# Lógica de períodos-base
# -----------------------
@pytest.mark.parametrize(
    ("ano", "esperado"),
    [
        (1952, (1936, 1965)),
        (1977, (1961, 1990)),
        (2000, (1981, 2010)),
        (2015, (1991, 2020)),  # regra >= 2011
    ],
)
def test_periodo_base(oni_teste: ONI, ano, esperado):
    b_ini, b_fim = oni_teste._periodo_base(ano, ano_max=2024)
    assert (b_ini, b_fim) == esperado


def test_periodo_base_newbase_policy(oni_teste: ONI):
    oni_teste.NEWBASE_EFFECTIVE_DATE = "2000-01-01"
    idx = pd.date_range("2000-01-01", periods=312, freq="MS")
    serie = pd.Series(np.linspace(0, 1, len(idx)), index=idx)
    oni_teste._update_base_policy(serie)

    assert oni_teste.NEWBASE_ACTIVE is True
    assert oni_teste.ANO_MAX_BASE == 2025

    assert oni_teste._periodo_base(2013, ano_max=2025) == (1996, 2025)


def test_periodo_base_premin_drop(oni_teste: ONI):
    oni_teste.PREMIN_POLICY = "DROP"
    oni_teste.ANO_MIN_SERIE = 1901
    base = oni_teste._periodo_base(1890, ano_max=1950)
    assert base is None


# -----------------------
# Sufixo e média móvel
# -----------------------
def test_sufixo_nome(oni_teste: ONI):
    idx = pd.to_datetime(["2000-01-01", "2000-02-01", "2000-12-01"])
    s = pd.Series([27.0, 28.0, 26.5], index=idx)
    assert oni_teste._sufixo_nome(s) == "122000"  # mmYYYY


def test_media_movel_trimestre_regra_min2de3(oni_teste: ONI):
    # Série mensal simples (Jan..Jun)
    dates = pd.date_range("2001-01-01", periods=6, freq="MS")
    vals = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], index=dates)
    # rolling(3, center=True).mean com regra "manter se count>=2"
    mm3 = oni_teste._media_movel_trimestre(vals)

    # Fev (Jan/Fev/Mar) → (1+2+3)/3 = 2.0
    assert mm3.loc["2001-02-01"] == pytest.approx(2.00)
    # Abr (Mar/Abr/Mai) → (3+4+5)/3 = 4.0
    assert mm3.loc["2001-04-01"] == pytest.approx(4.0)
    # Mai (Abr/Mai/Jun) → (4+5+6)/3 = 5.0
    assert mm3.loc["2001-05-01"] == pytest.approx(5.0)


# -----------------------
# Anomalia e tabela trimestral
# -----------------------
def test_anomalia_trimestral_com_climatologia_sintetica(oni_teste: ONI):
    # Constrói oni_raw de 4 anos, com padrão conhecido por mês:
    # Para simplificar, define oni_raw = (mês) como valor base,
    # e repete a sequência para ter climatologia estável.
    idx = pd.date_range("2000-01-01", periods=48, freq="MS")
    base = np.array([1,2,3,4,5,6,7,8,9,10,11,12], dtype=float)
    oni_raw = pd.Series(np.tile(base, 4), index=idx)

    # Como a climatologia por mês (média dentro da janela dinâmica) ≈ o próprio "base",
    # a anomalia deve ficar ~0.0 (com arredondamento a 0.1)
    oni_final = oni_teste._anomalia_trimestral(oni_raw)
    # pega alguns meses para conferir ~0.0
    subset = oni_final.loc["2001-01-01":"2001-12-01"]
    assert np.allclose(subset.values, 0.0, atol=0.15)


def test_tabela_trimestral_mapping(oni_teste: ONI):
    # Monta oni_final com meses 12/2001, 01/2002, 02/2002 para checar NDJ/DJF
    idx = pd.to_datetime(["2001-12-01", "2002-01-01", "2002-02-01"])
    oni_final = pd.Series([0.6, -0.4, 0.8], index=idx)
    tab = oni_teste._tabela_trimestral(oni_final)

    # Esperado: linha para Year=2001 com NDJ=+0.6
    #           linha para Year=2002 com DJF=-0.4 e FMA=+0.8? (fev → "FMA")
    assert (tab["Year"] == 2001).any()
    assert (tab["Year"] == 2002).any()

    row_2001 = tab[tab["Year"] == 2001].iloc[0]
    assert row_2001["NDJ"] == "0.6"

    row_2002 = tab[tab["Year"] == 2002].iloc[0]
    assert row_2002["DJF"] == "-0.4"
    assert row_2002["JFM"] == "0.8"


# -----------------------
# IO de CSV TOTAL
# -----------------------
def test_salvar_e_carregar_sst_csv(oni_teste: ONI, tmp_path):
    # Série TOTAL mensal artificial
    idx = pd.to_datetime(["1999-01-01", "1999-02-01", "1999-03-01"])
    serie = pd.Series([26.5, 26.7, 27.0], index=idx)

    path_csv = tmp_path / "serie_total.csv"
    oni_teste._salvar_sst_csv(serie, path_csv)

    assert path_csv.exists()
    # Carrega e compara
    carregada = oni_teste._carregar_sst_csv(path_csv)
    pd.testing.assert_index_equal(carregada.index, serie.index)
    assert np.allclose(carregada.values, serie.values)


def test_exportar_mensal_e_trimestral_df(oni_teste: ONI):
    tabela = pd.DataFrame(
        [
            {"Year": 2001, "NDJ": "0.6"},
            {"Year": 2002, "DJF": "-0.4", "JFM": "0.8"},
        ]
    )
    csv_path = oni_teste._exportar_mensal_de_tabela(tabela)
    assert csv_path.exists()

    mensal = pd.read_csv(csv_path)
    assert mensal["data"].tolist() == ["2001-12-01", "2002-01-01", "2002-02-01"]
    assert mensal["oni"].round(1).tolist() == [0.6, -0.4, 0.8]

    trimestral = oni_teste._montar_trimestral_df(tabela)
    assert list(trimestral.columns) == ["YR", "TRIM", "ONI"]
    assert trimestral["ONI"].dtype.kind == "f"
    assert trimestral["TRIM"].tolist() == ["NDJ", "DJF", "JFM"]

def test_validate_config_oni_requires_nome_teste():
    cfg = {"ONI_MODO": "TESTE", "ONI_TESTE_ANO_INICIO": 1950,
           "ONI_TESTE_LAT_MIN": -5, "ONI_TESTE_LAT_MAX": 5,
           "ONI_TESTE_LON_MIN": -170, "ONI_TESTE_LON_MAX": -120}
    with pytest.raises(ValueError) as exc:
        validate_config_ONI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] ONI_TESTE_NOME obrigatório no modo TESTE")


def test_validate_config_oni_externo_ok(tmp_path):
    csv_path = tmp_path / "oni.csv"
    csv_path.write_text("ano;mes;tsm\n2000;1;26.5\n", encoding="utf-8")
    cfg = {"ONI_MODO": "EXTERNO", "ONI_EXTERNO_CAMINHO_TSM": str(csv_path)}
    validate_config_ONI(cfg)  # não deve lançar


def test_validate_config_oni_externo_arquivo_inexistente(tmp_path):
    missing = tmp_path / "nao_existe.csv"
    cfg = {"ONI_MODO": "EXTERNO", "ONI_EXTERNO_CAMINHO_TSM": str(missing)}
    with pytest.raises(ValueError) as exc:
        validate_config_ONI(cfg)
    msg = str(exc.value)
    assert "[ERRO ARQUIVO CONFIG] Arquivo ONI externo não encontrado:" in msg
    assert str(missing) in msg


def test_validate_config_oni_externo_colunas_invalidas(tmp_path):
    csv_path = tmp_path / "oni.csv"
    csv_path.write_text("ano;mes;valor\n2000;1;26.5\n", encoding="utf-8")
    cfg = {"ONI_MODO": "EXTERNO", "ONI_EXTERNO_CAMINHO_TSM": str(csv_path)}
    with pytest.raises(ValueError) as exc:
        validate_config_ONI(cfg)
    msg = str(exc.value)
    assert "[ERRO ARQUIVO CONFIG] ONI externo deve conter colunas" in msg
    assert "ano" in msg and "mes" in msg and "tsm" in msg
    assert "valor" in msg


def test_validate_config_oni_ano_inicio_invalido():
    cfg = {
        "ONI_MODO": "TESTE",
        "ONI_TESTE_NOME": "nome",
        "ONI_TESTE_ANO_INICIO": "foo",
        "ONI_TESTE_LAT_MIN": -5,
        "ONI_TESTE_LAT_MAX": 5,
        "ONI_TESTE_LON_MIN": -170,
        "ONI_TESTE_LON_MAX": -120,
    }
    with pytest.raises(ValueError) as exc:
        validate_config_ONI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] ONI_TESTE_ANO_INICIO inválido: foo")


def test_validate_config_oni_modo_desconhecido():
    cfg = {"ONI_MODO": "FOO"}
    with pytest.raises(ValueError) as exc:
        validate_config_ONI(cfg)
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] ONI_MODO inválido: FOO")


def test_oni_lat_lon_clamped_e_invertido(tmp_cwd, capsys):
    oni = ONI({
        "ONI_MODO": "TESTE",
        "ONI_TESTE_NOME": "teste",
        "ONI_TESTE_LAT_MIN": 120,
        "ONI_TESTE_LAT_MAX": -120,
        "ONI_TESTE_LON_MIN": -400,
        "ONI_TESTE_LON_MAX": 400,
        "ONI_TESTE_ANO_INICIO": 1950,
    })
    assert -90.0 <= oni.lat_min <= 90.0
    assert -90.0 <= oni.lat_max <= 90.0
    assert oni.lat_min < oni.lat_max
    assert -180.0 <= oni.lon_min <= 180.0
    assert -180.0 <= oni.lon_max <= 180.0



# -----------------------
# Download (HEAD) sem rede
# -----------------------
def _fake_head_response(headers_dict):
    class _R:
        def __init__(self, h): self.headers = h
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
    return _R(headers_dict)


def test_download_pula_quando_arquivo_atualizado(tmp_cwd, monkeypatch):
    oni = ONI({"ONI_MODO": "REFERENCIA"})
    # Cria arquivo local vazio
    oni.arquivo_nc.write_bytes(b"")
    # Ajusta mtime local para ser mais novo que remoto
    local_mtime = 2_000_000_000  # timestamp futuro
    os.utime(oni.arquivo_nc, (local_mtime, local_mtime))

    # Simula HEAD com Last-Modified mais antigo + Content-Length=0
    lm_remote = "Tue, 01 Jan 2019 00:00:00 GMT"
    headers = {"Last-Modified": lm_remote, "Content-Length": "0"}

    def fake_urlopen(req, timeout=30):
        assert req.method == "HEAD"
        return _fake_head_response(headers)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    # urlretrieve não deve ser chamado
    monkeypatch.setattr("urllib.request.urlretrieve", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Não era para baixar")))

    # Executa
    oni._download()


def test_download_atualiza_quando_remoto_mais_novo(tmp_cwd, monkeypatch):
    oni = ONI({"ONI_MODO": "REFERENCIA"})
    oni.arquivo_nc.write_bytes(b"old")
    # mtime local antigo
    local_mtime = 1_600_000_000
    os.utime(oni.arquivo_nc, (local_mtime, local_mtime))

    # HEAD indica Last-Modified mais novo
    lm_remote = "Tue, 01 Jan 2023 00:00:00 GMT"
    headers = {"Last-Modified": lm_remote, "Content-Length": "3"}

    def fake_urlopen(req, timeout=30):
        return _fake_head_response(headers)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    # Simula download criando arquivo temporário "conteudo_novo"
    tmp_download = (oni.DATA_DIR / "tmp_download.nc")
    tmp_download.write_bytes(b"new")

    def fake_urlretrieve(url):
        # retorna (arquivo_tmp, headers)
        return str(tmp_download), None

    moved = {"called": False}

    def fake_move(src, dst):
        moved["called"] = True
        # copia para destino
        Path(dst).write_bytes(Path(src).read_bytes())

    monkeypatch.setattr("urllib.request.urlretrieve", lambda url: fake_urlretrieve(url))
    monkeypatch.setattr("shutil.move", fake_move)

    oni._download()
    assert moved["called"] is True
    assert oni.arquivo_nc.read_bytes() == b"new"
