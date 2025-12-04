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
from .atm_tools import validate_config_AMO, TRUE_VALUES, FALSE_VALUES
from src.logging import format_log
from urllib.parse import urlparse
import shutil

def _cfg_message(message: str) -> str:
    return format_log("ERRO_CONF", message=message)

class AMO:
    """
    Cálculo do índice AMO com três caminhos de entrada:
      1) ERSSTv5 (TOTAL → SSTA por base climatológica)
      2) Kaplan (anomalias já fornecidas)
      3) CSV externo com TSM TOTAL (→ SSTA pela base especificada)
    Controlado via config.txt (ver exemplo).
    """

    METRICS_COLUMNS = [
        "experimento",
        "fonte",
        "base",
        "data_inicio",
        "data_fim",
        "n_registros",
        "rmse",
        "mae",
        "bias",
        "corr",
        "r2",
        "slope",
        "intercept",
        "desv_pad_erro",
    ]

    # URLs oficiais
    URL_ERSSV5_NC = "https://downloads.psl.noaa.gov/Datasets/noaa.ersst.v5/sst.mnmean.nc"
    URL_KAPLAN_NC = "https://downloads.psl.noaa.gov/Datasets/kaplan_sst/sst.mean.anom.nc"
    URL_NCEI_AMO  = "https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.amo.dat"
    URL_PSL_KAP_UNS = "https://psl.noaa.gov/data/correlation/amon.us.long.data"
    URL_PSL_KAP_SMO = "https://psl.noaa.gov/data/correlation/amon.sm.long.data"

    FILL_MISSING = -99.999

    def __init__(self, cfg: dict):
        validate_config_AMO(cfg)
        self.cfg = cfg

        # ==================== DIRETÓRIOS ====================
        self.DATA_DIR = Path(cfg.get("DATA_DIR", "data"))
        self.OUT_DIR  = Path(cfg.get("OUT_DIR", OUTPUT_ROOT / "AMO"))
        self.SUF_EXEC = datetime.now().strftime("%Y%m")

        # ==================== LOGO ====================
        logo_cfg = str(self.cfg.get("AMO_LOGO_PATH", "") or "").strip()
        self.logo_path: Path | None = None
        if logo_cfg:
            candidate = Path(logo_cfg).expanduser()
            if candidate.exists():
                self.logo_path = candidate
        if self.logo_path is None:
            for fallback in ("utils/atmosmarine.png", "src/atmosmarine.png"):
                candidate = Path(fallback)
                if candidate.exists():
                    self.logo_path = candidate
                    break


        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR = self.DATA_DIR / "cache" / "AMO"
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        legacy_ncei = self.DATA_DIR / "ersst.v5.amo.dat"
        cache_ncei = self._cache_file("ersst.v5.amo.dat")
        if legacy_ncei.exists():
            if not cache_ncei.exists():
                try:
                    cache_ncei.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(legacy_ncei, cache_ncei)
                except Exception:
                    try:
                        shutil.copy2(legacy_ncei, cache_ncei)
                    except Exception:
                        pass
            else:
                try:
                    legacy_ncei.unlink()
                except Exception:
                    pass

        # ==================== ARQUIVOS LOCAIS ====================
        self.nc_ersst  = self.DATA_DIR / "ersst_v5.nc"
        self.nc_kaplan = self.DATA_DIR / "kaplan_sst.mean.anom.nc"

        # ==================== CONTROLE DE MODO ====================
        self.modo = str(cfg.get("AMO_MODO", "REFERENCIA")).strip().upper()
        self.TESTE_VALIDACAO_COMPLETA = self._as_bool_ext(
            cfg.get("AMO_TESTE_VALIDACAO_COMPLETA", "NAO"),
            label="AMO_TESTE_VALIDACAO_COMPLETA"
        )
        self.NOME_TESTE = ""
        if self.modo == "TESTE":
            if self.TESTE_VALIDACAO_COMPLETA:
                self.NOME_TESTE = "VALIDACAO"
            else:
                nome_teste_cfg = str(cfg.get("AMO_TESTE_NOME", "PERSONALIZADO")).strip()
                self.NOME_TESTE = nome_teste_cfg or "PERSONALIZADO"
            self.cfg["AMO_TESTE_NOME"] = self.NOME_TESTE

        # -------------------- Flags de transformação --------------------
        self.remove_trend  = self._as_bool_ext(self.cfg.get("AMO_TESTE_REMOCAO_TENDENCIA", "NAO"), label="AMO_TESTE_REMOCAO_TENDENCIA")
        self.remove_global = self._as_bool_ext(self.cfg.get("AMO_TESTE_REMOCAO_GLOBAL", "NAO"), label="AMO_TESTE_REMOCAO_GLOBAL")

        # ==================== BASE CLIMATOLÓGICA ====================
        if self.modo == "TESTE" and not self.TESTE_VALIDACAO_COMPLETA:
            base_str = str(cfg.get("AMO_TESTE_BASE_CLIMA", "1971-01:2000-12")).strip()
            try:
                b0, b1 = base_str.split(":")
                self.base_ext = (int(b0.split("-")[0]), int(b1.split("-")[0]))
            except Exception:
                self.base_ext = (1971, 2000)
            self.baselines = [self.base_ext]
        elif self.modo == "EXTERNO":
            base_years = self._parse_base_years(cfg.get("AMO_EXTERNO_BASE_CLIMA", "1971-01:2000-12"))
            self.baselines = [base_years]
        else:
            self.baselines = [(1971, 2000)]
        for base in self.baselines:
            base_str = self._format_baseline(base)
            if base_str:
                message = f"Base climatológica AMO - Modo {self.modo} → {base_str}"
                print(format_log("INFO", message=message))

        # ==================== SUBPASTAS ====================
        raiz_base = self.OUT_DIR / self.modo
        if self.modo == "TESTE":
            if self.TESTE_VALIDACAO_COMPLETA:
                raiz_base = self.OUT_DIR / "TESTE_VALIDACAO"
            else:
                nome_teste = self.NOME_TESTE or "PERSONALIZADO"
                raiz_base = self.OUT_DIR / f"TESTE_{self._slug(nome_teste)}"

        self.OUT_DIR = raiz_base
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR_tables = self.OUT_DIR
        self.OUT_DIR_figs   = self.OUT_DIR
        self.OUT_DIR_valida = self.OUT_DIR
        # Alias usado em alguns fluxos legados (EXTERNO)
        self.OUT_DIR_valid  = self.OUT_DIR

        # Garante atributos sempre definidos (mesmo se não usados)
        self.ds_ersst = None
        self.ds_kap   = None

        # ==================== CHECAGEM DOS DADOS ====================
        self._check_input_files()

        # ==================== CONTROLE DE FONTE ====================
        self.usa_externo = (self.modo == "EXTERNO")

        fonte_cfg = str(cfg.get("AMO_TESTE_TSM", "ERSSTv5")).strip().upper()
        self.want_ersst = (fonte_cfg == "ERSSTV5") or (self.modo in {"REFERENCIA"} and not self.usa_externo)
        self.want_kaplan = (fonte_cfg == "KAPLAN") or (self.modo in {"REFERENCIA"} and not self.usa_externo)
        if self.modo == "TESTE" and self.TESTE_VALIDACAO_COMPLETA:
            # Validação completa replica o pipeline de referência, exige ERSSTv5 e Kaplan
            self.want_ersst = True
            self.want_kaplan = True


    # ======================================================
    # Funções auxiliares (copiadas/adaptadas de BaseIndice)
    # ======================================================
    def _as_bool_ext(self, val, *, label: str = "opção") -> bool:
        if isinstance(val, bool):
            return val
        raw = str(val or "").strip()
        normalized = raw.lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
        message = (
            f"{label}: valor '{raw}' inválido. "
            f"Use verdadeiros {sorted(TRUE_VALUES)} ou falsos {sorted(FALSE_VALUES)}."
        )
        raise ValueError(format_log("ERRO_CONF", message=message))

    def _slug(self, txt: str) -> str:
        return str(txt).lower().replace(" ", "_")

    def _cache_file(self, filename: str) -> Path:
        return self.CACHE_DIR / filename

    def _format_baseline(self, base) -> str | None:
        if base is None:
            return None
        if isinstance(base, (list, tuple)) and len(base) == 2:
            a, b = base

            def _conv(val):
                if val is None:
                    return None
                if isinstance(val, pd.Timestamp):
                    return val.year
                if isinstance(val, (datetime, np.datetime64)):
                    return pd.to_datetime(val).year
                try:
                    val_str = str(val).strip()
                    if len(val_str) >= 4 and val_str[:4].isdigit():
                        return int(val_str[:4])
                    return int(float(val_str))
                except Exception:
                    return val

            a_conv = _conv(a)
            b_conv = _conv(b)
            if isinstance(a_conv, int) and isinstance(b_conv, int):
                return f"{a_conv:04d}-{b_conv:04d}"
            return f"{a_conv}-{b_conv}"
        return str(base)

    def _parse_base_years(self, base_str: str | None, default: tuple[int, int] = (1971, 2000)) -> tuple[int, int]:
        """
        Extrai apenas os anos (YYYY) de um período informado no formato
        'YYYY-01:YYYY-12', 'YYYY:YYYY' ou 'YYYY-YYYY'. Retorna `default` em caso de erro.
        """
        base_txt = str(base_str or "").strip()
        if not base_txt:
            return default
        try:
            if ":" in base_txt:
                start, end = base_txt.split(":", 1)
            else:
                parts = base_txt.split("-")
                if len(parts) >= 2:
                    start = f"{parts[0]}-01"
                    end = f"{parts[1]}-12"
                else:
                    raise ValueError
            y0 = int(str(start).strip()[:4])
            y1 = int(str(end).strip()[:4])
            if y0 > y1:
                raise ValueError
            return (y0, y1)
        except Exception:
            return default

    def _check_input_files(self):
        """Verifica se os arquivos locais existem; se não, alerta o usuário"""
        if self.modo in {"REFERENCIA"} or self.TESTE_VALIDACAO_COMPLETA:
            if not self.nc_ersst.exists():
                print(format_log("ATENCAO", message=f"Arquivo ERSSTv5 não encontrado localmente → baixando {self.nc_ersst}"))
            if not self.nc_kaplan.exists():
                print(format_log("ATENCAO", message=f"Arquivo KAPLAN não encontrado localmente → baixando {self.nc_kaplan}"))
        elif self.modo == "TESTE":
            fonte = str(self.cfg.get("AMO_TESTE_TSM", "ERSSTv5")).strip().upper()
            if fonte == "ERSSTV5" and not self.nc_ersst.exists():
                print(format_log("ATENCAO", message=f"Arquivo ERSSTv5 não encontrado localmente → baixando {self.nc_ersst}"))
            if fonte == "KAPLAN" and not self.nc_kaplan.exists():
                print(format_log("ATENCAO", message=f"Arquivo KAPLAN não encontrado localmente → baixando {self.nc_kaplan}"))

    def _strip_comment(self, v):
        if isinstance(v, (int, float, bool)) or v is None:
            return v
        s = str(v)
        for sep in ("#", ";"):
            if sep in s:
                s = s.split(sep, 1)[0]
        return s.strip()

    def _as_float(self, v, default=0.0) -> float:
        if isinstance(v, (int, float)): 
            return float(v)
        s = self._strip_comment(v)
        if s == "" or s is None:
            return float(default)
        try:
            return float(s.replace(",", "."))
        except Exception:
            return float(default)

    def _as_date(self, v, default=None):
        s = self._strip_comment(v)
        if not s:
            return pd.to_datetime(default) if default else pd.NaT
        return pd.to_datetime(s)

    def _parse_base(self, base: str) -> Tuple[int,int]:
        try:
            a, b = str(base).split("-")
            return int(a), int(b)
        except Exception:
            return (1971, 2000)

    def _normalize_lon(self, lon: xr.DataArray) -> xr.DataArray:
        arr = lon.values
        if np.nanmin(arr) >= 0.0:
            arr = ((arr + 180.0) % 360.0) - 180.0
        return xr.DataArray(arr, dims=lon.dims, coords=lon.coords, name=lon.name)

    def _subset_region(self, ds: xr.Dataset) -> tuple[xr.Dataset, str, str]:
        lon_name = "lon" if "lon" in ds.coords else ("longitude" if "longitude" in ds.coords else list(ds.coords)[0])
        lat_name = "lat" if "lat" in ds.coords else ("latitude" if "latitude" in ds.coords else list(ds.coords)[1])
        ds = ds.assign_coords({lon_name: self._normalize_lon(ds[lon_name])})
        ds = ds.sortby(lon_name).sortby(lat_name)
        ds_sub = ds.sel({lon_name: slice(self.lon_min, self.lon_max),
                         lat_name: slice(self.lat_min, self.lat_max)})
        return ds_sub, lon_name, lat_name
    
    def _subset_region_custom(self, ds: xr.Dataset, lon_min, lon_max, lat_min, lat_max):
        lon_name = "lon" if "lon" in ds.coords else ("longitude" if "longitude" in ds.coords else list(ds.coords)[0])
        lat_name = "lat" if "lat" in ds.coords else ("latitude" if "latitude" in ds.coords else list(ds.coords)[1])
        ds = ds.assign_coords({lon_name: self._normalize_lon(ds[lon_name])}).sortby(lon_name).sortby(lat_name)
        ds_sub = ds.sel({lon_name: slice(lon_min, lon_max), lat_name: slice(lat_min, lat_max)})
        return ds_sub, lon_name, lat_name
    
    def _to_csv_table(self, s: pd.Series):
        """
        Converte uma série mensal em tabela ano×12 com cabeçalho em inglês.
        """
        if s is None or s.empty:
            return ""

        df = s.to_frame(name="value").copy()
        df["Year"] = df.index.year
        df["Month"] = df.index.month

        # monta tabela pivotada ano × 12
        df_wide = df.pivot(index="Year", columns="Month", values="value")
        df_wide = df_wide.reindex(columns=range(1, 13))
        df_wide.columns = ["JAN","FEB","MAR","APR","MAY","JUN",
                        "JUL","AUG","SEP","OCT","NOV","DEC"]
        return df_wide

    def _area_weighted_mean(self, da: xr.DataArray, lon_name: str, lat_name: str) -> xr.DataArray:
        w = np.cos(np.deg2rad(da[lat_name]))
        W2D = w.broadcast_like(da)
        num = (da * W2D).where(np.isfinite(da)).sum(dim=(lon_name, lat_name))
        den = W2D.where(np.isfinite(da)).sum(dim=(lon_name, lat_name))
        return (num / den).rename("areal")

    def _detrend_pd(self, s: pd.Series) -> pd.Series:
        y = s.to_numpy(dtype=float)
        t = np.arange(len(y), dtype=float)
        m = np.isfinite(y)
        if m.sum() < 2: return s.copy()
        a, b = np.polyfit(t[m], y[m], 1)
        return pd.Series(y - (a*t + b), index=s.index, name="detrended")

    def _to_psl_text(self, series: pd.Series, title: str, year_end: int | None = None) -> str:
        s = series.dropna().copy()
        if year_end is not None and not s.empty:
            s = s[s.index.year <= year_end]
        if s.empty:
            raise ValueError(_cfg_message(f"Série vazia ao gerar PSL para: {title}. Verifique janelas e datas de suavização."))

        df = s.to_frame("val")
        df["YEAR"] = df.index.year
        df["MONTH"] = df.index.month
        y0, y1 = int(df["YEAR"].min()), int(df["YEAR"].max())
        tab = df.pivot_table(index="YEAR", columns="MONTH", values="val", aggfunc="mean")
        tab = tab.reindex(index=range(y0, y1+1), columns=range(1,13)).sort_index().fillna(self.FILL_MISSING)

        lines = []
        lines.append(title)
        lines.append("YEAR    JAN     FEB     MAR     APR     MAY     JUN     JUL     AUG     SEP     OCT     NOV     DEC")
        for yr, row in tab.iterrows():
            vals = " ".join(f"{v:7.3f}" for v in row.values)
            lines.append(f"{yr:4d} {vals}")
        return "\n".join(lines)

    def _fonte_tag(self) -> str:
        if self.usa_externo:
            return f"EXTERNO_{self._slug(self.fonte_nome)}"
        up = self.fonte_nome.strip().upper()
        if up in ("ERSSTV5","ERSSTV5 ","ERSST"): return "ERSSTv5"
        if up in ("KAPLAN","KAPLAN_SSTA","KAP"): return "KAPLAN"
        if up in ("PADRÃO","PADRAO","PADRAO "): return "ERSSTv5"
        return self._slug(self.fonte_nome)
    
    # ====== Export helpers (NCEI-like table) ======
    def _series_to_year12_df(self, s: pd.Series, y0: int | None = None, y1: int | None = None, ndigits: int = 2) -> pd.DataFrame:
        s = s.dropna().copy()
        s.index = s.index.to_period("M").to_timestamp(how="start")
        if s.empty:
            return pd.DataFrame(index=[], columns=range(1, 13))
        if y0 is None:
            y0 = int(s.index.year.min())
        if y1 is None:
            y1 = int(s.index.year.max())
        df = (
            s.to_frame("PDO")
            .assign(Year=lambda d: d.index.year, Month=lambda d: d.index.month)
            .pivot(index="Year", columns="Month", values="PDO")
            .reindex(index=range(y0, y1 + 1), columns=range(1, 13))
        )
        df.index.name = "Year"
        return df.round(ndigits)
    
    def _slug(self, s: str) -> str:
        s = str(s or "").strip()
        return "".join(ch for ch in s if ch.isalnum() or ch in ("-","_")) or "externo"

    # -------------------- IO & preparação --------------------

    def _http_head(self, url: str) -> dict:
        try:
            req = urllib.request.Request(url, method="HEAD")
        except TypeError:
            # compat: Python antigo
            req = urllib.request.Request(url)
            req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(req, timeout=60) as r:
            return dict(r.headers)
            
        
    def _remote_last_modified(self, url: str):
        try:
            h = self._http_head(url)
            lm = h.get("Last-Modified")
            if lm:
                return parsedate_to_datetime(lm)
        except Exception:
            pass
        return None

    def _download_nc_with_checks(self, url: str, dest: Path, label: str):
        print(format_log("INFO", message=f"Verificando o arquivo de TSM {label}"))

        lm_remote_ts = None
        size_remote = None
        head_ok = False
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                headers = r.headers
                lm = headers.get("Last-Modified")
                if lm:
                    lm_remote_ts = parsedate_to_datetime(lm).timestamp()
                cl = headers.get("Content-Length")
                if cl:
                    try:
                        size_remote = int(cl)
                    except Exception:
                        size_remote = None
                head_ok = True
        except Exception as e:
            print(format_log(
                "ATENCAO",
                message=(
                    "Não foi possível consultar metadados no servidor "
                    f"({e.__class__.__name__}) para saber se existe versão mais nova do {label}. "
                    "Usaremos a versão atual local."
                ),
            ))

        if dest.exists():
            if head_ok and lm_remote_ts is not None:
                mtime_local = os.path.getmtime(dest)
                tamanhos_batem = (size_remote is None) or (dest.stat().st_size == size_remote)
                if mtime_local >= lm_remote_ts and tamanhos_batem:
                    print(format_log("INFO", message=f"Arquivo {label} local está atualizado – sem necessidade de download."))
                    return
                else:
                    print(format_log("INFO", message=f"Versão disponível no servidor possivelmente mais atual → atualizando {label}."))
            else:
                print(format_log("INFO", message="Sem informações do arquivo remoto → utilizando arquivo local existente."))
                return

        print(format_log("DOWNLOAD", target=label, dest=str(dest), reason="Iniciando o download..."))
        try:
            tmp_file, _ = urllib.request.urlretrieve(url)
            shutil.move(tmp_file, dest)
            print(format_log("DOWNLOAD", target=label, dest=str(dest), reason="download concluído!"))
        except Exception as e:
            if dest.exists():
                print(format_log(
                    "ATENCAO",
                    message=f"Falha ao baixar {label} ({e.__class__.__name__}: {e}). Usando cópia local existente.",
                ))
                return
            print(format_log(
                "ERRO",
                message=f"{label} indisponível ({e.__class__.__name__}: {e}) e nenhuma cópia local foi encontrada.",
            ))
            return

        try:
            with xr.open_dataset(dest) as ds:
                if "time" in ds.coords or "time" in ds.variables:
                    t = pd.to_datetime(ds["time"].values)
                    tmin = pd.Timestamp(t.min()).to_pydatetime().date()
                    tmax = pd.Timestamp(t.max()).to_pydatetime().date()
                    print(format_log("INFO", message=f"Dado {label} → cobertura temporal {tmin} → {tmax}"))

                else:
                    print(format_log("INFO", message=f"No dado {label} variável 'TIME' ausente → não foi possível verificar a cobertura temporal."))

        except Exception as e:
            print(format_log("ATENCAO", message=f"No dado {label} → falha ao ler cobertura temporal: {e}"))


    def _download_if_needed(self):
        if self.modo == "EXTERNO":
            return
        if self.want_ersst:
            try:
                self._download_nc_with_checks(self.URL_ERSSV5_NC, self.nc_ersst, "ERSSTv5")
            except Exception as err:
                print(format_log("ERRO", message=f"ERSSTv5: download abortado ({err})"))
                raise
        if self.want_kaplan:
            try:
                self._download_nc_with_checks(self.URL_KAPLAN_NC, self.nc_kaplan, "Kaplan")
            except Exception as err:
                print(format_log("ERRO", message=f"Kaplan: download abortado ({err})"))
                raise

    def _open_datasets(self):
        if self.modo == "EXTERNO":
            return
        if self.want_ersst and self.ds_ersst is None:
            self.ds_ersst = xr.open_dataset(self.nc_ersst)
        if self.want_kaplan and self.ds_kap is None:
            self.ds_kap = xr.open_dataset(self.nc_kaplan)

    # -------------------- Carregamento da série de entrada --------------------


    def _load_input_sst_series(self):
        """
        Carrega a série SSTA para o modo TESTE personalizado,
        baseado em AMO_TESTE_TSM = ERSSTv5 | KAPLAN.
        """
        fonte = getattr(self, "fonte_nome", "ERSSTv5").upper().strip()

        if fonte == "ERSSTV5":
            # Garante que o arquivo NetCDF do ERSSTv5 está disponível
            if not hasattr(self, "nc_ersst"):
                self.nc_ersst = self.DATA_DIR / "sst.mnmean_ERSSTv5.nc"
            if not self.nc_ersst.exists():
                raise RuntimeError(format_log("ERRO", message=f"Arquivo ERSSTv5 não encontrado em {self.nc_ersst}"))

            print(format_log("INFO", message=f"Carregando ERSSTv5 de {self.nc_ersst}"))
            s_ssta = self._load_ersst_series(
                self.nc_ersst,
                lat_min=self.lat_min,
                lat_max=self.lat_max,
                lon_min=self.lon_min,
                lon_max=self.lon_max,
                base=self.base_ext
            )
            return s_ssta

        elif fonte == "KAPLAN":
            # idem, mas usa o arquivo Kaplan
            if not hasattr(self, "nc_kaplan"):
                self.nc_kaplan = self.DATA_DIR / "kaplan_sst.nc"
            if not self.nc_kaplan.exists():
                raise RuntimeError(format_log("ERRO", message=f"Arquivo Kaplan não encontrado em {self.nc_kaplan}"))

            print(format_log("INFO", message=f"Carregando TSM Kaplan de {self.nc_kaplan}"))

            s_ssta = self._load_kaplan_series(
                self.nc_kaplan,
                lat_min=self.lat_min,
                lat_max=self.lat_max,
                lon_min=self.lon_min,
                lon_max=self.lon_max,
                base=self.base_ext
            )
            return s_ssta

        else:
            raise RuntimeError(format_log("ERRO", message=f"Opção de Fonte de dados '{fonte}' não suportada em AMO_TESTE_TSM → use ERSSTv5 ou KAPLAN."))


    def load_psl_data(path: Path) -> pd.Series:
        """
        Lê arquivos oficiais do PSL (Kaplan AMO unsmoothed/smoothed).
        Converte em série mensal contínua.
        """
        df = pd.read_fwf(
            path,
            header=None,
            widths=[6] + [7]*12,     # 1 coluna para ano + 12 colunas para meses
            skiprows=1,              # pula linha de cabeçalho
            na_values=[-99.990, -99.99, -9.99]
        )
        df = df.dropna(how="all")   # remove linhas vazias

        # Coloca nomes nas colunas
        df.columns = ["ano"] + list(range(1, 13))

        # Converte de wide para long
        df = df.melt(id_vars=["ano"], var_name="mes", value_name="valor").dropna()

        # Cria coluna de datas
        df["data"] = pd.to_datetime(
            df["ano"].astype(str) + "-" + df["mes"].astype(str) + "-01",
            format="%Y-%m-%d"
        )

        # Ordena e retorna série
        df = df.sort_values("data")
        return pd.Series(df["valor"].values, index=df["data"])

        
    def _load_ersst_series(self, nc_path: Path, lat_min, lat_max, lon_min, lon_max, base: tuple[int,int]) -> pd.Series:
        """
        Carrega série do ERSSTv5:
        - abre NetCDF
        - recorta região
        - calcula média areal
        - transforma em anomalias usando a base fornecida
        """
        ds = xr.open_dataset(nc_path)
        ds_sub, ln, lt = self._subset_region_custom(ds, lon_min, lon_max, lat_min, lat_max)
        var = "sst"
        total = self._area_weighted_mean(ds_sub[var], ln, lt).to_series()
        s_ssta = self._anom_from_total(total, base)
        return s_ssta

    def _load_kaplan_series(self, nc_path: Path, lat_min, lat_max, lon_min, lon_max, base: tuple[int,int]) -> pd.Series:
        """
        Carrega série do Kaplan:
        - abre NetCDF
        - recorta região
        - calcula média areal
        - Kaplan já vem como anomalias (anom), então só faz detrend se necessário
        """
        ds = xr.open_dataset(nc_path)
        ds_sub, ln, lt = self._subset_region_custom(ds, lon_min, lon_max, lat_min, lat_max)
        var = "anom" if "anom" in ds_sub.data_vars else list(ds_sub.data_vars)[0]
        reg = self._area_weighted_mean(ds_sub[var], ln, lt).to_series()
        return reg


    def _anom_from_total(self, s_total: pd.Series, base: Tuple[int,int]) -> pd.Series:
        """Remove climatologia mensal do TOTAL usando anos [base]."""
        m = (s_total.index.year >= base[0]) & (s_total.index.year <= base[1])
        clim = s_total[m].groupby(s_total[m].index.month).mean()
        # duas formas equivalentes – escolha uma:

        # (a) via transform (mantém a ordem original)
        anom = s_total.groupby(s_total.index.month).transform(lambda x: x - clim.loc[x.name])

        # ou (b) via mapeamento do mês → climatologia
        # anom = s_total - s_total.index.month.map(clim)

        return anom
    
    def _read_year12_csv(self, path, colname="serie"):
        """
        Lê CSV no formato ano×12 (em inglês: YEAR,JAN,...,DEC)
        e retorna DataFrame mensal com índice datetime.
        """
        df = pd.read_csv(path, index_col=0)
        df.index.name = "YEAR"

        meses = ["JAN","FEB","MAR","APR","MAY","JUN",
                "JUL","AUG","SEP","OCT","NOV","DEC"]

        series = []
        for ano, row in df.iterrows():
            for i, mes in enumerate(meses, start=1):
                val = row[mes]
                if pd.notna(val):
                    # força float com 3 casas
                    series.append([pd.Timestamp(year=int(ano), month=i, day=1),
                                round(float(val), 3)])

        s = pd.DataFrame(series, columns=["time", colname]).set_index("time")
        return self._monthly_align(s)




    # -------------------- Execução --------------------

    def run(self):
        self._download_if_needed()
        self._open_datasets()
        if self.modo == "REFERENCIA":
            self.want_kaplan = True
            self.want_ersst  = True
            self.lon_west = -80.0
            self.lon_east = 0.0
            self.kap_lat_min, self.kap_lat_max = 0.0, 70.0
            self.ers_lat_min, self.ers_lat_max = 0.0, 60.0
            self.baselines = [(1971, 2000)]

            # CHAMADA CORRETA
            self._run_best_only()
            self._plot_reference_figures()
            return


        # ====================== MODO TESTE ===========================
        if self.modo == "TESTE":
            if self.TESTE_VALIDACAO_COMPLETA:
                # primeiro define os atributos
                self.lon_west = -80.0
                self.lon_east = 0.0
                self.kap_lat_min, self.kap_lat_max = 0.0, 70.0
                self.ers_lat_min, self.ers_lat_max = 0.0, 60.0

                # depois roda o pipeline
                self._run_full_pipeline()
                self._plot_reference_figures()

                # extra: roda também o custom test se quiser
                if self._as_bool_ext(self.cfg.get("AMO_TESTE_EXTRA", "NAO"), label="AMO_TESTE_EXTRA"):
                    self._run_custom_test()
                return
            else:
                self._run_custom_test()
                return

        # ====================== MODO EXTERNO =========================
        if self.modo == "EXTERNO":
            self._run_externo()
            return

    # -------------------- Validação básica --------------------
    def _read_psl_standard(self, path: str | Path) -> pd.Series:
        import pandas as pd, numpy as np, re, requests, io

        # --- abre arquivo ou URL ---
        raw_text = None
        cache_file = None
        is_url = str(path).startswith("http")
        if is_url:
            url = str(path)
            cache_name = {
                self.URL_PSL_KAP_UNS: "kaplan_psl_unsmoothed.dat",
                self.URL_PSL_KAP_SMO: "kaplan_psl_smoothed.dat",
            }.get(url)
            if cache_name is None:
                parsed = urlparse(url)
                base = Path(parsed.path).name or "psl_data.txt"
                cache_name = self._slug(base)
            cache_file = self._cache_file(cache_name)
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                raw_text = resp.text
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(raw_text, encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                if cache_file and cache_file.exists():
                    print(format_log("ERRO", message=f"Falha ao baixar {url} ({e}); usando cache {cache_file}"))
                    raw_text = cache_file.read_text(encoding="utf-8", errors="ignore")
                else:
                    raise
        else:
            with open(path, "r") as f:
                raw_text = f.read()

        raw_lines = raw_text.splitlines() if raw_text else []

        # --- tenta formato ano+12 meses (unsmoothed) ---
        data_lines = [ln for ln in raw_lines
                    if len(ln.strip().split()) == 13 and re.match(r"^\d{4}$", ln.strip().split()[0])]
        if data_lines:
            df = pd.read_csv(io.StringIO("\n".join(data_lines)), sep=r"\s+", header=None)
            df.columns = ["YEAR","JAN","FEB","MAR","APR","MAY","JUN",
                        "JUL","AUG","SEP","OCT","NOV","DEC"]
            df_long = df.melt(id_vars=["YEAR"], var_name="month", value_name="value")
            month_map = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
                        "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
            df_long["month"] = df_long["month"].map(month_map)
            df_long["time"] = pd.to_datetime(dict(year=df_long["YEAR"],
                                                month=df_long["month"], day=15))
            df_long["value"] = pd.to_numeric(df_long["value"], errors="coerce")
            df_long.loc[df_long["value"] < -90, "value"] = np.nan
            return df_long.set_index("time")["value"]

        # --- tenta formato ano valor (smoothed) ---
        data_lines = [ln for ln in raw_lines
                    if len(ln.strip().split()) == 2 and re.match(r"^\d{4}$", ln.strip().split()[0])]
        if data_lines:
            df = pd.read_csv(io.StringIO("\n".join(data_lines)), sep=r"\s+", header=None, names=["YEAR","value"])
            df["time"] = pd.to_datetime(dict(year=df["YEAR"], month=7, day=15))
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df.loc[df["value"] < -90, "value"] = np.nan
            return df.set_index("time")["value"]

        # --- tenta CSV ano×12 ---
        try:
            df = pd.read_csv(path)
            if "Year" in df.columns or "YEAR" in df.columns:
                year_col = "Year" if "Year" in df.columns else "YEAR"
                months = [c for c in df.columns if c not in [year_col]]
                df_long = df.melt(id_vars=[year_col], var_name="month", value_name="value")
                month_map = {m.upper(): i+1 for i, m in enumerate(months)}
                df_long["month"] = df_long["month"].map(month_map)
                df_long["time"] = pd.to_datetime(dict(year=df_long[year_col],
                                                    month=df_long["month"], day=15))
                return df_long.set_index("time")["value"].astype(float)
        except Exception:
            pass

        # --- tenta CSV simples (data, valor) ---
        try:
            df = pd.read_csv(path)
            if "data" in df.columns and len(df.columns) == 2:
                df["time"] = pd.to_datetime(df["data"])
                return df.set_index("time").iloc[:,1].astype(float)
        except Exception:
            pass
        raise ValueError(_cfg_message(f"Formato inesperado em arquivo PSL/CSV: {path}"))



    def _read_ncei_amo(self) -> pd.Series:
        cache_file = self._cache_file("ersst.v5.amo.dat")
        legacy_file = self.DATA_DIR / "ersst.v5.amo.dat"
        raw = None
        try:
            raw = urllib.request.urlopen(self.URL_NCEI_AMO, timeout=30).read().decode("utf-8", "ignore")
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(raw, encoding="utf-8")
            except Exception:
                pass
        except Exception as e:
            for fallback in (cache_file, legacy_file):
                if fallback.exists():
                    print(format_log("ATENCAO", message=f"Falha ao baixar NCEI ({e}); usando cache local: {fallback}"))
                    raw = fallback.read_text(encoding="utf-8", errors="ignore")
                    break
            if raw is None:
                print(format_log("ERRO", message=f"Falha ao baixar NCEI e nenhum cache disponível: {e}"))
                return pd.Series(dtype=float)

        rows = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            toks = ln.split()
            if len(toks) >= 3 and toks[0].isdigit() and toks[1].isdigit():
                year, month = int(toks[0]), int(toks[1])
                try:
                    val = float(toks[2].replace(",", "."))
                except Exception:
                    val = np.nan
                rows.append({"YEAR": year, "MONTH": month, "val": val})
            elif len(toks) >= 13 and toks[0].isdigit():
                year = int(toks[0])
                for m, v in enumerate(toks[1:13], start=1):
                    try:
                        val = float(v.replace(",", "."))
                    except Exception:
                        val = np.nan
                    rows.append({"YEAR": year, "MONTH": m, "val": val})

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(dict(year=df["YEAR"], month=df["MONTH"], day=15))
        return df.set_index("time")["val"].sort_index()
    
    # -------------------- Utilidades da validação & plots --------------------

    def _align_monthly_series(self, s: pd.Series) -> pd.Series:
        """Força todas as séries para índice mensal (YYYY-MM) alinhado."""
        if s is None or s.empty:
            return pd.Series(dtype=float)
        return s.copy().to_period("M").to_timestamp(how="S")

    def _normalize_monthly_index(self, s: pd.Series) -> pd.Series:
        """Força índice mensal no formato YYYY-MM (primeiro dia do mês)."""
        if s is None or s.empty:
            return pd.Series(dtype=float)
        return s.copy().to_period("M").to_timestamp(how="S")

    def _save_validation_pair(
        self,
        calc_series: pd.Series,
        ref_series: pd.Series | None,
        out_path: Path,
        calc_col_name: str,
        ref_col_name: str = "AMO_REFERENCIA",
    ):
        """
        Salva uma série calculada alinhada com sua referência oficial no formato desejado:
        colunas = [data, <nome_do_metodo>, <nome_referencia>]
        """
        if calc_series is None or calc_series.empty:
            print(format_log("ATENCAO", message=f"Série calculada vazia para {out_path.name} — arquivo não gerado."))

            return

        calc_aligned = self._align_monthly_series(calc_series)
        ref_aligned = self._align_monthly_series(ref_series) if ref_series is not None else pd.Series(dtype=float)

        df = pd.DataFrame({
            "data": calc_aligned.index,
            calc_col_name: calc_aligned.values,
        })

        if ref_aligned.empty:
            df[ref_col_name] = np.nan
        else:
            df[ref_col_name] = ref_aligned.reindex(calc_aligned.index).values

        df = df.dropna(subset=[calc_col_name], how="all")
        if df.empty:
            print(format_log("ERRO", message=f"Dados combinados vazios para {out_path.name} — arquivo não gerado."))

            return

        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False, float_format="%.3f", date_format="%Y-%m-%d")
        print(format_log("SALVO", item="Série temporal da validação →", destino=str(out_path)))


    @staticmethod
    def _monthly_align(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["__ym__"] = out.index.to_period("M")
        out = out.groupby("__ym__").mean(numeric_only=True)
        out.index = out.index.to_timestamp(how="S")
        return out

    # -------------------- Depuração controlada --------------------

    def _debug_series_sample(self, label: str, series: pd.Series, max_items: int = 3):
        """Imprime amostra curta de uma série quando em modo de validação completa."""
        modo = getattr(self, "modo", "").upper()
        if not (getattr(self, "TESTE_VALIDACAO_COMPLETA", False) or modo in {"EXTERNO", "TESTE"}):
            return
        if series is None or series.empty:
            print(format_log("ERRO", message=f"Série vazia para {label}"))
            return
        s = series.dropna()
        if s.empty:
            print(format_log("ERRO", message=f"Sem valores válidos para {label}"))

            return
        head = s.iloc[:max_items]
        entries = ", ".join(f"{idx.strftime('%Y-%m')}={val:.3f}" for idx, val in head.items())
        if len(s) > max_items:
            last_idx = s.index[-1]
            last_val = s.iloc[-1]
            entries = f"{entries}, ... {last_idx.strftime('%Y-%m')}={last_val:.3f}"
        print(format_log("INFO", message=f"Amostras dos valores de remoção: {label} → {entries}"))


    def _debug_trend_info(self, label: str, series: pd.Series):
        """Imprime informação sobre a tendência linear mensal da série."""
        modo = getattr(self, "modo", "").upper()
        if not (getattr(self, "TESTE_VALIDACAO_COMPLETA", False) or modo in {"EXTERNO", "TESTE"}):
            return
        if series is None or series.empty:
            print(format_log("ERRO", message=f"Série vazia para {label} - sem tendência"))

            return
        arr = series.to_numpy(dtype=float)
        mask = np.isfinite(arr)
        if mask.sum() < 2:
            print(format_log("ERRO", message=f"Dados insuficientes para tendência de {label}"))

            return
        t = np.arange(len(arr), dtype=float)[mask]
        vals = arr[mask]
        slope, intercept = np.polyfit(t, vals, 1)
        slope_decade = slope * 120  # 12 meses * 10 anos
        print(format_log("INFO", message=f"{label}: slope={slope:.4e}/mês (~{slope_decade:.3f} por década)"))


    def _plot_amo(self, df: pd.DataFrame, col: str, title: str, outfile: Path,
                smooth_win: int = 121, annotate: dict | None = None,
                ylim: tuple[float, float] | None = None):
        import matplotlib.pyplot as plt
        from matplotlib.dates import YearLocator, DateFormatter
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        import matplotlib.image as mpimg

        s = df[col].astype(float).copy()
        if smooth_win and smooth_win > 1:
            s = s.rolling(smooth_win, center=True,
                        min_periods=max(1, smooth_win // 2)).mean()
        t = s.index
        y = s.values

        fig, ax = plt.subplots(figsize=(12, 3.2), dpi=300)
        ax.set_title(title, fontsize=12, pad=10)
        ax.axhline(0, lw=1.2, color="#222222", alpha=0.9)

        # Áreas coloridas
        ax.fill_between(t, 0, y, where=(y >= 0), interpolate=True, alpha=0.8, color="red")
        ax.fill_between(t, 0, y, where=(y < 0), interpolate=True, alpha=0.8, color="blue")

        # Eixo X fixo, sem espaço sobrando
        ax.set_xlim(t[0], t[-1])
        ax.margins(x=0)

        # Configuração do eixo X
        ax.xaxis.set_major_locator(YearLocator(base=5))
        ax.xaxis.set_major_formatter(DateFormatter("%Y"))
        ax.xaxis.set_minor_locator(YearLocator(base=1))
        for lab in ax.get_xticklabels(which="major"):
            lab.set_rotation(30); lab.set_ha("right")
        ax.tick_params(axis="x", which="major", labelsize=9)
        ax.tick_params(axis="x", which="minor", length=3, labelsize=0)

        # Eixo Y fixo se informado, senão automático
        if ylim:
            ax.set_ylim(*ylim)
        else:
            yabs = float(np.nanmax(np.abs(y))) if np.isfinite(y).any() else 0.4
            ymax = max(0.4, round((yabs * 1.1) / 0.1) * 0.1)
            ax.set_ylim(-ymax, ymax)

        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.grid(axis="y", ls=":", lw=0.6, alpha=0.6)

        # Anotação estatística
        if annotate and np.isfinite(annotate.get("corr", np.nan)) and np.isfinite(annotate.get("rmse", np.nan)):
            txt = f"r = {annotate['corr']:.3f}\nRMSE = {annotate['rmse']:.3f}"
            ax.text(0.18, 0.965, txt, transform=ax.transAxes, ha="right", va="top",
                    fontsize=10, bbox=dict(facecolor="white", alpha=0.75, boxstyle="round,pad=0.25"))

        # Logo
        try:
            if self.logo_path and self.logo_path.exists():
                arr = mpimg.imread(str(self.logo_path))
                ab = AnnotationBbox(OffsetImage(arr, zoom=0.03),
                                    (0.12, 0.014), xycoords="axes fraction",
                                    frameon=False, box_alignment=(1, 0))
                ax.add_artist(ab)
        except Exception:
            pass

        outfile.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(outfile, bbox_inches="tight", dpi=300)
        plt.close(fig)
        print(format_log("SALVO", item=f"Figura da série temporal do AMO - TESTE →", destino=str(outfile)))


    def _run_metrics(self, model_df: pd.DataFrame, ref_df: pd.DataFrame,
                    model_col: str, ref_col: str, out_prefix: str,
                    exp_name: str = "-", fonte: str = "-", baseline: str = "-", save=True):

        merged = model_df.join(ref_df, how="inner")
        a = pd.to_numeric(merged[model_col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(merged[ref_col],   errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(a) & np.isfinite(b)
        used = merged.index.values[mask]
        a, b = a[mask], b[mask]

        stats = {
            "experimento": exp_name,
            "fonte": fonte,
            "base": baseline,
            "n_registros": int(mask.sum()),
            "corr": np.nan,
            "rmse": np.nan,
            "mae": np.nan,
            "bias": np.nan,
            "slope": np.nan,
            "intercept": np.nan,
            "desv_pad_erro": np.nan,
            "r2": np.nan,
            "data_inicio": None,
            "data_fim": None,
        }

        if stats["n_registros"] > 1:
            r = float(np.corrcoef(a, b)[0, 1])
            rmse = float(np.sqrt(np.mean((a - b) ** 2)))
            mae  = float(np.mean(np.abs(a - b)))
            bias = float(np.mean(a - b))
            slope, intercept = np.polyfit(b, a, 1)
            desv_pad_erro = float(np.std(a - b, ddof=1))
            stats.update({
                "corr": r,
                "rmse": rmse,
                "mae": mae,
                "bias": bias,
                "slope": slope,
                "intercept": intercept,
                "desv_pad_erro": desv_pad_erro,
                "r2": float(r**2),
                "data_inicio": pd.to_datetime(used.min()).strftime("%Y-%m"),
                "data_fim":   pd.to_datetime(used.max()).strftime("%Y-%m"),
            })

        # Decide onde salvar
        # Só salva se for permitido
        if save and self.modo not in {"REFERENCIA"} and not (
            self.modo == "TESTE" and getattr(self, "TESTE_VALIDACAO_COMPLETA", False)
        ):
            # Se for caminho completo, salva direto
            out_path = Path(out_prefix)
            if out_path.suffix == ".csv":
                out_path.parent.mkdir(parents=True, exist_ok=True)
                cols_order = self.METRICS_COLUMNS
                df_stats = pd.DataFrame([stats])
                df_stats = df_stats[[c for c in cols_order if c in df_stats.columns] + [c for c in df_stats.columns if c not in cols_order]]
                df_stats.to_csv(out_path, index=False, float_format="%.3f")
            else:
                # Caso antigo: prefixo simples → salvar em OUT_DIR_valida
                (self.OUT_DIR_valida / f"{out_prefix}.csv").parent.mkdir(parents=True, exist_ok=True)
                cols_order = self.METRICS_COLUMNS
                df_stats = pd.DataFrame([stats])
                df_stats = df_stats[[c for c in cols_order if c in df_stats.columns] + [c for c in df_stats.columns if c not in cols_order]]
                df_stats.to_csv(self.OUT_DIR_valida / f"{out_prefix}.csv", index=False, float_format="%.3f")


        pretty_name = exp_name.replace("_", " ").strip()
        print(f"[ESTATÍSTICA] {pretty_name} N={stats['n_registros']} Correlação={stats['corr']:.3f} RMSE={stats['rmse']:.3f}")
        return stats



    def _run_full_pipeline(self):
        """
        Validação completa:
        - Kaplan (unsmoothed + smoothed) vs PSL
        - ERSSTv5 (Bruto/Detrend/NA-Global) vs NCEI para cada baseline
        - Escolhe a melhor combinação (RMSE↓, r↑)
        - Plota e salva métricas consolidadas
        """
        # 1) Kaplan
        k_uns, k_smo, _, _ = self._compute_amo_kaplan_outputs()
        psl_uns_s = self._read_psl_standard(self.URL_PSL_KAP_UNS)
        psl_smo_s = self._read_psl_standard(self.URL_PSL_KAP_SMO)
        ncei_s    = self._read_ncei_amo()

        def to_monthly_df(s: pd.Series, name: str) -> pd.DataFrame:
            df = pd.DataFrame({name: s}).copy()
            df.index = pd.to_datetime(df.index).to_period("M").to_timestamp(how="S")
            return self._monthly_align(df)

        psl_uns  = to_monthly_df(psl_uns_s, "psl_uns")
        psl_smo  = to_monthly_df(psl_smo_s, "psl_smo")
        ncei     = to_monthly_df(ncei_s,    "ncei_amo")
        my_k_uns = to_monthly_df(k_uns,     "my_k_uns")
        my_k_smo = to_monthly_df(k_smo,     "my_k_smo")

        # Janelas oficiais
        my_k_uns = my_k_uns.loc["1856-01":"2023-01"]; psl_uns = psl_uns.loc["1856-01":"2023-01"]
        my_k_smo = my_k_smo.loc["1861-01":"2018-01"]; psl_smo = psl_smo.loc["1861-01":"2018-01"]

        st_k_uns = self._run_metrics(
            my_k_uns, psl_uns,
            "my_k_uns", "psl_uns", "Kaplan_vs_PSL",
            exp_name="Kaplan_vs_PSL_unsmoothed", fonte="Kaplan", baseline="1951-1980"
        )

        st_k_smo = self._run_metrics(
            my_k_smo, psl_smo,
            "my_k_smo", "psl_smo", "Kaplan_suav_vs_PSL",
            exp_name="Kaplan_vs_PSL_smoothed", fonte="Kaplan", baseline="1951-1980"
        )

        # 2) ERSSTv5
        results = []
        stats_rows = []
        for base in self.baselines:
            amo_raw, amo_dt, amo_ts, files, tag = self._compute_ersst_variants_outputs(base)

            def to_df(s: pd.Series, name: str) -> pd.DataFrame:
                df = pd.DataFrame({name: s}).copy()
                df.index = df.index.to_period("M").to_timestamp(how="S")
                return df

            df_raw = to_df(amo_raw, "raw_na_ssta")
            df_dt  = to_df(amo_dt,  "na_detrended")
            df_ts  = to_df(amo_ts,  "tshea_removed")

            st_raw = self._run_metrics(
                df_raw, ncei,
                "raw_na_ssta", "ncei_amo",
                f"ERSSTv5_bruto_vs_NCEI_{tag}",
                exp_name="ERSSTv5_bruto_vs_NCEI", fonte="ERSSTv5_bruto", baseline=tag
            )

            st_dt  = self._run_metrics(
                df_dt, ncei,
                "na_detrended", "ncei_amo",
                f"ERSSTv5_rem.tend_vs_NCEI_{tag}",
                exp_name="ERSSTv5_rem.tend_vs_NCEI", fonte="ERSSTv5_rem.tend", baseline=tag
            )

            st_ts  = self._run_metrics(
                df_ts, ncei,
                "tshea_removed", "ncei_amo",
                f"ERSSTv5_rem.global_vs_NCEI_{tag}",
                exp_name="ERSSTv5_rem.global_vs_NCEI", fonte="ERSSTv5_rem.global", baseline=tag
            )

            results.extend([
                (f"Bruto ({tag})", st_raw, amo_raw, tag),
                (f"Detrended ({tag})", st_dt, amo_dt, tag),
                (f"GlobalRemoved ({tag})", st_ts, amo_ts, tag),
            ])

            stats_rows.extend([st_raw, st_dt, st_ts])

        # 3) Melhor ERSSTv5
        def ranking_key(item):
            st = item[1]
            rmse = st.get("rmse", np.inf); corr = st.get("corr", -np.inf)
            rmse = np.inf if (rmse is None or np.isnan(rmse)) else rmse
            corr = -np.inf if (corr is None or np.isnan(corr)) else corr
            return (rmse, -corr)

        best_label, best_stats, best_series, best_tag = sorted(results, key=ranking_key)[0]
        self.last_ersst_best = best_series
        tag = best_tag
        self.best_tag = best_tag

        # 3b) Séries combinadas para validação (formato longo)
        if self.TESTE_VALIDACAO_COMPLETA:
            combined_dir = self.OUT_DIR_tables

            ncei_series = ncei_s if isinstance(ncei_s, pd.Series) else pd.Series(dtype=float)
            self._save_validation_pair(
                amo_raw,
                ncei_series,
                combined_dir / f"AMO_ERSSTv5vsNCEI_bruto_{self.SUF_EXEC}.csv",
                "AMO_CALC_bruto",
                "AMO_NCEI"
            )
            self._save_validation_pair(
                amo_dt,
                ncei_series,
                combined_dir / f"AMO_ERSSTv5vsNCEI_rem.tend_{self.SUF_EXEC}.csv",
                "AMO_CALC_rem.tend",
                "AMO_NCEI"
            )
            self._save_validation_pair(
                amo_ts,
                ncei_series,
                combined_dir / f"AMO_ERSSTv5vsNCEI_rem.global_{self.SUF_EXEC}.csv",
                "AMO_CALC_rem.global",
                "AMO_NCEI"
            )

            if isinstance(k_smo, pd.Series):
                self._save_validation_pair(
                    k_smo,
                    psl_smo_s if isinstance(psl_smo_s, pd.Series) else pd.Series(dtype=float),
                    combined_dir / f"AMO_KAPLANvsPSL_suav_{self.SUF_EXEC}.csv",
                    "AMO_CALC_KAPLAN_suav",
                    "AMO_PSL_suav"
                )
            if isinstance(k_uns, pd.Series):
                self._save_validation_pair(
                    k_uns,
                    psl_uns_s if isinstance(psl_uns_s, pd.Series) else pd.Series(dtype=float),
                    combined_dir / f"AMO_KAPLANvsPSL_{self.SUF_EXEC}.csv",
                    "AMO_CALC_KAPLAN_nao.suav",
                    "AMO_PSL_nao.suav"
                )


        # 4) Figuras (atenção à suavização)
        fig_dir = self.OUT_DIR

        # Kaplan SUAVIZADO (já suavizado → smooth_win=0)
        kap_df_smo = self._monthly_align(pd.DataFrame({"amo_kaplan_smo": k_smo}))
        self._plot_amo(
            kap_df_smo,
            "amo_kaplan_smo",
            "Índice AMO | Calculado com TSM Kaplan | Suavização de 121 meses | Base Climatológica 1951-1980",
            fig_dir / f"AMO_serie.temporal_KAPLAN_suav_{self.SUF_EXEC}.png",
            smooth_win=0,
            annotate={
                "corr": st_k_smo.get("corr", np.nan),
                "rmse": st_k_smo.get("rmse", np.nan)
            }
        )

        # Kaplan NÃO SUAVIZADO
        kap_df_uns = self._monthly_align(pd.DataFrame({"amo_kaplan_uns": k_uns}))
        self._plot_amo(
            kap_df_uns,
            "amo_kaplan_uns",
            "Índice AMO | Calculado com TSM Kaplan | Sem Suavização | Base Climatológica 1951-1980",
            fig_dir / f"AMO_serie.temporal_KAPLAN_{self.SUF_EXEC}.png",
            smooth_win=0,
            annotate={
                "corr": st_k_uns.get("corr", np.nan),
                "rmse": st_k_uns.get("rmse", np.nan)
            }
        )

        # ERSSTv5 Bruto
        self._plot_amo(
            to_df(amo_raw, "raw_na_ssta"),
            "raw_na_ssta",
            f"Índice AMO | Calculado com TSM ERSSTv5 | Base Climatológica {tag}",
            fig_dir / f"AMO_serie.temporal_ERSSTv5_bruto_{self.SUF_EXEC}.png",
            smooth_win=0,
            annotate={
                "corr": st_raw.get("corr", np.nan),
                "rmse": st_raw.get("rmse", np.nan)
            }
        )

        # ERSSTv5 Detrended
        self._plot_amo(
            to_df(amo_dt, "na_detrended"),
            "na_detrended",
            f"Índice AMO | Calculado com TSM ERSSTv5 com remoção de tendência linear mensal | Base Climatológica {tag}",
            fig_dir / f"AMO_serie.temporal_ERSSTv5_rem.tend_{self.SUF_EXEC}.png",
            smooth_win=0,
            annotate={
                "corr": st_dt.get("corr", np.nan),
                "rmse": st_dt.get("rmse", np.nan)
            }
        )

        # ERSSTv5 TS06 (remoção global)
        self._plot_amo(
            to_df(amo_ts, "tshea_removed"),
            "tshea_removed",
            f"Índice AMO | Calculado com TSM ERSSTv5 com remoção do Efeito Global no Atlântico (entre 60°S e 60°N) | Base Climatológica {tag}",
            fig_dir / f"AMO_serie.temporal_ERSSTv5_rem.global_{self.SUF_EXEC}.png",
            smooth_win=0,
            annotate={
                "corr": st_ts.get("corr", np.nan),
                "rmse": st_ts.get("rmse", np.nan)
            }
        )


        # 5) Estatísticas consolidadas
        df_all = pd.DataFrame([st_k_uns, st_k_smo] + stats_rows)
        cols_order = self.METRICS_COLUMNS
        df_all = df_all[[c for c in cols_order if c in df_all.columns] + [c for c in df_all.columns if c not in cols_order]]

        out_stats = self.OUT_DIR_valida / f"AMO_metricas_estatisticas_{self.SUF_EXEC}.csv"
        out_stats.parent.mkdir(parents=True, exist_ok=True)
        df_all.to_csv(out_stats, index=False, float_format="%.3f")
        print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do AMO →", destino=str(out_stats)))



    def _run_best_only(self):
        fig_dir = self.OUT_DIR
        val_dir = self.OUT_DIR
        tab_dir = self.OUT_DIR
        fig_dir.mkdir(parents=True, exist_ok=True)
        val_dir.mkdir(parents=True, exist_ok=True)
        tab_dir.mkdir(parents=True, exist_ok=True)

        rows = []

        # ------------------ KAPLAN (calculado: não suavizado + suavizado) ------------------
        if self.want_kaplan:
            k_uns, k_smo, _, _ = self._compute_amo_kaplan_outputs()
    
            # métricas vs PSL (se refs disponíveis) – apenas para consolidado
            try:
                psl_uns_s = self._read_psl_standard(self.URL_PSL_KAP_UNS)
                psl_smo_s = self._read_psl_standard(self.URL_PSL_KAP_SMO)

                def to_mdf(s, name):
                    if s is None or s.empty:
                        return pd.DataFrame(columns=[name])
                    df = pd.DataFrame({name: s}).copy()
                    df.index = pd.to_datetime(df.index, errors="coerce").to_period("M").to_timestamp(how="S")
                    return self._monthly_align(df)

                my_k_uns = to_mdf(k_uns, "my_k_uns").loc["1856-01":"2023-01"]
                psl_uns  = to_mdf(psl_uns_s, "psl_uns").loc["1856-01":"2023-01"]
                st_k_uns = self._run_metrics(
                    my_k_uns, psl_uns,
                    "my_k_uns", "psl_uns",
                    "Kaplan_vs_PSL",
                    exp_name="Kaplan_vs_PSL_unsmoothed",
                    fonte="Kaplan",
                    baseline="1951-1980"
                )
                my_k_smo = to_mdf(k_smo, "my_k_smo").loc["1861-01":"2018-01"]
                psl_smo  = to_mdf(psl_smo_s, "psl_smo").loc["1861-01":"2018-01"]
                st_k_smo = self._run_metrics(
                    my_k_smo, psl_smo,
                    "my_k_smo", "psl_smo",
                    "Kaplan_suav_vs_PSL",
                    exp_name="Kaplan_vs_PSL_smoothed",
                    fonte="Kaplan",
                    baseline="1951-1980"
                )

                rows.extend([st_k_uns, st_k_smo])
            except Exception as e:
                print(format_log("ERRO", message=f"Não foi possível calcular métricas Kaplan vs PSL: {e}"))

        # ------------------ ERSSTv5 (melhor: RAW na base 1971–2000; sem salvar variantes) ------------------
        amo_raw, _, _, _, tag = (None, None, None, None, None)
        if self.want_ersst:
            base_best = (1971, 2000)
            if base_best not in self.baselines:
                self.baselines.append(base_best)

        amo_raw, _, _, _, tag = self._compute_ersst_variants_outputs(base_best, write_variant_files=False)
        self.last_ersst_best = amo_raw
        self.best_tag = tag

        # métricas consolidadas vs NCEI (se disponível)
        try:
            def to_mdf(s, name):
                if s is None or s.empty:
                    return pd.DataFrame(columns=[name])
                df = pd.DataFrame({name: s}).copy()
                df.index = df.index.to_period("M").to_timestamp(how="S")
                return self._monthly_align(df)

            ers_df = to_mdf(amo_raw, "amo_ersst_best")
            ncei_s = self._read_ncei_amo()
            if not ncei_s.empty:
                ncei = to_mdf(ncei_s, "ncei_amo")
                st_ers = self._run_metrics(
                ers_df, ncei,
                "amo_ersst_best", "ncei_amo",
                f"ERSSTv5_melhor_vs_NCEI_{tag}",
                exp_name="ERSSTv5_vs_NCEI",
                fonte="ERSSTv5",
                baseline=tag
            )

                rows.append(st_ers)
        except Exception as e:
            print(format_log("ERRO", message=f"Não foi possível calcular métricas ERSST vs NCEI: {e}"))

        # ------------------ Estatísticas (consolidado) ------------------
        if rows:
            out_csv = self.OUT_DIR_valida / f"AMO_metricas_estatisticas_{self.SUF_EXEC}.csv"
            df_rows = pd.DataFrame(rows)
            cols_order = self.METRICS_COLUMNS
            df_rows = df_rows[[c for c in cols_order if c in df_rows.columns] + [c for c in df_rows.columns if c not in cols_order]]
            df_rows.to_csv(out_csv, index=False, float_format="%.3f")
            print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas do AMO ERSST vs NCEI", destino=f"{out_csv}"))

        # ------------------ NOVAS TABELAS ------------------
        try:
            # 1) ERSSTv5 vs NCEI
            if amo_raw is not None:
                ncei_s = self._read_ncei_amo()
                amo_al = self._align_monthly_series(amo_raw)
                ncei_al = self._align_monthly_series(ncei_s)
                df_ersst_ncei = pd.DataFrame({
                    "data": amo_al.index,
                    "AMO_CALC_ERSSTV5": amo_al.values,
                    "AMO_NCEI": ncei_al.reindex(amo_al.index).values
                })
                df_ersst_ncei.to_csv(tab_dir / f"AMO_ERSSTv5vsNCEI_{self.SUF_EXEC}.csv", index=False, float_format="%.3f")

            # 2) Kaplan suavizado
            if k_smo is not None:
                psl_smo = self._read_psl_standard(self.URL_PSL_KAP_SMO)
                kap_smo_al = self._align_monthly_series(k_smo)
                psl_smo_al = self._align_monthly_series(psl_smo)
                df_kap_smo = pd.DataFrame({
                    "data": kap_smo_al.index,
                    "AMO_CALC_KAPLAN_suav": kap_smo_al.values,
                    "AMO_PSL_suav": psl_smo_al.reindex(kap_smo_al.index).values
                })
                df_kap_smo.to_csv(tab_dir / f"AMO_KAPLANvsPSL_suav_{self.SUF_EXEC}.csv", index=False, float_format="%.3f")

            # 3) Kaplan não suavizado
            if k_uns is not None:
                psl_uns = self._read_psl_standard(self.URL_PSL_KAP_UNS)
                kap_uns_al = self._align_monthly_series(k_uns)
                psl_uns_al = self._align_monthly_series(psl_uns)
                df_kap_uns = pd.DataFrame({
                    "data": kap_uns_al.index,
                    "AMO_CALC_KAPLAN_nao.suav": kap_uns_al.values,
                    "AMO_PSL_nao.suav": psl_uns_al.reindex(kap_uns_al.index).values
                })
                df_kap_uns.to_csv(tab_dir / f"AMO_KAPLANvsPSL_{self.SUF_EXEC}.csv", index=False, float_format="%.3f")


            print(format_log("SALVO", item=f"Arquivo CSV com as séries ERSSTv5/NCEI e Kaplan/PSL salvas em", destino=f"{tab_dir}"))


        except Exception as e:
            print(format_log("ERRO", message=f"Não foi possível salvar tabelas com as séries combinadas ERSSTv5/NCEI e Kaplan/PSL: {e}"))

    def _plot_reference_figures(self):
        fig_dir = self.OUT_DIR
        tab_dir = self.OUT_DIR
        fig_dir.mkdir(parents=True, exist_ok=True)

        # ===================== KAPLAN CALCULADO =====================
        if self.want_kaplan:
            kap_uns_series = getattr(self, "last_kaplan_uns", pd.Series(dtype=float))
            if kap_uns_series is not None and not kap_uns_series.empty:
                kap_uns_df = self._monthly_align(pd.DataFrame({"amo_kaplan_uns": kap_uns_series}))
                self._plot_amo(
                    kap_uns_df, "amo_kaplan_uns",
                    "Índice AMO | Calculado com TSM Kaplan | Não suavizado",
                    fig_dir / f"AMO_serie.temporal_KAPLAN_{self.SUF_EXEC}.png",
                    smooth_win=0, ylim=(-1, 1)
                )

            kap_smo_series = getattr(self, "last_kaplan_smo", pd.Series(dtype=float))
            if kap_smo_series is not None and not kap_smo_series.empty:
                kap_smo_df = self._monthly_align(pd.DataFrame({"amo_kaplan_smo": kap_smo_series}))
                self._plot_amo(
                    kap_smo_df, "amo_kaplan_smo",
                    "Índice AMO | Calculado com TSM Kaplan | Suavização de 121 meses",
                    fig_dir / f"AMO_serie.temporal_KAPLAN_suav_{self.SUF_EXEC}.png",
                    smooth_win=0, ylim=(-0.5, 0.5)
                )

        # ===================== ERSSTv5 (melhor configuração) =====================
        if self.want_ersst:
            ersst_series = getattr(self, "last_ersst_best", pd.Series(dtype=float))
            if ersst_series is not None and not ersst_series.empty:
                ers_df = self._monthly_align(pd.DataFrame({"amo_ersst_best": ersst_series}))
                self._plot_amo(
                    ers_df, "amo_ersst_best",
                    f"Índice AMO | Calculado com TSM ERSSTv5 | Base Climatológica {getattr(self, 'best_tag', '1971-2000')}",
                    fig_dir / f"AMO_serie.temporal_ERSSTv5_{self.SUF_EXEC}.png",
                    smooth_win=0, ylim=(-2, 2)
                )

    # -------------------- Cálculos específicos (como no script) --------------------
    def _compute_amo_kaplan_outputs(self) -> tuple[pd.Series, pd.Series, Path, Path]:
        """
        Gera os arquivos PSL do Kaplan (unsmoothed + smoothed) e retorna:
        (serie_unsmoothed, serie_smoothed, path_unsmoothed, path_smoothed)
        """
        base_str = self._format_baseline((1951, 1980))
        if base_str:
            message = f"Base climatológica AMO com TSM KAPLAN - Modo {self.modo} → {base_str}"
            print(format_log("INFO", message=message))
        if self.ds_kap is None:
            self.ds_kap = xr.open_dataset(self.nc_kaplan)

        # recorte e média areal (anomalias já vêm no Kaplan)
        ds_sub, ln, lt = self._subset_region_custom(
            self.ds_kap, self.lon_west, self.lon_east, self.kap_lat_min, self.kap_lat_max
        )
        var = "anom" if "anom" in ds_sub.data_vars else list(ds_sub.data_vars)[0]
        reg = self._area_weighted_mean(ds_sub[var], ln, lt).to_series()

        # detrend e janelas oficiais
        amo_detr = self._detrend_pd(reg)
        k_uns = amo_detr.loc["1856-01":"2023-01"]
        k_smo = amo_detr.rolling(121, center=True).mean().loc["1861-01":"2018-01"].dropna()

        # Armazena para possíveis usos posteriores (plots, validação)
        self.last_kaplan_uns = k_uns
        self.last_kaplan_smo = k_smo

        print(format_log("INFO", message=f"Índice AMO com KAPLAN calculado."))
        return k_uns, k_smo, None, None
    
    def _da_to_series_time(self, da: xr.DataArray) -> pd.Series:
        """Converte um DataArray 1D (tempo) em Series com DatetimeIndex (ordem crescente)."""
        # Garante que só haja o eixo 'time' restante
        if "time" not in da.dims or len(da.dims) != 1:
            # se sobrou alguma dimensão extra, reduz com mean (na prática não deve acontecer)
            other_dims = [d for d in da.dims if d != "time"]
            if other_dims:
                da = da.mean(dim=other_dims)
        t = pd.to_datetime(da["time"].values)
        s = pd.Series(da.values, index=t)
        s = s.sort_index()
        return s

    def _compute_ersst_variants_outputs(self, baseline: tuple[int,int], write_variant_files: bool = True):
        """
        Para a ERSSTv5, calcula 3 variantes (NA SSTA; detrended; NA−Global 60S–60N).
        Quando write_variant_files=True, salva 3 arquivos PSL e retorna seus paths.
        Quando False, apenas calcula e retorna as séries (sem salvar os TXT individuais).
        Retorna: (serie_raw, serie_detrended, serie_ts06, {"raw":path|None, "dt":path|None, "ts":path|None}, tag)
        """
        # base_str = self._format_baseline(baseline)
        # if base_str:
            # message = f"Baseline ERSSTv5 (modo {self.modo}): {base_str}"
            # print(format_log("INFO", message=message))
        if self.ds_ersst is None:
            self.ds_ersst = xr.open_dataset(self.nc_ersst)

        # --- Atlântico Norte (ERSST: usar limites próprios) ---
        ds_na, ln, lt = self._subset_region_custom(
            self.ds_ersst, self.lon_west, self.lon_east, self.ers_lat_min, self.ers_lat_max
        )
        var = "sst"
        na_total = self._area_weighted_mean(ds_na[var], ln, lt).to_series()

        # --- Global 60S–60N ---
        ds_glb = self.ds_ersst.copy()
        lon_name = "lon" if "lon" in ds_glb.coords else ("longitude" if "longitude" in ds_glb.coords else list(ds_glb.coords)[0])
        lat_name = "lat" if "lat" in ds_glb.coords else ("latitude" if "latitude" in ds_glb.coords else list(ds_glb.coords)[1])
        ds_glb = ds_glb.assign_coords({lon_name: self._normalize_lon(ds_glb[lon_name])}).sortby(lon_name).sortby(lat_name)
        ds_glb = ds_glb.sel({lat_name: slice(-60.0, 60.0), lon_name: slice(-180.0, 180.0)})
        gl_total = self._area_weighted_mean(ds_glb[var], lon_name, lat_name).to_series()

        # --- Anomalias por base ---
        na_ssta = self._anom_from_total(na_total, baseline)
        gl_ssta = self._anom_from_total(gl_total, baseline)

        # Depuração: amostras e tendências usadas nas remoções
        self._debug_series_sample(f"NA SSTA ({baseline[0]}-{baseline[1]})", na_ssta)
        self._debug_series_sample("Global SSTA 60S–60N", gl_ssta)
        self._debug_trend_info("Tendência NA SSTA", na_ssta)
        self._debug_trend_info("Tendência Global SSTA", gl_ssta)

        # Variantes
        amo_raw = na_ssta.copy()                  # NA SSTA
        amo_dt  = self._detrend_pd(na_ssta)       # detrended
        amo_ts  = (na_ssta - gl_ssta).rename("ts06")  # NA − Global(60S–60N)

        # Cortes 1854 → último comum
        first = pd.Timestamp("1854-01-01")
        last  = min(amo_raw.index.max(), amo_dt.index.max(), amo_ts.index.max())
        amo_raw = amo_raw.loc[first:last]
        amo_dt  = amo_dt.loc[first:last]
        amo_ts  = amo_ts.loc[first:last]

        tag = f"{baseline[0]}-{baseline[1]}"

        files = {"raw": None, "dt": None, "ts": None}
        if write_variant_files:
            print(format_log("INFO", message=f"Índice AMO com ERSSTv5 calculado."))
        else:
            print(format_log("INFO", message=f"Índice AMO com ERSSTv5 calculado."))
        return amo_raw, amo_dt, amo_ts, files, tag


    def _validacao_basica(self, amo_uns: pd.Series, amo_smo: pd.Series, fonte_tag: str):
            rows = []
            try:
                if not self.usa_externo and self._fonte_tag() == "ERSSTv5":
                    ref = self._read_ncei_amo()  # unsmoothed
                    comp = pd.concat([amo_uns.rename("calc"), ref.rename("ref")], axis=1).dropna()
                    if not comp.empty:
                        corr = comp["calc"].corr(comp["ref"])
                        rmse = float(np.sqrt(np.mean((comp["calc"] - comp["ref"]) ** 2)))
                        bias = float((comp["calc"] - comp["ref"]).mean())
                        rows.append(["ERSSTv5_NCEI_unsmoothed", corr, rmse, bias, comp.index.min(), comp.index.max()])
                if not self.usa_externo and self._fonte_tag() == "KAPLAN":
                    for smooth, url in [(False, self.URL_PSL_KAP_UNS), (True, self.URL_PSL_KAP_SMO)]:
                        ref = self._read_psl_standard(url)
                        calc = amo_smo if smooth else amo_uns
                        comp = pd.concat([calc.rename("calc"), ref.rename("ref")], axis=1).dropna()
                        if not comp.empty:
                            corr = comp["calc"].corr(comp["ref"])
                            rmse = float(np.sqrt(np.mean((comp["calc"] - comp["ref"]) ** 2)))
                            bias = float((comp["calc"] - comp["ref"]).mean())
                            tag = "Kaplan_PSL_smoothed" if smooth else "Kaplan_PSL_unsmoothed"
                            rows.append([tag, corr, rmse, bias, comp.index.min(), comp.index.max()])
            except Exception as e:
                print(format_log(f"ERRO", message=f"Validação não concluída: {e}"))

            if rows:
                dfm = pd.DataFrame(rows, columns=["referencia","corr","rmse","bias","inicio","fim"])
                dfm.to_csv(self.OUT_DIR_valida / f"validacao_{fonte_tag}.csv", index=False)
                print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do AMO →", destino=str(self.OUT_DIR_valida)))

    def _align_monthly_index(self, s: pd.Series) -> pd.Series:
        """Normaliza índice para o primeiro dia do mês (YYYY-MM-01)."""
        if s is None or s.empty:
            return pd.Series(dtype=float)
        return s.copy().to_period("M").to_timestamp(how="S")
    
    def _run_custom_test(self):
        print(format_log(f"INFO", message=f"Iniciando o cálculo do AMO no modo TESTE Personalizado"))

        # -------------------- Limites e datas --------------------
        self.lat_min = self._as_float(self.cfg.get("AMO_TESTE_LAT_MIN", 0.0))
        self.lat_max = self._as_float(self.cfg.get("AMO_TESTE_LAT_MAX", 60.0))
        self.lon_min = self._as_float(self.cfg.get("AMO_TESTE_LON_MIN", -80.0))
        self.lon_max = self._as_float(self.cfg.get("AMO_TESTE_LON_MAX", 0.0))

        inicio = self._as_date(self.cfg.get("AMO_TESTE_INICIO", "1856-01-01"))
        final  = self._as_date(self.cfg.get("AMO_TESTE_FINAL", "2023-01-15"))

        # -------------------- Flags de transformação --------------------
        self.remove_trend  = self._as_bool_ext(self.cfg.get("AMO_TESTE_REMOCAO_TENDENCIA", "NAO"), label="AMO_TESTE_REMOCAO_TENDENCIA")
        self.remove_global = self._as_bool_ext(self.cfg.get("AMO_TESTE_REMOCAO_GLOBAL", "NAO"), label="AMO_TESTE_REMOCAO_GLOBAL")

        # -------------------- Suavização --------------------
        suaviza = self._as_bool_ext(self.cfg.get("AMO_TESTE_SUAVIZACAO", "NAO"), label="AMO_TESTE_SUAVIZACAO")
        win     = int(self._as_float(self.cfg.get("AMO_TESTE_JANELA_SUAVIZACAO", 121)))

        # -------------------- Fonte e base --------------------
        self.fonte_nome = str(self.cfg.get("AMO_TESTE_TSM","ERSSTv5")).strip()
        self.base_ext   = getattr(self, "base_ext", (1971, 2000))
        nome_teste = self.NOME_TESTE or "PERSONALIZADO"
        base_str = self._format_baseline(self.base_ext)
        if base_str:
            message = f"TESTE Personalizado: {self._slug(nome_teste)} | Base climatológica {base_str}"
            print(format_log("INFO", message=message))

        # -------------------- Carrega série --------------------
        s_ssta = self._load_input_sst_series()
        if s_ssta is None or s_ssta.empty:
            raise RuntimeError(_cfg_message(
                f"Anomalia de TSM vazia no modo TESTE para a fonte {self.fonte_nome}. "
                "Possível erro de opção no arquivo de configuração."
            ))


        # normaliza índice sempre
        s_ssta = self._normalize_monthly_index(s_ssta)

        # -------------------- Datas do config (ano-mês) --------------------
        inicio_str = self.cfg.get("AMO_TESTE_INICIO", "1854-01")
        final_str  = self.cfg.get("AMO_TESTE_FINAL", "2023-01")

        # converte para Timestamp (primeiro dia do mês)
        inicio = pd.Period(inicio_str, freq="M").to_timestamp(how="S")
        final  = pd.Period(final_str,  freq="M").to_timestamp(how="S")

        # --- recorte temporal
        s_ssta = s_ssta[(s_ssta.index >= inicio) & (s_ssta.index <= final)]

        if s_ssta.empty:
            raise RuntimeError(_cfg_message(
                f"Série de anomalia vazia após aplicar intervalo {inicio_str} → {final_str}. "
                "Verifique se a fonte selecionada possui dados para este período."
            ))

        efetivo_ini = s_ssta.index.min()
        efetivo_fim = s_ssta.index.max()
        if efetivo_ini is not None and pd.notna(efetivo_ini) and efetivo_ini > inicio:
            print(format_log(
                "ATENCAO",
                message=(
                    f"Série selecionada inicia em {efetivo_ini:%Y-%m} e "
                    f"valor solicitado no config foi {inicio:%Y-%m}. "
                    "Ajuste o intervalo se necessário."
                )
            ))
        if efetivo_fim is not None and pd.notna(efetivo_fim) and efetivo_fim < final:
            print(format_log(
                "ATENCAO",
                message=(
                    f"Série selecionada termina em {efetivo_fim:%Y-%m} e "
                    f"valor solicitado no config foi {final:%Y-%m}. "
                    "Ajuste o intervalo se necessário."
                )
            ))

        # --- remoção global opcional
        if self.remove_global:
            s_global = self._calc_global_mean(base=self.base_ext)
            if not s_global.empty:
                s_global = s_global.reindex(s_ssta.index).interpolate().ffill().bfill()
                s_ssta = s_ssta - s_global
                self._debug_series_sample("Remoção global (anomalia 60°S–60°N) aplicada", s_global)
            else:
                print(format_log("ATENCAO", message="Série global vazia → remoção global não aplicada."))
        else:
            s_global = pd.Series(dtype=float)

        # --- remoção de tendência opcional
        if self.remove_trend:
            amo_uns = self._detrend_pd(s_ssta)
            amo_uns.name = "AMO_tend.rem"
            self._debug_trend_info("Remoção de tendência aplicada", s_ssta)
        else:
            amo_uns = s_ssta.copy()
            amo_uns.name = "AMO_bruto"

        # --- série suavizada (se pedido)
        if suaviza:
            valid_count = int(amo_uns.dropna().shape[0])
            if win > valid_count:
                print(format_log(
                    "ATENCAO",
                    message=(
                        "Janela de suavização solicitada excede a quantidade de meses válidos "
                        f"({win} > {valid_count}). A série suavizada ficará vazia para o intervalo selecionado."
                    )
                ))
            amo_smo = amo_uns.rolling(win, center=True).mean()
            amo_smo = amo_smo[(amo_smo.index >= inicio) & (amo_smo.index <= final)].dropna()
        else:
            amo_smo = pd.Series(dtype=float)

        fonte_tag = self._fonte_tag()

        # ==================== LOG ====================
        if self.modo == "TESTE" and not self.TESTE_VALIDACAO_COMPLETA:
            print(format_log(
                "INFO",
                message=f"Opções de personalização → Remoção de tendência = {self.remove_trend}, Remoção global = {self.remove_global}"
            ))

        # -------------------- Salvamentos --------------------
        if amo_uns.empty:
            raise ValueError(_cfg_message(f"Série vazia ao calcular AMO {fonte_tag} no modo TESTE não suavizado. Verifique janelas e datas de suavização."))

        print(format_log("INFO", message=f"Índice AMO modo TESTE {fonte_tag} calculado."))

        # Se SUAVIZACAO = SIM, salva também a suavizada
        if suaviza and not amo_smo.empty:
            print(format_log("INFO", message=f"Índice AMO modo TESTE ({fonte_tag}) suavizada calculado."))


        # -------------------- Plots --------------------
        base_str = f"{self.base_ext[0]}-{self.base_ext[1]}"
        trend_str = "com remoção de tendência" if self.remove_trend else "sem remoção de tendência"
        global_str = "com remoção global" if self.remove_global else "sem remoção global"

        # não suavizado
        self._plot_amo(
            pd.DataFrame({"amo_custom": amo_uns}),
            "amo_custom",
            f"Índice AMO | Calculado com a TSM {fonte_tag} | Sem Suavização | "
            f"Base Climatológica {base_str} | "
            f"{trend_str} | {global_str}",
            self.OUT_DIR_figs / f"AMO_serie.temporal_{fonte_tag}_{self._slug(nome_teste)}_{self.SUF_EXEC}.png",
            smooth_win=0
        )

        # suavizado
        if suaviza and not amo_smo.empty:
            self._plot_amo(
                pd.DataFrame({"amo_custom": amo_smo}),
                "amo_custom",
                f"Índice AMO | Calculado com a TSM {fonte_tag} | Suavização {win} meses | "
                f"Base Climatológica {base_str} | "
                f"{trend_str} | {global_str}",
                self.OUT_DIR_figs / f"AMO_serie.temporal_{fonte_tag}_{self._slug(nome_teste)}_suav_{self.SUF_EXEC}.png",
                smooth_win=0
            )

        # -------------------- Métricas --------------------
        try:
            metrics_rows = []
            if self.want_ersst:
                # compara com NCEI
                ncei_s = self._read_ncei_amo()
                if not ncei_s.empty:
                    df_ref  = pd.DataFrame({"ncei_amo": ncei_s})
                    df_test = pd.DataFrame({"amo_test": amo_uns})
                    df_ref.index  = df_ref.index.to_period("M").to_timestamp(how="S")
                    df_test.index = df_test.index.to_period("M").to_timestamp(how="S")
                    st = self._run_metrics(
                        df_test, df_ref,
                        "amo_test", "ncei_amo",
                        f"AMO_{fonte_tag}_TESTE_vs_NCEI",
                        exp_name=f"{fonte_tag}_TESTE",
                        fonte=fonte_tag,
                        baseline=f"{self.base_ext[0]}-{self.base_ext[1]}",
                        save=False
                    )
                    serie_cmp = df_test.join(df_ref, how="inner").rename(
                        columns={
                            "amo_test": "AMO_CALC_bruto",
                            "ncei_amo": "AMO_NCEI",
                        }
                    )
                    serie_cmp = serie_cmp.copy()
                    serie_cmp.index = pd.to_datetime(serie_cmp.index).to_period("M").to_timestamp(how="S")
                    serie_cmp.index.name = "data"
                    serie_cmp = serie_cmp.reset_index()
                    serie_cmp["data"] = pd.to_datetime(serie_cmp["data"]).dt.strftime("%Y-%m")
                    out_cmp = self.OUT_DIR_tables / f"AMO_{fonte_tag}vsNCEI_{self.SUF_EXEC}.csv"
                    serie_cmp.to_csv(out_cmp, index=False, float_format="%.3f")
                    print(format_log("SALVO", item="Série comparativa AMO vs NCEI →", destino=str(out_cmp)))
                    st = st.copy()
                    st["serie"] = "nao_suavizada"
                    metrics_rows.append(st)

                    if suaviza and not amo_smo.empty:
                        df_test_smo = pd.DataFrame({"amo_test": amo_smo})
                        df_test_smo.index = df_test_smo.index.to_period("M").to_timestamp(how="S")
                        st_smo = self._run_metrics(
                            df_test_smo, df_ref,
                            "amo_test", "ncei_amo",
                            f"AMO_{fonte_tag}_TESTE_vs_NCEI_suav",
                            exp_name=f"{fonte_tag}_TESTE_SUAVIZADA",
                            fonte=fonte_tag,
                            baseline=f"{self.base_ext[0]}-{self.base_ext[1]}",
                            save=False
                        )
                        serie_cmp_smo = df_test_smo.join(df_ref, how="inner").rename(
                            columns={
                                "amo_test": "AMO_CALC_suavizado",
                                "ncei_amo": "AMO_NCEI",
                            }
                        )
                        serie_cmp_smo = serie_cmp_smo.copy()
                        serie_cmp_smo.index = pd.to_datetime(serie_cmp_smo.index).to_period("M").to_timestamp(how="S")
                        serie_cmp_smo.index.name = "data"
                        serie_cmp_smo = serie_cmp_smo.reset_index()
                        serie_cmp_smo["data"] = pd.to_datetime(serie_cmp_smo["data"]).dt.strftime("%Y-%m")
                        out_cmp_smo = self.OUT_DIR_tables / f"AMO_{fonte_tag}vsNCEI_suavizado_{self.SUF_EXEC}.csv"
                        serie_cmp_smo.to_csv(out_cmp_smo, index=False, float_format="%.3f")
                        print(format_log("SALVO", item="Série comparativa AMO vs NCEI (suavizada) →", destino=str(out_cmp_smo)))
                        st_smo = st_smo.copy()
                        st_smo["serie"] = f"suavizada_{win}"
                        metrics_rows.append(st_smo)

                    if metrics_rows:
                        metrics_df = pd.DataFrame(metrics_rows)
                        cols = ["serie"] + self.METRICS_COLUMNS
                        metrics_df = metrics_df[[c for c in cols if c in metrics_df.columns] + [c for c in metrics_df.columns if c not in cols]]
                        metrics_path = self.OUT_DIR_valida / f"AMO_metricas_estatisticas_{self._slug(nome_teste)}_{self.SUF_EXEC}.csv"
                        metrics_df.to_csv(metrics_path, index=False, float_format="%.3f")
                        print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas do AMO no modo TESTE com TSM {fonte_tag} →", destino=str(metrics_path)))
            elif self.want_kaplan:
                # compara com PSL
                try:
                    psl_uns_s = self._read_psl_standard(self.URL_PSL_KAP_UNS)
                    df_ref  = pd.DataFrame({"psl_amo": psl_uns_s})
                    df_test = pd.DataFrame({"amo_test": amo_uns})
                    df_ref.index  = df_ref.index.to_period("M").to_timestamp(how="S")
                    df_test.index = df_test.index.to_period("M").to_timestamp(how="S")
                    st = self._run_metrics(
                        df_test, df_ref,
                        "amo_test", "psl_amo",
                        f"AMO_{fonte_tag}_TESTE_vs_PSL",
                        exp_name=f"{fonte_tag}_TESTE",
                        fonte=fonte_tag,
                        baseline="1951-1980",
                        save=False
                    )
                    serie_cmp = df_test.join(df_ref, how="inner").rename(
                        columns={
                            "amo_test": "AMO_CALC_bruto",
                            "psl_amo": "AMO_PSL",
                        }
                    )
                    serie_cmp = serie_cmp.copy()
                    serie_cmp.index = pd.to_datetime(serie_cmp.index).to_period("M").to_timestamp(how="S")
                    serie_cmp.index.name = "data"
                    serie_cmp = serie_cmp.reset_index()
                    serie_cmp["data"] = pd.to_datetime(serie_cmp["data"]).dt.strftime("%Y-%m")
                    out_cmp = self.OUT_DIR_tables / f"AMO_{fonte_tag}vsPSL_{self.SUF_EXEC}.csv"
                    serie_cmp.to_csv(out_cmp, index=False, float_format="%.3f")
                    print(format_log("SALVO", item="Série comparativa AMO vs PSL →", destino=str(out_cmp)))
                    st = st.copy()
                    st["serie"] = "nao_suavizada"
                    metrics_rows.append(st)

                    if suaviza and not amo_smo.empty:
                        df_test_smo = pd.DataFrame({"amo_test": amo_smo})
                        df_test_smo.index = df_test_smo.index.to_period("M").to_timestamp(how="S")
                        st_smo = self._run_metrics(
                            df_test_smo, df_ref,
                            "amo_test", "psl_amo",
                            f"AMO_{fonte_tag}_TESTE_vs_PSL_suav",
                            exp_name=f"{fonte_tag}_TESTE_SUAVIZADA",
                            fonte=fonte_tag,
                            baseline="1951-1980",
                            save=False
                        )
                        serie_cmp_smo = df_test_smo.join(df_ref, how="inner").rename(
                            columns={
                                "amo_test": "AMO_CALC_suavizado",
                                "psl_amo": "AMO_PSL",
                            }
                        )
                        serie_cmp_smo = serie_cmp_smo.copy()
                        serie_cmp_smo.index = pd.to_datetime(serie_cmp_smo.index).to_period("M").to_timestamp(how="S")
                        serie_cmp_smo.index.name = "data"
                        serie_cmp_smo = serie_cmp_smo.reset_index()
                        serie_cmp_smo["data"] = pd.to_datetime(serie_cmp_smo["data"]).dt.strftime("%Y-%m")
                        out_cmp_smo = self.OUT_DIR_tables / f"AMO_{fonte_tag}vsPSL_suavizado_{self.SUF_EXEC}.csv"
                        serie_cmp_smo.to_csv(out_cmp_smo, index=False, float_format="%.3f")
                        print(format_log("SALVO", item="Série comparativa AMO vs PSL (suavizada) →", destino=str(out_cmp_smo)))
                        st_smo = st_smo.copy()
                        st_smo["serie"] = f"suavizada_{win}"
                        metrics_rows.append(st_smo)

                    if metrics_rows:
                        metrics_df = pd.DataFrame(metrics_rows)
                        cols = [
                            "serie", "experimento", "fonte", "baseline", "data_inicio", "data_fim",
                            "n_registros", "rmse", "mae", "bias", "corr", "r2",
                            "slope", "intercept", "desv_pad_erro"
                        ]
                        metrics_df = metrics_df[[c for c in cols if c in metrics_df.columns] + [c for c in metrics_df.columns if c not in cols]]
                        metrics_path = self.OUT_DIR_valida / f"AMO_metricas_estatisticas_{fonte_tag}_{self._slug(nome_teste)}_{self.SUF_EXEC}.csv"
                        metrics_df.to_csv(metrics_path, index=False, float_format="%.3f")
                        print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas do AMO no modo TESTE {fonte_tag} →", destino=str(metrics_path)))

                except Exception as e:
                    print(format_log("ATENCAO", message=f"Não foi possível calcular métricas Kaplan TESTE: {e}"))
        except Exception as e:
            print(format_log("ERRO", message=f"Falha no cálculo de métricas TESTE {fonte_tag}: {e}"))


        # plot da região escolhida (apenas no TESTE customizado)
        self._plot_regiao_amo_bbox()


    def _run_externo(self):
        nome_ext = str(self.cfg.get("AMO_EXTERNO_NOME_TSM", self.cfg.get("AMO_EXTERNO_NOME", "EXTERNO"))).strip()

        caminho_cfg = str(self.cfg.get("AMO_EXTERNO_CAMINHO_TSM", self.cfg.get("AMO_EXTERNO_CAMINHO", ""))).strip()
        caminho  = Path(caminho_cfg).expanduser()
        base_str = str(self.cfg.get("AMO_EXTERNO_BASE_CLIMA", "1971-01:2000-12")).strip()
        suaviza  = self._as_bool_ext(self.cfg.get("AMO_EXTERNO_SUAVIZACAO", "NAO"), label="AMO_EXTERNO_SUAVIZACAO")
        win      = int(self._as_float(self.cfg.get("AMO_EXTERNO_JANELA_SUAVIZACAO", 121)))
        rem_trend  = self._as_bool_ext(self.cfg.get("AMO_EXTERNO_REMOCAO_TENDENCIA", "NAO"), label="AMO_EXTERNO_REMOCAO_TENDENCIA")
        rem_global = self._as_bool_ext(self.cfg.get("AMO_EXTERNO_REMOCAO_GLOBAL", "NAO"), label="AMO_EXTERNO_REMOCAO_GLOBAL")
        caminho_global_cfg = str(self.cfg.get("AMO_EXTERNO_CAMINHO_TSM_GLOBAL", "")).strip()
        caminho_global = Path(caminho_global_cfg).expanduser() if caminho_global_cfg else None

        if not caminho_cfg:
            raise RuntimeError(_cfg_message("AMO_EXTERNO_CAMINHO_TSM não definido."))
        if not caminho.exists():
            raise RuntimeError(_cfg_message(f"Caminho para o arquivo CSV EXTERNO não encontrado: {caminho}"))

        # ================== Ajuste nos diretórios ==================
        # Antes de criar, eliminamos a pasta EXTERNO/ antiga se existir
        old_dir = OUTPUT_ROOT / "AMO" / "EXTERNO"
        if old_dir.exists():
            import shutil
            shutil.rmtree(old_dir)
            #print(f"[INFO] Pasta antiga removida: {old_dir}")

        # Pasta correta: AMO/EXTERNO_{nome_ext}
        ext_tag = f"EXTERNO_{self._slug(nome_ext)}"
        self.OUT_DIR        = OUTPUT_ROOT / "AMO" / ext_tag
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR_tables = self.OUT_DIR
        self.OUT_DIR_figs   = self.OUT_DIR
        self.OUT_DIR_valid  = self.OUT_DIR
        self.OUT_DIR_valida = self.OUT_DIR
        print(format_log("INFO", message=f"Diretórios configurados para modo EXTERNO: {self.OUT_DIR}"))


        # -------------------- Carrega CSV externo --------------------
        df = pd.read_csv(caminho, sep=";", engine="python")
        if not {"ano", "mes", "tsm"}.issubset(df.columns):
            raise RuntimeError(_cfg_message("Arquivo CSV EXTERNO inválido. Formato esperado para as colunas: ano;mes;tsm"))

        df["time"] = pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=1))
        df = df.set_index("time").sort_index()
        sst = df["tsm"].astype(float)

        # -------------------- Calcula anomalias (climatologia da base) --------------------
        base_years = self._parse_base_years(base_str, default=None)
        if base_years is None:
            y0, y1 = 1971, 2000
            print(format_log(
                "ATENCAO",
                message=f"AMO_EXTERNO_BASE_CLIMA inválido ('{base_str}'); usando padrão 1971-01:2000-12."
            ))
        else:
            y0, y1 = base_years
        base_fmt = self._format_baseline((y0, y1))
        if base_fmt:
            ext_slug = self._slug(nome_ext) or "externo"
            message = f"Baseline EXTERNO ({ext_slug}): {base_fmt}"
            # print(format_log("INFO", message=message))

        # recorte da base climatológica
        sst_base = sst[(sst.index.year >= y0) & (sst.index.year <= y1)]

        # climatologia mensal
        clima = sst_base.groupby(sst_base.index.month).mean()

        # anomalias
        ssta = sst - sst.index.month.map(clima)


        efetivo_ini = sst.index.min()
        efetivo_fim = sst.index.max()
        if efetivo_ini is not None and pd.notna(efetivo_ini) and efetivo_ini.year > y0:
            print(format_log(
                "ATENCAO",
                message=(
                    f"Série externa inicia em {efetivo_ini:%Y-%m}, acima do início da base climatológica ({y0}). "
                    "A climatologia considera apenas os anos disponíveis."
                )
            ))
        if efetivo_fim is not None and pd.notna(efetivo_fim) and efetivo_fim.year < y1:
            print(format_log(
                "ATENCAO",
                message=(
                    f"Série externa termina em {efetivo_fim:%Y-%m}, antes do fim da base climatológica ({y1}). "
                    "Considerando para a base apenas os anos disponíveis."
                )
            ))

        # -------------------- Remoção opcional de global --------------------
        s_global = pd.Series(dtype=float)
        if rem_global:
            try:
                if caminho_global and caminho_global.exists():
                    df_glb = pd.read_csv(caminho_global, sep=";", engine="python")
                    if not {"ano", "mes", "tsm"}.issubset(df_glb.columns):
                        raise RuntimeError(_cfg_message("Arquivo global externo inválido. Esperado colunas: ano;mes;tsm"))
                    df_glb["time"] = pd.to_datetime(dict(year=df_glb["ano"], month=df_glb["mes"], day=1))
                    df_glb = df_glb.set_index("time").sort_index()
                    sst_global = df_glb["tsm"].astype(float)
                    base_mask = (sst_global.index.year >= y0) & (sst_global.index.year <= y1)
                    if not base_mask.any():
                        raise RuntimeError(_cfg_message("Base climatológica fora do intervalo do arquivo global externo."))
                    clima_global = sst_global[base_mask].groupby(sst_global[base_mask].index.month).mean()
                    s_global = sst_global - sst_global.index.month.map(clima_global)
                    print(format_log("INFO", message=f"Remoção global aplicada usando arquivo externo: {caminho_global}"))
                else:
                    if caminho_global_cfg and not (caminho_global and caminho_global.exists()):
                        print(format_log("ATENCAO", message=f"Arquivo global externo não encontrado ({caminho_global}); usando ERSSTv5."))
                    s_global = self._calc_global_mean(base=(y0, y1))  # usa ERSSTv5 com mesma base
                    if not s_global.empty:
                        print(format_log("INFO", message=f"Remoção global aplicada com ERSSTv5."))
                if not s_global.empty:
                    s_global = s_global.reindex(ssta.index).interpolate().ffill().bfill()
                    ssta = ssta - s_global
                    self._debug_series_sample(f"EXTERNO remoção global ({nome_ext})", s_global)
                else:
                    print(format_log("ATENCAO", message=f"Série global vazia → Remoção global não aplicada."))

            except Exception as e:
                print(format_log("ERRO", message=f"Falha na remoção global: {e}"))

        # -------------------- Remoção opcional de tendência --------------------
        if rem_trend:
            amo_uns = self._detrend_pd(ssta)
            amo_uns.name = "AMO_tend.rem"
            self._debug_trend_info(f"EXTERNO remoção de tendência ({nome_ext})", ssta)
            self._debug_series_sample(f"EXTERNO tendência removida ({nome_ext})", amo_uns)
        else:
            amo_uns = ssta.copy()
            amo_uns.name = "AMO_bruto"

        # -------------------- Suavização opcional --------------------
        if suaviza:
            amo_smo = amo_uns.rolling(win, center=True).mean().dropna()
        else:
            amo_smo = pd.Series(dtype=float)

        fonte_tag = self._slug(nome_ext)

        # -------------------- Salvamentos --------------------
        if amo_uns.empty:
            raise ValueError(format_log("ERRO", message=f"Série externa vazia após processamento para {nome_ext}."))
        print(format_log("INFO", message=f"Índice AMO modo EXTERNO {fonte_tag} calculado."))


        if not amo_smo.empty:
            print(format_log("INFO", message=f"Índice AMO modo EXTERNO {fonte_tag} suavizada calculada."))

        # -------------------- Plots --------------------
        base_label = f"{y0}-{y1}"
        trend_str = "com remoção de tendência" if rem_trend else "sem remoção de tendência"
        global_str = "com remoção global" if rem_global else "sem remoção global"

        # não suavizado
        self._plot_amo(
            pd.DataFrame({"amo_externo": amo_uns}),
            "amo_externo",
            f"Índice AMO | Calculado com TSM {nome_ext} | Sem Suavização | "
            f"Base {base_label} | {trend_str} | {global_str}",
            self.OUT_DIR_figs / f"AMO_serie.temporal_{fonte_tag}_EXTERNO_{self.SUF_EXEC}.png",
            smooth_win=0
        )
        # suavizado
        if suaviza and not amo_smo.empty:
            self._plot_amo(
                pd.DataFrame({"amo_externo": amo_smo}),
                "amo_externo",
                f"Índice AMO | Calculado com TSM {nome_ext} | Suavização {win} meses | "
                f"Base {base_label} | {trend_str} | {global_str}",
                self.OUT_DIR_figs / f"AMO_serie.temporal_{fonte_tag}_EXTERNO_suav_{self.SUF_EXEC}.png",
                smooth_win=0
            )

        # -------------------- Métricas (opcional: compara com NCEI) --------------------
        try:
            ncei_s = self._read_ncei_amo()
            if not ncei_s.empty:
                df_ref  = pd.DataFrame({"AMO_NCEI": ncei_s})
                df_ref.index  = df_ref.index.to_period("M").to_timestamp(how="S")

                metrics_rows = []

                df_test = pd.DataFrame({"amo_test": amo_uns})
                df_test.index = df_test.index.to_period("M").to_timestamp(how="S")

                # Série comparativa (não suavizada)
                serie_cmp = df_test.join(df_ref, how="inner").rename(columns={"amo_test": "AMO_CALC"})
                if not serie_cmp.empty:
                    serie_cmp.index.name = "data"
                    serie_cmp = serie_cmp.reset_index()
                    serie_cmp["data"] = pd.to_datetime(serie_cmp["data"]).dt.strftime("%Y-%m")
                out_cmp = self.OUT_DIR_tables / f"AMO_{fonte_tag}_EXTERNO_vsNCEI_{self.SUF_EXEC}.csv"
                serie_cmp.to_csv(out_cmp, index=False, float_format="%.3f")
                print(format_log("SALVO", item="Série comparativa AMO EXTERNO vs NCEI →", destino=str(out_cmp)))

                st = self._run_metrics(
                    df_test, df_ref,
                    "amo_test", "AMO_NCEI",
                    f"AMO_{fonte_tag}_EXTERNO_vsNCEI",
                    exp_name=f"EXTERNO_{nome_ext}",
                    fonte=nome_ext,
                    baseline=base_label,
                    save=False
                )
                st = st.copy()
                st["serie"] = "nao_suavizada"
                metrics_rows.append(st)

                if suaviza and not amo_smo.empty:
                    df_test_smo = pd.DataFrame({"amo_test": amo_smo})
                    df_test_smo.index = df_test_smo.index.to_period("M").to_timestamp(how="S")
                    serie_cmp_smo = df_test_smo.join(df_ref, how="inner").rename(
                        columns={"amo_test": "AMO_CALC_suav"}
                    )
                    if not serie_cmp_smo.empty:
                        serie_cmp_smo.index.name = "data"
                        serie_cmp_smo = serie_cmp_smo.reset_index()
                        serie_cmp_smo["data"] = pd.to_datetime(serie_cmp_smo["data"]).dt.strftime("%Y-%m")
                        out_cmp_smo = self.OUT_DIR_tables / f"AMO_{fonte_tag}_EXTERNO_vsNCEI_suav_{self.SUF_EXEC}.csv"
                        cols_order = ["data", "AMO_CALC_suav", "AMO_NCEI"]
                        serie_cmp_smo = serie_cmp_smo[cols_order]
                        serie_cmp_smo.to_csv(out_cmp_smo, index=False, float_format="%.3f")
                        print(format_log("SALVO", item="Série comparativa AMO EXTERNO vs NCEI (suavizada) →", destino=str(out_cmp_smo)))

                    st_smo = self._run_metrics(
                        df_test_smo, df_ref,
                        "amo_test", "AMO_NCEI",
                        f"AMO_{fonte_tag}_EXTERNO_vsNCEI_suav",
                        exp_name=f"EXTERNO_{nome_ext}_SUAVIZADA",
                        fonte=nome_ext,
                        baseline=base_label,
                        save=False
                    )
                    st_smo = st_smo.copy()
                    st_smo["serie"] = f"suavizada_{win}"
                    metrics_rows.append(st_smo)

                if metrics_rows:
                    metrics_df = pd.DataFrame(metrics_rows)
                    cols = ["serie"] + self.METRICS_COLUMNS
                    metrics_df = metrics_df[[c for c in cols if c in metrics_df.columns] + [c for c in metrics_df.columns if c not in cols]]
                    metrics_name = f"AMO_metricas_estatisticas_{self.SUF_EXEC}.csv"
                    metrics_path = self.OUT_DIR_valid / metrics_name
                    metrics_df.to_csv(metrics_path, index=False, float_format="%.3f")
                    print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas do AMO modo EXTERNO {nome_ext} →", destino=str(metrics_path)))

            else:
                print(format_log("ATENCAO", message=f"[INFO] Sem dados NCEI disponíveis para comparar no modo EXTERNO {nome_ext}."))
        except Exception as e:
            print(format_log("ERRO", message=f"Falha no cálculo de métricas EXTERNO {nome_ext}: {e}"))


    def _calc_global_mean(self, base: tuple[int, int] | None = None) -> pd.Series:
        """
        Calcula a média global de TSM (ERSSTv5) e devolve como série mensal
        de anomalias (YYYY-MM-01), respeitando a base climatológica informada.
        """
        base_years = base or getattr(self, "base_ext", (1971, 2000))
        try:
            y0, y1 = int(base_years[0]), int(base_years[1])
        except Exception:
            y0, y1 = 1971, 2000

        ds = self.ds_ersst
        opened_here = False
        if ds is None:
            nc_path = getattr(self, "nc_ersst", self.DATA_DIR / "ersst_v5.nc")
            try:
                ds = xr.open_dataset(nc_path)
                opened_here = True
            except Exception as e:
                print(format_log("ERRO", message=f"Falha ao abrir ERSSTv5 ({nc_path}) para média global: {e}"))
                return pd.Series(dtype=float)

        try:
            sst = ds["sst"]
            dims = list(sst.dims)
            lon_name = next((d for d in dims if d.lower().startswith("lon")), dims[-1])
            lat_name = next((d for d in dims if d.lower().startswith("lat")), dims[-2] if len(dims) >= 2 else dims[-1])
            sst = sst.assign_coords({lon_name: self._normalize_lon(sst[lon_name])}).sortby(lon_name).sortby(lat_name)

            # média global ponderada
            global_total = self._area_weighted_mean(sst, lon_name, lat_name).to_series()
            global_total.index = global_total.index.to_period("M").to_timestamp(how="S")
            global_total = global_total.astype(float)

            global_anom = self._anom_from_total(global_total, (y0, y1))
            return global_anom
        except Exception as e:
            print(format_log("ERRO", message=f"Falha ao calcular média global: {e}"))

            return pd.Series(dtype=float)
        finally:
            if opened_here:
                ds.close()

    
    def _plot_regiao_amo_bbox(self, suffix=""):
        # normaliza lat/lon para exibição

        nome_teste = self.NOME_TESTE or "PERSONALIZADO"

        lat_min, lat_max = sorted([float(self.lat_min), float(self.lat_max)])
        lon_min, lon_max = float(self.lon_min), float(self.lon_max)

        def to_pm180(v: float) -> float:
            return ((v + 180.0) % 360.0) - 180.0

        a = to_pm180(lon_min)
        b = to_pm180(lon_max)

        try:
            from matplotlib.patches import Rectangle
            import cartopy.crs as ccrs
            import cartopy.feature as cfeature

            proj = ccrs.PlateCarree()
            fig = plt.figure(figsize=(9, 4.5))
            ax = plt.axes(projection=proj)
            ax.set_global()
            ax.coastlines(linewidth=0.6)
            ax.add_feature(cfeature.LAND, facecolor="0.92", edgecolor="none", zorder=0)
            ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5, linestyle="--")

            rects = []
            if a <= b:
                rects.append((a, lat_min, b - a, lat_max - lat_min))
            else:
                rects.append((a, lat_min, 180 - a, lat_max - lat_min))
                rects.append((-180, lat_min, b - (-180), lat_max - lat_min))

            for x0, y0, w, h in rects:
                ax.add_patch(Rectangle((x0, y0), w, h, linewidth=1.6,
                                    edgecolor="tab:red", facecolor="none",
                                    transform=ccrs.PlateCarree(), zorder=5))

            ax.set_title(
                f"Região de recorte AMO | lat: {lat_min:g}..{lat_max:g}, "
                f"lon: {lon_min:g}..{lon_max:g}"
            )
        except Exception:
            # fallback simples (sem Cartopy)
            from matplotlib.patches import Rectangle
            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.set_xlim(-180, 180); ax.set_ylim(-90, 90)
            ax.grid(True, linestyle="--", alpha=0.4)
            ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

            rects = []
            if a <= b:
                rects.append((a, lat_min, b - a, lat_max - lat_min))
            else:
                rects.append((a, lat_min, 180 - a, lat_max - lat_min))
                rects.append((-180, lat_min, b - (-180), lat_max - lat_min))
            for x0, y0, w, h in rects:
                ax.add_patch(Rectangle((x0, y0), w, h, linewidth=1.6,
                                    edgecolor="tab:red", facecolor="none"))

            ax.set_title(
                f"Região de recorte AMO {self._slug(getattr(self, 'NOME_TESTE',''))} | "
                f"lat: {lat_min:g}..{lat_max:g}, lon: {lon_min:g}..{lon_max:g}\n"
                f"(visualização simplificada)"
            )

        out = self.OUT_DIR_figs / f"AMO_regiao_{self._slug(nome_teste)}_{self.SUF_EXEC}{suffix}.png"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(format_log("SALVO", item="Região Experimental do AMO salvo →", destino=str(out)))
