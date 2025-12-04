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

from .imports import *  # noqa: F401,F403
from .imports import _dt  # nome começa com underscore; importa explicitamente
from .logging import format_log
from datetime import datetime


def _cfg_message(message: str) -> str:
    return format_log("ERRO_CONF", message=message)


TRUE_VALUES = {"s", "sim", "yes", "y", "true", "1"}
FALSE_VALUES = {"n", "nao", "não", "no", "false", "0"}
_BOOL_ALLOWED = TRUE_VALUES | FALSE_VALUES

def _parse_date_safe(txt: str, default=None):
    try:
        return pd.to_datetime(txt)
    except Exception:
        return default

def _parse_baseline_safe(txt: str):
    try:
        y0, y1 = txt.split(":")
        d0 = pd.to_datetime(y0, errors="coerce")
        d1 = pd.to_datetime(y1, errors="coerce")
        return d0, d1
    except Exception:
        return None, None


# ---------------- ONI ----------------
def validate_config_ONI(cfg):
    modo = str(cfg.get("ONI_MODO", "REFERENCIA")).upper()
    if modo not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"ONI_MODO inválido: {modo}"))

    if modo == "TESTE":
        nome = cfg.get("ONI_TESTE_NOME", "")
        if not nome:
            raise ValueError(_cfg_message("ONI_TESTE_NOME obrigatório no modo TESTE"))
        ano_ini = cfg.get("ONI_TESTE_ANO_INICIO", 1950)
        if not str(ano_ini).isdigit() or int(ano_ini) < 1854:
            raise ValueError(_cfg_message(f"ONI_TESTE_ANO_INICIO inválido: {ano_ini}"))
        # checar coordenadas
        for k in ["ONI_TESTE_LAT_MIN", "ONI_TESTE_LAT_MAX", "ONI_TESTE_LON_MIN", "ONI_TESTE_LON_MAX"]:
            v = str(cfg.get(k, ""))
            try:
                float(v)
            except Exception:
                raise ValueError(_cfg_message(f"{k} inválido: {v}"))

    if modo == "EXTERNO":
        caminho = str(cfg.get("ONI_EXTERNO_CAMINHO_TSM", "")).strip()
        if not caminho or not os.path.exists(caminho):
            raise ValueError(_cfg_message(f"Arquivo ONI externo não encontrado: {caminho}"))
        try:
            df = pd.read_csv(caminho, sep=";")
        except Exception:
            raise ValueError(_cfg_message(f"Falha ao ler {caminho} (esperado CSV com separador ';')"))
        required = {"ano", "mes", "tsm"}
        if not required.issubset(set(df.columns.str.lower())):
            raise ValueError(_cfg_message(f"ONI externo deve conter colunas {required}, recebido: {df.columns.tolist()}"))


# ---------------- SOI ----------------
def validate_config_SOI(cfg):
    modo = str(cfg.get("SOI_MODO", "REFERENCIA")).upper()
    if modo not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"SOI_MODO inválido: {modo}"))

    if modo == "TESTE":
        base = str(cfg.get("SOI_TESTE_BASE_CLIMA", ""))
        d0, d1 = _parse_baseline_safe(base)
        if d0 is None or d1 is None:
            raise ValueError(_cfg_message(f"SOI_TESTE_BASE_CLIMA inválido: {base}"))
        metodo = str(cfg.get("SOI_TESTE_METODO", ""))
        if metodo not in {"CRU", "CPC_PADRONIZADO", "CPC_ANOMALIA", "TODOS"}:
            raise ValueError(_cfg_message(f"SOI_TESTE_METODO inválido: {metodo}"))

    if modo == "EXTERNO":
        base = str(cfg.get("SOI_EXTERNO_BASE_CLIMA", ""))
        d0, d1 = _parse_baseline_safe(base)
        if d0 is None or d1 is None:
            raise ValueError(_cfg_message(f"SOI_EXTERNO_BASE_CLIMA inválido: {base}"))
        for arq in ["SOI_EXTERNO_TAHITI", "SOI_EXTERNO_DARWIN"]:
            caminho = str(cfg.get(arq, "")).strip()
            if not caminho or not os.path.exists(caminho):
                raise ValueError(_cfg_message(f"Arquivo {arq} não encontrado: {caminho}"))
            try:
                df = pd.read_csv(caminho, sep=";")
            except Exception:
                raise ValueError(_cfg_message(f"Falha ao ler {caminho}. Esperado CSV com separador ';'"))
            required = {"ano", "mes", "slp"}
            if not required.issubset(set(df.columns.str.lower())):
                raise ValueError(_cfg_message(f"Arquivo {arq} deve conter colunas {required}, recebido: {df.columns.tolist()}"))


