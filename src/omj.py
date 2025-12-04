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
from .imports import _dt
from .atm_tools import validate_config_OMJ
from src.logging import format_log


class OMJ:
    """
    OMJ — Cálculo do índice tipo RMM (Wheeler & Hendon 2004) usando OLR+U850+U200.
    Estruturado como classe, com etapas separadas em funções.
    Integra com um config.txt estilo dos demais índices.

    Principais métodos públicos:
      - run(): executa o pipeline conforme config (download, processa, salva, valida, plota)
      - plot_diagrama(): gera o diagrama de fase WH04 para um período
    """

    METRICS_COLUMNS = [
        "serie",
        "N",
        "data_inicio",
        "data_final",
        "corr_rmm1",
        "corr_rmm2",
        "rmse_rmm1",
        "rmse_rmm2",
        "bias_rmm1",
        "bias_rmm2",
        "corr_amp",
        "rmse_amp",
        "med_abs_erro_angulo",
        "nota",
    ]


    @dataclass(frozen=True)
    class _ResolvedPath:
        raw: str
        paths: tuple[Path, ...]

        def __post_init__(self) -> None:
            if not self.paths:
                raise ValueError("_ResolvedPath requer ao menos um caminho físico")

        def __iter__(self):
            return iter(self.paths)

        def __len__(self) -> int:
            return len(self.paths)

        def __bool__(self) -> bool:
            return bool(self.paths)

        @property
        def name(self) -> str:
            if len(self.paths) == 1:
                return self.paths[0].name
            first = self.paths[0].name
            return f"{first} (+{len(self.paths) - 1})"

        def as_open_args(self) -> list[str]:
            return [str(p) for p in self.paths]

        def __str__(self) -> str:
            if len(self.paths) == 1:
                return str(self.paths[0])
            preview = ", ".join(str(p) for p in self.paths[:2])
            if len(self.paths) > 2:
                preview = f"{preview}, ... (+{len(self.paths) - 2} arquivos)"
            return f"{self.raw} -> {preview}"

    # ===================== BoM (série oficial RMM) =====================
    BOM_URLS = [
        "https://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt",  # prioridade
        "https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt",
        "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt",
    ]

    DIM_HINTS_DEFAULT: dict[str, tuple[str, ...]] = {
        "time": ("time", "valid_time", "time_counter", "t", "date", "dates", "tempo"),
        "lat": ("lat", "latitude", "latitudes", "nav_lat", "y"),
        "lon": ("lon", "longitude", "longitudes", "nav_lon", "x"),
        "level": ("level", "lev", "plev", "pressure_level", "isobaricInhPa", "isobaricinhpa", "isobaric", "pressure"),
    }

    def _get_bom_series(self) -> pd.DataFrame:
        """
        Obtem a serie oficial RMM da BoM:
        1) tenta WEB com cabecalhos de navegador (evita 403);
        2) salva/atualiza cache local em data/cache/OMJ/bom_rmm_cache.txt;
        3) se a web falhar, tenta o cache; se ainda assim falhar, erra.
        """
        # 1) Web primeiro (evita 403 com headers)
        web_err = None
        try:
            txt = self._download_text_first_ok(self.BOM_URLS, timeout=60)
            dfb = self._parse_bom_rmm_text(txt)
            if not dfb.empty:
                # 2) persiste/atualiza cache
                try:
                    self.bom_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self.bom_cache_path.write_text(txt, encoding="utf-8")
                    print(format_log("CACHE", action="Dado em cache Bureau of Meteorologia (BoM) atualizado →", path=str(self.bom_cache_path)))
                except Exception:
                    pass
                print(format_log("INFO", message=f"Série Temporal do Bureau of Meteorologia (BoM): {dfb.index.min().date()}..{dfb.index.max().date()} (N={len(dfb)})"))
                return dfb
        except Exception as e:
            web_err = e

        # 3) Fallback: cache fixo da classe
        if self.bom_cache_path.exists():
            try:
                txt = self.bom_cache_path.read_text(encoding="utf-8", errors="ignore")
                dfb = self._parse_bom_rmm_text(txt)
                if not dfb.empty:
                    print(
                        format_log(
                            "INFO",
                            message=f"BoM (cache fallback): {self.bom_cache_path} → {dfb.index.min().date()}..{dfb.index.max().date()} (N={len(dfb)})",
                        )
                    )
                    return dfb
            except Exception:
                pass

        # fallback extra: arquivo solto na raiz do projeto (se você já tiver um legado)
        root = Path("bom_rmm_cache.txt")
        if root.exists():
            try:
                txt = root.read_text(encoding="utf-8", errors="ignore")
                dfb = self._parse_bom_rmm_text(txt)
                if not dfb.empty:
                    print(
                        format_log(
                            "INFO",
                            message=f"BoM (cache local raiz): {root} → {dfb.index.min().date()}..{dfb.index.max().date()} (N={len(dfb)})",
                        )
                    )
                    return dfb
            except Exception:
                pass

        raise RuntimeError(f"Falha ao obter série BoM ({web_err})")


    def _load_bom_rmm(self, path_or_url: str | Path) -> pd.DataFrame:
        """Leitura direta de arquivo local (não usada no caminho padrão)."""
        p = Path(str(path_or_url))
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            return self._parse_bom_rmm_text(txt)
        return pd.DataFrame(columns=["rmm1","rmm2","phase","amplitude"])


    # ===================== URLs padrão de dados =====================
    OLR_URL1_DEFAULT = "https://downloads.psl.noaa.gov/Datasets/cpc_blended_olr-2.5deg/olr.day.mean.nc"  # 1991-presente (CPC)
    OLR_URL2_DEFAULT = "https://downloads.psl.noaa.gov/Datasets/interp_OLR/olr.day.mean.nc"              # ~1974-2022 (interp CDR)
    U_URLS_DEFAULT   = [
        "https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis/Dailies/pressure/uwnd.{year}.nc",
        "https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis/pressure/uwnd.{year}.nc",
    ]

    # ===================== Caminhos padrão =====================
    OLR_DEST_CPC = Path("data/olr/olr.day.mean_1991-presente.nc")
    OLR_DEST_OLD = Path("data/olr/olr.day.mean_1974-2022.nc")
    U_DIR        = Path("data/u_ncep_R1")

    # ----------------------------------------------------------
    # __init__ + utilidades de config
    # ----------------------------------------------------------
    from contextlib import contextmanager

    def __init__(self, cfg: dict | str | Path):
        # aceita dict (já parseado) ou caminho p/ config.txt
        if isinstance(cfg, (str, Path)):
            self.cfg = self._parse_config_file(Path(cfg))
        elif isinstance(cfg, dict):
            self.cfg = cfg
        else:
            raise TypeError("cfg deve ser dict ou caminho para config.txt")

        validate_config_OMJ(self.cfg)

        # modo
        self.modo = (self._get_str("OMJ_MODO", "TESTE") or "TESTE").strip().upper()
        self.MODO = self.modo  # compat

        # nomes auxiliares para compor as pastas (opcionais no config)
        self.NOME_TESTE = (self.cfg.get("OMJ_TESTE_NOME") or self.cfg.get("NOME_TESTE") or "sem_nome")
        self.NOME_EXPERIMENTO = (self.cfg.get("OMJ_NOME_EXPERIMENTO") or self.cfg.get("NOME_EXPERIMENTO") or "EXTERNO")
        self.NOME_EXTERNO = (self.cfg.get("OMJ_EXTERNO_NOME") or self.NOME_EXPERIMENTO or "EXTERNO")

        def _slug(s: str) -> str:
            import re, unicodedata
            s = (s or "").strip()
            s = unicodedata.normalize("NFKD", s)
            s = "".join(c for c in s if not unicodedata.combining(c))
            s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
            s = re.sub(r"__+", "_", s).strip("._-")
            return s or "sem_nome"

        base = OUTPUT_ROOT / "OMJ"
        if self.MODO == "REFERENCIA":
            raiz = base / "REFERENCIA"
            self.output_tag = "REFERENCIA"
        elif self.MODO == "TESTE":
            slug_teste = _slug(self.NOME_TESTE)
            raiz = base / f"TESTE_{slug_teste}"
            self.output_tag = f"TESTE_{slug_teste}"
        else:  # EXTERNO
            slug_ext = _slug(self.NOME_EXTERNO)
            raiz = base / f"EXTERNO_{slug_ext}"
            self.output_tag = f"EXTERNO_{slug_ext}"

        self.OUT_DIR = raiz
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR_tables = self.OUT_DIR
        self.OUT_DIR_figs   = self.OUT_DIR
        self.OUT_DIR_valida = self.OUT_DIR

        # datas para teste/base/plot
        self.teste_ini = self._get_date("OMJ_TESTE_INICIO", "1979-01-01")
        self.teste_fim = self._get_date("OMJ_TESTE_FIM",    None)
        self.externo_ini = self._get_date("OMJ_EXTERNO_INICIO", None)
        self.externo_fim = self._get_date("OMJ_EXTERNO_FIM", None)

        if self.MODO == "TESTE":
            base_cfg = self._get_str("OMJ_TESTE_BASE_CLIMA", None)
        elif self.MODO == "EXTERNO":
            base_cfg = self._get_str("OMJ_EXTERNO_BASE_CLIMA", None)
        else:
            base_cfg = self._get_str("OMJ_BASE_CLIMA", None)

        if not base_cfg:
            base_cfg = "1979-01-01:2000-12-31"

        base_pair = (base_cfg or "").replace(";", ":")
        if ":" not in base_pair:
            raise ValueError(f"[ERRO CONFIG] Base climatológica OMJ deve usar ':' (recebido: {base_cfg!r})")
        try:
            self.base_ini, self.base_fim = [pd.to_datetime(x.strip()).date() for x in base_pair.split(":", 1)]
        except Exception:
            raise ValueError(f"[ERRO CONFIG] Base climatológica OMJ inválida: {base_cfg!r}")

        # Referência (usa início + fim)
        self.diag_ini = self._get_date("OMJ_REF_DIAGRAMA_INICIO", None)
        self.diag_fim = self._get_date("OMJ_REF_DIAGRAMA_FINAL", None)
        self.diag_dias_ref = self._get_int("OMJ_REF_DIAGRAMA_DIAS_PLOT", None)

        # TESTE/EXTERNO (início + dias)
        self.diag_ini_teste = self._get_date("OMJ_TESTE_DIAGRAMA_INICIO", None)
        self.diag_dias_teste = self._get_int("OMJ_TESTE_DIAGRAMA_DIAS_PLOT", None)
        self.diag_ini_ext = self._get_date("OMJ_EXTERNO_DIAGRAMA_INICIO", None)
        self.diag_dias_ext = self._get_int("OMJ_EXTERNO_DIAGRAMA_DIAS_PLOT", None)

        # configuração de plot do diagrama WH04, dependente do modo
        self.plotar = False
        self.diag_plot_ini = None
        self.diag_plot_fim = None
        self.diag_keys_hint = ""

        if self.MODO == "REFERENCIA":
            self.plotar = self._get_bool("OMJ_REF_DIAGRAMA", default=True)
            self.diag_keys_hint = "OMJ_REF_DIAGRAMA_INICIO/(FINAL ou DIAGRAMA_DIAS_PLOT)"
            self.diag_plot_ini = self.diag_ini
            if self.diag_plot_ini is not None:
                if self.diag_fim is not None:
                    self.diag_plot_fim = self.diag_fim
                elif self.diag_dias_ref is not None:
                    if self.diag_dias_ref > 0:
                        self.diag_plot_fim = self.diag_plot_ini + pd.to_timedelta(int(self.diag_dias_ref) - 1, unit="D")
                    else:
                        print(format_log("ATENCAO", message=f"OMJ_REF_DIAGRAMA_DIAS_PLOT deve ser > 0 (recebido {self.diag_dias_ref})."))
            else:
                # se existir fim mas não início, avisa (para manter compat com configs antigas)
                if self.diag_fim is not None and self.diag_plot_ini is None:
                    print(format_log("ATENCAO", message="OMJ_REF_DIAGRAMA_FINAL definido sem OMJ_REF_DIAGRAMA_INICIO."))
        elif self.MODO == "TESTE":
            self.plotar = self._get_bool("OMJ_TESTE_DIAGRAMA", default=False)
            self.diag_keys_hint = "OMJ_TESTE_DIAGRAMA_INICIO/DIAGRAMA_DIAS_PLOT"
            if self.diag_ini_teste is not None and self.diag_dias_teste is not None:
                if self.diag_dias_teste > 0:
                    self.diag_plot_ini = self.diag_ini_teste
                    self.diag_plot_fim = self.diag_ini_teste + pd.to_timedelta(int(self.diag_dias_teste) - 1, unit="D")
                else:
                    print(format_log("ATENCAO", message=f"OMJ_TESTE_DIAGRAMA_DIAS_PLOT deve ser > 0 (recebido {self.diag_dias_teste})."))
        else:  # EXTERNO
            self.plotar = self._get_bool("OMJ_EXTERNO_DIAGRAMA", default=False)
            self.diag_keys_hint = "OMJ_EXTERNO_DIAGRAMA_INICIO/DIAGRAMA_DIAS_PLOT"
            if self.diag_ini_ext is not None and self.diag_dias_ext is not None:
                if self.diag_dias_ext > 0:
                    self.diag_plot_ini = self.diag_ini_ext
                    self.diag_plot_fim = self.diag_ini_ext + pd.to_timedelta(int(self.diag_dias_ext) - 1, unit="D")
                else:
                    print(format_log("ATENCAO", message=f"OMJ_EXTERNO_DIAGRAMA_DIAS_PLOT deve ser > 0 (recebido {self.diag_dias_ext})."))

        # fontes externas (modo EXTERNO)
        self.external_olr_path = None
        self.external_u_combined_path = None
        self.external_u850_path = None
        self.external_u200_path = None
        self.use_external_olr = False
        self.use_external_u = False
        self.external_olr_scale = 1.0
        self.external_olr_scale_provided = False
        self.external_olr_var = None
        self.external_u_var_combined = None
        self.external_u850_var = None
        self.external_u200_var = None
        self.external_dim_hints: dict[str, list[str]] = {}

        if self.MODO == "EXTERNO":
            olr_sentinels = {"olr", "default"}
            uwnd_sentinels = {"ncep_r1", "default", "ncep1", "ncepr1"}

            self.external_olr_path = self._resolve_external_path("OMJ_EXTERNO_CAMINHO_OLR", olr_sentinels)
            if self.external_olr_path is None:
                # compatibilidade com chave antiga
                self.external_olr_path = self._resolve_external_path("OMJ_EXTERNO_OLR", olr_sentinels)

            u850_path = self._resolve_external_path("OMJ_EXTERNO_CAMINHO_U850", uwnd_sentinels)
            if u850_path is None:
                u850_path = self._resolve_external_path("OMJ_EXTERNO_U850", uwnd_sentinels)
            u200_path = self._resolve_external_path("OMJ_EXTERNO_CAMINHO_U200", uwnd_sentinels)
            if u200_path is None:
                u200_path = self._resolve_external_path("OMJ_EXTERNO_U200", uwnd_sentinels)

            if u850_path and u200_path and u850_path == u200_path:
                self.external_u_combined_path = u850_path
            else:
                self.external_u850_path = u850_path
                self.external_u200_path = u200_path
                if (self.external_u850_path is None) ^ (self.external_u200_path is None):
                    raise ValueError("[ERRO CONFIG] Informe caminhos para ambos OMJ_EXTERNO_U850 e OMJ_EXTERNO_U200 ou deixe os dois como 'ncep_r1'.")

            self.use_external_olr = self.external_olr_path is not None
            self.use_external_u = (
                self.external_u_combined_path is not None
                or (self.external_u850_path is not None and self.external_u200_path is not None)
            )
            scale_keys = (
                "OMJ_EXTERNO_OLR_ESCALA",
                "OMJ_EXTERNO_OLR_SCALE",
            )
            for key in scale_keys:
                raw_scale = self._get_str(key, None)
                if raw_scale in (None, ""):
                    continue
                try:
                    self.external_olr_scale = float(str(raw_scale).replace(",", "."))
                    self.external_olr_scale_provided = True
                    break
                except Exception:
                    print(format_log("ATENCAO", message=f"Valor inválido para {key}: {raw_scale!r}. Ignorando."))

            self.external_olr_var = self._get_str("OMJ_EXTERNO_OLR_VAR", None)
            self.external_u_var_combined = self._get_str("OMJ_EXTERNO_U_VAR", None)
            self.external_u850_var = self._get_str("OMJ_EXTERNO_U850_VAR", None)
            self.external_u200_var = self._get_str("OMJ_EXTERNO_U200_VAR", None)

            dim_keys = [
                ("time", "OMJ_EXTERNO_DIM_TIME"),
                ("lat", "OMJ_EXTERNO_DIM_LAT"),
                ("lon", "OMJ_EXTERNO_DIM_LON"),
                ("level", "OMJ_EXTERNO_DIM_LEVEL"),
            ]
            dim_hints: dict[str, list[str]] = {}
            for dim_key, cfg_key in dim_keys:
                hints_raw = self._parse_str_list(self.cfg.get(cfg_key))
                if not hints_raw:
                    continue
                allowed = {alias.lower(): alias for alias in self.DIM_HINTS_DEFAULT.get(dim_key, ())}
                filtered: list[str] = []
                for hint in hints_raw:
                    if not hint:
                        continue
                    hint_norm = hint.strip()
                    if not hint_norm:
                        continue
                    key_lower = hint_norm.lower()
                    if allowed and key_lower not in allowed:
                        print(
                            format_log(
                                "ATENCAO",
                                message=(
                                    f"Dimensão externa '{dim_key}': ignorando valor '{hint_norm}' "
                                    f"(opções válidas: {sorted(set(allowed.values()))})."
                                ),
                            )
                        )
                        continue
                    canonical = allowed.get(key_lower, hint_norm)
                    if canonical not in filtered:
                        filtered.append(canonical)
                if filtered:
                    dim_hints[dim_key] = filtered
            self.external_dim_hints = dim_hints

        # latitudes para média equatorial (padrão WH04 ~ ±15°)
        self.lat_min = float(self.cfg.get("OMJ_LAT_MIN", -15))
        self.lat_max = float(self.cfg.get("OMJ_LAT_MAX",  15))

        # --- Remoção de ENOS/ONI: NAO | SIM | AMBOS ---
        raw = (self._get_str("OMJ_REMOCAO_ONI", "NAO") or "NAO").strip().upper()
        if raw in ("SIM", "YES", "Y", "TRUE", "1"):
            mode = "SIM"
        elif raw in ("AMBOS", "BOTH"):
            mode = "AMBOS"
        else:
            mode = "NAO"
        self.remocao_oni_mode = mode
        self.want_sem = True
        self.want_com = (mode in ("SIM", "AMBOS"))

        # caminho do ONI mensal
        oni_path_cfg = (self.cfg.get("OMJ_ONI_MENSAL_CSV") or self.cfg.get("OMJ_CAMINHO_ONI")
                        or "OMJ/oni_sst_nino34_ERSSTv5_mensal.csv")
        self.oni_csv = Path(oni_path_cfg)

        # performance/robustez
        self.fast_olr = True

        # logo
        self.logo_path = Path(self.cfg.get("OMJ_LOGO_PATH", "src/atmosmarine.png"))

        # validação vs BoM (sempre habilitada)
        self.bom_cache_path = Path("data/cache/OMJ/bom_rmm_cache.txt")

        #EOF meto
        self.eof_store = {}

    @staticmethod
    def _parse_config_file(path: Path) -> dict:
        d = {}
        if not path.exists():
            return d
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("="):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if "#" in v:  # remove comentários à direita
                v = v.split("#", 1)[0].strip()
            d[k] = v
        return d

    def _get_str(self, key: str, default: str | None = None) -> str | None:
        return (self.cfg.get(key, default) if self.cfg is not None else default)

    def _get_bool(self, key: str, default: bool = False) -> bool:
        raw = (self.cfg.get(key, None) if self.cfg is not None else None)
        if raw is None:
            return default
        raw = str(raw).strip().lower()
        return raw in ("1", "true", "t", "sim", "yes", "y", "on")

    def _get_int(self, key: str, default: int | None = None) -> int | None:
        raw = (self.cfg.get(key, None) if self.cfg is not None else None)
        if raw in (None, "", "None", "null"):
            return default
        try:
            return int(float(str(raw).strip()))
        except Exception:
            print(format_log("ATENCAO", message=f"Valor inteiro inválido para {key}: {raw}"))
            return default

    def _get_date(self, key: str, default: str | None) -> pd.Timestamp | None:
        val = self.cfg.get(key, None) if self.cfg is not None else None
        if val in (None, "", "None", "null"):
            return pd.to_datetime(default) if default else None
        s = str(val).strip()
        try:
            return pd.to_datetime(s, dayfirst=("-" in s and s.split("-")[0].isdigit() and len(s.split("-")[0]) <= 2))
        except Exception:
            return pd.to_datetime(default) if default else None

    @staticmethod
    def _parse_str_list(val) -> list[str]:
        if val in (None, ""):
            return []
        if isinstance(val, (list, tuple, set)):
            return [str(x).strip() for x in val if str(x).strip()]
        txt = str(val).replace(";", ",")
        return [p.strip() for p in txt.split(",") if p.strip()]

    def _resolve_external_path(self, key: str, sentinel_tokens: set[str] | None = None) -> "OMJ._ResolvedPath" | None:
        raw = self._get_str(key, None)
        if raw is None:
            return None
        val = str(raw).strip()
        if not val:
            return None

        sentinels = {s.lower() for s in (sentinel_tokens or set())}
        if val.lower() in sentinels:
            return None

        chunks = [c.strip() for c in re.split(r"[,;]", val) if c.strip()]
        if not chunks:
            return None

        resolved: list[Path] = []
        for chunk in chunks:
            expanded_chunk = os.path.expandvars(os.path.expanduser(chunk))
            has_wildcards = any(sym in expanded_chunk for sym in "*?[]")
            if has_wildcards:
                matches = sorted(Path(p) for p in glob(expanded_chunk, recursive=True))
                if not matches:
                    raise FileNotFoundError(
                        f"[ERRO CONFIG] Padrão {chunk!r} (chave {key}) não encontrou arquivos."
                    )
                resolved.extend(matches)
                continue

            p = Path(expanded_chunk)
            if p.is_dir():
                matches = sorted(p.glob("*.nc"))
                if not matches:
                    raise FileNotFoundError(
                        f"[ERRO CONFIG] Diretório {p} em {key} não contém arquivos .nc"
                    )
                resolved.extend(matches)
            else:
                if not p.exists():
                    raise FileNotFoundError(f"[ERRO CONFIG] Caminho para {key} não encontrado: {p}")
                resolved.append(p)

        if not resolved:
            raise FileNotFoundError(f"[ERRO CONFIG] Nenhum arquivo identificado para {key} ({val}).")

        # mantém ordem de aparição mas elimina duplicados
        ordered_unique: list[Path] = []
        seen = set()
        for item in resolved:
            marker = str(item)
            if marker in seen:
                continue
            seen.add(marker)
            ordered_unique.append(item)

        return OMJ._ResolvedPath(val, tuple(ordered_unique))

    def _name_with_suffix(self, filename: str) -> str:
        p = Path(filename)
        suffix = getattr(self, "SUF_EXEC", None)
        if not suffix:
            suffix = _dt.datetime.now().strftime("%Y%m")
        if p.suffix:
            return f"{p.stem}_{suffix}{p.suffix}"
        return f"{p.name}_{suffix}"

    # ----------------------------------------------------------
    # Logging simples
    # ----------------------------------------------------------
    @contextmanager
    def Step(self, descricao: str):
        depth = getattr(self, "_step_depth", 0)
        indent = "  " * depth
        t0 = time.time()
        print(format_log("INFO", message=f"{indent}|Início do Processo| → {descricao}"), flush=True)
        setattr(self, "_step_depth", depth + 1)
        try:
            yield
        except Exception as e:
            import sys
            dt = time.time() - t0
            print(
                format_log("ERRO", message=f"{indent}|Falha no Processo| → {descricao} - |Tempo decorrido|: {dt:.2f}s - {e}"),
                file=sys.stderr,
                flush=True,
            )
            raise
        else:
            dt = time.time() - t0
            print(format_log("INFO", message=f"{indent}|Final do Processo| → {descricao} - |Tempo do Processo|: {dt:.2f}s"), flush=True)
        finally:
            setattr(self, "_step_depth", depth)

    # ----------------------------------------------------------
    # Download/atualização + helpers
    # ----------------------------------------------------------
    def _download_text_first_ok(self, urls: list[str], timeout=60) -> str:
        """Tenta baixar texto das URLs com cabeçalhos de navegador."""
        import urllib.request, urllib.error
        hdrs = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
            "Accept": "text/plain,text/*;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
            "Connection": "keep-alive",
            "Referer": "https://www.bom.gov.au/climate/mjo/",
        }
        last_err = None
        for u in urls:
            try:
                req = urllib.request.Request(u, headers=hdrs, method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read()
                    return data.decode("utf-8", errors="ignore")
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Falha ao obter série BoM (último erro: {last_err})")

    def _parse_bom_rmm_text(self, text: str) -> pd.DataFrame:
        """
        Lê o texto bruto do arquivo RMM da BoM, ignorando cabeçalhos e sufixos textuais.
        Retorna DataFrame indexado por data com colunas rmm1, rmm2, phase, amplitude.
        """
        import io, re
        import pandas as pd
        numeric_lines = []
        for ln in text.splitlines():
            if re.match(r"^\s*\d{4}\s+\d{1,2}\s+\d{1,2}\b", ln):
                toks = re.split(r"\s+", ln.strip())
                if len(toks) >= 7:
                    numeric_lines.append(" ".join(toks[:7]))
        if not numeric_lines:
            return pd.DataFrame(columns=["rmm1", "rmm2", "phase", "amplitude"])

        buf = io.StringIO("\n".join(numeric_lines))
        df = pd.read_csv(
            buf, sep=r"\s+", header=None,
            names=["year", "month", "day", "rmm1", "rmm2", "phase", "amplitude"],
            na_values=["1.E36", "1E36", "1.0E36", "999", "999.0"],
            engine="python"
        )
        df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=df.day), errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date").sort_index()
        df["rmm1"] = pd.to_numeric(df["rmm1"], errors="coerce")
        df["rmm2"] = pd.to_numeric(df["rmm2"], errors="coerce")
        df["amplitude"] = pd.to_numeric(df["amplitude"], errors="coerce")
        df["phase"] = pd.to_numeric(df["phase"], errors="coerce").astype("Int64")
        return df[["rmm1", "rmm2", "phase", "amplitude"]]

    def _load_bom_rmm(self, path_or_url: str | Path) -> pd.DataFrame:
        """Lê cache local ou baixa e parseia BoM."""
        import urllib.request
        p = Path(str(path_or_url))
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            return self._parse_bom_rmm_text(txt)

        req = urllib.request.Request(str(path_or_url), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            txt = r.read().decode(charset, errors="ignore")
        # cacheia
        try:
            self.bom_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.bom_cache_path.write_text(txt, encoding="utf-8")
        except Exception:
            pass
        return self._parse_bom_rmm_text(txt)

    @staticmethod
    def _head_last_modified(url: str) -> pd.Timestamp | None:
        import urllib.request
        from email.utils import parsedate_to_datetime
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                lm = r.headers.get("Last-Modified")
                if lm:
                    return pd.to_datetime(parsedate_to_datetime(lm))
        except Exception:
            return None
        return None

    def _needs_download_year(self, url_templates: list[str], year: int, dest: Path) -> tuple[bool, str | None]:
        """Decide se baixa/atualiza UWND do ano dado. Retorna (needs, chosen_url|None)."""
        if not dest.exists():
            for tmpl in url_templates:
                try:
                    _ = self._head_last_modified(tmpl.format(year=year))
                    return True, tmpl.format(year=year)
                except Exception:
                    continue
            return True, url_templates[0].format(year=year)

        local_mtime = pd.Timestamp(dest.stat().st_mtime, unit="s", tz="UTC").tz_localize(None)
        best_url = None
        best_lm  = None
        for tmpl in url_templates:
            url = tmpl.format(year=year)
            lm  = self._head_last_modified(url)
            if lm is not None:
                lm = lm.tz_localize(None)
                if (best_lm is None) or (lm > best_lm):
                    best_lm, best_url = lm, url

        if best_lm is not None:
            return (best_lm > local_mtime), (best_url if best_lm > local_mtime else None)

        age_days = (pd.Timestamp.utcnow().tz_localize(None) - local_mtime).days
        cur_year = pd.Timestamp.utcnow().year
        max_age  = 1 if (year == cur_year) else 30
        return (age_days >= max_age), (url_templates[0].format(year=year) if age_days >= max_age else None)

    @staticmethod
    def _force_download(url: str, dest: Path):
        import urllib.request, shutil, os
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1200) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(tmp, dest)

    def _needs_download(self, url: str, dest: Path) -> bool:
        if not dest.exists():
            return True
        lm = self._head_last_modified(url)
        if lm is None:
            now_naive = pd.Timestamp.utcnow().tz_localize(None)
            local_mtime = pd.Timestamp(dest.stat().st_mtime, unit="s")
            age_days = (now_naive - local_mtime).days
            if "olr.day.mean_1991-presente" in str(dest):
                return age_days >= 1
            return age_days >= 30
        local_mtime = pd.Timestamp(dest.stat().st_mtime, unit="s", tz="UTC")
        return lm.tz_localize(None) > local_mtime.tz_localize(None)

    def ensure_olr(self, url_cpc: str | None = None, url_old: str | None = None):
        if self.use_external_olr:
            print(format_log("INFO", message=f"OLR externo informado ({self.external_olr_path}) — pulando download padrão."))
            return
        url_cpc = url_cpc or self.cfg.get("OLR_URL1", self.OLR_URL1_DEFAULT)
        url_old = url_old or self.cfg.get("OLR_URL2", self.OLR_URL2_DEFAULT)
        if self._needs_download(url_cpc, self.OLR_DEST_CPC):
            print(format_log("DOWNLOAD", target="OLR/1991-atual", dest=str(self.OLR_DEST_CPC), reason="Baixando/Atualizando arquivo"))
            try:
                self._force_download(url_cpc, self.OLR_DEST_CPC)
            except Exception as e:
                if self.OLR_DEST_CPC.exists():
                    print(
                        format_log(
                            "ATENCAO",
                            message=f"Falha ao atualizar OLR/1991-atual ({e}) — usando arquivo local: {self.OLR_DEST_CPC}",
                        )
                    )
                else:
                    raise RuntimeError(
                        format_log(
                            "ERRO",
                            message=f"Não foi possível baixar OLR/1991-atual ({e}) e nenhum arquivo local foi encontrado.",
                        )
                    ) from e
        else:
            print(format_log("INFO", message=f"Arquivo OLR/1991-atual atualizado: {self.OLR_DEST_CPC}"))
        if self._needs_download(url_old, self.OLR_DEST_OLD):
            print(format_log("DOWNLOAD", target="Arquivo OLR/1974-2022", dest=str(self.OLR_DEST_OLD), reason="Baixando/Atualizando arquivo"))
            try:
                self._force_download(url_old, self.OLR_DEST_OLD)
            except Exception as e:
                if self.OLR_DEST_OLD.exists():
                    print(
                        format_log(
                            "ATENCAO",
                            message=f"Falha ao atualizar OLR antigo ({e}) — usando arquivo local antigo: {self.OLR_DEST_OLD}",
                        )
                    )
                else:
                    raise RuntimeError(
                        format_log(
                            "ERRO",
                            message=f"Não foi possível baixar OLR antigo ({e}) e nenhum arquivo local foi encontrado.",
                        )
                    ) from e
        else:
            print(format_log("INFO", message=f"Arquivo OLR/1974-2022 atualizado: {self.OLR_DEST_OLD}"))

        if not self.OLR_DEST_CPC.exists():
            raise FileNotFoundError(format_log("ERRO", message=f"Arquivo OLR CPC inexistente em {self.OLR_DEST_CPC}."))
        if not self.OLR_DEST_OLD.exists():
            raise FileNotFoundError(format_log("ERRO", message=f"Arquivo OLR antigo inexistente em {self.OLR_DEST_OLD}."))

        # última data no CPC (1991-presente)
        try:
            last = self._nc_last_time(self.OLR_DEST_CPC)
            if last is not None:
                print(format_log("INFO", message=f"Última data em {self.OLR_DEST_CPC.resolve()}: {last.date()}"))
            else:
                print(format_log("ERRO", message=f"Não foi possível determinar a última data em {self.OLR_DEST_CPC.resolve()}"))
        except Exception as e:
            print(format_log("ERRO", message=f"Falha ao ler última data do OLR CPC: {e}"))

    def ensure_uwnd(self, u_urls: list[str] | None = None):
        if self.use_external_u:
            print(format_log("INFO", message="UWND externo informado — pulando atualização NCEP."))
            return
        u_urls = u_urls or self.U_URLS_DEFAULT
        base_start_year = None
        base_end_year = None
        if getattr(self, "base_ini", None) is not None:
            base_start_year = pd.Timestamp(self.base_ini).year
        if getattr(self, "base_fim", None) is not None:
            base_end_year = pd.Timestamp(self.base_fim).year

        start_year = base_start_year if base_start_year is not None else 1979
        end_year = base_end_year if base_end_year is not None else pd.Timestamp.utcnow().year

        if self.teste_ini is not None:
            start_year = min(start_year, pd.Timestamp(self.teste_ini).year)
        if self.teste_fim is not None:
            end_year = max(end_year, pd.Timestamp(self.teste_fim).year)

        if self.externo_ini is not None:
            start_year = min(start_year, pd.Timestamp(self.externo_ini).year)
        if self.externo_fim is not None:
            end_year = max(end_year, pd.Timestamp(self.externo_fim).year)

        end_year = max(end_year, pd.Timestamp.utcnow().year)
        years = range(start_year, end_year + 1)
        self.U_DIR.mkdir(parents=True, exist_ok=True)

        for y in years:
            dest = self.U_DIR / f"uwnd.{y}.nc"
            needs, url = self._needs_download_year(u_urls, y, dest)
            if needs:
                chosen = url or (u_urls[0].format(year=y))
                try:
                    reason = "Arquivo ausente → Baixando..." if not dest.exists() else "Atualização programada"
                    print(format_log("DOWNLOAD", target=f"UWND {y}", dest=str(dest), reason=reason))
                    self._force_download(chosen, dest)
                except Exception as e:
                    if dest.exists():
                        print(
                            format_log(
                                "ATENCAO",
                                message=f"Falhou baixar/atualizar UWND {y} ({e}) — usando arquivo local antigo: {dest}",
                            )
                        )
                    else:
                        raise RuntimeError(
                            format_log(
                                "ERRO",
                                message=f"Não foi possível obter UWND {y} ({e}) e não há cache local em {dest}.",
                            )
                        ) from e
            else:
                print(format_log("INFO", message=f"Vento Zonal - UWND {y} atualizado: {dest}"))

        # última data no conjunto UWND
        try:
            files = sorted(self.U_DIR.glob("uwnd.*.nc"))
            if not files:
                print(format_log("ERRO", message=f"Nenhum UWND encontrado em {self.U_DIR.resolve()}"))
                return
            last_dates = []
            for f in files:
                lt = self._nc_last_time(f)
                if lt is not None:
                    last_dates.append((lt, f))
            if last_dates:
                last_date, last_file = max(last_dates, key=lambda x: x[0])
                print(
                    format_log(
                        "INFO",
                        message=(
                            f"Última data dos arquivos UWND (em {last_file.name}): "
                            f"{last_date.date()}"
                        ),
                    )
                )
            else:
                print(format_log("ERRO", message="Não foi possível determinar a última data nos arquivos UWND."))
        except Exception as e:
            print(format_log("ERRO", message=f"Falha ao ler última data dos UWND: {e}"))

    @staticmethod
    def _nc_last_time(path: Path):
        """Retorna a última data (Timestamp) encontrada no NetCDF ou None."""
        import xarray as xr
        last_err = None
        for eng in ("h5netcdf", "netcdf4"):
            try:
                ds = xr.open_dataset(path, engine=eng, decode_cf=True, cache=False)
                for cand in ("time", "TIME", "valid_time", "t", "date", "dates"):
                    if cand in ds.coords:
                        t = pd.to_datetime(ds[cand].values)
                        ds.close()
                        return pd.to_datetime(t[-1]) if len(t) > 0 else None
                for v in ds.variables:
                    dims = getattr(ds[v], "dims", ())
                    if "time" in dims or "TIME" in dims:
                        if "time" in ds.variables:
                            t = pd.to_datetime(ds["time"].values)
                        elif "TIME" in ds.variables:
                            t = pd.to_datetime(ds["TIME"].values)
                        else:
                            continue
                        ds.close()
                        return pd.to_datetime(t[-1]) if len(t) > 0 else None
                ds.close()
            except Exception as e:
                last_err = e
                continue
        return None
    
    def _stash_eof(self, tag, EOFs, Svals, col_ok, lons, scales, t_index, base_mask, n_modes):
        """
        Guarda tudo que precisamos para plotar EOFs e calcular variâncias.
        - tag: 'SEM' ou 'COM'
        - EOFs: matriz (M_keep × n_modes) com autovetores (VT[:n].T)
        - Svals: singulares completos (comprimento = M_keep)
        - col_ok: máscara booleana (3*Nlon) das colunas mantidas na base
        """
        import numpy as np
        nlon = len(lons)
        var_slices = {
            "olr":  slice(0, nlon),
            "u850": slice(nlon, 2*nlon),
            "u200": slice(2*nlon, 3*nlon),
        }
        # explained variance ratio global por PC
        s2 = (Svals**2).astype(float)
        evr = s2 / s2.sum()

        self.eof_store[tag] = dict(
            EOFs=EOFs,                 # (M_keep × n_modes)
            Svals=Svals,               # (M_keep,)
            evr=evr,                   # (M_keep,)
            col_ok=np.asarray(col_ok, bool),   # (3*Nlon,)
            lons=np.asarray(lons, float),
            scales=scales,             # {'olr':..., 'u850':..., 'u200':...}
            var_slices=var_slices,
            t_index=t_index,
            base_mask=np.asarray(base_mask, bool),
            nlon=nlon,
            n_modes=int(n_modes),
        )


    # ----------------------------------------------------------
    # Abertura/merge OLR
    # ----------------------------------------------------------
    @staticmethod
    def _lat_sorted(da: xr.DataArray) -> xr.DataArray:
        if "lat" in da.dims and da.lat.size > 1 and float(da.lat[0]) > float(da.lat[-1]):
            return da.isel(lat=slice(None, None, -1))
        return da

    @staticmethod
    def _norm_lon0360(da: xr.DataArray) -> xr.DataArray:
        if "lon" not in da.dims:
            return da
        lon2 = (np.asarray(da["lon"].values) % 360.0 + 360.0) % 360.0
        return da.assign_coords(lon=("lon", lon2)).sortby("lon")

    @staticmethod
    def _ensure_time_lon(da: xr.DataArray) -> xr.DataArray:
        order = [d for d in ("time", "lat", "lon") if d in da.dims]
        tail = [d for d in da.dims if d not in order]
        return da.transpose(*(order + tail))

    @staticmethod
    def _open_dataset_any(path: Path | "OMJ._ResolvedPath") -> xr.Dataset:
        if isinstance(path, OMJ._ResolvedPath):
            targets = path.as_open_args()
        else:
            targets = [str(Path(path))]

        last = None
        engines = ("h5netcdf", "netcdf4", None)
        for eng in engines:
            try:
                if len(targets) == 1:
                    return xr.open_dataset(targets[0], engine=eng, decode_cf=True, cache=False)
                return xr.open_mfdataset(
                    targets,
                    engine=eng,
                    decode_cf=True,
                    combine="by_coords",
                    parallel=False,
                )
            except Exception as e:
                last = e
                continue
        raise RuntimeError(format_log("ERRO", message=f"Falha ao abrir {path}: {last}"))

    def _standardize_da(self, da: xr.DataArray) -> xr.DataArray:
        rename_map = {}
        alias_map = {dim: list(self.DIM_HINTS_DEFAULT.get(dim, ())) for dim in self.DIM_HINTS_DEFAULT}
        for dim, hints in (self.external_dim_hints or {}).items():
            alias_map.setdefault(dim, [])
            for hint in hints:
                if not hint:
                    continue
                if hint not in alias_map[dim]:
                    alias_map[dim].append(hint)
                hint_lower = hint.lower()
                if hint_lower not in alias_map[dim]:
                    alias_map[dim].append(hint_lower)

        dims_and_coords = set(da.dims) | set(da.coords)
        for target, aliases in alias_map.items():
            for alias in aliases:
                if alias in dims_and_coords and alias != target:
                    rename_map[alias] = target
                elif alias.lower() in dims_and_coords and alias.lower() != target:
                    rename_map[alias.lower()] = target
        if rename_map:
            da = da.rename({k: v for k, v in rename_map.items() if k in da.dims or k in da.coords})
        if "time" not in da.dims:
            raise ValueError(format_log("ERRO", message="Variável não possui dimensão temporal reconhecida ('time')."))
        return da

    @staticmethod
    def _detect_data_var(ds: xr.Dataset, priority: list[str], contains: list[str], label: str) -> str:
        names = list(ds.data_vars)
        lower_map = {name.lower(): name for name in names}
        for key in priority:
            if key in lower_map:
                return lower_map[key]
        for key in priority:
            for name in names:
                if key in name.lower():
                    return name
        for key in contains:
            for name in names:
                if key in name.lower():
                    return name
        if len(names) == 1:
            return names[0]
        raise ValueError(
            format_log("ERRO", message=f"Não encontrei variável adequada em {label}; disponíveis: {names}")
        )

    @staticmethod
    def _match_dataset_var(ds: xr.Dataset, desired: str | None) -> str | None:
        if desired in (None, ""):
            return None
        if desired in ds.data_vars:
            return desired
        lower_map = {name.lower(): name for name in ds.data_vars}
        return lower_map.get(str(desired).lower())

    @staticmethod
    def _sel_level(da: xr.DataArray, target: float, tolerance: float = 0.6) -> xr.DataArray:
        if "level" not in da.dims:
            raise ValueError(format_log("ERRO", message="Dados de vento precisam da dimensão 'level'."))
        levels = pd.to_numeric(np.asarray(da["level"].values).ravel(), errors="coerce")
        if np.isnan(levels).all():
            raise ValueError(format_log("ERRO", message="Valores de nível inválidos em dataset de vento."))
        scaled_levels = levels.copy()
        if np.nanmax(np.abs(scaled_levels)) > 2000:
            scaled_levels = scaled_levels / 100.0
        idx = int(np.nanargmin(np.abs(scaled_levels - target)))
        sel_val = float(levels[idx])
        sel_val_scaled = float(scaled_levels[idx])
        if abs(sel_val_scaled - target) > tolerance:
            raise ValueError(
                format_log("ERRO", message=f"Nível {target} hPa não encontrado (nível mais próximo: {sel_val_scaled}).")
            )
        return da.isel(level=idx, drop=True)

    @staticmethod
    def _slice_time_range(da: xr.DataArray, start: pd.Timestamp | None, end: pd.Timestamp | None) -> xr.DataArray:
        if start is not None and end is not None:
            return da.sel(time=slice(start, end))
        if start is not None:
            return da.sel(time=slice(start, None))
        if end is not None:
            return da.sel(time=slice(None, end))
        return da

    def _slice_for_outputs(self, obj):
        """
        Recorta Series/DataFrames para o intervalo de saída configurado nos modos TESTE/EXTERNO.
        Em outros modos retorna o objeto original.
        """
        if obj is None:
            return obj
        if self.MODO == "TESTE":
            start = self.teste_ini
            end = self.teste_fim
        elif self.MODO == "EXTERNO":
            start = self.externo_ini
            end = self.externo_fim
        else:
            return obj
        if start is None and end is None:
            return obj
        if isinstance(obj, (pd.Series, pd.DataFrame)):
            data = obj
            if start is not None:
                data = data.loc[data.index >= start]
            if end is not None:
                data = data.loc[data.index <= end]
            return data
        return obj

    @staticmethod
    def _infer_time_step_seconds(da: xr.DataArray) -> float | None:
        if "time" not in da.dims:
            return None
        times = pd.to_datetime(da["time"].values)
        if times.size < 2:
            return None
        diffs = np.diff(times.values.astype("datetime64[ns]").astype("int64")) / 1e9
        diffs = diffs[np.isfinite(diffs)]
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            return None
        return float(np.median(diffs))

    @staticmethod
    def _open_olr_file(path: Path) -> xr.DataArray:
        last = None
        for eng in ("h5netcdf", "netcdf4"):
            try:
                ds = xr.open_dataset(path, engine=eng, cache=False, decode_cf=True)
                da = ds["olr"]
                if "latitude" in da.dims or "longitude" in da.dims:
                    da = da.rename({"latitude": "lat", "longitude": "lon"})
                da = OMJ._ensure_time_lon(OMJ._norm_lon0360(OMJ._lat_sorted(da)))
                nt = da.sizes["time"]
                for it in sorted({0, nt // 2, nt - 1}):
                    _ = da.isel(time=it, lat=slice(0, 2), lon=slice(0, 2)).load()
                ds.close()
                return da
            except Exception as e:
                last = e
        raise RuntimeError(format_log("ERRO", message=f"Falha ao abrir {path.name}: {last}"))

    def open_olr_merged(self) -> xr.DataArray:
        if self.use_external_olr:
            print(format_log("INFO", message=f"Abrindo OLR externo: {self.external_olr_path}"))
            return self._load_external_olr()
        self.ensure_olr()
        old = self._open_olr_file(self.OLR_DEST_OLD)
        cpc = self._open_olr_file(self.OLR_DEST_CPC)
        t0_cpc = pd.to_datetime(cpc.time.values[0])
        old_cut = old.sel(time=slice(None, t0_cpc - np.timedelta64(1, "D")))
        merged = xr.concat([old_cut, cpc], dim="time").sortby("time")

        def _rng(da: xr.DataArray, label: str):
            t0 = pd.to_datetime(da.time.values[0]).date()
            t1 = pd.to_datetime(da.time.values[-1]).date()
            print(format_log("INFO", message=f"{label}: {t0} → {t1} (N={da.sizes['time']})"))

        _rng(old, "Período de OLR/1974-2022")
        _rng(cpc, "Período de OLR/1991-atual")
        _rng(merged, "Novo Período de OLR após a concatenação")
        return merged

    def _apply_external_olr_scaling(self, da: xr.DataArray, var_name: str) -> xr.DataArray:
        if not isinstance(da, xr.DataArray):
            return da

        units = str(da.attrs.get("units", "") or "").lower()
        long_name = str(da.attrs.get("long_name", "") or "").lower()
        var_lower = (var_name or "").lower()

        cfg_scale = float(self.external_olr_scale or 1.0)
        cfg_provided = bool(self.external_olr_scale_provided)
        manual_applied = False

        energy_like = (
            var_lower in {"tisr", "ssrd", "ssr"}
            or "j m" in units
            or "j/m" in units
            or "joule" in units
            or "energia" in long_name
        )

        if energy_like:
            divisor = None
            source = ""
            if cfg_provided and abs(cfg_scale) > 1e-12:
                divisor = cfg_scale
                manual_applied = True
                source = f"configurado ({cfg_scale:g} s)"
            else:
                divisor = self._infer_time_step_seconds(da)
                if divisor and divisor > 0:
                    source = f"inferido (≈{divisor:g} s)"
            if divisor and divisor > 0:
                da = da / divisor
                attrs = dict(da.attrs)
                attrs["units"] = "W m-2"
                attrs["conversion_note"] = f"dividido_por_{divisor:g}_s"
                da.attrs = attrs
                print(format_log("INFO", message=f"OLR externo '{var_name}': convertendo J m⁻² → W m⁻² ({source})."))
            else:
                mensagem = (
                    f"OLR externo '{var_name}' aparenta estar em energia acumulada (J m⁻²), "
                    "mas não foi possível determinar o Δt para converter em W m⁻²."
                )
                if cfg_provided and abs(cfg_scale) <= 1e-12:
                    mensagem += " Verifique o valor informado em *_OLR_ESCALA."
                print(format_log("ATENCAO", message=mensagem))

        if cfg_provided and not manual_applied and abs(cfg_scale - 1.0) > 1e-9:
            if cfg_scale > 0:
                if cfg_scale > 1.0:
                    da = da / cfg_scale
                    op = "dividindo"
                else:
                    da = da * cfg_scale
                    op = "multiplicando"
                attrs = dict(da.attrs)
                attrs["manual_scale_applied"] = float(cfg_scale)
                da.attrs = attrs
                print(format_log("INFO", message=f"OLR externo '{var_name}': {op} por fator {cfg_scale:.6g}."))
            else:
                print(format_log("ATENCAO", message=f"Fator *_OLR_ESCALA inválido ({cfg_scale}); ignorando."))
        return da

    def _load_external_olr(self) -> xr.DataArray:
        if self.external_olr_path is None:
            raise RuntimeError(format_log("ERRO", message="Caminho externo de OLR não configurado."))
        ds = self._open_dataset_any(self.external_olr_path)
        try:
            if self.external_olr_var:
                matched = self._match_dataset_var(ds, self.external_olr_var)
                if matched is None:
                    raise RuntimeError(
                        f"Variável '{self.external_olr_var}' não encontrada em {self.external_olr_path}. "
                        f"Disponíveis: {list(ds.data_vars)}"
                    )
                var_name = matched
            else:
                var_name = self._detect_data_var(
                    ds,
                    priority=["olr", "rlut", "ttr"],
                    contains=["olr", "outgoing_longwave", "longwave", "toa"],
                    label=self.external_olr_path.name,
                )
            da = ds[var_name].load()
        finally:
            ds.close()
        da = self._standardize_da(da)
        da = self._ensure_time_lon(self._norm_lon0360(self._lat_sorted(da)))
        da = da.sortby("time")
        if self.MODO == "EXTERNO":
            da = self._apply_external_olr_scaling(da, var_name)
        return da

    def _load_external_uwnd(self) -> xr.DataArray:
        if self.external_u_combined_path is not None:
            u850, u200 = self._load_uwnd_combined_levels(self.external_u_combined_path, self.external_u_var_combined)
        else:
            if self.external_u850_path is None or self.external_u200_path is None:
                raise RuntimeError(format_log("ERRO", message="Caminhos externos de U850/U200 não configurados."))
            u850 = self._load_uwnd_level_file(self.external_u850_path, 850.0, self.external_u850_var)
            u200 = self._load_uwnd_level_file(self.external_u200_path, 200.0, self.external_u200_var)

        u850, u200 = xr.align(u850, u200, join="inner")
        level_coord = xr.DataArray([850.0, 200.0], dims=["level"], coords={"level": [850.0, 200.0]})
        combined = xr.concat([u850, u200], dim=level_coord)
        combined.name = u850.name or u200.name or "uwnd"
        combined = self._ensure_time_lon(self._norm_lon0360(self._lat_sorted(combined)))
        return combined.sortby("time")

    def _load_uwnd_combined_levels(self, path: Path | "OMJ._ResolvedPath", var_name: str | None = None) -> tuple[xr.DataArray, xr.DataArray]:
        ds = self._open_dataset_any(path)
        try:
            selected = self._match_dataset_var(ds, var_name)
            if selected is None:
                selected = self._detect_data_var(
                    ds,
                    priority=["uwnd", "u"],
                    contains=["uwnd", "u_component", "zonal_wind", "u-wind"],
                    label=path.name if isinstance(path, OMJ._ResolvedPath) else Path(path).name,
                )
            da = ds[selected].load()
        finally:
            ds.close()
        da = self._standardize_da(da)
        if "level" not in da.dims:
            raise ValueError(format_log("ERRO", message=f"Arquivo {path} deve conter dimensão de níveis (level/plev)."))
        levels = pd.to_numeric(np.asarray(da["level"].values), errors="coerce")
        da = da.assign_coords(level=levels)
        if np.isnan(levels).all():
            raise ValueError(format_log("ERRO", message=f"Níveis inválidos no arquivo {path}."))
        u850 = self._sel_level(da, 850.0)
        u200 = self._sel_level(da, 200.0)
        u850 = self._ensure_time_lon(self._norm_lon0360(self._lat_sorted(u850)))
        u200 = self._ensure_time_lon(self._norm_lon0360(self._lat_sorted(u200)))
        return u850.sortby("time"), u200.sortby("time")

    def _load_uwnd_level_file(self, path: Path | "OMJ._ResolvedPath", target_level: float, var_name: str | None = None) -> xr.DataArray:
        ds = self._open_dataset_any(path)
        try:
            selected = self._match_dataset_var(ds, var_name)
            if selected is None:
                selected = self._detect_data_var(
                    ds,
                    priority=["uwnd", "u"],
                    contains=["uwnd", "u_component", "zonal_wind", "u-wind"],
                    label=path.name if isinstance(path, OMJ._ResolvedPath) else Path(path).name,
                )
            da = ds[selected].load()
        finally:
            ds.close()
        da = self._standardize_da(da)
        if "level" in da.dims:
            levels = pd.to_numeric(np.asarray(da["level"].values), errors="coerce")
            da = da.assign_coords(level=levels)
            if np.isnan(levels).all():
                raise ValueError(format_log("ERRO", message=f"Níveis inválidos no arquivo {path}."))
            da = self._sel_level(da, target_level)
        da = self._ensure_time_lon(self._norm_lon0360(self._lat_sorted(da)))
        return da.sortby("time")

    # ----------------------------------------------------------
    # ONI helper
    # ----------------------------------------------------------
    def _load_oni_series(self) -> pd.Series:
        try:
            oni_df = pd.read_csv(self.oni_csv, sep=None, engine="python", comment="#")
        except Exception as e:
            raise RuntimeError(format_log("ERRO", message=f"Falha ao ler OMJ_CAMINHO_ONI ({self.oni_csv}): {e}"))

        if oni_df.empty:
            raise ValueError(format_log("ERRO", message=f"Arquivo ONI vazio: {self.oni_csv}"))

        cols_lower = {c.lower(): c for c in oni_df.columns}

        # Determina datas
        date_aliases = ("date", "data")
        col_date = None
        for alias in date_aliases:
            if alias in cols_lower:
                col_date = cols_lower[alias]
                break

        if col_date is not None:
            oni_df[col_date] = pd.to_datetime(oni_df[col_date], errors="coerce")
        elif {"ano", "mes"}.issubset(cols_lower.keys()):
            col_year = cols_lower["ano"]
            col_month = cols_lower["mes"]
            years = pd.to_numeric(oni_df[col_year], errors="coerce")
            months = pd.to_numeric(oni_df[col_month], errors="coerce")
            if "dia" in cols_lower:
                days = pd.to_numeric(oni_df[cols_lower["dia"]], errors="coerce")
            else:
                days = pd.Series(1, index=oni_df.index, dtype=float)
            years_i = years.round().astype(pd.Int64Dtype())
            months_i = months.round().astype(pd.Int64Dtype())
            days_i = days.fillna(1).round().astype(pd.Int64Dtype())
            col_date = "date"
            oni_df[col_date] = pd.to_datetime(
                {"year": years_i, "month": months_i, "day": days_i},
                errors="coerce"
            )
        else:
            raise ValueError(
                format_log(
                    "ERRO",
                    message=(
                        "Arquivo ONI deve conter coluna 'date' ou pares 'ano'/'mes'. "
                        f"Colunas encontradas: {list(oni_df.columns)}"
                    ),
                )
            )

        if oni_df[col_date].isnull().all():
            raise ValueError(format_log("ERRO", message=f"Coluna de datas inválida em {self.oni_csv}"))

        # Determina coluna de valores
        value_col = None
        for key in ("oni", "anomalia", "sst", "tsm", "valor", "value"):
            if key in cols_lower:
                value_col = cols_lower[key]
                break
        if value_col is None:
            raise ValueError(
                format_log(
                    "ERRO",
                    message=f"Arquivo ONI deve conter coluna de valores (ex.: 'oni', 'tsm'); colunas: {list(oni_df.columns)}",
                )
            )

        series = (
            oni_df[[col_date, value_col]]
            .dropna(subset=[col_date])
            .set_index(col_date)
            .sort_index()[value_col]
        )
        series = pd.to_numeric(series, errors="coerce").dropna()
        if series.empty:
            raise ValueError(format_log("ERRO", message=f"Série ONI sem valores numéricos válidos em {self.oni_csv}"))
        series.name = "oni"
        return series.asfreq("MS")

    # ----------------------------------------------------------
    # UWND concat + níveis
    # ----------------------------------------------------------
    def open_uwnd_concat(self) -> xr.DataArray:
        if self.use_external_u:
            # print(format_log("INFO", message="Abrindo UWND externo."))
            return self._load_external_uwnd()
        files = sorted(self.U_DIR.glob("uwnd.*.nc"))
        if not files:
            raise FileNotFoundError(
                format_log("ERRO", message="Nenhum uwnd.YYYY.nc em data/u_ncep_R1/ — rode ensure_uwnd().")
            )

        # 1) Tenta open_mfdataset SEM dask (chunks=None)
        try:
            ds = xr.open_mfdataset(
                files,
                combine="by_coords",
                decode_cf=True,
                cache=False,
                chunks=None,        # <- evita dask
                parallel=False
            )
        except ImportError:
            # 2) Fallback: sem dask, abre arquivo a arquivo e combina
            datasets = None
            last = None
            for eng in ("h5netcdf", "netcdf4"):
                try:
                    datasets = [xr.open_dataset(f, engine=eng, decode_cf=True, cache=False) for f in files]
                    break
                except Exception as e:
                    last = e
                    continue
            if not datasets:
                raise RuntimeError(format_log("ERRO", message=f"Falha ao abrir UWND sem dask: {last}"))
            # combine_by_coords lida com concatenação por 'time'
            ds = xr.combine_by_coords(datasets, combine_attrs="drop_conflicts")

        var = ds["uwnd"]
        if "latitude" in var.dims or "longitude" in var.dims:
            var = var.rename({"latitude": "lat", "longitude": "lon"})
        var = self._norm_lon0360(self._lat_sorted(var))
        return var


    @staticmethod
    def _daily_mean_if_needed(da: xr.DataArray) -> xr.DataArray:
        t = pd.DatetimeIndex(da["time"].values)
        return da if pd.infer_freq(t) == "D" else da.resample(time="1D").mean()

    @staticmethod
    def select_levels(var: xr.DataArray) -> tuple[xr.DataArray, xr.DataArray, str]:
        levname = "level" if "level" in var.dims else ("lev" if "lev" in var.dims else None)
        if levname is None:
            raise ValueError(format_log("ERRO", message="Sem dimensão de níveis em uwnd (level/lev)."))
        levs = set(np.asarray(var[levname].values).astype(float).tolist())
        if not {200.0, 850.0}.issubset(levs):
            raise ValueError(
                format_log(
                    "ERRO", message=f"Níveis 200/850 ausentes; disponíveis: {sorted(list(levs))[:10]} ..."
                )
            )
        return var.sel({levname: 850}), var.sel({levname: 200}), levname

    # ----------------------------------------------------------
    # Médias equatoriais (robustas)
    # ----------------------------------------------------------
    def lat_band_mean_fast(self, da: xr.DataArray, lat_min=None, lat_max=None) -> xr.DataArray:
        lat_min = self.lat_min if lat_min is None else lat_min
        lat_max = self.lat_max if lat_max is None else lat_max
        da = self._norm_lon0360(self._lat_sorted(da))
        out = da.sel(lat=slice(lat_min, lat_max)).mean("lat")
        return self._ensure_time_lon(out)

    def lat_band_mean_tolerant(self, da: xr.DataArray, lat_min=None, lat_max=None, probe_tile=True) -> xr.DataArray:
        lat_min = self.lat_min if lat_min is None else lat_min
        lat_max = self.lat_max if lat_max is None else lat_max
        da = self._norm_lon0360(self._lat_sorted(da))
        band = da.sel(lat=slice(lat_min, lat_max))
        times = pd.DatetimeIndex(band.time.values)
        lon = band.lon
        rows, bad = [], []
        for t in times:
            try:
                x = band.sel(time=t).mean("lat")
                if probe_tile:
                    _ = x.isel(lon=0).values
                rows.append(x.assign_coords(time=t).expand_dims("time"))
            except Exception:
                bad.append(str(pd.to_datetime(t).date()))
                fill = xr.DataArray(np.full(lon.shape, np.nan), coords={"lon": lon}, dims=("lon",))
                rows.append(fill.assign_coords(time=t).expand_dims("time"))
        out = xr.concat(rows, dim="time").sortby("time")
        if bad:
            exemplos = ", ".join(bad[:12])
            if len(bad) > 12:
                exemplos += " ..."
            print(
                format_log(
                    "INFO",
                    message=f"OLR: Dias ignorados (NaN): {len(bad)} — ex.: {exemplos}",
                )
            )
        return self._ensure_time_lon(out)

    def lat_band_mean_safe(self, da: xr.DataArray, lat_min=None, lat_max=None) -> xr.DataArray:
        if not self.fast_olr:
            return self.lat_band_mean_tolerant(da, lat_min, lat_max)
        try:
            return self.lat_band_mean_fast(da, lat_min, lat_max)
        except Exception as e:
            print(format_log("INFO", message=f"OLR: FAST quebrou ({e}); caindo para tolerante."))
            return self.lat_band_mean_tolerant(da, lat_min, lat_max)

    # ----------------------------------------------------------
    # Pré-processamento (Fourier3, ONI mensal opcional, 120d-prev)
    # ----------------------------------------------------------
    @staticmethod
    def preprocess_field_vec(da_eq: xr.DataArray, oni_monthly: pd.Series | None) -> xr.DataArray:
        da_eq = da_eq.transpose("time", "lon")
        t = pd.DatetimeIndex(da_eq.time.values)
        Y = da_eq.values.astype(float)

        allnan = np.isnan(Y).all(axis=0)
        col_mean = np.nanmean(Y, axis=0, keepdims=True)
        col_mean[:, allnan] = 0.0
        Yf = np.where(np.isnan(Y), col_mean, Y)

        doy = t.dayofyear.values
        doy = np.where((t.month == 2) & (t.day == 29), 59, doy)
        w = 2 * np.pi / 365.0
        X = np.stack([
            np.ones_like(doy, float),
            np.cos(1*w*doy), np.sin(1*w*doy),
            np.cos(2*w*doy), np.sin(2*w*doy),
            np.cos(3*w*doy), np.sin(3*w*doy),
        ], axis=1)
        beta, *_ = np.linalg.lstsq(X, Yf, rcond=None)
        Yd = Yf - X @ beta

        if oni_monthly is not None:
            start_m = t.min().to_period('M').to_timestamp()
            end_m   = t.max().to_period('M').to_timestamp()
            pred_m  = oni_monthly.reindex(pd.date_range(start_m, end_m, freq='MS')).ffill()
            p = pred_m.reindex(t, method='ffill').values.astype(float)

            for m in range(1, 13):
                mask = (t.month == m)
                if mask.sum() < 20:
                    continue
                Xm = np.stack([p[mask], np.ones(mask.sum(), float)], axis=1)
                Ym = Yd[mask, :]
                colm = np.nanmean(Ym, axis=0, keepdims=True)
                colm = np.where(np.isnan(colm), 0.0, colm)
                Ym_f = np.where(np.isnan(Ym), colm, Ym)
                beta_m, *_ = np.linalg.lstsq(Xm, Ym_f, rcond=None)
                Yd[mask, :] = Ym - (Xm @ beta_m)

        da_tmp = xr.DataArray(Yd, coords={"time": da_eq.time, "lon": da_eq.lon}, dims=("time", "lon"))
        ma = da_tmp.rolling(time=120, min_periods=1).mean().shift(time=1)
        out = da_tmp - ma
        out.values[:, allnan] = np.nan
        return out

    # ----------------------------------------------------------
    # Empilhamento, base, EOF/SVD, projeção
    # ----------------------------------------------------------
    @staticmethod
    def as_time_lon(da: xr.DataArray) -> xr.DataArray:
        return da.transpose("time", "lon")

    @staticmethod
    def stack_features(olr: xr.DataArray, u850: xr.DataArray, u200: xr.DataArray):
        olr, u850, u200 = xr.align(olr, u850, u200, join="inner")
        lons = olr["lon"].values
        s_olr  = float(np.nanstd(olr.values))
        s_u850 = float(np.nanstd(u850.values))
        s_u200 = float(np.nanstd(u200.values))
        X = np.hstack([olr.values/s_olr, u850.values/s_u850, u200.values/s_u200])
        return X, lons, {"olr": s_olr, "u850": s_u850, "u200": s_u200}

    @staticmethod
    def filter_base(X: np.ndarray, t_index: pd.DatetimeIndex,
                    base_start: str, base_end: str,
                    day_nan_thr=0.2, col_nan_thr=0.2):
        mask = (t_index >= pd.to_datetime(base_start)) & (t_index <= pd.to_datetime(base_end))
        Xb = X[mask].copy()
        day_ok = np.isnan(Xb).mean(axis=1) <= day_nan_thr
        Xb = Xb[day_ok]
        col_ok = np.isnan(Xb).mean(axis=0) <= col_nan_thr
        Xb = Xb[:, col_ok]
        info = dict(
            base_days=int(mask.sum()),
            kept_days=int(day_ok.sum()),
            kept_cols=int(col_ok.sum()),
            day_nan_thr=day_nan_thr,
            col_nan_thr=col_nan_thr
        )
        return Xb, mask, col_ok, info

    @staticmethod
    def svd_eof(X: np.ndarray, n=2):
        X0 = X - np.nanmean(X, axis=0, keepdims=True)
        X0 = np.where(np.isnan(X0), 0.0, X0)
        U, S, VT = np.linalg.svd(X0, full_matrices=False)
        PCs = U[:, :n] * S[:n]
        EOFs = VT[:n, :].T
        return EOFs, PCs, S

    @staticmethod
    def project_all(X_all: np.ndarray, col_ok: np.ndarray, EOFs: np.ndarray,
                    pc_mean: np.ndarray, pc_std: np.ndarray) -> np.ndarray:
        Xp = X_all[:, col_ok]
        X0 = Xp - np.nanmean(Xp, axis=0, keepdims=True)
        X0 = np.where(np.isnan(X0), 0.0, X0)
        PCs = X0 @ EOFs
        RMM = (PCs - pc_mean) / pc_std
        return RMM

    # ----------------------------------------------------------
    # Alinhamento físico (âncoras IO/WP)
    # ----------------------------------------------------------
    @staticmethod
    def _box_mean_olr_conv(OLR_P: xr.DataArray, lon0: float, lon1: float) -> pd.Series:
        olr = OLR_P
        if (olr.lon < 0).any():
            olr = olr.assign_coords(lon=(olr.lon % 360)).sortby("lon")
        sel = olr.sel(lon=slice(lon0, lon1))
        if sel.sizes.get("lon", 0) == 0:
            raise ValueError(
                format_log("ERRO", message=f"Nenhum ponto lon em {lon0}–{lon1} na grade OLR.")
            )
        conv = (-sel.mean("lon")).to_series()
        conv.name = f"conv_{int(lon0)}_{int(lon1)}E"
        return conv

    @staticmethod
    def align_to_physics(df_rmm: pd.DataFrame, OLR_P: xr.DataArray, amp_thr: float = 1.0):
        io = OMJ._box_mean_olr_conv(OLR_P, 60, 100)
        wp = OMJ._box_mean_olr_conv(OLR_P, 140, 170)

        A = df_rmm.copy()
        tmp = A.join(io, how="inner").join(wp, how="inner").dropna(subset=["rmm1", "rmm2"])
        if tmp.empty:
            raise RuntimeError("[INFO] Sem interseção temporal entre RMM e OLR_P para alinhamento físico.")

        amp = np.hypot(tmp["rmm1"], tmp["rmm2"])
        mask = amp >= amp_thr
        if mask.sum() < 20:
            mask = np.isfinite(amp)

        X1, X2 = tmp["rmm1"].values, tmp["rmm2"].values
        IO, WP = tmp[io.name].values, tmp[wp.name].values
        m = mask.values.astype(bool)

        C = {
            "id":       lambda x, y: ( x,  y),
            "flip":     lambda x, y: (-x, -y),
            "swap":     lambda x, y: ( y, -x),
            "swapflip": lambda x, y: (-y,  x),
            "flipx":    lambda x, y: (-x,  y),
            "flipy":    lambda x, y: ( x, -y),
        }

        def _corr(a, b):
            a = np.asarray(a, float); b = np.asarray(b, float)
            mm = np.isfinite(a) & np.isfinite(b) & m
            if mm.sum() < 3:
                return -np.inf
            return float(np.corrcoef(a[mm], b[mm])[0, 1])

        best_key, best_score = None, -1e9
        for k, f in C.items():
            r1p, r2p = f(X1, X2)
            score = (_corr(r1p, IO) if np.isfinite(_corr(r1p, IO)) else -np.inf) \
                  + (_corr(r2p, WP) if np.isfinite(_corr(r2p, WP)) else -np.inf)
            if score > best_score:
                best_key, best_score = k, score

        out = A.copy()
        out["rmm1"], out["rmm2"] = C[best_key](out["rmm1"].values, out["rmm2"].values)
        out["amplitude"] = np.hypot(out["rmm1"], out["rmm2"])
        ang = (np.degrees(np.arctan2(out["rmm2"], out["rmm1"])) % 360.0)
        bins = [0, 45, 90, 135, 180, 225, 270, 315, 360]
        lab = [5,6,7,8,1,2,3,4]
        ii = np.digitize(ang, bins, right=False) - 1
        out["phase"] = [lab[int(np.clip(i, 0, 7))] for i in ii]

        return out, best_key

    # ----------------------------------------------------------
    # Pipeline principal
    # ----------------------------------------------------------
    def run(self):
        with self.Step("Verificando a existência dos dados de OLR & UWND"):
            if self.use_external_olr:
                print(format_log("INFO", message=f"Dado OLR externo disponível ({self.external_olr_path})."))
            else:
                self.ensure_olr()
            if self.use_external_u:
                targets = [p for p in [self.external_u_combined_path, self.external_u850_path, self.external_u200_path] if p is not None]
                print(
                    format_log(
                        "INFO",
                        message=f"Dado UWND externo disponível ({', '.join(str(p) for p in targets)}).",
                    )
                )
            else:
                self.ensure_uwnd()

        with self.Step("Abrindo os arquivos de OLR"):
            OLR = self.open_olr_merged()

        with self.Step("Abrindo os arquivos de UWND"):
            UWND = self.open_uwnd_concat()
            uwnd_ini = pd.to_datetime(UWND.time.values[0]).date()
            uwnd_fim = pd.to_datetime(UWND.time.values[-1]).date()
            print(
                format_log(
                    "INFO",
                    message=(
                        f"Período de UWND após a concatenação: {uwnd_ini} → {uwnd_fim} "
                        f"(N={UWND.sizes.get('time', len(UWND.time))})"
                    ),
                )
            )

        U850, U200, _ = self.select_levels(self._daily_mean_if_needed(UWND))

        OLR_eq  = self.lat_band_mean_safe(self._daily_mean_if_needed(OLR))
        U850_eq = self.lat_band_mean_fast(U850)
        U200_eq = self.lat_band_mean_fast(U200)

        with self.Step("Alinhando os tempos dos arquivos OLR/U850/U200"):
            OLR_eq, U850_eq, U200_eq = xr.align(OLR_eq, U850_eq, U200_eq, join="inner")

        with self.Step("Lendo dados de OLR/U850/U200"):
            OLR_eq  = OLR_eq.load()
            U850_eq = U850_eq.load()
            U200_eq = U200_eq.load()

        # carregar ONI apenas se vamos gerar COM_REMOCAO_ENOS
        oni_m = None
        if self.want_com:
            try:
                oni_m = self._load_oni_series()
                print(
                    format_log(
                        "INFO",
                        message=f"ONI mensal disponível: {oni_m.index.min().date()} → {oni_m.index.max().date()}",
                    )
                )
            except Exception as e:
                print(
                    format_log(
                        "ATENCAO",
                        message=(
                            f"Remoção de ENOS pedida ({self.remocao_oni_mode}), mas falhou carregar ENOS ({e}). "
                            "Seguindo SEM remoção do ENOS."
                        ),
                    )
                )
                self.want_com = False
                oni_m = None

        # SEM ENOS
        with self.Step("Pré-processamento da OMJ sem aplicar a remoção do ENOS (vetorizado)"):
            OLR_P_sem  = self.preprocess_field_vec(OLR_eq,  oni_monthly=None)
            U850_P_sem = self.preprocess_field_vec(U850_eq, oni_monthly=None)
            U200_P_sem = self.preprocess_field_vec(U200_eq, oni_monthly=None)

        # COM ENOS (opcional)
        OLR_P_com = U850_P_com = U200_P_com = None
        if self.want_com and (oni_m is not None):
            with self.Step("Pré-processamento da OMJ considerando os dados de ONI para remoção do sinal do ENOS (vetorizado)"):
                OLR_P_com  = self.preprocess_field_vec(OLR_eq,  oni_monthly=oni_m)
                U850_P_com = self.preprocess_field_vec(U850_eq, oni_monthly=oni_m)
                U200_P_com = self.preprocess_field_vec(U200_eq, oni_monthly=oni_m)

        def _pipeline_to_df(OLR_P, U850_P, U200_P, base_ini, base_fim, tag: str):
            OLR_P  = self.as_time_lon(OLR_P)
            U850_P = self.as_time_lon(U850_P)
            U200_P = self.as_time_lon(U200_P)
            X_all, LONS, SCALES = self.stack_features(OLR_P, U850_P, U200_P)
            TIDX = pd.DatetimeIndex(OLR_P.time.values)

            base_ini_eff = max(pd.to_datetime(base_ini), TIDX.min())
            base_fim_eff = min(pd.to_datetime(base_fim), TIDX.max())

            def _log_base_filter_info(data: dict) -> None:
                base_days = data.get("base_days", "?")
                kept_days = data.get("kept_days", "?")
                kept_cols = data.get("kept_cols", "?")
                day_thr = data.get("day_nan_thr", "?")
                col_thr = data.get("col_nan_thr", "?")
                print(format_log("INFO", message="Resultado da filtragem da base climatológica (BC):"))
                print(
                    format_log(
                        "INFO",
                        message=(
                            f"  Dias na BC: {base_days} | Dias BC após o filtro: {kept_days} | "
                            f"Colunas mantidas na BC: {kept_cols} | "
                            f"Limite de NaN por dia: {day_thr} | Limite de NaN por coluna: {col_thr}"
                        ),
                    )
                )

            Xb, base_mask, col_ok, info = self.filter_base(
                X_all, TIDX, base_ini_eff, base_fim_eff, day_nan_thr=0.2, col_nan_thr=0.2
            )
            _log_base_filter_info(info)
            if Xb.shape[0] < 60:
                print(format_log("INFO", message="EOF: Base pequena; relaxando para 0.3/0.3…"))
                Xb, base_mask, col_ok, info = self.filter_base(
                    X_all, TIDX, base_ini_eff, base_fim_eff, day_nan_thr=0.3, col_nan_thr=0.3
                )
                _log_base_filter_info(info)
            EOFs, PCs_base, Svals = self.svd_eof(Xb, n=2)
            pc_mean = PCs_base.mean(axis=0)
            pc_std  = PCs_base.std(axis=0, ddof=1)
            # guarda para plots/métricas
            self._stash_eof(
                tag=tag, EOFs=EOFs, Svals=Svals, col_ok=col_ok, lons=LONS,
                scales=SCALES, t_index=TIDX, base_mask=base_mask, n_modes=EOFs.shape[1]
            )

            RMM = self.project_all(X_all, col_ok, EOFs, pc_mean, pc_std)
            df  = pd.DataFrame({"date": TIDX, "rmm1": RMM[:, 0], "rmm2": RMM[:, 1]}).set_index("date")
            df["amplitude"] = np.sqrt(df.rmm1**2 + df.rmm2**2)
            ang = np.degrees(np.arctan2(df.rmm2, df.rmm1)) % 360
            df["phase"] = np.digitize(ang, [0,45,90,135,180,225,270,315,360]) % 8
            df["phase"] = df["phase"].replace({0: 8})
            return df, OLR_P

        with self.Step("Construindo DataFrame do OMJ sem aplicar nenhuma remoção do ENOS"):
            df_sem_full, OLR_P_SEM = _pipeline_to_df(OLR_P_sem, U850_P_sem, U200_P_sem, self.base_ini, self.base_fim, tag="SEM")
            df_sem_phys_full, key_sem = self.align_to_physics(df_sem_full, OLR_P_SEM, amp_thr=1.0)

        df_sem = self._slice_for_outputs(df_sem_full)
        df_sem_phys = self._slice_for_outputs(df_sem_phys_full)

        if self.MODO == "TESTE":
            if isinstance(df_sem, pd.DataFrame) and df_sem.empty:
                print(format_log("ATENCAO", message="Série sem aplicar nenhuma remoção do ENOS corre vazia no intervalo OMJ_TESTE_INICIO/OMJ_TESTE_FIM."))
            if isinstance(df_sem_phys, pd.DataFrame) and df_sem_phys.empty:
                print(format_log("ATENCAO", message="Série sem aplicar nenhuma remoção do ENOS vazia no intervalo configurado."))

        df_com_phys = df_com = None
        if (OLR_P_com is not None) and (U850_P_com is not None) and (U200_P_com is not None):
            with self.Step("Construindo DataFrame do OMJ aplicando a remoção do ENOS"):

                df_com_full, OLR_P_COM = _pipeline_to_df(OLR_P_com, U850_P_com, U200_P_com, self.base_ini, self.base_fim, tag="COM")
                df_com_phys_full, key_com = self.align_to_physics(df_com_full, OLR_P_COM, amp_thr=1.0)
            df_com = self._slice_for_outputs(df_com_full)
            df_com_phys = self._slice_for_outputs(df_com_phys_full)
            if self.MODO == "TESTE":
                if isinstance(df_com, pd.DataFrame) and df_com.empty:
                    print(format_log("ATENCAO", message="Série aplicando a remoção do ENOS vazia no intervalo OMJ_TESTE_INICIO/OMJ_TESTE_FIM."))
                if isinstance(df_com_phys, pd.DataFrame) and df_com_phys.empty:
                    print(format_log("ATENCAO", message="Série aplicando a remoção do ENOS vazia no intervalo configurado."))

        # salvar
        self.save_outputs(df_sem=df_sem, df_sem_phys=df_sem_phys, df_com=df_com, df_com_phys=df_com_phys)

        # validação vs BoM
        self.validate_vs_bom(df_sem_phys=df_sem_phys, df_com_phys=df_com_phys)

        # plot (opcional) — estritamente pelo intervalo do config
        if self.plotar:
            if (self.diag_plot_ini is None) or (self.diag_plot_fim is None):
                hint = self.diag_keys_hint or "parâmetros de diagrama"
                print(
                    format_log(
                        "INFO",
                        message=f"Opção de plotagem habilitada, mas defina {hint} corretamente. Diagrama não será gerado.",
                    )
                )
            else:
                fname_sem = f"OMJ_diagrama_WH04_SEM_REMOCAO_ENOS_{self.diag_plot_ini.date()}_{self.diag_plot_fim.date()}.png"
                save_sem = self.OUT_DIR_figs / self._name_with_suffix(fname_sem)
                self.plot_diagrama(
                    source=self.OUT_DIR_tables / self._name_with_suffix("OMJ_SEM_REMOCAO_ENOS.csv"),
                    start=self.diag_plot_ini, end=self.diag_plot_fim,
                    amp_circle=1.0,
                    save_path=save_sem
                )
                if self.want_com and isinstance(df_com_phys, pd.DataFrame):
                    try:
                        fname_com = f"OMJ_diagrama_WH04_COM_REMOCAO_ENOS_{self.diag_plot_ini.date()}_{self.diag_plot_fim.date()}.png"
                        save_com = self.OUT_DIR_figs / self._name_with_suffix(fname_com)
                        self.plot_diagrama(
                            source=self.OUT_DIR_tables / self._name_with_suffix("OMJ_COM_REMOCAO_ENOS.csv"),
                            start=self.diag_plot_ini,
                            end=self.diag_plot_fim,
                            amp_circle=1.0,
                            save_path=save_com,
                        )
                    except Exception as e:
                        print(format_log("ATENCAO", message=f"Falha ao plotar diagrama COM ENOS: {e}"))
        # plotagem comparativa OMJ vs BoM (2x3)
        # --- plotagem comparativa OMJ vs BoM (3x2) — SÉRIE TOTAL (interseção OMJ×BoM)
        try:
            save_sem = self.OUT_DIR_figs / self._name_with_suffix("OMJ_serie-temporal_CALCvsBoM_SEM_REMOCAO_ENOS.png")
            self.plot_validacao_bom_3x2(modo="SEM", save_path=save_sem)
        except Exception as e:
            print(
                format_log("ATENCAO", message=f"Plotagem comparativa OMJ vs BoM (SEM ENOS) falhou ({e})")
            )

        if self.want_com and isinstance(df_com_phys, pd.DataFrame):
            try:
                save_com = self.OUT_DIR_figs / self._name_with_suffix("OMJ_serie-temporal_CALCvsBoM_COM_REMOCAO_ENOS.png")
                self.plot_validacao_bom_3x2(modo="COM", save_path=save_com)
            except Exception as e:
                print(
                    format_log("ATENCAO", message=f"Plotagem comparativa OMJ vs BoM (COM ENOS) falhou ({e})")
                )

        print(format_log("INFO", message="Plotagem OMJ concluída."))

        # # EOFs (SEM) — normalizado
        # self.plot_eofs(tag="SEM", n_modes=2,
        #             save_path=self.OUT_DIR_figs / "EOFs_SEM.png")

        # # EOFs (COM), se houver
        # if "COM" in self.eof_store:
        #     self.plot_eofs(tag="COM", n_modes=2,
        #                 save_path=self.OUT_DIR_figs / "EOFs_COM.png")

        # Tabelas de variância
        self.eof_variance_tables(
            tag="SEM",
            save_pc_csv=self.OUT_DIR_valida / self._name_with_suffix("OMJ_EOF_variancia_por_EOF_SEM_REMOCAO_ENOS.csv"),
            save_var_csv=self.OUT_DIR_valida / self._name_with_suffix("OMJ_EOF_variancia_por_variavel_SEM_REMOCAO_ENOS.csv"),
        )
        # Tabelas de variância – COM ENOS (se disponível)
        if "COM" in self.eof_store:
            self.eof_variance_tables(
                tag="COM",
                save_pc_csv=self.OUT_DIR_valida / self._name_with_suffix("OMJ_EOF_variancia_por_PC_COM_REMOCAO_ENOS.csv"),
                save_var_csv=self.OUT_DIR_valida / self._name_with_suffix("OMJ_EOF_variancia_por_variavel_COM_REMOCAO_ENOS.csv"),
            )
            
        if "SEM" in self.eof_store and "COM" in self.eof_store:
            save_compare = self.OUT_DIR_figs / self._name_with_suffix("OMJ_EOF_SEM_REMOCAOvsCOM_REMOCAO.png")
            self.plot_eofs_compare_3x2(tag_sem="SEM", tag_com="COM", n_modes=2, unscale=False, save_path=save_compare)
        elif "SEM" in self.eof_store:
            save_sem_only = self.OUT_DIR_figs / self._name_with_suffix("OMJ_EOFs_SEM_REMOCAO_ENOS.png")
            try:
                self.plot_eofs(tag="SEM", n_modes=2, unscale=False, save_path=save_sem_only)
            except Exception as e:
                print(format_log("ATENCAO", message=f"Falha ao gerar figura de EOFs SEM ENOS ({e})"))

    # ----------------------------------------------------------
    # Salvamento de CSVs
    # ----------------------------------------------------------
    def save_outputs(self, df_sem: pd.DataFrame, df_sem_phys: pd.DataFrame | None,
                     df_com: pd.DataFrame | None, df_com_phys: pd.DataFrame | None):
        salvar_raw = self._get_bool("OMJ_SALVAR_RAW", False)

        def _save(df, fname, descricao: str):
            out = self.OUT_DIR_tables / self._name_with_suffix(fname)
            df[["rmm1","rmm2","amplitude","phase"]].to_csv(
                out, index=True, date_format="%Y-%m-%d", float_format="%.6f"
            )
            print(format_log("SALVO", item=descricao, destino=str(out)))

        if salvar_raw and isinstance(df_sem, pd.DataFrame):
            _save(df_sem, "OMJ_SEM_REMOCAO_ENOS_RAW.csv", "Série OMJ sem remoção do ENSO (RAW) salva →")
        if salvar_raw and isinstance(df_com, pd.DataFrame):
            _save(df_com, "OMJ_COM_REMOCAO_ENOS_RAW.csv", "Série OMJ com remoção do ENSO (RAW) salva →")

        if isinstance(df_sem_phys, pd.DataFrame):
            _save(df_sem_phys, "OMJ_SEM_REMOCAO_ENOS.csv", "Série OMJ sem remoção do ENSO salva →")
        if isinstance(df_com_phys, pd.DataFrame):
            _save(df_com_phys, "OMJ_COM_REMOCAO_ENOS.csv", "Série OMJ com remoção do ENSO salva →")

    # ----------------------------------------------------------
    # Diagrama de fase WH04
    # ----------------------------------------------------------
    @staticmethod
    def _load_rmm(source):
        if isinstance(source, pd.DataFrame):
            df = source.copy()
        else:
            df = pd.read_csv(source)
        if not isinstance(df.index, pd.DatetimeIndex):
            date_col = None
            for c in ("date","data","Date","DATE"):
                if c in df.columns:
                    date_col = c; break
            if date_col is None:
                raise ValueError(format_log("ERRO", message="Não encontrei coluna de datas ('date')."))
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
        colmap = {c.lower(): c for c in df.columns}
        for k in ("rmm1","rmm2"):
            if k not in colmap:
                raise ValueError(format_log("ERRO", message="Tabela não tem colunas rmm1/rmm2."))
        if "amplitude" not in colmap:
            df["amplitude"] = np.sqrt(df[colmap["rmm1"]]**2 + df[colmap["rmm2"]]**2)
            colmap["amplitude"] = "amplitude"
        if "phase" not in colmap:
            ang = (np.degrees(np.arctan2(df[colmap["rmm2"]], df[colmap["rmm1"]])) % 360.0)
            bins = [0,45,90,135,180,225,270,315,360]
            lab  = [5,6,7,8,1,2,3,4]
            idx = np.digitize(ang, bins, right=False) - 1
            df["phase"] = [lab[int(np.clip(i,0,7))] for i in idx]
            colmap["phase"] = "phase"
        df = df.rename(columns={
            colmap["rmm1"]: "rmm1",
            colmap["rmm2"]: "rmm2",
            colmap["amplitude"]: "amplitude",
            colmap["phase"]: "phase",
        })
        df = df.sort_index()
        return df[["rmm1","rmm2","amplitude","phase"]]

    def plot_diagrama(self, source=None,
                      start=None, end=None, amp_circle=1.0,
                      save_path=None, title=None,
                      hilight_last_n=None, **kwargs):
        import numpy as np
        import matplotlib.pyplot as plt
        import matplotlib.lines as mlines
        import matplotlib.image as mpimg
        import matplotlib.patheffects as pe
        from matplotlib.offsetbox import AnnotationBbox, OffsetImage

        default_source = self.OUT_DIR_tables / self._name_with_suffix("OMJ_SEM_REMOCAO_ENOS.csv")
        df = self._load_rmm(source or default_source)
        if start: df = df.loc[pd.to_datetime(start):]
        if end:   df = df.loc[:pd.to_datetime(end)]
        if df.empty:
            raise ValueError(format_log("ERRO", message="Janela escolhida não tem dados."))

        meses_pt = {
            1:"janeiro", 2:"fevereiro", 3:"março", 4:"abril",
            5:"maio", 6:"junho", 7:"julho", 8:"agosto",
            9:"setembro", 10:"outubro", 11:"novembro", 12:"dezembro"
        }
        base_colors = [
            "#e60026", "#ff6a00", "#00a84f", "#6a00a8",
            "#cc4c02", "#00b5ad", "#5a5a5a", "#0064ff",
            "#ff2fb2", "#c4c700", "#00c7ff", "#ff9f0a",
        ]
        month_color = {m+1: base_colors[m] for m in range(12)}

        x = df["rmm1"].to_numpy()
        y = df["rmm2"].to_numpy()
        t = pd.DatetimeIndex(df.index)
        amp = df["amplitude"].to_numpy()
        from math import ceil
        rmax = float(ceil(max(amp.max(), 1.5, 4.0)*1.05*2)/2)

        fig, ax = plt.subplots(figsize=(7,7), dpi=300)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-rmax, rmax); ax.set_ylim(-rmax, rmax)
        ax.axhline(0, color="0.85", lw=1)
        ax.axvline(0, color="0.85", lw=1)

        th = np.linspace(0, 2*np.pi, 361)
        ax.plot(amp_circle*np.cos(th), amp_circle*np.sin(th), ":", lw=1.1, color="0.5", zorder=0)

        for deg in range(0, 360, 45):
            th = np.deg2rad(deg)
            ax.plot([0, rmax*np.cos(th)], [0, rmax*np.sin(th)], color="0.9", lw=1, zorder=0)

        rlab = rmax*0.78
        labels_num = {0:5, 45:6, 90:7, 135:8, 180:1, 225:2, 270:3, 315:4}
        for deg, ph in labels_num.items():
            th = np.deg2rad(deg+22.5)
            ax.text(rlab*np.cos(th), rlab*np.sin(th), str(ph),
                    ha="center", va="center", fontsize=10, color="0.35")

        ax.text(0,  rmax*0.95, "Pacífico Oeste", ha="center", va="top", fontsize=11, color="0.25")
        ax.text( rmax*0.98, 0, "Continente Marítimo", ha="right", va="center", fontsize=11, color="0.25", rotation=270)
        ax.text(0, -rmax*0.95, "Oceano Índico", ha="center", va="bottom", fontsize=11, color="0.25")
        ax.text(-rmax*0.98, 0, "Hemisfério Oeste e África", ha="left", va="center", fontsize=11, color="0.25", rotation=90)

        meses_presentes = t.month.to_numpy()
        meses_unicos_ordenados = list(dict.fromkeys(meses_presentes))
        legend_handles = []


        pts = np.column_stack([x, y])                       # (N, 2)
        segs = np.stack([pts[:-1], pts[1:]], axis=1)        # (N-1, 2, 2)

        # mantém continuidade só onde ambos os pontos são válidos
        ok = np.isfinite(segs).all(axis=(1, 2))
        segs = segs[ok]

        # escolha a regra de cor do segmento:
        # 1) cor do "dia de chegada" (i+1): segue a cor do mês para onde o ponto vai
        seg_month = t.month[1:].to_numpy()[ok]
        # (se preferir cor do "dia de partida", use t.month[:-1].to_numpy()[ok])

        seg_colors = [month_color.get(int(m), "#333333") for m in seg_month]

        lc = LineCollection(segs, colors=seg_colors, linewidths=1.0, zorder=2)
        ax.add_collection(lc)

        # --- LEGENDA POR MÊS (mantém como antes, sem redesenhar linhas) ---
        meses_presentes = list(dict.fromkeys(t.month.to_numpy()))
        legend_handles = [
            mlines.Line2D([], [], color=month_color.get(int(m), "#333333"), lw=2, label=meses_pt[int(m)])
            for m in meses_presentes
        ]


        # pontos e rótulos (sem sombra)
        ax.scatter(x, y, s=18, facecolor="white", edgecolor="0.2", linewidth=0.7, zorder=3)
        for xi, yi, ti in zip(x, y, t):
            ax.text(xi, yi, f"{ti.day}", fontsize=7.5, color="#222222",
                    ha="center", va="center", zorder=4)

        # início/final
        m_ini = t[0].month; m_fim = t[-1].month
        c_ini = month_color.get(m_ini, "#333333")
        c_fim = month_color.get(m_fim, "#333333")
        ax.scatter([x[0]],[y[0]], s=80, marker="o", color=c_ini, edgecolor="black", linewidth=0.6, zorder=5)
        ax.scatter([x[-1]],[y[-1]], s=80, marker="s", color=c_fim, edgecolor="black", linewidth=0.6, zorder=5)
        ax.annotate("Início", (x[0], y[0]), xytext=(0, 12), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color=c_ini, weight="bold", zorder=6)
        ax.annotate("Final",  (x[-1], y[-1]), xytext=(0, 12), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color=c_fim, weight="bold", zorder=6)

        ax.set_xlabel("RMM1"); ax.set_ylabel("RMM2")
        ax.grid(ls=":", color="0.9")
        if title is None:
            ini_str = df.index.min().strftime("%Y-%m-%d")
            fim_str = df.index.max().strftime("%Y-%m-%d")
            title = f"Diagrama de fase (RMM1, RMM2) para {ini_str} até {fim_str}"
        ax.set_title(title, fontsize=12.5)

        if legend_handles:
            leg = ax.legend(handles=legend_handles, loc="upper left", frameon=True, fontsize=9, title=None)
            leg._legend_box.align = "left"

        try:
            if self.logo_path and self.logo_path.exists():
                img = mpimg.imread(str(self.logo_path))
                ab = AnnotationBbox(OffsetImage(img, zoom=0.04, resample=True),
                                    (0.98, 0.02), xycoords="axes fraction",
                                    frameon=False, box_alignment=(1,0))
                ax.add_artist(ab)
        except Exception as e:
            print(format_log("ERRO", message=f"Logo não inserido ({e})"))

        plt.tight_layout()
        if save_path:
            fig.savefig(save_path, bbox_inches="tight", dpi=300)
            print(format_log("SALVO", item="Figura gerada →", destino=str(save_path)))
        return fig, df

    # ----------------------------------------------------------
    # Métricas / Validação
    # ----------------------------------------------------------
    @staticmethod
    def _rmse(a: pd.Series, b: pd.Series) -> float:
        v = (a.astype(float) - b.astype(float))**2
        v = v[np.isfinite(v)]
        return float(np.sqrt(v.mean())) if len(v) else float("nan")

    @staticmethod
    def _angle_deg(r1, r2) -> pd.Series:
        return (pd.Series(np.degrees(np.arctan2(r2, r1))) % 360.0)

    @staticmethod
    def _ang_err_deg(a_deg: pd.Series, b_deg: pd.Series) -> float:
        x = (a_deg.astype(float) - b_deg.astype(float) + 180.0) % 360.0 - 180.0
        x = x[np.isfinite(x)]
        return float(np.median(np.abs(x))) if len(x) else float("nan")

    def _pair_metrics_vs_bom(self, ours: pd.DataFrame, bom: pd.DataFrame, label: str, note: str = "") -> dict:
        label_clean = label.strip()
        nota = note.strip()

        defaults = {
            "serie": label_clean,
            "N": 0,
            "data_inicio": None,
            "data_final": None,
            "corr_rmm1": np.nan,
            "corr_rmm2": np.nan,
            "rmse_rmm1": np.nan,
            "rmse_rmm2": np.nan,
            "bias_rmm1": np.nan,
            "bias_rmm2": np.nan,
            "corr_amp": np.nan,
            "rmse_amp": np.nan,
            "med_abs_erro_angulo": np.nan,
            "nota": nota,
        }

        J = ours.join(bom, how="inner", lsuffix="_omj", rsuffix="_bom")
        J = J.dropna(subset=["rmm1_omj","rmm2_omj","rmm1_bom","rmm2_bom"])
        if J.empty:
            if not nota:
                defaults["nota"] = "sem_intersecao"
            print(format_log("ATENCAO", message=f"Validação OMJ ({label_clean}) sem interseção com BoM."))
            return defaults

        ang_omj = self._angle_deg(J["rmm1_omj"], J["rmm2_omj"])
        ang_bom = self._angle_deg(J["rmm1_bom"], J["rmm2_bom"])
        amp_omj = (J["rmm1_omj"]**2 + J["rmm2_omj"]**2)**0.5
        amp_bom = (J["rmm1_bom"]**2 + J["rmm2_bom"]**2)**0.5

        defaults.update(
            N=int(len(J)),
            data_inicio=str(J.index.min().date()),
            data_final=str(J.index.max().date()),
            corr_rmm1=float(J["rmm1_omj"].corr(J["rmm1_bom"])),
            corr_rmm2=float(J["rmm2_omj"].corr(J["rmm2_bom"])),
            rmse_rmm1=self._rmse(J["rmm1_omj"], J["rmm1_bom"]),
            rmse_rmm2=self._rmse(J["rmm2_omj"], J["rmm2_bom"]),
            bias_rmm1=float((J["rmm1_omj"] - J["rmm1_bom"]).mean()),
            bias_rmm2=float((J["rmm2_omj"] - J["rmm2_bom"]).mean()),
            corr_amp=float(amp_omj.corr(amp_bom)),
            rmse_amp=self._rmse(amp_omj, amp_bom),
            med_abs_erro_angulo=self._ang_err_deg(ang_omj, ang_bom),
        )
        return defaults

    def validate_vs_bom(self, df_sem_phys: pd.DataFrame | None,
                        df_com_phys: pd.DataFrame | None):
        try:
            bom = self._get_bom_series()
        except Exception as e:
            print(format_log("ATENCAO", message=f"Não foi possível validar contra BoM ({e})"))
            return

        pre_end  = pd.Timestamp("2013-12-31")
        pos_ini  = pd.Timestamp("2014-01-01")

        rows = []

        # Pré-2014: BoM remove ENSO → comparar com COM_REMOCAO_ENOS (ou fallback SEM_REMOCAO_ENOS se não existir)
        bom_pre = bom.loc[:pre_end]
        if not bom_pre.empty:
            if isinstance(df_com_phys, pd.DataFrame) and not df_com_phys.empty:
                ours_pre = df_com_phys.loc[bom_pre.index.min(): bom_pre.index.max()]
                rows.append(self._pair_metrics_vs_bom(ours_pre, bom_pre, "PRE_2014_COM_REMOCAO_ENOS"))
            elif isinstance(df_sem_phys, pd.DataFrame) and not df_sem_phys.empty:
                ours_pre = df_sem_phys.loc[bom_pre.index.min(): bom_pre.index.max()]
                rows.append(self._pair_metrics_vs_bom(ours_pre, bom_pre, "PRE_2014_SEM_REMOCAO_ENOS", note="sem_interceccao"))
            else:
                print(format_log("ATENCAO", message="Sem série OMJ para validar no pré-2014."))

        # Pós-2014: BoM não remove ENSO → comparar com SEM_REMOCAO_ENOS (ou fallback COM_REMOCAO_ENOS)
        bom_pos = bom.loc[pos_ini:]
        if not bom_pos.empty:
            if isinstance(df_sem_phys, pd.DataFrame) and not df_sem_phys.empty:
                ours_pos = df_sem_phys.loc[bom_pos.index.min(): bom_pos.index.max()]
                rows.append(self._pair_metrics_vs_bom(ours_pos, bom_pos, "POS_2014_SEM_REMOCAO_ENOS"))
            elif isinstance(df_com_phys, pd.DataFrame) and not df_com_phys.empty:
                ours_pos = df_com_phys.loc[bom_pos.index.min(): bom_pos.index.max()]
                rows.append(self._pair_metrics_vs_bom(ours_pos, bom_pos, "POS_2014_COM_REMOCAO_ENOS", note="fallback_com_remocao"))
            else:
                print(format_log("ATENCAO", message="Sem série OMJ para validar no pós-2014."))

        if not rows:
            print(format_log("ATENCAO", message="Validação contra BoM não produziu resultados."))
            return

        met = pd.DataFrame(rows)
        cols = [c for c in self.METRICS_COLUMNS if c in met.columns]
        met = met[cols]
        out = self.OUT_DIR_valida / self._name_with_suffix("OMJ_metricas_estatisticas.csv")
        met.to_csv(out, index=False, float_format="%.6f")
        print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do OMJ →", destino=str(out)))

    def plot_validacao_bom_3x2(self, modo: str = "SEM", save_path=None):
        """Gera figura 3x2 comparando OMJ vs BoM para a série solicitada.

        Parameters
        ----------
        modo : str
            ``"SEM"`` (padrão) ou ``"COM"`` indicando a série física utilizada
            (OMJ_*_REMOCAO_ENOS). O valor é case-insensitive.
        save_path : Path-like, optional
            Caminho para salvar a figura. Se ``None`` retorna apenas (fig, df).
        """
        modo = (modo or "SEM").strip().upper()
        if modo not in {"SEM", "COM"}:
            raise ValueError(f"Modo inválido para plot_validacao_bom_3x2: {modo!r}")

        # --- BoM (web → cache)
        bom = self._get_bom_series()[["rmm1","rmm2"]].rename(
            columns={"rmm1":"rmm1_bom","rmm2":"rmm2_bom"}
        )

        # --- nossas tabelas PHYS
        def _load_tbl(path):
            if path.exists():
                df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
                return df[["rmm1","rmm2"]].copy()
            return None

        p_sem = self.OUT_DIR_tables / self._name_with_suffix("OMJ_SEM_REMOCAO_ENOS.csv")
        p_com = self.OUT_DIR_tables / self._name_with_suffix("OMJ_COM_REMOCAO_ENOS.csv")
        split = pd.Timestamp("2014-01-01")

        if modo == "SEM":
            ours_raw = _load_tbl(p_sem)
        else:
            ours_raw = _load_tbl(p_com)

        expected_fname = "OMJ_SEM_REMOCAO_ENOS.csv" if modo == "SEM" else "OMJ_COM_REMOCAO_ENOS.csv"
        if ours_raw is None or ours_raw.empty:
            raise RuntimeError(f"Tabela {expected_fname} não encontrada ou vazia em OUT_DIR/tabelas.")

        ours = ours_raw.sort_index().rename(
            columns={"rmm1": "rmm1_omj", "rmm2": "rmm2_omj"}
        )

        # --- interseção temporal (SÉRIE TOTAL)
        J = ours.join(bom, how="inner")
        if J.empty:
            raise RuntimeError("Sem interseção temporal OMJ vs BoM.")

        # --- vieses
        J["bias_rmm1"] = J["rmm1_omj"] - J["rmm1_bom"]
        J["bias_rmm2"] = J["rmm2_omj"] - J["rmm2_bom"]

        # --- limites simétricos por par / por viés
        def _sym_lim(vals, pad=0.05, min_yl=1.0):
            m = float(np.nanmax(np.abs(vals))) if len(vals) else 1.0
            m = max(m, min_yl)
            return (-m*(1+pad), m*(1+pad))

        y1 = _sym_lim(J[["rmm1_omj","rmm1_bom"]].values)
        y2 = _sym_lim(J[["rmm2_omj","rmm2_bom"]].values)
        yb1 = _sym_lim(J["bias_rmm1"].values, min_yl=0.5)
        yb2 = _sym_lim(J["bias_rmm2"].values, min_yl=0.5)

        # --- figura 3x2
        fig, axes = plt.subplots(3, 2, figsize=(14, 9.2), dpi=300, sharex=True)
        (ax11, ax12), (ax21, ax22), (ax31, ax32) = axes

        locator = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator)

        def _mark_split(ax, limits: tuple[float, float]) -> None:
            if not (J.index.min() <= split <= J.index.max()):
                return
            ax.axvline(split, color="0.68", ls="--", lw=1)
            y0, y1 = limits
            pad = (y1 - y0) * 0.08
            y_text = y1 - pad
            ax.text(
                split,
                y_text,
                "2014",
                ha="center",
                va="top",
                fontsize=8.5,
                color="#444444",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.85),
            )

        # Linha 1 — RMM1
        label_calc = "RMM1 Calculado"
        if modo == "SEM":
            label_calc += " (SEM REMOÇÃO DO ENOS)"
        else:
            label_calc += " (COM REMOÇÃO DO ENOS)"

        lw_series = 0.18
        lw_bias = 0.8
        title_font = 13

        ax11.plot(J.index, J["rmm1_omj"], lw=lw_series, color="#0064ff", label=label_calc)
        ax11.set_ylim(*y1); _mark_split(ax11, y1); ax11.set_ylabel("RMM1 (Calculado)" \
        "")
        ax11.grid(ls=":", color="0.9"); ax11.legend(loc="upper left", fontsize=9)
        ax11.set_title("RMM1 — Calculado", fontsize=title_font)

        ax12.plot(J.index, J["rmm1_bom"], lw=lw_series, color="#e60026", label="RMM1 BoM")
        ax12.set_ylim(*y1); _mark_split(ax12, y1)
        ax12.grid(ls=":", color="0.9"); ax12.legend(loc="upper left", fontsize=9)
        ax12.set_title("RMM1 — BoM", fontsize=title_font)

        # Linha 2 — RMM2
        label_calc_rmm2 = label_calc.replace("RMM1", "RMM2")
        ax21.plot(J.index, J["rmm2_omj"], lw=lw_series, color="#0064ff", label=label_calc_rmm2)
        ax21.set_ylim(*y2); _mark_split(ax21, y2); ax21.set_ylabel("RMM2 (Calculado)")
        ax21.grid(ls=":", color="0.9"); ax21.legend(loc="upper left", fontsize=9)
        ax21.set_title("RMM2 — Calculado", fontsize=title_font)

        ax22.plot(J.index, J["rmm2_bom"], lw=lw_series, color="#e60026", label="RMM2 BoM")
        ax22.set_ylim(*y2); _mark_split(ax22, y2)
        ax22.grid(ls=":", color="0.9"); ax22.legend(loc="upper left", fontsize=9)
        ax22.set_title("RMM2 — BoM", fontsize=title_font)

        # Linha 3 — Viés
        ax31.plot(J.index, J["bias_rmm1"], lw=lw_bias, color="#5a5a5a", label="Bias Temporal RMM1 (Calculado)")
        ax31.axhline(0, color="0.5", lw=0.2); ax31.set_ylim(*yb1); _mark_split(ax31, yb1)
        ax31.grid(ls=":", color="0.9"); ax31.legend(loc="upper left", fontsize=9)
        ax31.set_title("RMM1 — bias (Calculado−BoM)", fontsize=title_font)
        ax31.set_ylabel("Viés")
        ax32.plot(J.index, J["bias_rmm2"], lw=lw_bias, color="#5a5a5a", label="Bias Temporal RMM2 (Calculado−BoM)")
        ax32.axhline(0, color="0.5", lw=0.2); ax32.set_ylim(*yb2); _mark_split(ax32, yb2)
        ax32.grid(ls=":", color="0.9"); ax32.legend(loc="upper left", fontsize=9)
        ax32.set_title("RMM2 — bias (Calculado−BoM)", fontsize=title_font)

        # Eixo X bonito (apenas última linha mostra ticks, mas sharex aplica a todos)
        for ax in (ax31, ax32):
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)
        for ax in axes.flatten():
            ax.set_xlim(J.index.min(), J.index.max())

        # Título geral
        t0 = J.index.min().strftime("%Y-%m-%d")
        t1 = J.index.max().strftime("%Y-%m-%d")
        modo_txt = "Sem remoção do ENOS" if modo == "SEM" else "Com remoção do ENOS"
        fig.suptitle(
            f"Série Temporal índice OMJ (RMM1/RMM2) vs BoM — {modo_txt} — {t0} a {t1}",
            y=0.9,
            fontsize=15,
        )

        plt.tight_layout(rect=[0.03, 0.04, 0.98, 0.92])
        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")
            print(
                format_log(
                    "SALVO",
                    item=f"Figura comparativa OMJ vs BoM ({modo_txt}) →",
                    destino=str(save_path),
                )
            )
        return fig, J
    
    def plot_eofs(self, tag="SEM", n_modes=2, unscale=False, save_path=None):
        import numpy as np, matplotlib.pyplot as plt

        info = self.eof_store.get(tag)
        if not info:
            raise RuntimeError(f"EOFs de tag '{tag}' ainda não foram calculados.")

        EOFs   = info["EOFs"]                     # (M_keep × n_modes)
        evr    = info["evr"]                      # (M_keep,)
        evr_pc = evr[:EOFs.shape[1]]
        col_ok = info["col_ok"]
        lons   = info["lons"]; nlon = info["nlon"]
        sl     = info["var_slices"]; scales = info["scales"]

        # === NOVO: converter e reordenar longitudes para [-180, 180] ===
        lon180 = ((lons + 180.0) % 360.0) - 180.0
        order = np.argsort(lon180)  # ordem para plot contínuo de -180 → 180

        keep = col_ok
        keep_olr  = keep[sl["olr"]]
        keep_u850 = keep[sl["u850"]]
        keep_u200 = keep[sl["u200"]]

        idx_olr  = np.nonzero(keep_olr )[0]
        idx_u850 = np.nonzero(keep_u850)[0]
        idx_u200 = np.nonzero(keep_u200)[0]

        off_olr  = 0
        off_u850 = off_olr  + keep_olr.sum()
        off_u200 = off_u850 + keep_u850.sum()

        rows = []
        for name, idx_var, off, sc in [
            ("OLR",  idx_olr,  off_olr,  scales["olr"]),
            ("U850", idx_u850, off_u850, scales["u850"]),
            ("U200", idx_u200, off_u200, scales["u200"]),
        ]:
            mats = []
            for k in range(min(n_modes, EOFs.shape[1])):
                arr = np.full(nlon, np.nan, float)
                block = EOFs[off: off + len(idx_var), k]
                arr[idx_var] = block * (sc if unscale else 1.0)
                # === NOVO: reordenar o vetor para acompanhar lon180 ===
                arr = arr[order]
                mats.append(arr)
            rows.append((name, np.vstack(mats)))   # (n_modes × nlon reordenado)

        # plot: 3 linhas (variáveis) × n_modes colunas (PCs)
        fig, axes = plt.subplots(3, min(n_modes, EOFs.shape[1]), figsize=(12, 7.8), dpi=300, sharex=True)
        if axes.ndim == 1:
            axes = axes[0][None, :]

        for i, (vname, mats) in enumerate(rows):
            for k in range(mats.shape[0]):
                ax = axes[i, k]
                ax.plot(lon180[order], mats[k])
                ax.axhline(0, color="0.6", lw=1)
                ax.set_xlim(-180, 180)  # === NOVO: limitar eixo X ===
                if i == 0:
                    ax.set_title(f"EOF{k+1}  (EVR={evr_pc[k]*100:.1f}%)")
                if k == 0:
                    ax.set_ylabel(vname)
                if i == 2:
                    ax.set_xlabel("Longitude (°, −180…180)")
                ax.grid(ls=":", color="0.9")

        fig.suptitle(f"OMJ — EOFs ({tag})  •  base climatológica: {self.base_ini}–{self.base_fim}", y=0.995)
        plt.tight_layout(rect=[0, 0, 1, 0.97])
        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")
            print(format_log("SALVO", item=f"EOFs ({tag}) →", destino=str(save_path)))
        return fig
    
    def plot_eofs_compare_3x2(self,
                          tag_sem="SEM", tag_com="COM",
                          n_modes=2, unscale=False, save_path=None):
        """
        Figura única 3x2 (variáveis nas linhas: OLR, U850, U200; modos nas colunas: EOF1, EOF2),
        com curvas sobrepostas: SEM remoção (vermelho) vs COM remoção (azul).
        Eixo X em −180..180.
        """
        import numpy as np, matplotlib.pyplot as plt

        info_sem = self.eof_store.get(tag_sem)
        info_com = self.eof_store.get(tag_com)
        if not info_sem or not info_com:
            raise RuntimeError("Faltam EOFs no cache: garanta que 'SEM' e 'COM' foram calculados.")

        def _build_rows(info, n_modes, unscale):
            EOFs   = info["EOFs"]                   # (M_keep × n_modes_total)
            evr_pc = info["evr"][:EOFs.shape[1]]    # EVR global por PC
            col_ok = info["col_ok"]
            lons   = info["lons"]; nlon = info["nlon"]
            sl     = info["var_slices"]; scales = info["scales"]

            # longitudes em [-180, 180] e ordem de plot
            lon180 = ((lons + 180.0) % 360.0) - 180.0
            order = np.argsort(lon180)

            keep = col_ok
            m_olr  = keep[sl["olr"]]
            m_u850 = keep[sl["u850"]]
            m_u200 = keep[sl["u200"]]
            n_olr, n_u850, n_u200 = int(m_olr.sum()), int(m_u850.sum()), int(m_u200.sum())

            off_olr  = 0
            off_u850 = off_olr  + n_olr
            off_u200 = off_u850 + n_u850

            rows = {}
            for name, n_keep, off, sc in [
                ("OLR",  n_olr,  off_olr,  scales["olr"]),
                ("U850", n_u850, off_u850, scales["u850"]),
                ("U200", n_u200, off_u200, scales["u200"]),
            ]:
                mats = []
                for k in range(min(n_modes, EOFs.shape[1])):
                    arr = np.full(nlon, np.nan, float)
                    block = EOFs[off: off + n_keep, k]
                    arr_idx = np.nonzero([m_olr, m_u850, m_u200][["OLR","U850","U200"].index(name)])[0]
                    arr[arr_idx] = block * (sc if unscale else 1.0)
                    # reordenar para −180…180
                    mats.append(arr[order])
                rows[name] = np.vstack(mats)   # (n_modes × nlon)
            return dict(rows=rows, lon180=lon180[order], evr_pc=evr_pc)

        A = _build_rows(info_sem, n_modes, unscale)   # SEM (vermelho)
        B = _build_rows(info_com, n_modes, unscale)   # COM (azul)

        # plot 3x2
        fig, axes = plt.subplots(3, min(n_modes, A["rows"]["OLR"].shape[0]),
                                figsize=(12, 8.2), dpi=300, sharex=True)
        if axes.ndim == 1:
            axes = axes[None, :]

        var_order = ["OLR", "U850", "U200"]
        colors = {"SEM":"#e60026", "COM":"#0064ff"}  # vermelho, azul (pedido)
        for i, vname in enumerate(var_order):
            for k in range(min(n_modes, A["rows"][vname].shape[0])):
                ax = axes[i, k]
                # SEM (vermelho)
                ax.plot(A["lon180"], A["rows"][vname][k], lw=1.2, color=colors["SEM"],
                        label=f"SEM remoção (EVR={A['evr_pc'][k]*100:.1f}%)")
                # COM (azul)
                ax.plot(B["lon180"], B["rows"][vname][k], lw=1.2, color=colors["COM"],
                        label=f"COM remoção (EVR={B['evr_pc'][k]*100:.1f}%)")

                ax.axhline(0, color="0.6", lw=1)
                ax.set_xlim(-180, 180)
                ax.set_ylim(-0.15, 0.15)

                if i == 0:
                    ax.set_title(f"EOF{k+1}")
                if k == 0:
                    ax.set_ylabel(vname)
                if i == 2:
                    ax.set_xlabel("Longitude (°, −180…180)")
                ax.grid(ls=":", color="0.9")
                ax.legend(loc="upper right", fontsize=8, frameon=True)

        fig.suptitle(
            f"OMJ — EOFs comparativos (SEM vs COM remoção do ONI)\n"
            f"Base: {self.base_ini}–{self.base_fim}",
            y=0.995,
            fontsize=17,
        )
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")
            print(format_log("SALVO", item="Figura com EOF explicados SEM REMOÇÃO DO ENOS vs COM  REMOÇÃO DO ENOS →", destino=str(save_path)))
        return fig


    def eof_variance_tables(self, tag="SEM", save_pc_csv=None, save_var_csv=None):
        """
        Retorna dois DataFrames:
        - df_pc: uma linha por PC (EVR do PC e fração desse PC atribuída a cada variável)
        - df_var: contribuição total por variável somando os PCs disponíveis
        Pode salvar CSVs se caminhos forem passados.
        """
        import numpy as np, pandas as pd

        info = self.eof_store.get(tag)
        if not info:
            raise RuntimeError(f"EOFs de tag '{tag}' ainda não foram calculados.")

        EOFs   = info["EOFs"]          # (M_keep × n_modes) — colunas normalizadas (||v_k||=1)
        evr_pc = info["evr"][:EOFs.shape[1]]
        keep   = info["col_ok"]
        sl     = info["var_slices"]

        # máscaras (no espaço "mantido"):
        m_olr  = keep[sl["olr"]]
        m_u850 = keep[sl["u850"]]
        m_u200 = keep[sl["u200"]]
        n_olr, n_u850, n_u200 = m_olr.sum(), m_u850.sum(), m_u200.sum()

        off_olr  = 0
        off_u850 = off_olr  + n_olr
        off_u200 = off_u850 + n_u850

        rows = []
        for k in range(EOFs.shape[1]):
            v = EOFs[:, k]                 # vetor do PC k (unit norm)
            v_olr  = v[off_olr :  off_olr  + n_olr ]
            v_u850 = v[off_u850: off_u850 + n_u850]
            v_u200 = v[off_u200: off_u200 + n_u200]
            # fração do PC atribuída a cada grupo (somas de quadrados; total=1)
            w_olr  = float(np.sum(v_olr**2))
            w_u850 = float(np.sum(v_u850**2))
            w_u200 = float(np.sum(v_u200**2))
            # parcela da variância total (EVR_k * peso_do_grupo)
            rows.append(dict(
                eof=k+1,
                var_eof=evr_pc[k],
                peso_olr=w_olr, peso_u850=w_u850, peso_u200=w_u200,
                var_olr=evr_pc[k]*w_olr,
                var_u850=evr_pc[k]*w_u850,
                var_u200=evr_pc[k]*w_u200,
            ))

        df_pc = pd.DataFrame(rows)
        df_var = pd.DataFrame({
            "variavel": ["OLR", "U850", "U200"],
            "evr_total": [
                df_pc["var_olr"].sum(),
                df_pc["var_u850"].sum(),
                df_pc["var_u200"].sum(),
            ]
        })

        if save_pc_csv:
            df_pc.to_csv(save_pc_csv, index=False, float_format="%.6f")
            print(format_log("SALVO", item=f"Variância por EOF {tag} REMOÇÃO DO ENOS →", destino=str(save_pc_csv)))
        if save_var_csv:
            df_var.to_csv(save_var_csv, index=False, float_format="%.6f")
            print(format_log("SALVO", item=f"Variância por variável {tag} REMOÇÃO DO ENOS →", destino=str(save_var_csv)))

        return df_pc, df_var
