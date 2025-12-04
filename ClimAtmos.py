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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo
import io
from pathlib import Path
import sys
import pandas as pd

# Carrega módulos utilitários compartilhados (mantém efeitos de importação)
from src import imports as _shared_imports  # noqa: F401
from src import atm_tools as _shared_tools  # noqa: F401
from src.logging import format_log


class _SelectiveStream(io.TextIOBase):
    def __init__(self, stream: io.TextIOBase, level: int):
        self._stream = stream
        self._level = level
        self._buffer = ""

    def write(self, data):
        if not data:
            return 0
        self._buffer += data
        count = len(data)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line + "\n")
        return count

    def flush(self):
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""
        self._stream.flush()

    def _emit(self, text: str):
        if self._should_emit(text):
            self._stream.write(text)

    def _should_emit(self, text: str) -> bool:
        level = self._level
        if level >= 2:
            return True
        upper = text.upper()
        if any(token in upper for token in ("[ERRO", "[WARN", "TRACEBACK", "EXCEPTION")):
            return True
        base_tokens = (
            "********** INICIANDO",
            "REGISTRANDO LOG",
            "EXECUTANDO NO MODO",
            "NÃO → NÃO SERÁ EXECUTADO",
            "NAO → NÃO SERÁ EXECUTADO",
        )
        if any(token in upper for token in base_tokens):
            return True
        if level == 1 and "SALVO" in upper:
            return True
        return False

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


class _StdoutTee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()

    def isatty(self):
        return any(getattr(stream, "isatty", lambda: False)() for stream in self._streams)


def _sanitize_segment(txt: str) -> str:
    if not txt:
        return "UNDEFINED"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(txt).upper())


# Importa as classes dos índices individualmente
from src.aao import AAO
from src.amo import AMO
from src.mei import MEI
from src.omj import OMJ
from src.oni import ONI
from src.pdo import PDO
from src.soi import SOI

# ----------------------------- CLI -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Executa índices (ONI/AMO/PDO/SOI/MEI/PSL/OMJ/AAO) com base no config.txt.")
    p.add_argument("--config", "-c", default="template.conf", help="Caminho para o arquivo de configuração (padrão: config.txt).")
    return p.parse_args()