# ---------------- AMO ----------------
def validate_config_AMO(cfg):
    modo = str(cfg.get("AMO_MODO", "REFERENCIA")).upper()
    if modo not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"AMO_MODO inválido: {modo}"))

    def _ensure_bool_option(key: str):
        val = cfg.get(key)
        if val in (None, ""):
            return
        if isinstance(val, bool):
            return
        raw = str(val).strip()
        if not raw:
            return
        normalized = raw.lower()
        if normalized in _BOOL_ALLOWED:
            return
        raise ValueError(
            _cfg_message(
                f"{key}: valor '{raw}' inválido. "
                f"Use verdadeiros {sorted(TRUE_VALUES)} ou falsos {sorted(FALSE_VALUES)}."
            )
        )

    if modo == "TESTE":
        base = str(cfg.get("AMO_TESTE_BASE_CLIMA", ""))
        d0, d1 = _parse_baseline_safe(base)
        if d0 is None or d1 is None:
            raise ValueError(_cfg_message(f"AMO_TESTE_BASE_CLIMA inválido: {base}"))
        if d0 >= d1:
            raise ValueError(_cfg_message(f"AMO_TESTE_BASE_CLIMA requer início < fim (recebido: {base})"))
        min_year = 1854
        max_year = datetime.now().year
        if d0.year < min_year or d1.year > max_year:
            raise ValueError(
                _cfg_message(
                    f"AMO_TESTE_BASE_CLIMA fora da faixa suportada ({min_year}-{max_year}): {base}"
                )
            )
        for k in ["AMO_TESTE_LAT_MIN", "AMO_TESTE_LAT_MAX", "AMO_TESTE_LON_MIN", "AMO_TESTE_LON_MAX"]:
            v = str(cfg.get(k, ""))
            try:
                float(v)
            except Exception:
                raise ValueError(_cfg_message(f"{k} inválido: {v}"))
        # checa periodo temporal
        inicio = _parse_date_safe(cfg.get("AMO_TESTE_INICIO", ""), None)
        fim = _parse_date_safe(cfg.get("AMO_TESTE_FINAL", ""), None)
        if inicio is None or fim is None or inicio >= fim:
            raise ValueError(_cfg_message(f"AMO_TESTE_INICIO/FINAL inválidos: {inicio}, {fim}"))

    if modo == "EXTERNO":
        caminho_cfg = str(cfg.get("AMO_EXTERNO_CAMINHO_TSM", cfg.get("AMO_EXTERNO_CAMINHO", ""))).strip()
        if not caminho_cfg or not os.path.exists(caminho_cfg):
            raise ValueError(_cfg_message(f"Arquivo externo AMO não encontrado: {caminho_cfg}"))
        try:
            df = pd.read_csv(caminho_cfg, sep=";")
        except Exception:
            raise ValueError(_cfg_message(f"Falha ao ler {caminho_cfg}. Esperado CSV com separador ';'"))
        required = {"ano", "mes", "tsm"}
        if not required.issubset(set(df.columns.str.lower())):
            raise ValueError(_cfg_message(f"Arquivo externo AMO deve conter colunas {required}, recebido: {df.columns.tolist()}"))

    bool_keys = [
        "AMO_TESTE_VALIDACAO_COMPLETA",
        "AMO_TESTE_REMOCAO_TENDENCIA",
        "AMO_TESTE_REMOCAO_GLOBAL",
        "AMO_TESTE_SUAVIZACAO",
        "AMO_TESTE_EXTRA",
        "AMO_EXTERNO_SUAVIZACAO",
        "AMO_EXTERNO_REMOCAO_TENDENCIA",
        "AMO_EXTERNO_REMOCAO_GLOBAL",
    ]
    for key in bool_keys:
        _ensure_bool_option(key)


