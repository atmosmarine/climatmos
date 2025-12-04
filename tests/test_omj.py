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

# test_omj.py
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from src.omj import OMJ
from src.atm_tools import validate_config_OMJ


def test_validate_config_omj_modo_invalido():
    with pytest.raises(ValueError) as exc:
        validate_config_OMJ({"OMJ_MODO": "foo"})
    assert str(exc.value).endswith("[ERRO ARQUIVO CONFIG] OMJ_MODO inválido: foo")


def test_validate_config_omj_externo_olr_obrigatorio():
    cfg = {
        "OMJ_MODO": "EXTERNO",
        "OMJ_EXTERNO_U850": "default",
        "OMJ_EXTERNO_U200": "default",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_OMJ(cfg)
    expected = "[ERRO ARQUIVO CONFIG] Informe OMJ_EXTERNO_OLR ou OMJ_EXTERNO_CAMINHO_OLR no modo EXTERNO."
    assert str(exc.value).endswith(expected)


def test_validate_config_omj_externo_caminho_inexistente(tmp_path):
    cfg = {
        "OMJ_MODO": "EXTERNO",
        "OMJ_EXTERNO_OLR": str(tmp_path / "olr.nc"),
        "OMJ_EXTERNO_U850": "default",
        "OMJ_EXTERNO_U200": "default",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_OMJ(cfg)
    expected = f"[ERRO ARQUIVO CONFIG] Caminho inexistente em OMJ_EXTERNO_OLR: {tmp_path / 'olr.nc'}"
    assert str(exc.value).endswith(expected)


def test_validate_config_omj_externo_diretorio_sem_nc(tmp_path):
    empty_dir = tmp_path / "dados"
    empty_dir.mkdir()
    (empty_dir / "arquivo.txt").write_text("dummy", encoding="utf-8")
    cfg = {
        "OMJ_MODO": "EXTERNO",
        "OMJ_EXTERNO_OLR": str(empty_dir),
        "OMJ_EXTERNO_U850": "default",
        "OMJ_EXTERNO_U200": "default",
    }
    with pytest.raises(ValueError) as exc:
        validate_config_OMJ(cfg)
    expected = f"[ERRO ARQUIVO CONFIG] Diretório {empty_dir} em OMJ_EXTERNO_OLR não contém arquivos no formato .nc."
    assert str(exc.value).endswith(expected)


def test_validate_config_omj_externo_ok_com_sentinelas():
    cfg = {
        "OMJ_MODO": "EXTERNO",
        "OMJ_EXTERNO_OLR": "default",
        "OMJ_EXTERNO_U850": "default",
        "OMJ_EXTERNO_U200": "default",
    }
    validate_config_OMJ(cfg)


def test_omj_resolved_path_behaviour(tmp_path):
    files = (tmp_path / "a.nc", tmp_path / "b.nc")
    for f in files:
        f.write_text("data", encoding="utf-8")

    resolved = OMJ._ResolvedPath("pattern", tuple(files))

    assert len(resolved) == 2
    assert resolved.name.startswith("a.nc")
    assert list(resolved) == list(files)
    assert resolved.as_open_args() == [str(files[0]), str(files[1])]
    text = str(resolved)
    assert "pattern" in text and files[1].name in text


def test_omj_parse_config_file(tmp_path):
    cfg_file = tmp_path / "omj.conf"
    cfg_file.write_text(
        """
        # Comentário
        OMJ_MODO = EXTERNO  # outro comentário
        CHAVE=A
        invalido
        =sem_chave
        """,
        encoding="utf-8",
    )
    parsed = OMJ._parse_config_file(cfg_file)
    assert parsed["OMJ_MODO"] == "EXTERNO"
    assert parsed["CHAVE"] == "A"
    assert "invalido" not in parsed


def test_omj_parse_bom_rmm_text():
    text = """# header\n1999 12 30 1.0 2.0 3 1.1\n2000 01 01 0.5 -0.5 4 0.8\n"""
    omj = OMJ.__new__(OMJ)
    df = OMJ._parse_bom_rmm_text(omj, text)
    assert list(df.columns) == ["rmm1", "rmm2", "phase", "amplitude"]
    assert df.index.min() == pd.Timestamp("1999-12-30")
    assert df.loc[pd.Timestamp("2000-01-01"), "amplitude"] == pytest.approx(0.8)


def test_omj_parse_str_list():
    assert OMJ._parse_str_list(None) == []
    assert OMJ._parse_str_list([" a ", ""]) == ["a"]
    assert OMJ._parse_str_list("x; y ,z") == ["x", "y", "z"]


def test_omj_resolve_external_path(tmp_path):
    data_dir = tmp_path / "dados"
    data_dir.mkdir()
    file_a = data_dir / "a.nc"
    file_b = data_dir / "b.nc"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")
    (data_dir / "ignorar.txt").write_text("x", encoding="utf-8")

    omj = OMJ.__new__(OMJ)
    omj.cfg = {
        "OMJ_TESTE_CAMINHO": f"{data_dir}/*.nc, {file_a}",
    }
    resolved = omj._resolve_external_path("OMJ_TESTE_CAMINHO")
    assert isinstance(resolved, OMJ._ResolvedPath)
    assert resolved.raw.startswith(str(data_dir))
    assert list(resolved.paths) == [file_a, file_b]


def test_omj_resolve_external_path_sentinel():
    omj = OMJ.__new__(OMJ)
    omj.cfg = {"OMJ_TESTE_CAMINHO": "default"}
    assert omj._resolve_external_path("OMJ_TESTE_CAMINHO", {"default"}) is None


def test_omj_name_with_suffix():
    omj = OMJ.__new__(OMJ)
    omj.SUF_EXEC = "202401"
    assert omj._name_with_suffix("arquivo.txt") == "arquivo_202401.txt"
    assert omj._name_with_suffix("semext") == "semext_202401"


def test_omj_step_context_logs(capsys):
    omj = OMJ.__new__(OMJ)
    with omj.Step("Processo principal"):
        with omj.Step("Interno"):
            pass
    out = capsys.readouterr().out
    assert "|Início do Processo| → Processo principal" in out
    assert "  |Início do Processo| → Interno" in out
    assert "|Final do Processo| → Processo principal" in out


def test_omj_needs_download_year_when_missing(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    monkeypatch.setattr(omj, "_head_last_modified", lambda url: pd.Timestamp("2023-01-01", tz="UTC"))

    urls = ["https://example.com/{year}/file.nc"]
    dest = tmp_path / "uwnd.2024.nc"
    needs, chosen = omj._needs_download_year(urls, 2024, dest)
    assert needs is True
    assert chosen == urls[0].format(year=2024)


def test_omj_needs_download_year_up_to_date(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    dest = tmp_path / "uwnd.2000.nc"
    dest.write_text("data", encoding="utf-8")
    now = time.time()
    os.utime(dest, (now, now))

    monkeypatch.setattr(omj, "_head_last_modified", lambda url: pd.Timestamp("2000-01-01", tz="UTC"))
    urls = ["https://example.com/{year}/file.nc", "https://mirror/{year}/file.nc"]
    needs, chosen = omj._needs_download_year(urls, 2000, dest)
    assert needs is False
    assert chosen is None


def test_omj_needs_download_year_age_threshold(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    dest = tmp_path / "uwnd.1990.nc"
    dest.write_text("data", encoding="utf-8")
    old = time.time() - 60 * 60 * 24 * 40
    os.utime(dest, (old, old))

    monkeypatch.setattr(omj, "_head_last_modified", lambda url: None)
    urls = ["https://example.com/{year}/file.nc"]
    needs, chosen = omj._needs_download_year(urls, 1990, dest)
    assert needs is True
    assert chosen == urls[0].format(year=1990)


def test_omj_needs_download_remote_newer(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    dest = tmp_path / "olr.nc"
    dest.write_text("data", encoding="utf-8")
    old = time.time() - 60 * 60 * 24 * 2
    os.utime(dest, (old, old))

    monkeypatch.setattr(omj, "_head_last_modified", lambda url: pd.Timestamp.utcnow())
    assert omj._needs_download("https://example.com/olr.nc", dest) is True


def test_omj_needs_download_remote_none(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    dest = tmp_path / "olr.day.mean_1991-presente.nc"
    dest.write_text("data", encoding="utf-8")
    old = time.time() - 60 * 60 * 24 * 2
    os.utime(dest, (old, old))

    monkeypatch.setattr(omj, "_head_last_modified", lambda url: None)
    assert omj._needs_download("https://example.com/olr.nc", dest) is True


def test_omj_needs_download_remote_recent(tmp_path, monkeypatch):
    omj = OMJ.__new__(OMJ)
    dest = tmp_path / "olr.nc"
    dest.write_text("data", encoding="utf-8")
    now = time.time()
    os.utime(dest, (now, now))

    recent = pd.Timestamp.utcnow() - pd.Timedelta(hours=1)
    monkeypatch.setattr(omj, "_head_last_modified", lambda url: recent)
    assert omj._needs_download("https://example.com/olr.nc", dest) is False