# ------------------------- CONFIG LOADER ------------------------
def load_config(path: str) -> dict:
    cfg = {}
    if not path:
        return cfg
    p = Path(path)
    if not p.exists():
        print(format_log("ATENCAO", message=f"Arquivo de configuração não encontrado: {p.resolve()} → usando defaults embutidos."))
        return cfg

    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or set(line) <= set("= -_*/\\|"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            # Não remova ';' – precisamos dele em campos como OMJ_BASE_CLIMA
            v = v.split("#", 1)[0].strip()
            if not k:
                continue
            cfg[k] = v
    return cfg


# ----------------------- PARSERS AUXILIARES ---------------------
TRUE_VALUES = {"s", "sim", "yes", "y", "true", "1"}
FALSE_VALUES = {"n", "nao", "não", "no", "false", "0"}

def parse_bool(val: str, *, label: str = "opção") -> bool:
    raw = str(val or "").strip()
    normalized = raw.lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    print(format_log(
        "ATENCAO",
        message=(
            f"{label}: valor '{raw}' inválido. "
            f"Use verdadeiros {sorted(TRUE_VALUES)} ou falsos {sorted(FALSE_VALUES)}."
        ),
    ))
    return False

def parse_list(val: str) -> list:
    return [x.strip() for x in (val or "").split(",") if x.strip()]


# -------------------------- EXECUÇÃO ----------------------------
def run_toggle(label: str, cls, enabled: bool, cfg: dict, *, log_level: int):
    print("")

    print(format_log("\nINFO", message=f"********** INICIANDO O {label} *************"))

    if not enabled:
        print(format_log("\nINFO", message=f"{label} = NÃO → Não será executado"))
        return

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            instancia = cls(cfg)
    except Exception as exc:
        sys.stdout.write(buffer.getvalue())
        sys.stdout.flush()
        raise SystemExit(str(exc)) from None

    captured_init = buffer.getvalue()

    modo_atual = getattr(instancia, "MODO", getattr(instancia, "modo", "DESCONHECIDO"))
    if modo_atual is None:
        modo_atual = "DESCONHECIDO"
    modo_atual = str(modo_atual).upper()

    modo_slug = _sanitize_segment(modo_atual)
    if modo_atual == "TESTE":
        nome_teste = getattr(instancia, "NOME_TESTE", cfg.get(f"{label.upper()}_TESTE_NOME", ""))
        if nome_teste:
            modo_slug = f"TESTE_{_sanitize_segment(nome_teste)}"
    elif modo_atual == "EXTERNO":
        nome_ext = getattr(instancia, "NOME_SST", cfg.get(f"{label.upper()}_EXTERNO_NOME", ""))
        if nome_ext:
            modo_slug = f"EXTERNO_{_sanitize_segment(nome_ext)}"

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    log_name = f"{_sanitize_segment(label)}_{modo_slug}_{now:%Y%m%d_%H%M}.log"
    log_path = logs_dir / log_name

    label_upper = label.upper()
    prefix_upper = f"{label_upper}_"

    section_entries: list[tuple[str, object]] = []
    added_keys: set[str] = set()

    def _append_key_if_present(key: str):
        if key in cfg and key not in added_keys:
            section_entries.append((key, cfg[key]))
            added_keys.add(key)

    _append_key_if_present(label_upper)
    _append_key_if_present(f"{label_upper}_MODO")

    for key, value in cfg.items():
        if key in added_keys:
            continue
        if key.upper().startswith(prefix_upper):
            section_entries.append((key, value))
            added_keys.add(key)

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"# Log do índice {label} ({modo_atual})\n")
        log_file.write(f"# Gerado em: {now:%Y-%m-%d %H:%M:%S}\n")
        log_file.write(f"# Configuração ({label}):\n")
        if section_entries:
            for key, value in section_entries:
                log_file.write(f"{key} = {value}\n")
        else:
            log_file.write("# (sem chaves específicas para este índice no config)\n")
        log_file.write("\n")
        log_file.flush()

        console_stream = _SelectiveStream(sys.stdout, log_level)
        tee = _StdoutTee(console_stream, log_file)
        with contextlib.redirect_stdout(tee):
            print(format_log("INFO", message=f"Registrando log em {log_path}"))
            print(format_log("RODANDO", message=f"{label} = SIM → executando no modo {modo_atual}"))
            if captured_init:
                if log_level >= 2:
                    print(captured_init, end="")
                else:
                    log_file.write(captured_init)
                    if not captured_init.endswith("\n"):
                        log_file.write("\n")
                    log_file.flush()
            try:
                instancia.run()
                print(format_log("SALVO", item=f"Log salvo → {label}", destino=str(log_path)))
            except Exception as exc:
                print(format_log("ERRO", message=f"Falha na execução: {exc}"))
                raise SystemExit(str(exc)) from None


def main():
    args = parse_args()
    cfg = load_config(args.config)
    Path("logs").mkdir(parents=True, exist_ok=True)

    raw_log_level = cfg.get("LOGS", 2)
    try:
        log_level = int(str(raw_log_level).strip())
    except Exception:
        log_level = 2
    log_level = max(0, min(log_level, 2))

    # --------- Lê toggles ----------
    aao_on = parse_bool(cfg.get("AAO"), label="AAO")
    amo_on = parse_bool(cfg.get("AMO"), label="AMO")
    mei_on = parse_bool(cfg.get("MEI"), label="MEI")
    omj_on = parse_bool(cfg.get("OMJ"), label="OMJ")
    oni_on = parse_bool(cfg.get("ONI"), label="ONI")
    pdo_on = parse_bool(cfg.get("PDO"), label="PDO")
    soi_on = parse_bool(cfg.get("SOI"), label="SOI")


    # --------- Executa todos via run_toggle ----------
    # Se quiser rodar OMJ primeiro, deixe-o no topo.
    run_toggle("AAO", AAO, aao_on, cfg, log_level=log_level)
    run_toggle("AMO", AMO, amo_on, cfg, log_level=log_level)
    run_toggle("MEI", MEI, mei_on, cfg, log_level=log_level)
    run_toggle("OMJ", OMJ, omj_on, cfg, log_level=log_level)
    run_toggle("ONI", ONI, oni_on, cfg, log_level=log_level)
    run_toggle("PDO", PDO, pdo_on, cfg, log_level=log_level)
    run_toggle("SOI", SOI, soi_on, cfg, log_level=log_level)

if __name__ == "__main__":
    main()