# ---------------- AAO ----------------
def validate_config_AAO(cfg):
    if not cfg:
        return

    modo_cfg = str(cfg.get("AAO_MODO", "REFERENCIA") or "").strip().upper()
    if modo_cfg and modo_cfg not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"AAO_MODO inválido: {modo_cfg}"))

    def _ensure_float_like(key: str):
        val = cfg.get(key)
        if val in (None, ""):
            return
        try:
            float(str(val).replace(",", "."))
        except Exception as exc:
            raise ValueError(_cfg_message(f"{key} inválido: {val}")) from exc

    def _ensure_int_like(key: str):
        val = cfg.get(key)
        if val in (None, ""):
            return
        try:
            int(float(str(val).replace(",", ".")))
        except Exception as exc:
            raise ValueError(_cfg_message(f"{key} inválido: {val}")) from exc

    if modo_cfg == "TESTE":
        _ensure_int_like("AAO_TESTE_NIVEL_Z")
        _ensure_float_like("AAO_TESTE_LAT_MAX")
        inicio = cfg.get("AAO_TESTE_INICIO")
        if inicio not in (None, "") and _parse_date_safe(inicio, None) is None:
            raise ValueError(_cfg_message(f"AAO_TESTE_INICIO inválido: {inicio}"))
        base = cfg.get("AAO_TESTE_BASE_CLIMA")
        if base not in (None, ""):
            d0, d1 = _parse_baseline_safe(base)
            if d0 is None or d1 is None or d0 >= d1:
                raise ValueError(_cfg_message(f"AAO_TESTE_BASE_CLIMA inválido: {base}"))
    if modo_cfg == "EXTERNO":
        _ensure_int_like("AAO_EXTERNO_NIVEL_Z")
        _ensure_int_like("AAO_EXTERNO_NIVEL_Z_")
        _ensure_float_like("AAO_EXTERNO_LAT_MAX")
        caminho = str(cfg.get("AAO_EXTERNO_CAMINHO", "")).strip()
        if not caminho:
            raise ValueError(_cfg_message("AAO_EXTERNO_CAMINHO obrigatório no modo EXTERNO."))
        if not Path(caminho).expanduser().exists():
            raise FileNotFoundError(_cfg_message(f"Arquivo indicado em AAO_EXTERNO_CAMINHO não encontrado: {caminho}"))
        inicio_ext = cfg.get("AAO_EXTERNO_INICIO")
        if inicio_ext not in (None, "") and _parse_date_safe(inicio_ext, None) is None:
            raise ValueError(_cfg_message(f"AAO_EXTERNO_INICIO inválido: {inicio_ext}"))
        base_ext = cfg.get("AAO_EXTERNO_BASE_CLIMA")
        if base_ext not in (None, ""):
            d0, d1 = _parse_baseline_safe(base_ext)
            if d0 is None or d1 is None or d0 >= d1:
                raise ValueError(_cfg_message(f"AAO_EXTERNO_BASE_CLIMA inválido: {base_ext}"))

    bstart = cfg.get("AAO_BASE_START")
    bend = cfg.get("AAO_BASE_END")
    dt_start = dt_end = None
    if bstart:
        try:
            dt_start = pd.to_datetime(str(bstart).strip())
        except Exception as exc:
            raise ValueError(_cfg_message(f"AAO_BASE_START inválido: {bstart}")) from exc
    if bend:
        try:
            dt_end = pd.to_datetime(str(bend).strip())
        except Exception as exc:
            raise ValueError(_cfg_message(f"AAO_BASE_END inválido: {bend}")) from exc
    if dt_start is not None and dt_end is not None and dt_end <= dt_start:
        raise ValueError(_cfg_message(f"AAO_BASE_END ({bend}) deve ser posterior a AAO_BASE_START ({bstart})."))

    level = cfg.get("AAO_LEVEL_HPA")
    if level not in (None, ""):
        try:
            lvl = int(float(str(level).strip()))
        except Exception as exc:
            raise ValueError(_cfg_message(f"AAO_LEVEL_HPA inválido: {level}")) from exc
        if lvl <= 0:
            raise ValueError(_cfg_message(f"AAO_LEVEL_HPA deve ser positivo: {level}"))

    lat_max = cfg.get("AAO_LAT_MAX")
    if lat_max not in (None, ""):
        try:
            float(str(lat_max).replace(",", "."))
        except Exception as exc:
            raise ValueError(_cfg_message(f"AAO_LAT_MAX inválido: {lat_max}")) from exc

    include_20s = cfg.get("AAO_INCLUDE_20S")
    if include_20s not in (None, ""):
        val = str(include_20s).strip().lower()
        if val not in ("sim", "nao", "não", "true", "false", "1", "0", "y", "n"):
            raise ValueError(_cfg_message(f"AAO_INCLUDE_20S inválido: {include_20s}"))

    ddof = cfg.get("AAO_STD_DDOF")
    if ddof not in (None, ""):
        try:
            ddof_val = int(str(ddof).strip())
        except Exception as exc:
            raise ValueError(_cfg_message(f"AAO_STD_DDOF inválido: {ddof}")) from exc
        if ddof_val < 0:
            raise ValueError(_cfg_message(f"AAO_STD_DDOF deve ser >= 0: {ddof}"))

    ref_inicio = cfg.get("AAO_REFERENCIA_INICIO")
    if ref_inicio not in (None, "") and _parse_date_safe(ref_inicio, None) is None:
        raise ValueError(_cfg_message(f"AAO_REFERENCIA_INICIO inválido: {ref_inicio}"))
    global_inicio = cfg.get("AAO_INICIO")
    if global_inicio not in (None, "") and _parse_date_safe(global_inicio, None) is None:
        raise ValueError(_cfg_message(f"AAO_INICIO inválido: {global_inicio}"))

    modo = cfg.get("AAO_DOWNLOAD")
    if modo not in (None, ""):
        val = str(modo).strip().lower()
        if val not in ("sim", "nao", "não", "true", "false", "1", "0", "y", "n"):
            raise ValueError(_cfg_message(f"AAO_DOWNLOAD inválido: {modo}"))

