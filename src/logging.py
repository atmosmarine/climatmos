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

from __future__ import annotations

"""
Catálogo central de mensagens padronizadas para todo o projeto.

O objetivo é substituir `print("[INFO] ...")` espalhados pelos módulos
por chamadas uniformes. A partir deste arquivo, basta chamar:

    from .logging import format_log, LOGS
    print(format_log("INFO", message="Processo iniciado"))

Caso precise de novos padrões (por exemplo, `[ERRO] ...`), cadastre via
`register_log("ERRO", "[ERRO] {detalhe}")`.
"""

from typing import Dict
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover  (py<3.9 fallback)
    ZoneInfo = None

def _now_local() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/Sao_Paulo"))
        except Exception:
            pass
    return datetime.now()

def _ts_prefix() -> str:
    return _now_local().strftime("[%Y-%m-%d %H:%M]")

# Dicionário base com os "coringas" solicitados (pode ser expandido).
LOGS: Dict[str, str] = {
    "RODANDO": "[RODANDO] {message}", 
    "PULANDO": "[PULANDO] {message}",
    "INFO": "[INFO] {message}", #
    "ATENCAO": "[ATENÇÃO] {message}", # print(format_log("ATENCAO", message=f"{msg}"))
    "ERRO": "[ERRO] {message}", # print(format_log("ERRO", message=f"Falha ao abrir {p}: {e}"))
    "DOWNLOAD": "[DOWNLOAD] {target} em {dest} → {reason}", # print(format_log("DOWNLOAD", target="ERSSTv5", dest=str(self.arquivo_nc), reason="Iniciando o download..."))
    "CACHE": "[CACHE] {action} → {path}", # print(format_log("CACHE", action="Arquivo atualizado no cache local", path=f"{fname}")) 
    "SALVO": "[SALVO] {item} {destino}", # print(format_log("SALVO", item="Tabela da variação do SOI Mensal no formato oficial →", destino=f"{csv_path}"))
    "ERRO_CONF": "[ERRO ARQUIVO CONFIG] {message}", # raise ValueError(_cfg_message("CSV externo precisa de colunas: ano/mes/slp (ou year/month/slp)."))
}

def register_log(tag: str, template: str, *, overwrite: bool = True) -> None:
    """
    Adiciona (ou atualiza) um template identificado pelo `tag`.

    Exemplos:
        register_log("ERRO", "[ERRO] {detalhe}")
        register_log("LOAD", "[LOAD] Arquivo {arquivo} carregado.")
    """
    key = (tag or "").strip().upper()
    if not key:
        raise ValueError("tag deve ser uma string não vazia.")
    if key in LOGS and not overwrite:
        raise KeyError(f"Mensagem já cadastrada para tag '{key}'; use overwrite=True.")
    LOGS[key] = template


def format_log(tag: str, /, **params) -> str:
    """
    Retorna o texto correspondente ao `tag` informado, aplicando `str.format`.

    Exemplo:
        format_log("DOWNLOAD", target="ERSSTv5", dest="data/ersst.nc", reason="arquivo ausente")
    """
    key = (tag or "").strip().upper()
    if key not in LOGS:
        raise KeyError(f"Tag '{key}' não cadastrada em LOGS.")
    return f"{_ts_prefix()} {LOGS[key].format(**params)}"


def has_log(tag: str) -> bool:
    """True se o `tag` existir no catálogo."""
    return (tag or "").strip().upper() in LOGS


def remove_log(tag: str) -> None:
    """Remove um template existente; ignora caso não exista."""
    key = (tag or "").strip().upper()
    LOGS.pop(key, None)


__all__ = ["LOGS", "register_log", "format_log", "has_log", "remove_log"]
