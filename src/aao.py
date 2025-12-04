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
from .atm_tools import validate_config_AAO, _parse_baseline_safe
from src.logging import format_log


class AAO:
    DATA_URL = "https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis/Monthlies/pressure/hgt.mon.mean.nc"
    CPC_URL = (
        "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/"
        "daily_ao_index/aao/monthly.aao.index.b79.current.ascii.table"
    )
    DEFAULT_LOGO = Path("utils/atmosmarine.png")

    def __init__(self, cfg: dict | None = None):
        validate_config_AAO(cfg)
        self.cfg = cfg or {}
        self.SUF_EXEC = _dt.datetime.now().strftime("%Y%m")

        modo = str(self.cfg.get("AAO_MODO", "REFERENCIA") or "").strip().upper()
        self.modo = modo if modo in {"REFERENCIA", "TESTE", "EXTERNO"} else "REFERENCIA"

        self.case_name = None
        base_out = self._resolve_dir("AAO_OUTDIR", OUTPUT_ROOT / "AAO")
        if self.modo == "TESTE":
            self.case_name = (
                self.cfg.get("AAO__TESTE_NOME")
                or self.cfg.get("AAO_TESTE_NOME")
                or "TESTE"
            )
            mode_dir = base_out / f"TESTE_{self._slug(self.case_name) or 'SEM_NOME'}"
        elif self.modo == "EXTERNO":
            self.case_name = self.cfg.get("AAO_EXTERNO_NOME") or "EXTERNO"
            mode_dir = base_out / f"EXTERNO_{self._slug(self.case_name) or 'EXTERNO'}"
        else:
            mode_dir = base_out / "REFERENCIA"

        self.include_20s = self._parse_bool(self.cfg.get("AAO_INCLUDE_20S"), default=True)
        self.std_ddof = self._parse_int(self.cfg.get("AAO_STD_DDOF"), default=0, min_val=0)

        level_raw = None
        if self.modo == "TESTE":
            level_raw = (
                self.cfg.get("AAO_TESTE_NIVEL_Z")
                or self.cfg.get("AAO_TESTE_NIVEL_Z_")
            )
        elif self.modo == "EXTERNO":
            level_raw = (
                self.cfg.get("AAO_EXTERNO_NIVEL_Z_")
                or self.cfg.get("AAO_EXTERNO_NIVEL_Z")
            )
        if level_raw in (None, ""):
            level_raw = self.cfg.get("AAO_LEVEL_HPA")
        self.level_hpa = self._parse_int(level_raw, default=700, min_val=1)

        lat_raw = None
        if self.modo == "TESTE":
            lat_raw = self.cfg.get("AAO_TESTE_LAT_MAX")
        elif self.modo == "EXTERNO":
            lat_raw = self.cfg.get("AAO_EXTERNO_LAT_MAX")
        if lat_raw in (None, ""):
            lat_raw = self.cfg.get("AAO_LAT_MAX")
        self.lat_max = self._parse_float(lat_raw, default=-20.0)

        default_base_start = "1979-01-01"
        default_base_end = "2000-12-31"
        base_start_dt = self._parse_date(self.cfg.get("AAO_BASE_START"), default=default_base_start)
        base_end_dt = self._parse_date(self.cfg.get("AAO_BASE_END"), default=default_base_end)

        if self.modo == "TESTE":
            base_period = self.cfg.get("AAO_TESTE_BASE_CLIMA")
            if base_period not in (None, ""):
                d0, d1 = _parse_baseline_safe(base_period)
                if d0 is not None and d1 is not None and d0 < d1:
                    base_start_dt, base_end_dt = pd.to_datetime(d0), pd.to_datetime(d1)
        elif self.modo == "EXTERNO":
            base_period = self.cfg.get("AAO_EXTERNO_BASE_CLIMA")
            if base_period not in (None, ""):
                d0, d1 = _parse_baseline_safe(base_period)
                if d0 is not None and d1 is not None and d0 < d1:
                    base_start_dt, base_end_dt = pd.to_datetime(d0), pd.to_datetime(d1)

        self.base_start = pd.to_datetime(base_start_dt)
        self.base_end = pd.to_datetime(base_end_dt)
        if self.base_end <= self.base_start:
            raise ValueError("AAO_BASE_END deve ser posterior a AAO_BASE_START.")

        plot_start_raw = None
        if self.modo == "TESTE":
            plot_start_raw = self.cfg.get("AAO_TESTE_INICIO")
        elif self.modo == "EXTERNO":
            plot_start_raw = self.cfg.get("AAO_EXTERNO_INICIO")
        else:
            plot_start_raw = self.cfg.get("AAO_REFERENCIA_INICIO")
        if plot_start_raw in (None, ""):
            plot_start_raw = self.cfg.get("AAO_INICIO")

        plot_start_dt = None
        if plot_start_raw not in (None, ""):
            plot_start_dt = pd.to_datetime(str(plot_start_raw).strip())

        self.plot_start_date = plot_start_dt or self.base_start

        base_var = self._parse_str(self.cfg.get("AAO_VAR_NAME"), default="hgt")
        base_scale = 1.0
        for key in ("AAO_VAR_ESCALA", "AAO_VAR_SCALE"):
            raw = self.cfg.get(key)
            if raw not in (None, ""):
                base_scale = self._parse_float(raw, default=1.0)
                break
        base_alias = []
        for key in ("AAO_VAR_ALTERNATIVA", "AAO_VAR_ALIASES"):
            ali = self._parse_str_list(self.cfg.get(key))
            if ali:
                base_alias = ali
                break

        if self.modo == "TESTE":
            base_var = self._parse_str(self.cfg.get("AAO_TESTE_VAR"), default=base_var)
            for key in ("AAO_TESTE_VAR_ESCALA", "AAO_TESTE_VAR_SCALE"):
                raw = self.cfg.get(key)
                if raw not in (None, ""):
                    base_scale = self._parse_float(raw, default=base_scale)
                    break
            alias_extra = []
            for key in ("AAO_TESTE_VAR_ALTERNATIVA", "AAO_TESTE_VAR_ALIASES"):
                ali = self._parse_str_list(self.cfg.get(key))
                if ali:
                    alias_extra = ali
                    break
            if alias_extra:
                base_alias = alias_extra
        elif self.modo == "EXTERNO":
            base_var = self._parse_str(self.cfg.get("AAO_EXTERNO_VAR"), default=base_var)
            for key in ("AAO_EXTERNO_VAR_ESCALA", "AAO_EXTERNO_VAR_SCALE"):
                raw = self.cfg.get(key)
                if raw not in (None, ""):
                    base_scale = self._parse_float(raw, default=base_scale)
                    break
            alias_extra = []
            for key in ("AAO_EXTERNO_VAR_ALTERNATIVA", "AAO_EXTERNO_VAR_ALIASES"):
                ali = self._parse_str_list(self.cfg.get(key))
                if ali:
                    alias_extra = ali
                    break
            if alias_extra:
                base_alias = alias_extra

        self.data_var_name = base_var or "hgt"
        self.data_var_scale = base_scale if base_scale not in (None, "") else 1.0
        if self.data_var_scale == 0:
            self.data_var_scale = 1.0
        aliases = base_alias or []
        if self.data_var_name.lower() != "hgt" and "hgt" not in [a.lower() for a in aliases]:
            aliases.append("hgt")
        if "z" not in [a.lower() for a in aliases]:
            aliases.append("z")
        self.data_var_aliases = aliases

        self.g_const = 9.80665

        self.download_enabled = self._parse_bool(
            self.cfg.get("AAO_DOWNLOAD"),
            default=(self.modo != "EXTERNO")
        )
        self.data_dir = self._resolve_dir("AAO_DATA_DIR", Path("data"))
        self.out_dir = mode_dir
        self.tab_dir = self.out_dir
        self.fig_dir = self.out_dir
        self.val_dir = self.out_dir
        for p in {self.data_dir, self.out_dir}:
            p.mkdir(parents=True, exist_ok=True)

        self.url_z700 = self._parse_str(self.cfg.get("AAO_URL_Z700"), default=self.DATA_URL)
        self.nc_path = self._resolve_nc_path()
        self.cpc_url = self._parse_str(self.cfg.get("AAO_CPC_TABLE_URL"), default=self.CPC_URL)
        self.cpc_local = self._resolve_optional_path(self.cfg.get("AAO_CPC_LOCAL"))
        self.cpc_cache_path = Path("data/cache/AAO/cpc_monthly_table.txt")
        self.cpc_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.logo_path = self._resolve_optional_path(self.cfg.get("AAO_LOGO_PATH")) or self.DEFAULT_LOGO
        self.logo_pos_main = self._parse_tuple(self.cfg.get("AAO_LOGO_POS_MAIN"), default=(0.11, 0.16))
        self.logo_pos_diff = self._parse_tuple(self.cfg.get("AAO_LOGO_POS_DIFF"), default=(0.11, 0.25))
        self.logo_zoom = self._parse_float(self.cfg.get("AAO_LOGO_ZOOM"), default=0.03)
        self.logo_anchor = self._parse_tuple(self.cfg.get("AAO_LOGO_ANCHOR"), default=(1, 1))

        self.top_ylim = self._parse_float_tuple(self.cfg.get("AAO_PLOT_YLIM_TOP"), default=(-4.0, 4.0))
        self.diff_ylim = self._parse_float_tuple(self.cfg.get("AAO_PLOT_YLIM_DIFF"), default=(-0.5, 0.5))
        self.threshold = self._parse_float(self.cfg.get("AAO_EVENT_THRESHOLD"), default=2.0)
        self.bar_days = max(1, self._parse_int(self.cfg.get("AAO_DIFF_BAR_DAYS"), default=25, min_val=1))
        self.save_loading = self._parse_bool(self.cfg.get("AAO_SAVE_LOADING"), default=True)

        print(format_log("INFO", message=f"AAO inicializado em modo {self.modo} → outputs em {self.out_dir}"))

    @staticmethod
    def _slug(value: str | None) -> str:
        if value in (None, ""):
            return ""
        txt = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
        txt = txt.replace(" ", "_")
        return re.sub(r"[^0-9a-zA-Z_-]", "", txt)

    # -------------------- parsing helpers --------------------
    @staticmethod
    def _parse_bool(val, default=False):
        if isinstance(val, bool):
            return val
        if val in (None, ""):
            return default
        s = str(val).strip().lower()
        if s in {"sim", "true", "1", "yes", "y"}:
            return True
        if s in {"nao", "não", "false", "0", "no", "n"}:
            return False
        return default

    @staticmethod
    def _parse_int(val, default=0, min_val=None):
        if val in (None, ""):
            return default
        try:
            out = int(float(str(val).replace(",", ".")))
        except Exception:
            return default
        if min_val is not None and out < min_val:
            return max(min_val, default)
        return out

    @staticmethod
    def _parse_float(val, default=0.0):
        if val in (None, ""):
            return float(default)
        try:
            return float(str(val).replace(",", "."))
        except Exception:
            return float(default)

    @staticmethod
    def _parse_date(val, default):
        if val in (None, ""):
            return pd.to_datetime(default)
        return pd.to_datetime(str(val).strip())

    @staticmethod
    def _parse_str(val, default=""):
        s = str(val).strip() if val not in (None, "") else ""
        return s or default

    @staticmethod
    def _parse_str_list(val) -> list[str]:
        if val in (None, ""):
            return []
        if isinstance(val, (list, tuple, set)):
            return [str(x).strip() for x in val if str(x).strip()]
        txt = str(val).replace(";", ",")
        return [p.strip() for p in txt.split(",") if p.strip()]

    def _resolve_dir(self, key, default: Path) -> Path:
        raw = self.cfg.get(key)
        if raw in (None, ""):
            return Path(default)
        return Path(str(raw)).expanduser()

    @staticmethod
    def _parse_tuple(val, default):
        if isinstance(val, (tuple, list)) and len(val) == 2:
            return tuple(float(x) for x in val)
        if val in (None, ""):
            return default
        parts = [p.strip() for p in str(val).replace(";", ",").split(",") if p.strip()]
        if len(parts) != 2:
            return default
        try:
            return tuple(float(p) for p in parts)
        except Exception:
            return default

    @staticmethod
    def _parse_float_tuple(val, default):
        if isinstance(val, (tuple, list)) and len(val) == 2:
            return (float(val[0]), float(val[1]))
        if val in (None, ""):
            return default
        parts = [p.strip() for p in str(val).replace(";", ",").split(",") if p.strip()]
        if len(parts) != 2:
            return default
        try:
            return (float(parts[0].replace(",", ".")), float(parts[1].replace(",", ".")))
        except Exception:
            return default

    def _resolve_nc_path(self) -> Path:
        if self.modo == "EXTERNO":
            raw_ext = self.cfg.get("AAO_EXTERNO_CAMINHO")
            if raw_ext in (None, ""):
                raise ValueError("[ERRO CONFIG] Informe AAO_EXTERNO_CAMINHO no modo EXTERNO.")
            path = Path(str(raw_ext)).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"[ERRO CONFIG] Caminho externo AAO não encontrado: {path}")
            return path
        raw = self.cfg.get("AAO_LOCAL_NC")
        if raw in (None, ""):
            return self.data_dir / "hgt_ncep_reanalise1.nc"
        return Path(str(raw)).expanduser()

    @staticmethod
    def _resolve_optional_path(val) -> Optional[Path]:
        if val in (None, ""):
            return None
        return Path(str(val)).expanduser()

    # -------------------- core helpers --------------------
    @staticmethod
    def _human(n: Optional[int]) -> str:
        if n is None:
            return "?"
        units = ["B", "KB", "MB", "GB", "TB"]
        if n <= 0:
            return "0 B"
        idx = min(int(math.log(n, 1024)), len(units) - 1)
        return f"{n / 1024 ** idx:.1f} {units[idx]}"

    @staticmethod
    def _remote_headers(url: str):
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as resp:
            return resp.headers

    def _ensure_dataset(self) -> Path:
        path = self.nc_path
        if path.exists() and path.stat().st_size > 0:
            if not self.download_enabled:
                return path
        if not self.download_enabled and not path.exists():
            raise FileNotFoundError(f"AAO_DOWNLOAD=NAO mas arquivo não encontrado: {path}")

        needs_download = not path.exists()
        if not needs_download:
            try:
                headers = self._remote_headers(self.url_z700)
                lm = headers.get("Last-Modified")
                cl = headers.get("Content-Length")
                if lm:
                    remote_dt = parsedate_to_datetime(lm).astimezone(timezone.utc)
                    local_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    if remote_dt > local_dt:
                        print(format_log("INFO", message=f"Versão remota mais nova disponível ({remote_dt:%Y-%m-%d} > {local_dt:%Y-%m-%d})."))
                        needs_download = True
                if not needs_download and cl:
                    remote_sz = int(cl)
                    if remote_sz != path.stat().st_size:
                        print(format_log(
                            "INFO",
                            message=(
                                f"Tamanho do arquivo remoto difere "
                                f"(remoto={self._human(remote_sz)} vs local={self._human(path.stat().st_size)})."
                            ),
                        ))
                        needs_download = True
            except Exception as exc:
                print(format_log("ATENCAO", message=f"Não foi possível verificar atualização do dataset ({exc})."))

        if not needs_download:
            return path
        if not self.download_enabled:
            print(format_log("ATENCAO", message="Download desabilitado; utilizando arquivo local existente, se houver."))
            if path.exists():
                return path
            raise FileNotFoundError(f"Arquivo necessário não encontrado: {path}")

        tmp = path.with_suffix(path.suffix + ".part")
        tmp.unlink(missing_ok=True)
        print(format_log("DOWNLOAD", target="AAO_Z700", dest=str(path), reason="Iniciando o download..."))
        with urllib.request.urlopen(self.url_z700) as resp, open(tmp, "wb") as f:
            total = resp.headers.get("Content-Length")
            total = int(total) if total is not None else None
            downloaded = 0
            chunk = 1024 * 1024
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                f.write(block)
                downloaded += len(block)
                if total:
                    pct = 100 * downloaded / total
                    sys.stdout.write(f"\r[DOWNLOAD] {self._human(downloaded)} / {self._human(total)} ({pct:5.1f}%)")
                    sys.stdout.flush()
            if total:
                sys.stdout.write("\n")
        Path(tmp).replace(path)
        print(format_log("DOWNLOAD", target="AAO_Z700", dest=str(path), reason="download concluído!"))
        print(format_log("SALVO", item="Dataset AAO Z700 →", destino=f"{path} ({self._human(path.stat().st_size)})"))
        return path

    @staticmethod
    def _lat_weights_sqrtcos(lat):
        lat_rad = np.deg2rad(np.asarray(lat, dtype=np.float64))
        weights = np.sqrt(np.cos(lat_rad))
        return np.where(weights > 0, weights, 0.0)

    @staticmethod
    def _robust_sel_lat(da, lat_max=-20.0, include_20S=False):
        cond = da["lat"] <= lat_max if include_20S else da["lat"] < lat_max
        return da.where(cond, drop=True)

    @staticmethod
    def _build_base_mask(Aw_base):
        stacked = Aw_base.stack(space=("lat", "lon"))
        valid_space = ~stacked.isnull().any("time")
        return valid_space.unstack("space")

    @staticmethod
    def _compute_loading_eof1(Aw_base):
        mask_map = AAO._build_base_mask(Aw_base)
        Awm = Aw_base.where(mask_map)
        st = Awm.stack(space=("lat", "lon")).dropna(dim="space", how="any").transpose("time", "space")
        T = st.sizes.get("time", 0)
        M = st.sizes.get("space", 0)
        if T == 0 or M == 0:
            raise ValueError(f"Matriz base vazia para SVD (T={T}, M={M}).")
        X = st.values
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        eof1_space = Vt[0, :]
        pc1_base = U[:, 0] * S[0]
        var_exp = float((S[0] ** 2) / np.sum(S ** 2))
        eof1 = xr.DataArray(eof1_space, coords={"space": st.coords["space"]}, dims=("space",)).unstack("space").transpose("lat", "lon")
        norm = np.linalg.norm(eof1_space)
        if norm > 0:
            eof1 = eof1 / norm
            pc1_base = pc1_base * norm
        eof1.name = "AAO_loading"
        return eof1, xr.DataArray(pc1_base, coords={"time": Aw_base.time}, dims=("time",)), S[0], var_exp, mask_map

    @staticmethod
    def _project_pc1(Aw, eof1, mask_map):
        Awm = Aw.where(mask_map)
        eof1m = eof1.where(mask_map)
        X = Awm.stack(space=("lat", "lon")).transpose("time", "space")
        valid = ~X.isnull().any("time")
        X = X.sel(space=valid)
        Y = eof1m.stack(space=("lat", "lon"))
        X_al, Y_al = xr.align(X, Y, join="inner")
        return xr.dot(X_al, Y_al, dim="space")

    @staticmethod
    def _standardize_base(pc, base_start, base_end, ddof=0):
        base = pc.sel(time=slice(base_start, base_end))
        mu = float(base.mean())
        sd = float(base.std(ddof=ddof))
        if not np.isfinite(sd) or sd == 0:
            raise ValueError(f"DP base inválida (sd={sd}).")
        return (pc - mu) / sd, mu, sd

    def _read_cpc_monthly_table(self) -> pd.Series:
        try:
            with urllib.request.urlopen(self.cpc_url) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            try:
                self.cpc_cache_path.write_text(text, encoding="utf-8")
                print(
                    format_log(
                        "CACHE",
                        action="Cache CPC AAO mensal atualizado",
                        path=str(self.cpc_cache_path),
                    )
                )
            except Exception as cache_err:
                print(
                    format_log(
                        "ATENCAO",
                        message=f"Não foi possível atualizar o cache CPC ({cache_err}).",
                    )
                )
        except Exception as exc:
            print(format_log("ATENCAO", message=f"Falha ao baixar CPC ({exc})."))
            if self.cpc_local and self.cpc_local.exists():
                print(format_log("INFO", message=f"Usando arquivo local CPC: {self.cpc_local}"))
                text = Path(self.cpc_local).read_text(encoding="utf-8", errors="ignore")
            elif self.cpc_cache_path.exists():
                print(format_log("INFO", message=f"Usando cache CPC: {self.cpc_cache_path}"))
                text = self.cpc_cache_path.read_text(encoding="utf-8", errors="ignore")
            else:
                return pd.Series(dtype=float)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        data_lines = [ln for ln in lines if re.match(r"^\s*\d{4}\b", ln)]
        rows = []
        for ln in data_lines:
            parts = ln.split()
            year = int(parts[0])
            for month, value in enumerate(parts[1:13], start=1):
                try:
                    val = float(value)
                except Exception:
                    continue
                rows.append({"time": pd.Timestamp(year=year, month=month, day=1), "aao_cpc": val})
        if not rows:
            return pd.Series(dtype=float)
        ser = pd.DataFrame(rows).set_index("time").sort_index()["aao_cpc"]
        ser.index = pd.PeriodIndex(ser.index, freq="M")
        ser = ser.groupby(level=0).mean()
        ser.index = ser.index.to_timestamp(how="start")
        ser = ser.sort_index()
        return ser[~ser.index.duplicated(keep="last")]

    @staticmethod
    def _normalize_monthly_series(series: pd.Series, how="mean") -> pd.Series:
        s = series.dropna().copy()
        if s.empty:
            return s
        s.index = pd.to_datetime(s.index)
        pidx = pd.PeriodIndex(s.index, freq="M")
        s.index = pidx
        s = s.groupby(level=0).last() if how == "last" else s.groupby(level=0).mean()
        s.index = s.index.to_timestamp(how="start")
        s = s.sort_index()
        return s[~s.index.duplicated(keep="last")]

    @staticmethod
    def _align_ours_and_cpc(aao_da, cpc_series: pd.Series) -> pd.DataFrame:
        ours = AAO._normalize_monthly_series(aao_da.to_series().rename("ours"), how="mean")
        cpc = AAO._normalize_monthly_series(cpc_series.rename("cpc"), how="mean")
        df = pd.concat([ours, cpc], axis=1, join="inner").sort_index()
        return df.dropna()

    @staticmethod
    def _maybe_add_logo(ax, logo_path: Path | None, pos=(0.11, 0.16), zoom=0.03, anchor=(1, 1)):
        if not logo_path:
            return
        lp = Path(logo_path)
        if not lp.exists():
            print(format_log("ATENCAO", message=f"Logo não encontrado: {lp}"))
            return
        try:
            img = mpimg.imread(str(lp))
        except Exception as exc:
            print(format_log("ATENCAO", message=f"Falha ao ler logo ({exc})."))
            return
        ab = AnnotationBbox(
            OffsetImage(img, zoom=zoom),
            pos,
            xycoords="axes fraction",
            box_alignment=anchor,
            frameon=False,
            zorder=10,
            clip_on=False,
        )
        ax.add_artist(ab)

    @staticmethod
    def _bar_colors(values):
        return np.where(values >= 0, "#d62728", "#1f77b4")

    @staticmethod
    def _rolling_mean(series: pd.Series, window=3):
        return series.sort_index().rolling(window=window, min_periods=window).mean()

    @staticmethod
    def _make_blocks(start_year: int, end_year: int, span=15):
        blocks = []
        year = start_year
        while year + span - 1 < end_year:
            blocks.append((year, year + span - 1))
            year += span
        blocks.append((year, end_year))
        return blocks

    def _plot_aao_oni_style(self, series: pd.Series, title: str, outpath: Path):
        s = series.dropna().sort_index()
        if s.empty:
            print(format_log("ATENCAO", message=f"Série vazia — pulando {outpath.name}"))
            return
        fig, ax = plt.subplots(figsize=(14, 4))
        ax.fill_between(s.index, 0, s.values, where=s.values >= 0,
                        color="#d62728", linewidth=0.5, alpha=0.9, interpolate=True, zorder=2)
        ax.fill_between(s.index, 0, s.values, where=s.values < 0,
                        color="#1f77b4", linewidth=0.5, alpha=0.9, interpolate=True, zorder=2)
        ax.axhline(0, color="k", lw=1.0, alpha=0.85)
        ax.axhline(+self.threshold, ls="--", lw=1.0, color="#d62728", alpha=0.55)
        ax.axhline(-self.threshold, ls="--", lw=1.0, color="#1f77b4", alpha=0.55)
        ax.set_ylim(*self.top_ylim)
        ax.set_xlim(s.index.min(), s.index.max())
        ax.margins(x=0)
        ax.set_ylabel("Índice AAO")
        ax.set_title(title)

        span = s.index.max() - s.index.min()
        if span <= pd.Timedelta(days=365):
            locator = mdates.MonthLocator(interval=1)
            formatter = mdates.DateFormatter("%Y-%m")
        elif span <= pd.Timedelta(days=int(365 * 3.0)):
            locator = mdates.MonthLocator(interval=3)
            formatter = mdates.DateFormatter("%Y-%m")
        else:
            years = max(1, int(round(span.days / 365.25)))
            if years <= 10:
                locator = mdates.YearLocator(base=1)
            elif years <= 20:
                locator = mdates.YearLocator(base=2)
            else:
                locator = mdates.YearLocator(base=5)
            formatter = mdates.DateFormatter("%Y")
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        fig.autofmt_xdate()
        ax.grid(True, which="major", axis="y", alpha=0.25, linestyle=":")
        self._maybe_add_logo(ax, self.logo_path, self.logo_pos_main, self.logo_zoom, self.logo_anchor)
        fig.tight_layout()
        fig.savefig(outpath, dpi=150)
        plt.close(fig)
        print(format_log("SALVO", item="Figura com a série temporal do AAO  →", destino=str(outpath)))

    def _plot_compare_line_and_diff(self, df_cmp: pd.DataFrame, outpath: Path, metrics_df: pd.DataFrame | None = None):
        if df_cmp.empty:
            print(format_log("ATENCAO", message=f"Dados insuficientes para {outpath.name} — pulando."))
            return
        s_calc = df_cmp["ours"].dropna().sort_index()
        s_cpc = df_cmp["cpc"].dropna().sort_index()
        diff = s_calc - s_cpc
        if metrics_df is not None and not metrics_df.empty:
            row = metrics_df.iloc[0]
            r = float(row.get("corr_r", s_calc.corr(s_cpc)))
            bias = float(row.get("bias", diff.mean()))
            rmse = float(row.get("rmse", np.sqrt((diff ** 2).mean())))
        else:
            r = float(s_calc.corr(s_cpc))
            bias = float(diff.mean())
            rmse = float(np.sqrt((diff ** 2).mean()))
        diff_ylim = self.diff_ylim
        if diff_ylim is None:
            a = np.nanpercentile(np.abs(diff.values), 99.5)
            a = max(a, 0.05)
            diff_ylim = (-a * 1.1, a * 1.1)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 6.8), sharex=True, gridspec_kw={"height_ratios": [3.0, 1.4]})
        ax1.plot(s_calc.index, s_calc.values, lw=0.8, label="ClimAtmos", color="#1f77b4")
        ax1.plot(s_cpc.index, s_cpc.values, lw=0.8, label="Oficial CPC", alpha=0.9, color="#d62728")
        ax1.axhline(0, color="k", lw=1.0, alpha=0.6)
        ax1.set_ylabel("Índice AAO")
        ax1.set_ylim(*self.top_ylim)
        ax1.set_title("Série temporal Comparativa entre o Índice AAO Calculado (azul) vs Oficial CPC (vermelho)")
        ax1.legend(loc="upper left")
        ax1.grid(True, axis="y", alpha=0.25, linestyle=":")
        ax1.text(0.99, 0.02, f"r={r:.3f}  |  bias={bias:.2f}  |  RMSE={rmse:.2f}",
                 transform=ax1.transAxes, ha="right", va="bottom", fontsize=10, color="#333")
        self._maybe_add_logo(ax1, self.logo_path, self.logo_pos_main, self.logo_zoom, self.logo_anchor)
        width = pd.Timedelta(days=self.bar_days)
        ax2.bar(diff.index, diff.values, width=width, color=self._bar_colors(diff.values), edgecolor="none", alpha=0.9)
        ax2.axhline(0, color="k", lw=1.0, alpha=0.85)
        ax2.set_ylabel("Viés")
        ax2.set_title("Diferença entre o Calculado vs CPC (ClimAtmos - CPC)")
        ax2.grid(True, axis="y", alpha=0.25)
        ax2.set_ylim(*diff_ylim)
        span = s_calc.index.max() - s_calc.index.min()
        if span <= pd.Timedelta(days=365):
            locator = mdates.MonthLocator(interval=1)
            formatter = mdates.DateFormatter("%Y-%m")
        elif span <= pd.Timedelta(days=int(365 * 3.0)):
            locator = mdates.MonthLocator(interval=3)
            formatter = mdates.DateFormatter("%Y-%m")
        else:
            years = max(1, int(round(span.days / 365.25)))
            if years <= 10:
                locator = mdates.YearLocator(base=1)
            elif years <= 20:
                locator = mdates.YearLocator(base=2)
            else:
                locator = mdates.YearLocator(base=5)
            formatter = mdates.DateFormatter("%Y")
        ax2.xaxis.set_major_locator(locator)
        ax2.xaxis.set_major_formatter(formatter)
        ax2.margins(x=0)
        if diff_ylim[1] - diff_ylim[0] <= 1.0:
            ax2.yaxis.set_major_locator(MultipleLocator(0.1))
        self._maybe_add_logo(ax2, self.logo_path, self.logo_pos_diff, self.logo_zoom, self.logo_anchor)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(outpath, dpi=150)
        plt.close(fig)
        print(format_log("SALVO", item="Figura AAO comparação vs CPC →", destino=str(outpath)))

    def _trim_by_plot_start(self, obj: pd.Series | pd.DataFrame):
        if self.plot_start_date is None or obj is None:
            return obj
        if isinstance(obj.index, (pd.DatetimeIndex, pd.PeriodIndex)):
            return obj[obj.index >= self.plot_start_date]
        return obj

    def _plot_eof1_loading(self, nc_path: Path, variance: float):
        if not nc_path.exists():
            print(format_log("ATENCAO", message=f"Arquivo EOF não encontrado: {nc_path}"))
            return
        try:
            ds = xr.open_dataset(nc_path)
        except Exception as exc:
            print(format_log("ERRO", message=f"Falha ao abrir EOF {nc_path}: {exc}"))
            return
        try:
            data_vars = list(ds.data_vars)
            if not data_vars:
                print(format_log("ATENCAO", message=f"Dataset EOF vazio em {nc_path}"))
                return
            da = ds[data_vars[0]].squeeze()
            if {"lat", "lon"} - set(da.coords):
                print(format_log("ATENCAO", message=f"EOF sem coordenadas lat/lon em {nc_path}"))
                return
            da_plot = da.assign_coords(lon=((da["lon"] + 180) % 360) - 180)
            da_plot = da_plot.sortby("lon")
            arr = da_plot.to_numpy()
            if arr.ndim != 2:
                print(format_log("ATENCAO", message=f"EOF com dimensões inesperadas ({arr.shape}) em {nc_path}"))
                return
            lat = np.asarray(da_plot["lat"].values)
            lon = np.asarray(da_plot["lon"].values)
            scale_factor = 10.0
            base_levels = np.linspace(-0.05, 0.05, 17)
            levels = base_levels * scale_factor
            arr_plot = arr * scale_factor

            lon2, lat2 = np.meshgrid(lon, lat)
            proj = ccrs.PlateCarree()
            fig = plt.figure(figsize=(10, 5))
            ax = plt.axes(projection=proj)
            ax.set_extent([float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())], crs=proj)
            ax.coastlines(linewidth=0.6)
            ax.add_feature(cfeature.LAND, facecolor="0.92", edgecolor="none", zorder=0)
            gl = ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5, linestyle="--", x_inline=False, y_inline=False)
            gl.right_labels = False
            gl.top_labels = False
            gl.ylabel_style = {"size": 8}
            gl.xlabel_style = {"size": 8}

            cf = ax.contourf(lon2, lat2, arr_plot, levels=levels, cmap="RdBu_r", extend="both", transform=proj)
            ax.contour(lon2, lat2, arr_plot, levels=np.linspace(-0.05, 0.05, 9) * scale_factor, colors="k", linewidths=0.3, transform=proj)

            fonte = self.cfg.get("AAO_EXTERNO_NOME") if self.modo == "EXTERNO" else None
            if not fonte:
                fonte = self.case_name if self.case_name else None
            fonte_txt = f" | Fonte: {fonte}" if fonte else ""
            title = f"EOF principal — Variância explicada {variance * 100:.1f}%{fonte_txt}"
            ax.set_title(title)
            cbar = fig.colorbar(cf, ax=ax, orientation="vertical", pad=0.04, shrink=0.7)
            cbar.set_label("Carga EOF adimensional (x10)")

            fig_path = self.fig_dir / f"AAO_EOF_z{self.level_hpa}_{self.SUF_EXEC}.png"
            fig.savefig(fig_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(format_log("SALVO", item="Figura do mapa do EOF principal do índice AAO →", destino=str(fig_path)))
        finally:
            ds.close()

    def run(self):
        if self.modo == "REFERENCIA":
            print(format_log(
                "INFO",
                message=f"Modo REFERENCIA utilizando base climatológica {self.base_start:%Y-%m} → {self.base_end:%Y-%m}",
            ))
        if self.modo == "EXTERNO":
            print(format_log("INFO", message="Usando os dados externos fornecidos"))
        else:
            print(format_log("INFO", message="Verificando/baixando as Reanálises 1 do NCEP/NCAR"))
        nc = self._ensure_dataset()
        print(format_log("INFO", message="Iniciando o cálculo do AAO"))
        ds = xr.open_dataset(nc)
        try:
            required_dims = {
                "time": ["time", "valid_time", "date_time"],
                "lat": ["lat", "latitude"],
                "lon": ["lon", "longitude"],
                "level": ["level", "pressure_level", "isobaricInhPa"],
            }
            coord_map = {}
            for key, options in required_dims.items():
                found = None
                for opt in options:
                    if opt in ds.dims or opt in ds.coords:
                        found = opt
                        break
                if found is None:
                    raise RuntimeError(f"Dimensão/coordenada equivalente a '{key}' não encontrada em {nc} (esperado um de {options}).")
                coord_map[key] = found

            rename_core = {}
            if coord_map["time"] != "time":
                rename_core[coord_map["time"]] = "time"
            if coord_map["level"] not in ("level", "pressure_level"):
                rename_core[coord_map["level"]] = "level"
            if coord_map["lat"] != "lat":
                rename_core[coord_map["lat"]] = "lat"
            if coord_map["lon"] != "lon":
                rename_core[coord_map["lon"]] = "lon"
            if rename_core:
                ds = ds.rename(rename_core)

            print(format_log("INFO", message=f"Selecionando o nível vertical de {self.level_hpa} hPa"))
            candidates = [self.data_var_name] + [alias for alias in self.data_var_aliases if alias]
            seen = set()
            var_found = None
            for cand in candidates:
                if not cand:
                    continue
                key = cand.lower()
                if key in seen:
                    continue
                seen.add(key)
                if cand in ds:
                    var_found = cand
                    break
            if var_found is None:
                raise RuntimeError(
                    f"Variável '{self.data_var_name}' não encontrada no dataset. Disponíveis: {list(ds.data_vars)}"
                )
            if var_found != self.data_var_name:
                print(format_log("INFO", message=f"Variável '{self.data_var_name}' indisponível; usando '{var_found}' presente no dataset."))

            field = ds[var_found]
            scale = float(self.data_var_scale or 1.0)
            inferred_scale = None
            units_attr = str(field.attrs.get("units", "")).lower()
            long_name = str(field.attrs.get("long_name", "")).lower()
            if abs(scale - 1.0) < 1e-9:
                if var_found.lower() == "z" or "geopotential" in long_name:
                    if any(token in units_attr for token in ["m**2", "m^2", "j kg", "m2"]):
                        inferred_scale = 1.0 / self.g_const
                        scale = inferred_scale
            if abs(scale - 1.0) >= 1e-9:
                factor_msg = f"{scale:.6g}"
                if inferred_scale is not None:
                    print(format_log("INFO", message=f"Convertendo '{var_found}' de geopotencial para altura (÷g). Fator aplicado: {factor_msg}."))
                else:
                    print(format_log("INFO", message=f"Aplicando fator de escala {factor_msg} à variável '{var_found}'."))
                field = field * scale
                field.attrs = dict(field.attrs)
                field.attrs["units"] = "m"

            if "level" not in field.dims:
                rename_map = {}
                if "pressure_level" in field.dims:
                    rename_map["pressure_level"] = "level"
                elif coord_map.get("level") in field.dims:
                    rename_map[coord_map["level"]] = "level"
                if "latitude" in field.dims:
                    rename_map["latitude"] = "lat"
                if "longitude" in field.dims:
                    rename_map["longitude"] = "lon"
                if rename_map:
                    field = field.rename(rename_map)
            if "level" not in field.dims:
                raise RuntimeError(f"Campo '{var_found}' não possui dimensão 'level'. Dimensões: {field.dims}")
            if self.level_hpa not in field["level"].values:
                raise RuntimeError(f"Nível {self.level_hpa} hPa não disponível. Níveis: {field['level'].values}")
            z = field.sel(level=self.level_hpa)

            print(format_log("INFO", message="Recortando faixa ao sul de 20°S"))
            z = self._robust_sel_lat(z, lat_max=self.lat_max, include_20S=self.include_20s)
            if z.sizes.get("lat", 0) == 0:
                raise RuntimeError("Recorte resultou em zero latitudes.")
            print(format_log(
                "INFO",
                message=f"Latitude min/max selecionado após o recorte: {float(z.lat.min()):.1f}° / {float(z.lat.max()):.1f}°",
            ))

            print(format_log("INFO", message="Calculando climatologia mensal e anomalias"))
            # print(format_log(
            #     "INFO",
            #     message=f"Período calculado: {self.base_start:%Y-%m} → {self.base_end:%Y-%m}",
            # ))
            z_base = z.sel(time=slice(self.base_start, self.base_end))
            if z_base.sizes.get("time", 0) == 0:
                raise RuntimeError("Período base não encontrado no dataset.")
            clim = z_base.groupby("time.month").mean("time")
            anom = z.groupby("time.month") - clim

            print(format_log("INFO", message="Calculando pesos por área a partir da √(cos(lat))"))
            wlat = xr.DataArray(self._lat_weights_sqrtcos(z.lat), coords={"lat": z.lat}, dims=("lat",))
            Aw = anom * wlat

            print(format_log("INFO", message="Calculando EOF principal no período base"))
            Aw_base = Aw.sel(time=slice(self.base_start, self.base_end))
            eof1, pc1_base, s1, var_exp, mask_map = self._compute_loading_eof1(Aw_base)
            nspace = int(self._build_base_mask(Aw_base).sum())
            print(format_log("INFO", message=f"Variância explicada de {var_exp * 100:.1f}% no EOF principal| pontos espaciais: {nspace}"))

            print(format_log("INFO", message="Projetando no mapa e padronizando"))
            pc1_all = self._project_pc1(Aw, eof1, mask_map)
            aao_raw, mu_base, sd_base = self._standardize_base(pc1_all, self.base_start, self.base_end, self.std_ddof)
            aao = aao_raw

            cpc_series = self._read_cpc_monthly_table()
            aao_series = aao.to_series().dropna().sort_index()
            aao_series_out = self._trim_by_plot_start(aao_series).dropna().sort_index()
            if aao_series_out.empty:
                aao_series_out = aao_series
            if not cpc_series.empty:
                ix = aao_series.index.intersection(cpc_series.index)
                if len(ix) >= 2:
                    corr = aao_series.loc[ix].corr(cpc_series.loc[ix])
                    if corr < 0:
                        aao = -aao
                        aao_series = (-aao).to_series().dropna().sort_index()
                        aao_series_out = self._trim_by_plot_start(aao_series).dropna().sort_index()
                        if aao_series_out.empty:
                            aao_series_out = aao_series
            df_cmp = pd.DataFrame()
            metrics_df = pd.DataFrame()
            cpc_series_out = cpc_series
            if not cpc_series.empty:
                trimmed_cpc = self._trim_by_plot_start(cpc_series).dropna().sort_index()
                if not trimmed_cpc.empty:
                    cpc_series_out = trimmed_cpc
            if not cpc_series.empty:
                df_cmp = self._align_ours_and_cpc(aao, cpc_series)
                if not df_cmp.empty and self.plot_start_date is not None:
                    df_cmp = df_cmp[df_cmp.index >= self.plot_start_date]
                df_cmp = df_cmp.sort_index()
                if not df_cmp.empty:
                    n_meses = int(len(df_cmp))
                    if n_meses < 2:
                        print(format_log("ATENCAO", message="Dados insuficientes para gerar métricas estatísticas (menos de 2 registros)."))
                    else:
                        diff = df_cmp["ours"] - df_cmp["cpc"]
                        r = float(df_cmp["ours"].corr(df_cmp["cpc"]))
                        rmse = float(np.sqrt((diff ** 2).mean()))
                        mae = float(diff.abs().mean())
                        bias = float(diff.mean())
                        slope, intercept = np.polyfit(df_cmp["cpc"].values, df_cmp["ours"].values, 1)
                        r2 = float(r ** 2)
                        std_err = float(diff.std(ddof=1))
                        periodo_inicio = df_cmp.index.min().strftime("%Y-%m-%d")
                        periodo_fim = df_cmp.index.max().strftime("%Y-%m-%d")
                        fonte = f"NCEP/NCAR R1 Z{self.level_hpa} vs CPC (base {self.base_start:%Y-%m}–{self.base_end:%Y-%m})"
                        row = {
                            "fonte": fonte,
                            "data_inicio": periodo_inicio,
                            "data_fim": periodo_fim,
                            "n_registros": n_meses,
                            "rmse": rmse,
                            "mae": mae,
                            "bias": bias,
                            "corr": r,
                            "r2": r2,
                            "slope": float(slope),
                            "intercept": float(intercept),
                            "desv_pad_erro": std_err,
                        }
                        cols_order = [
                            "fonte", "data_inicio", "data_fim", "n_registros",
                            "rmse", "mae", "bias", "corr", "r2", "slope", "intercept", "desv_pad_erro",
                        ]
                        metrics_df = pd.DataFrame([row])
                        metrics_df = metrics_df[[c for c in cols_order if c in metrics_df.columns] + [c for c in metrics_df.columns if c not in cols_order]]
                        metrics_name = f"AAO_metricas_estatisticas_{self.SUF_EXEC}.csv"
                        val_path = self.val_dir / metrics_name
                        metrics_df.to_csv(val_path, index=False, float_format="%.6f")
                        print("[ESTATÍSTICAS] === Validação Calculado x CPC para o AAO mensal ===")
                        # resumo = (
                        print(f"Correlação={r:.3f} | R²={r2:.3f} | Viés={bias:.3f} | MAE={mae:.3f} | RMSE={rmse:.3f}")
                        print(f"slope={slope:.3f} | intercept={intercept:.3f} | desv_erro={std_err:.3f}  | N={n_meses}")

                        # print(format_log("INFO", message=resumo))
                        print(format_log("SALVO", item="Arquivo CSV com as métricas estatísticas entre o AAO Calculado vs CPC →", destino=str(val_path)))
                else:
                    print(format_log("ATENCAO", message="Séries CPC e AAO não possuem interseção suficiente para métricas."))
            else:
                print(format_log("ATENCAO", message="Série CPC indisponível — métricas não serão calculadas."))

            df_out = pd.DataFrame({"AAO_CALC": aao_series_out}).sort_index()
            df_out.index.name = "data"
            calc_path = self.tab_dir / f"AAO_serie-temporal_CALC_{self.SUF_EXEC}.csv"
            df_out.to_csv(calc_path, float_format="%.6f")
            print(format_log("SALVO", item="Série AAO calculada →", destino=str(calc_path)))

            if not df_cmp.empty:
                df_cmp2 = df_cmp.copy()
                df_cmp2["diff"] = df_cmp2["ours"] - df_cmp2["cpc"]
                df_cmp2 = df_cmp2.rename(columns={"ours": "AAO_CALC", "cpc": "AAO_CPC", "diff": "diferenca"})
                df_cmp2.index.name = "data"
                cmp_path = self.tab_dir / f"AAO_serie-temporal_CALCvsCPC_{self.SUF_EXEC}.csv"
                df_cmp2.to_csv(cmp_path, float_format="%.6f")
                print(format_log("SALVO", item="Comparação AAO calculado vs CPC →", destino=str(cmp_path)))

            if self.save_loading:
                load_name = f"AAO_EOF_z{self.level_hpa}_{self.SUF_EXEC}.nc"
                load_path = self.out_dir / load_name
                eof1.to_netcdf(load_path)
                print(format_log("SALVO", item="Arquivo Netcdf com EOF principal do AAO salvo →", destino=str(load_path)))
                self._plot_eof1_loading(load_path, var_exp)

            calc_series_plot = aao.to_series()
            trimmed_calc_plot = self._trim_by_plot_start(calc_series_plot).dropna().sort_index()
            if not trimmed_calc_plot.empty:
                calc_series_plot = trimmed_calc_plot
            calc_fig = self.fig_dir / f"AAO_serie-temporal_CALC_{self.SUF_EXEC}.png"
            self._plot_aao_oni_style(calc_series_plot, "Série Temporal do Índice de Oscilação Antártica | Calculado Reanálise NCEP", calc_fig)
            # if not cpc_series_out.empty:
            #     cpc_fig = self.fig_dir / f"AAO_serie-temporal_CPC_{self.SUF_EXEC}.png"
            #     self._plot_aao_oni_style(cpc_series_out, "Série Temporal do Índice de Oscilação Antártica | Referência CPC", cpc_fig)
            # if not df_cmp.empty:
            #     diff_fig = self.fig_dir / f"AAO_CALCvsCPC_{self.SUF_EXEC}.png"
            #     self._plot_compare_line_and_diff(df_cmp, diff_fig, metrics_df=metrics_df)

        finally:
            ds.close()