def validate_config_PDO(cfg):
    if not cfg:
        return

    modo_raw = str(cfg.get("PDO_MODO", "REFERENCIA") or "").strip()
    modo = modo_raw.upper()
    if modo == "VALIDACAO":
        modo = "REFERENCIA"
    if modo not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"PDO_MODO inválido: {modo_raw}"))

    def _norm_token(value: str) -> str:
        s = str(value or "").strip()
        if not s:
            return ""
        s = s.replace("—", "-").replace("–", "-").replace("−", "-")
        # Corrige zeros escritos com 'O' apenas em tokens numéricos (evita afetar palavras como 'TOTAL')
        if re.fullmatch(r"[0-9Oo:\-\s]+", s):
            s = s.replace("O", "0").replace("o", "0")
        return s

    def _ensure_float(key: str, lo: float | None = None, hi: float | None = None) -> float:
        raw = _norm_token(cfg.get(key, ""))
        if raw == "":
            raise ValueError(_cfg_message(f"{key} não informado."))
        try:
            val = float(raw)
        except Exception:
            raise ValueError(_cfg_message(f"{key} inválido: {cfg.get(key)!r}"))
        if lo is not None and val < lo:
            raise ValueError(_cfg_message(f"{key} abaixo do mínimo permitido ({lo})."))
        if hi is not None and val > hi:
            raise ValueError(_cfg_message(f"{key} acima do máximo permitido ({hi})."))
        cfg[key] = f"{val}"  # normaliza para string numérica limpa
        return val

    def _ensure_period(key: str, allow_keywords: set[str] | None = None):
        raw = _norm_token(cfg.get(key, ""))
        if not raw:
            raise ValueError(_cfg_message(f"{key} não informado."))
        upper = raw.upper()
        if allow_keywords and upper in allow_keywords:
            cfg[key] = upper
            return
        if ":" not in raw:
            raise ValueError(_cfg_message(f"{key} deve estar no formato AAAA-MM:AAAA-MM, recebido: {cfg.get(key)!r}"))
        ini_txt, fim_txt = [x.strip() for x in raw.split(":", 1)]
        ini = pd.to_datetime(ini_txt, errors="coerce")
        fim = pd.to_datetime(fim_txt, errors="coerce")
        if pd.isna(ini) or pd.isna(fim):
            raise ValueError(_cfg_message(f"{key} contém datas inválidas: {cfg.get(key)!r}"))
        if ini >= fim:
            raise ValueError(_cfg_message(f"{key} exige início anterior ao fim: {cfg.get(key)!r}"))
        cfg[key] = f"{ini.strftime('%Y-%m')}:{fim.strftime('%Y-%m')}"

    if modo == "TESTE":
        lat_min = _ensure_float("PDO_TESTE_LAT_MIN", -90.0, 90.0)
        lat_max = _ensure_float("PDO_TESTE_LAT_MAX", -90.0, 90.0)
        if lat_min >= lat_max:
            raise ValueError(_cfg_message(f"Faixa latitudinal inválida: {lat_min} ≥ {lat_max}"))

        lon_min = _ensure_float("PDO_TESTE_LON_MIN", -360.0, 360.0)
        lon_max = _ensure_float("PDO_TESTE_LON_MAX", -360.0, 360.0)
        if lon_min >= lon_max:
            raise ValueError(_cfg_message(f"Faixa longitudinal inválida: {lon_min} ≥ {lon_max}"))

        _ensure_period("PDO_TESTE_BASE_CLIMA")

    if modo == "EXTERNO":
        caminho = str(cfg.get("PDO_EXTERNO_CAMINHO", "")).strip()
        if not caminho:
            raise ValueError(_cfg_message("PDO_EXTERNO_CAMINHO não informado."))
        if not os.path.exists(caminho):
            raise ValueError(_cfg_message(f"Arquivo externo PDO não encontrado: {caminho}"))

        _ensure_period("PDO_EXTERNO_BASE_CLIMA")

        lat_min = _ensure_float("PDO_EXTERNO_LAT_MIN", -90.0, 90.0)
        lat_max = _ensure_float("PDO_EXTERNO_LAT_MAX", -90.0, 90.0)
        if lat_min >= lat_max:
            raise ValueError(_cfg_message(f"Faixa latitudinal externa inválida: {lat_min} ≥ {lat_max}"))

        lon_min = _ensure_float("PDO_EXTERNO_LON_MIN", -360.0, 360.0)
        lon_max = _ensure_float("PDO_EXTERNO_LON_MAX", -360.0, 360.0)
        if lon_min >= lon_max:
            raise ValueError(_cfg_message(f"Faixa longitudinal externa inválida: {lon_min} ≥ {lon_max}"))


def validate_config_MEI(cfg: dict | None) -> dict:
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise TypeError(_cfg_message("Configuração MEI deve ser um dicionário."))

    def _clean_str(value):
        if value is None:
            return ""
        txt = str(value).strip()
        if txt.lower() in {"", "none", "null"}:
            return ""
        return txt

    def _as_float(value, key, default=None):
        if value in (None, ""):
            if default is not None:
                return float(default)
            raise ValueError(_cfg_message(f"{key} não informado."))
        try:
            return float(str(value).replace(",", "."))
        except Exception as exc:
            raise ValueError(_cfg_message(f"{key} inválido: {value}")) from exc

    def _split_path_tokens(raw):
        if raw in (None, "", []):
            return []
        if isinstance(raw, (list, tuple, set)):
            items = raw
        else:
            items = re.split(r"[;,]", str(raw))
        tokens: list[str] = []
        for item in items:
            if item is None:
                continue
            txt = str(item).split("#", 1)[0].strip()
            if txt:
                tokens.append(txt)
        return tokens

    def _resolve_nc_paths(raw, label: str) -> list[Path]:
        tokens = _split_path_tokens(raw)
        resolved: list[Path] = []
        for token in tokens:
            expanded = os.path.expandvars(os.path.expanduser(token))
            has_wildcards = any(sym in expanded for sym in "*?[]")
            matches: list[Path] = []
            if has_wildcards:
                matches = [Path(m) for m in glob(expanded)]
            else:
                candidate = Path(expanded)
                if candidate.is_dir():
                    matches = sorted(candidate.glob("*.nc"))
                else:
                    matches = [candidate]
            if not matches:
                raise ValueError(_cfg_message(f"{label}: nenhum arquivo encontrado para {token!r}."))
            for match in matches:
                if not match.exists():
                    raise ValueError(_cfg_message(f"{label}: caminho inexistente {match} (origem {token!r})."))
                if match.is_dir():
                    raise ValueError(_cfg_message(f"{label}: diretório {match} não contém arquivos .nc."))
                resolved.append(match)
        return resolved

    def _parse_period(raw_value, key, default):
        if raw_value in (None, "", []):
            items = list(default)
        elif isinstance(raw_value, (list, tuple)):
            items = [str(x).strip() for x in raw_value if str(x).strip()]
        else:
            normalized = str(raw_value).replace(" ", "")
            items = [p.strip() for p in re.split(r"[;,:]", normalized) if p.strip()]
        if len(items) != 2:
            raise ValueError(_cfg_message(f"{key} deve conter exatamente 2 datas no formato: YYYY-MM, YYYY-MM. Recebido: {raw_value!r}"))
        parsed = []
        for token in items:
            dt = pd.to_datetime(token, format="%Y-%m", errors="coerce")
            if pd.isna(dt):
                dt = pd.to_datetime(f"{token}-01", errors="coerce")
            if pd.isna(dt):
                raise ValueError(_cfg_message(f"{key} contém data inválida: {token!r}"))
            parsed.append(dt)
        if parsed[0] >= parsed[1]:
            raise ValueError(_cfg_message(f"{key} exige início anterior ao fim: {items[0]} ≥ {items[1]}"))
        return tuple(items), tuple(parsed)

    allowed = {"REFERENCIA", "TESTE", "EXTERNO"}
    modo_raw = cfg.get("MEI_MODO", cfg.get("modo", "REFERENCIA"))
    modo = str(modo_raw or "REFERENCIA").strip().upper() or "REFERENCIA"
    if modo == "VALIDACAO":
        modo = "REFERENCIA"
    if modo not in allowed:
        raise ValueError(_cfg_message(f"MEI_MODO inválido: {modo_raw}"))

    def _fetch(option: str, *, default=None, allow_blank: bool = False):
        upper = option.upper()
        candidates = [
            f"MEI_{modo}_{upper}",
            f"MEI_{upper}",
            f"MEI{upper}",
            upper,
            upper.lower(),
            f"mei_{upper.lower()}",
        ]
        for key in candidates:
            if key in cfg:
                value = cfg[key]
                if isinstance(value, str):
                    trimmed = value.strip()
                    if not allow_blank and trimmed == "":
                        continue
                    if not allow_blank and trimmed.lower() in {"none", "null"}:
                        continue
                if value is None and not allow_blank:
                    continue
                return value
        return default

    sanitized: dict[str, object] = {"modo": modo, "MEI_MODO": modo}

    nome = _clean_str(_fetch("NOME", default=""))
    if nome:
        sanitized["nome"] = nome

    # Diretório de saída
    default_results = Path("./outputs/MEI").expanduser()
    if modo == "REFERENCIA":
        sanitized["path_results"] = str(default_results)
    elif modo == "TESTE":
        sanitized["path_results"] = str(default_results)
    else:
        path_results = _clean_str(_fetch("PATH_RESULTS", default=str(default_results)))
        if not path_results:
            raise ValueError(_cfg_message(f"MEI_{modo}_PATH_RESULTS não informado."))
        sanitized["path_results"] = str(Path(path_results).expanduser())

    # Fonte de dados externos (opcional exceto no modo EXTERNO)
    path_data = _clean_str(_fetch("PATH_DATA"))

    if modo == "EXTERNO":
        external_var_paths: dict[str, list[str]] = {}
        if path_data:
            path_candidate = Path(path_data).expanduser()
            if not path_candidate.exists():
                raise ValueError(_cfg_message(f"MEI_{modo}_PATH_DATA não encontrado: {path_data}"))
            sanitized["path_data"] = str(path_candidate)
        else:
            sanitized["path_data"] = None

        var_option_map = {
            "air": "TEMP",
            "slp": "SLP",
            "uwnd": "UWND",
            "vwnd": "VWND",
            "cldc": "CLOUD",
            "sst": "SST",
        }
        for canonical, option in var_option_map.items():
            raw_spec = _fetch(option, default=None, allow_blank=True)
            tokens = _split_path_tokens(raw_spec)
            if not tokens:
                continue
            resolved = _resolve_nc_paths(tokens, f"MEI_{modo}_{option}")
            if resolved:
                external_var_paths[canonical] = [str(p) for p in resolved]

        if external_var_paths:
            sanitized["external_var_paths"] = external_var_paths

        cloud_thresh_raw = _fetch("CLOUD_FRAC_OBS_MIN", default=None, allow_blank=True)
        if cloud_thresh_raw in (None, ""):
            cloud_thresh_raw = _fetch("CLOUD_FRAC_DIAS_MIN", default=None, allow_blank=True)
        if cloud_thresh_raw in (None, ""):
            cloud_thresh_raw = _fetch("CLOUD_FRAC_MINIMA", default=None, allow_blank=True)
        if cloud_thresh_raw in (None, ""):
            cloud_thresh_raw = _fetch("CLOUD_VALID_THRESHOLD", default=None, allow_blank=True)
        if cloud_thresh_raw not in (None, ""):
            try:
                cloud_thresh_val = float(str(cloud_thresh_raw).replace(",", "."))
            except Exception as exc:
                raise ValueError(_cfg_message(f"MEI_{modo}_CLOUD_FRAC_OBS_MIN inválido: {cloud_thresh_raw}")) from exc
            if not (0.0 <= cloud_thresh_val <= 1.0):
                raise ValueError(_cfg_message(f"MEI_{modo}_CLOUD_FRAC_OBS_MIN deve estar entre 0 e 1: {cloud_thresh_raw}"))
            sanitized["cloud_valid_threshold"] = cloud_thresh_val

        if "cldc" not in external_var_paths:
            print(format_log("ATENCAO", message="MEI EXTERNO → variável de nebulosidade (CLOUD) não fornecida; prosseguindo sem CLDC."))

        if sanitized["path_data"] is None and not external_var_paths:
            raise ValueError(_cfg_message(f"Informe MEI_{modo}_PATH_DATA ou arquivos individuais (MEI_{modo}_*_)."))
    else:
        sanitized["path_data"] = None

    def _resolve_lat_lon(default_lat=(-30.0, 30.0), default_lon=(100.0, 290.0)):
        lat_range = cfg.get("lat_range")
        if lat_range and isinstance(lat_range, (list, tuple)) and len(lat_range) == 2:
            lat_values = [lat_range[0], lat_range[1]]
        else:
            lat_min = _as_float(_fetch("LAT_MIN", default=default_lat[0]), f"MEI_{modo}_LAT_MIN", default_lat[0])
            lat_max = _as_float(_fetch("LAT_MAX", default=default_lat[1]), f"MEI_{modo}_LAT_MAX", default_lat[1])
            lat_values = [lat_min, lat_max]
        lat_min, lat_max = float(lat_values[0]), float(lat_values[1])
        if lat_min == lat_max:
            raise ValueError(_cfg_message("Limites de latitude iguais não são permitidos."))
        if lat_min > lat_max:
            lat_min, lat_max = lat_max, lat_min
        if lat_min < -90 or lat_max > 90:
            raise ValueError(_cfg_message(f"Faixa latitudinal inválida: {lat_min} .. {lat_max}"))

        lon_range = cfg.get("lon_range")
        if lon_range and isinstance(lon_range, (list, tuple)) and len(lon_range) == 2:
            lon_values = [lon_range[0], lon_range[1]]
        else:
            lon_min = _as_float(_fetch("LON_MIN", default=default_lon[0]), f"MEI_{modo}_LON_MIN", default_lon[0])
            lon_max = _as_float(_fetch("LON_MAX", default=default_lon[1]), f"MEI_{modo}_LON_MAX", default_lon[1])
            lon_values = [lon_min, lon_max]
        lon_min, lon_max = float(lon_values[0]), float(lon_values[1])
        if lon_min == lon_max:
            raise ValueError(_cfg_message("Limites de longitude iguais não são permitidos."))
        if lon_min > lon_max:
            lon_min, lon_max = lon_max, lon_min
        if lon_min < -360 or lon_max > 360:
            raise ValueError(_cfg_message(f"Faixa longitudinal inválida: {lon_min} .. {lon_max}"))
        return (lat_min, lat_max), (lon_min, lon_max)

    

    if modo in {"REFERENCIA", "TESTE"}:
        default_clim = ("1949-12", "1993-12")
        sanitized["resolution"] = 0.5
        sanitized["base_url_table"] = "https://psl.noaa.gov/enso/mei.old/table.html"
        sanitized["psl_base_url"] = "https://downloads.psl.noaa.gov/Datasets/icoads/2degree/enh"
        sanitized["psl_vars"] = ["slp", "sst", "uwnd", "vwnd", "air", "cldc"]

        lat_range, lon_range = _resolve_lat_lon()
        sanitized["lat_range"] = lat_range
        sanitized["lon_range"] = lon_range

        raw_clim = _fetch("BASE_CLIMATOLOGIA")
        tokens_clim, dates_clim = _parse_period(raw_clim, f"MEI_{modo}_BASE_CLIMATOLOGIA", default_clim)
        sanitized["base_climatology"] = tokens_clim

        if modo == "REFERENCIA":
            default_series = ("1949-12", "2017-12")
            raw_series = _fetch("BASE_SERIES") or ",".join(default_series)
            tokens_series, dates_series = _parse_period(raw_series, f"MEI_{modo}_BASE_SERIES", default_series)
        else:
            default_start, default_end = "1949-12", "2017-12"
            start_token = _clean_str(_fetch(f"MEI_{modo}_INICIO", default=default_start))
            end_token = _clean_str(_fetch(f"MEI_{modo}_FINAL", default=default_end))
            
            start_dt = pd.to_datetime(start_token, format="%Y-%m", errors="coerce")
            end_dt = pd.to_datetime(end_token, format="%Y-%m", errors="coerce")

            if pd.isna(start_dt) or pd.isna(end_dt):
                raise ValueError(_cfg_message(f"MEI_{modo}_INICIO e MEI_{modo}_FINAL precisam estar no formato YYYY-MM, YYYY-MM."))
            if start_dt >= end_dt:
                raise ValueError(_cfg_message(f"MEI_{modo}_INICIO deve ser anterior a MEI_{modo}_FINAL."))
            
            tokens_series = (start_token, end_token)
            dates_series = (start_dt, end_dt)


        if dates_series[1] < dates_clim[1]:
            raise ValueError(_cfg_message(f"MEI_{modo}_INICIO e MEI_{modo}_FINAL deve cobrir pelo menos até o fim de MEI_BASE_CLIMATOLOGIA."))
        
        sanitized["base_series"] = tokens_series
    else:
        sanitized["base_url_table"] = "https://psl.noaa.gov/enso/mei.old/table.html"
        default_clim = ("1950-12", "1993-12")
        
        # EXTERNO mantém flexibilidade original
        resolution_raw = _fetch("RESOLUCAO", default=0.5)
        resolution = _as_float(resolution_raw, f"MEI_{modo}_RESOLUCAO", default=0.5)
        if resolution <= 0:
            raise ValueError(_cfg_message(f"MEI_RESOLUCAO deve ser positivo: {resolution_raw}"))
        sanitized["resolution"] = resolution

        base_url_table = _clean_str(_fetch("BASE_URL"))
        if not base_url_table:
            base_url_table = _clean_str(_fetch("BASE_URL_TABLE"))
        if not base_url_table:
            base_url_table = "https://psl.noaa.gov/enso/mei.old/table.html"
        sanitized["base_url_table"] = base_url_table

        psl_base_url = _clean_str(_fetch("PSL_BASE_URL"))
        if not psl_base_url:
            psl_base_url = "https://downloads.psl.noaa.gov/Datasets/icoads/2degree/enh"
        sanitized["psl_base_url"] = psl_base_url

        vars_raw = _fetch("PSL_VARS", default=["slp", "sst", "uwnd", "vwnd", "air", "cldc"])
        if isinstance(vars_raw, str):
            vars_list = [v.strip() for v in re.split(r"[;,]", vars_raw) if v.strip()]
        else:
            vars_list = [str(v).strip() for v in vars_raw if str(v).strip()]
        if not vars_list:
            vars_list = ["slp", "sst", "uwnd", "vwnd", "air", "cldc"]
        sanitized["psl_vars"] = vars_list

        lat_range, lon_range = _resolve_lat_lon()
        sanitized["lat_range"] = lat_range
        sanitized["lon_range"] = lon_range

        default_start, default_end = "1950-12", "2017-06"
        start_token = _clean_str(_fetch(f"MEI_{modo}_INICIO", default=default_start))
        end_token = _clean_str(_fetch(f"MEI_{modo}_FINAL", default=default_end))
        
        start_dt = pd.to_datetime(start_token, format="%Y-%m", errors="coerce")
        end_dt = pd.to_datetime(end_token, format="%Y-%m", errors="coerce")
        
        tokens_series = (start_token, end_token)
        dates_series = (start_dt, end_dt)
        sanitized["base_series"] = tokens_series

        if pd.isna(start_dt) or pd.isna(end_dt):
            raise ValueError(_cfg_message(f"MEI_{modo}_INICIO e MEI_{modo}_FINAL precisam estar no formato YYYY-MM, YYYY-MM."))
        if start_dt >= end_dt:
            raise ValueError(_cfg_message(f"MEI_{modo}_INICIO deve ser anterior a MEI_{modo}_FINAL."))

        raw_clim = _fetch("BASE_CLIMATOLOGIA")
        tokens_clim, dates_clim = _parse_period(raw_clim, f"MEI_{modo}_BASE_CLIMATOLOGIA", default_clim)
        sanitized["base_climatology"] = tokens_clim

        if dates_series[1] < dates_clim[1]:
            raise ValueError(_cfg_message(f"MEI_{modo}_FINAL deve cobrir pelo menos até o fim de MEI_BASE_CLIMATOLOGIA."))
        sanitized["base_series"] = tokens_series

    return sanitized
def validate_config_OMJ(cfg):
    if not isinstance(cfg, dict) or not cfg:
        return

    modo_raw = str(cfg.get("OMJ_MODO", "TESTE") or "").strip()
    modo = modo_raw.upper()
    if modo not in {"REFERENCIA", "TESTE", "EXTERNO"}:
        raise ValueError(_cfg_message(f"OMJ_MODO inválido: {modo_raw}"))

    if modo != "EXTERNO":
        return

    def _strip(val):
        if val is None:
            return ""
        return str(val).split("#", 1)[0].strip()

    def _ensure_external_path(primary_key: str,
                              *,
                              aliases: list[str] | None = None,
                              sentinels: set[str] | None = None) -> None:
        sent = {s.lower() for s in (sentinels or set())}
        value = ""
        used_key = primary_key
        for key in [primary_key] + list(aliases or []):
            candidate = _strip(cfg.get(key))
            if candidate:
                value = candidate
                used_key = key
                break
        if not value:
            alias_txt = f" ou {'/'.join(aliases)}" if aliases else ""
            raise ValueError(_cfg_message(f"Informe {primary_key}{alias_txt} no modo EXTERNO."))

        chunks = [c.strip() for c in re.split(r"[,;]", value) if c.strip()]
        if not chunks:
            raise ValueError(_cfg_message(f"{used_key} inválido: {value!r}"))

        valid_found = False
        for chunk in chunks:
            if chunk.lower() in sent:
                return

            expanded = os.path.expanduser(os.path.expandvars(chunk))
            if any(sym in expanded for sym in "*?[]"):
                matches = glob(expanded, recursive=True)
                if not matches:
                    raise ValueError(_cfg_message(f"{used_key}: padrão {chunk!r} não encontrou arquivos."))
                ok = False
                for match in matches:
                    p = Path(match)
                    if p.is_file():
                        ok = True
                        break
                    if p.is_dir() and any(p.glob("*.nc")):
                        ok = True
                        break
                if not ok:
                    raise ValueError(_cfg_message(f"{used_key}: padrão {chunk!r} não aponta para arquivos NetCDF."))
                valid_found = True
                continue

            p = Path(expanded)
            if not p.exists():
                raise ValueError(_cfg_message(f"Caminho inexistente em {used_key}: {chunk}"))
            if p.is_dir() and not any(p.glob("*.nc")):
                raise ValueError(_cfg_message(f"Diretório {p} em {used_key} não contém arquivos no formato .nc."))
            valid_found = True
            break

        if not valid_found:
            raise ValueError(_cfg_message(f"{used_key} não possui caminhos válidos."))

    _ensure_external_path(
        "OMJ_EXTERNO_OLR",
        aliases=["OMJ_EXTERNO_CAMINHO_OLR"],
        sentinels={"olr", "default"},
    )
    _ensure_external_path(
        "OMJ_EXTERNO_U850",
        aliases=["OMJ_EXTERNO_CAMINHO_U850"],
        sentinels={"ncep_r1", "default", "ncep1", "ncepr1"},
    )
    _ensure_external_path(
        "OMJ_EXTERNO_U200",
        aliases=["OMJ_EXTERNO_CAMINHO_U200"],
        sentinels={"ncep_r1", "default", "ncep1", "ncepr1"},
    )
