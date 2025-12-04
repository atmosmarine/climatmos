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
from .atm_tools import validate_config_MEI
from src.logging import format_log

def _cfg_message(message: str) -> str:
    return format_log("ERRO_CONF", message=message)
    
class MEI:
    def __init__(self, cfg):
        from pathlib import Path
        import logging

        self.CONFIG = validate_config_MEI(cfg)
        self.mode = self.CONFIG.get("modo", "REFERENCIA")
        self.MODO = self.mode
        if self.mode == "TESTE":
            self.NOME_TESTE = self.CONFIG.get("nome") or self.CONFIG.get("MEI_TESTE_NOME", "")  
        elif self.mode == "EXTERNO":
            self.NOME_SST = self.CONFIG.get("nome") or self.CONFIG.get("MEI_EXTERNO_NOME", "")

        self.SUF_EXEC = _dt.datetime.now().strftime("%Y%m")

        self.ROOT_DIR = Path(__file__).resolve().parent.parent
        self.DATA_DIR = self.ROOT_DIR / "data"
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR = self.DATA_DIR / "cache/MEI"
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self.PATH_LOCAL = self.ROOT_DIR
        self.PATH_DOWNLOADS = self.DATA_DIR / "ICOADS"
        self.PATH_DOWNLOADS.mkdir(parents=True, exist_ok=True)

        legacy_psl_dir = self.ROOT_DIR / "PSL_NOAA"
        if legacy_psl_dir.exists() and legacy_psl_dir.is_dir():
            for item in legacy_psl_dir.glob("*"):
                dest = self.PATH_DOWNLOADS / item.name
                if not dest.exists():
                    try:
                        import shutil
                        shutil.move(str(item), str(dest))
                    except Exception as exc:
                        print(format_log(f"Falha ao migrar {item} para {dest}: {exc}"))
            try:
                legacy_psl_dir.rmdir()
            except OSError:
                pass

        # Criar subpastas
        base_results = Path(self.CONFIG["path_results"]).expanduser()
        def _slugify_text(value: str | None) -> str:
            import re
            import unicodedata
            if value is None:
                return "PADRAO"
            text = str(value)
            if not text:
                return "PADRAO"
            norm = unicodedata.normalize("NFKD", text)
            ascii_text = norm.encode("ascii", "ignore").decode("ascii")
            if not ascii_text:
                ascii_text = text
            slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")
            return slug or "PADRAO"

        if self.mode == "REFERENCIA":
            mode_segment = "REFERENCIA"
        elif self.mode == "TESTE":
            nome = cfg.get("MEI_TESTE_NOME") or self.CONFIG.get("nome") or "PADRAO"
            mode_segment = f"TESTE_{_slugify_text(nome)}"
        elif self.mode == "EXTERNO":
            nome = cfg.get("MEI_EXTERNO_NOME") or self.CONFIG.get("nome") or "PADRAO"
            mode_segment = f"EXTERNO_{_slugify_text(nome)}"
        else:
            mode_segment = _slugify_text(self.mode)

        self.RESULTADOS_DIR = base_results / mode_segment
        self.CONFIG["path_results"] = str(self.RESULTADOS_DIR)
        self.PLOTS_DIR = self.RESULTADOS_DIR 
        self.VALIDACAO_DIR = self.RESULTADOS_DIR 
        self.CSV_DIR = self.RESULTADOS_DIR 

        for pasta in [self.PLOTS_DIR, self.VALIDACAO_DIR, self.CSV_DIR]:
            pasta.mkdir(parents=True, exist_ok=True)

        # Atualizar paths no CONFIG para facilitar
        self.CONFIG["plots_dir"] = str(self.PLOTS_DIR) + "/"
        validacao_path = str(self.VALIDACAO_DIR) + "/"
        self.CONFIG["validacao_dir"] = validacao_path
        self.CONFIG["tabelas_dir"] = validacao_path
        self.CONFIG["csv_dir"] = str(self.CSV_DIR) + "/"
        self.CONFIG["cache_dir"] = str(self.CACHE_DIR)
        self._refresh_output_paths()

        pass

    def parse_list(val: str) -> list:
        return [x.strip() for x in (val or "").split(",") if x.strip()]

    def _refresh_output_paths(self) -> None:
        """Atualiza caminhos e identificadores baseados no período da série."""
        series_min, series_max = self.CONFIG["base_series"]
        self.base_series_tag = f"{series_min.replace('-', '')}_{series_max.replace('-', '')}"
        self.base_series_suffix = self.SUF_EXEC
        self.PATH_MEI_PLOT = self.PLOTS_DIR / f"MEI_serie-temporal_CALC_{self.base_series_suffix}.png"
        self.PATH_MEI_CSV_COMBINED = self.CSV_DIR / f"MEI_serie-temporal_CALCvsPSL{self.base_series_suffix}.csv"
        self.PATH_MEI_CSV_CALC = self.PATH_MEI_CSV_COMBINED
        self.PATH_MEI_CSV_REF = self.PATH_MEI_CSV_COMBINED
        # self.PATH_MEI_VALIDACAO = self.VALIDACAO_DIR / f"MEI_validacao_{self.base_series_suffix}.txt"
        self.PATH_MEI_CACHE_REF = self.CACHE_DIR / "MEI_REF_cache.csv"
        self.PATH_MEI_METRICAS = self.VALIDACAO_DIR / f"MEI_metricas_estatisticas_{self.base_series_suffix}.csv"
        self.PATH_MEI_METRICAS_BIM = self.VALIDACAO_DIR / f"MEI_metricas_bimensais_{self.base_series_suffix}.csv"
        self.CONFIG["mei_plot_path"] = str(self.PATH_MEI_PLOT)
        self.CONFIG["mei_csv_combined"] = str(self.PATH_MEI_CSV_COMBINED)
        self.CONFIG["mei_csv_calc"] = str(self.PATH_MEI_CSV_CALC)
        self.CONFIG["mei_csv_ref"] = str(self.PATH_MEI_CSV_REF)
        # self.CONFIG["mei_validacao_path"] = str(self.PATH_MEI_VALIDACAO)
        self.CONFIG["mei_cache_ref"] = str(self.PATH_MEI_CACHE_REF)
        self.CONFIG["mei_metricas_path"] = str(self.PATH_MEI_METRICAS)
        self.CONFIG["mei_metricas_bimensais_path"] = str(self.PATH_MEI_METRICAS_BIM)

    def _slug(self, value: str | None) -> str:
        """Gera identificador seguro para uso em nomes de arquivo."""
        if value is None:
            value = ""
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "" for ch in value)
        if not cleaned:
            cleaned = self.mode.lower()
        return cleaned

    def _plot_regiao_mei_bbox(self, suffix: str | None = None) -> None:
        """Plota a região espacial utilizada para o MEI nos modos TESTE/EXTERNO."""
        lat_range = self.CONFIG.get("lat_range") or (-30.0, 30.0)
        lon_range = self.CONFIG.get("lon_range") or (100.0, 290.0)
        lat_min, lat_max = sorted([float(lat_range[0]), float(lat_range[1])])
        lon_min, lon_max = float(lon_range[0]), float(lon_range[1])

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

            rects: list[tuple[float, float, float, float]] = []
            if a <= b:
                rects.append((a, lat_min, b - a, lat_max - lat_min))
            else:
                rects.append((a, lat_min, 180 - a, lat_max - lat_min))
                rects.append((-180, lat_min, b - (-180), lat_max - lat_min))

            for x0, y0, w, h in rects:
                ax.add_patch(
                    Rectangle(
                        (x0, y0),
                        w,
                        h,
                        linewidth=1.6,
                        edgecolor="tab:red",
                        facecolor="none",
                        transform=ccrs.PlateCarree(),
                        zorder=5,
                    )
                )

            ax.set_title(
                f"Região de recorte do MEI | lat: {lat_min:g}..{lat_max:g}, "
                f"lon: {lon_min:g}..{lon_max:g}"
            )
        except Exception:
            from matplotlib.patches import Rectangle

            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.set_xlim(-180, 180)
            ax.set_ylim(-90, 90)
            ax.grid(True, linestyle="--", alpha=0.4)
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")

            rects = []
            if a <= b:
                rects.append((a, lat_min, b - a, lat_max - lat_min))
            else:
                rects.append((a, lat_min, 180 - a, lat_max - lat_min))
                rects.append((-180, lat_min, b - (-180), lat_max - lat_min))
            for x0, y0, w, h in rects:
                ax.add_patch(
                    Rectangle(
                        (x0, y0),
                        w,
                        h,
                        linewidth=1.6,
                        edgecolor="tab:red",
                        facecolor="none",
                    )
                )

            ax.set_title(
                f"Região de recorte MEI {self._slug(self.CONFIG.get('nome') or self.mode)} | "
                f"lat: {lat_min:g}..{lat_max:g}, lon: {lon_min:g}..{lon_max:g}\n"
                f"(visualização simplificada)"
            )

        suffix = suffix or self.base_series_suffix
        nome_base = self.CONFIG.get("nome") or getattr(self, "NOME_TESTE", None) or getattr(self, "NOME_SST", None)
        slug = self._slug(nome_base)
        out = self.PLOTS_DIR / f"MEI_regiao_{slug}_{suffix}.png"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(format_log("SALVO", item="Região espacial do MEI salva em:", destino=f"{out}"))


    def run_psl(self, cfg: dict):
        base_url = cfg.get("psl_base_url")
        vars_list = cfg.get("psl_vars", [])
        print(format_log("DOWNLOAD", target="PSL", dest=base_url, reason=f"Variáveis solicitadas: {vars_list}"))
        self._download_psl(base_url, vars_list)

    def _download_psl(self, base_data: str, variables: list):
        import shutil
        import urllib.request

        self.LIST_VAR = variables

        for var in self.LIST_VAR:
            arquivo_nc = self.PATH_DOWNLOADS / f"{var}.nc"
            base_url = f"{base_data}/{var}.mean.nc"
        
            if not arquivo_nc.exists():
                print(
                    format_log(
                        "DOWNLOAD",
                        target=f"{var}.mean.nc",
                        dest=str(arquivo_nc),
                        reason="Arquivo ausente → iniciando download",
                    )
                )
                tmp_file, _ = urllib.request.urlretrieve(base_url)
                shutil.move(tmp_file, arquivo_nc)
                print(
                    format_log(
                        "DOWNLOAD",
                        target=f"{var}.mean.nc",
                        dest=str(arquivo_nc),
                        reason="Download concluído",
                    )
                )
            else:
                print(format_log("INFO", message=f"Arquivo {var} já existe – pulando download."))
            
    
    def _parse_date(self, s):
        y, m = s.split("-")
        return pd.Timestamp(int(y), int(m), 1).to_pydatetime()

    def _validate_dates(self, source) -> bool:
        import pandas as pd
        import xarray as xr
        from pathlib import Path

        close_ds = False
        if hasattr(source, "dims") and hasattr(source, "coords"):
            ds = source
        elif isinstance(source, (list, tuple)):
            paths = [str(Path(p)) for p in source]
            ds = xr.open_mfdataset(paths, combine="by_coords")
            close_ds = True
        else:
            source_str = str(source)
            if any(sym in source_str for sym in "*?[]"):
                ds = xr.open_mfdataset(source_str, combine="by_coords")
                close_ds = True
            else:
                path_obj = Path(source_str)
                if path_obj.is_dir():
                    ds = xr.open_mfdataset(str(path_obj / "*.nc"), combine="by_coords")
                else:
                    ds = xr.open_mfdataset(str(path_obj), combine="by_coords")
                close_ds = True

        # Verifica se a dimensão ou coordenada é "valid_time" e renomeia para "time"
        if "valid_time" in ds.dims or "valid_time" in ds.coords:
           ds = ds.rename({"valid_time": "time"})

        if "time" not in ds.coords and "time" not in ds.dims:
            if close_ds:
                ds.close()
            raise ValueError("O dataset não possui uma coordenada de tempo reconhecida ('time').")

        time_coord = ds["time"] if "time" in ds.coords else ds.coords["time"]
        if getattr(time_coord, "size", 0) == 0:
            if close_ds:
                ds.close()
            raise ValueError("O dataset externo não possui registros de tempo após o carregamento.")

        tmin = pd.to_datetime(time_coord.min().values).to_pydatetime()
        tmax = pd.to_datetime(time_coord.max().values).to_pydatetime()

        if close_ds:
            ds.close()
       

        clim_start, clim_end = map(self._parse_date, self.CONFIG["base_climatology"])
        series_start, series_end = map(self._parse_date, self.CONFIG["base_series"])

        def _as_month_start(dt_obj):
            return pd.Timestamp(dt_obj).to_period("M").to_timestamp()

        tmin_month = _as_month_start(tmin)
        tmax_month = _as_month_start(tmax)
        clim_start_month = _as_month_start(clim_start)
        clim_end_month = _as_month_start(clim_end)
        series_start_month = _as_month_start(series_start)
        series_end_month = _as_month_start(series_end)

        if self.mode == "EXTERNO":
            updated = False

            adj_clim_start = max(clim_start_month, tmin_month)
            adj_clim_end = min(clim_end_month, tmax_month)
            if adj_clim_start > adj_clim_end:
                raise ValueError(
                    format_log(
                        "ERRO",
                        message=(
                            "Período climatológico solicitado não possui interseção com os dados disponíveis. "
                            f"Série disponível: {tmin_month:%Y-%m} a {tmax_month:%Y-%m}."
                        ),
                    )
                )
            if (adj_clim_start != clim_start_month) or (adj_clim_end != clim_end_month):
                print(
                    format_log(
                        "INFO",
                        message=(
                            "Ajustando período climatológico (modo EXTERNO) para coincidir com os dados disponíveis: "
                            f"{adj_clim_start:%Y-%m} → {adj_clim_end:%Y-%m}."
                        ),
                    )
                )
                clim_start_month, clim_end_month = adj_clim_start, adj_clim_end
                self.CONFIG["base_climatology"] = (
                    clim_start_month.strftime("%Y-%m"),
                    clim_end_month.strftime("%Y-%m"),
                )
                updated = True

            adj_series_start = max(series_start_month, tmin_month)
            adj_series_end = min(series_end_month, tmax_month)
            if adj_series_start >= adj_series_end:
                raise ValueError(
                    format_log(
                        "ERRO",
                        message=(
                            "Período da série solicitado não possui interseção com os dados disponíveis. "
                            f"Série disponível: {tmin_month:%Y-%m} a {tmax_month:%Y-%m}."
                        ),
                    )
                )
            if (adj_series_start != series_start_month) or (adj_series_end != series_end_month):
                print(
                    format_log(
                        "INFO",
                        message=(
                            "Ajustando período da série (modo EXTERNO) para coincidir com os dados disponíveis: "
                            f"{adj_series_start:%Y-%m} → {adj_series_end:%Y-%m}."
                        ),
                    )
                )
                series_start_month, series_end_month = adj_series_start, adj_series_end
                self.CONFIG["base_series"] = (
                    series_start_month.strftime("%Y-%m"),
                    series_end_month.strftime("%Y-%m"),
                )
                updated = True

            if updated:
                self._refresh_output_paths()

            clim_start = clim_start_month.to_pydatetime()
            clim_end = clim_end_month.to_pydatetime()
            series_start = series_start_month.to_pydatetime()
            series_end = series_end_month.to_pydatetime()

        
        if (tmin <= clim_start) and (tmax >= clim_end):
            print(format_log("INFO", message=f"Período climatológico selecionado: de {clim_start:%Y-%m} a {clim_end:%Y-%m} → compatível."))

        else:
            msg1 = format_log("ATENCAO", message=f"Série disponível apenas de {tmin:%Y-%m} a {tmax:%Y-%m}.")
            msg2 = f"Período climatológico selecionado: de {clim_start:%Y-%m} a {clim_end:%Y-%m} → incompatível."

            print(msg1)
            print(format_log("ERRO", message=msg2))

            raise ValueError("Utilize um período válido dentro da climatologia disponível.")

        if (tmin <= series_start) and (tmax >= series_end):
           print(format_log("INFO", message=f"Período da série: de {series_start:%Y-%m} a {series_end:%Y-%m} → compatível."))
        else:
            msg1 = format_log("ATENCAO", message=f"Série disponível apenas de {tmin:%Y-%m} a {tmax:%Y-%m}.")
            msg2 = (f"Período da série solicitado: de {series_start:%Y-%m} a {series_end:%Y-%m} → incompatível.. ")
            
            print(msg1)
            print(format_log("ERRO", message=msg2))

            raise ValueError("Utilize um período válido dentro da série disponível.")
        
        return True

    def _ensure_data(self, CONFIG):
        from pathlib import Path
        import time, subprocess, xarray as xr, pandas as pd

        PATH_LOCAL = Path("..")
        PATH_DOWNLOAD = "ICOADS"
        SEARCH_PATH = list(PATH_LOCAL.rglob(f"{PATH_DOWNLOAD}"))

        PATH_RESULTADOS = Path(self.CONFIG["path_results"])
        PATH_RESULTADOS.mkdir(parents=True, exist_ok=True)
        # print(format_log("INFO", message=f"Diretório de resultados: {PATH_RESULTADOS}"))

#
        if SEARCH_PATH:
            PATH_DIR = SEARCH_PATH[0]
            print(format_log("INFO", message=f"Diretório {PATH_DOWNLOAD} encontrado: {PATH_DIR}"))
            self._validate_dates(PATH_DIR)
        else:
            print(format_log("ATENCAO", message=f"Diretório {PATH_DOWNLOAD} não encontrado."))
            SEARCH_PATH = []

        if not SEARCH_PATH:
            current_dir = Path(__file__).resolve().parent
            download_script = current_dir / "download_psl_noaa.py"  # corrigido typo

            if download_script.exists():
                print(
                    format_log(
                        "DOWNLOAD",
                        target="ICOADS PSL",
                        dest=str(download_script),
                        reason="Script localizado → iniciando execução",
                    )
                )
                start_dl = time.time()
                subprocess.run(["python", str(download_script)], check=True)
                elapsed_dl = time.time() - start_dl
                print(
                    format_log(
                        "DOWNLOAD",
                        target="ICOADS PSL",
                        dest=str(PATH_LOCAL.resolve()),
                        reason=f"Download concluído em {elapsed_dl:.2f} s",
                    )
                )
                SEARCH_PATH = list(PATH_LOCAL.rglob(f"{PATH_DOWNLOAD}"))
                if not SEARCH_PATH or not self._validate_dates(SEARCH_PATH[0]):
                    raise FileNotFoundError("Download não cobriu o período necessário.")
            else:
                raise FileNotFoundError("Script de download ausente.")

        PATH_DIR = SEARCH_PATH[0]
        self.CONFIG["path_data"] = str(PATH_DIR / "*.nc")

    def _load_and_preprocess(self):
        import xarray as xr
        import numpy as np
        import os
        import warnings
        import pandas as pd
        try:
            from xarray.core.indexing import PerformanceWarning as XArrayPerformanceWarning
        except ImportError:
            XArrayPerformanceWarning = None
        try:
            from dask.array.exceptions import PerformanceWarning as DaskPerformanceWarning
        except ImportError:
            DaskPerformanceWarning = None

        warnings.filterwarnings(
            "ignore",
            message="Slicing with an out-of-order index is generating",
        )

        for perf_warning in (XArrayPerformanceWarning, DaskPerformanceWarning):
            if perf_warning is not None:
                warnings.filterwarnings(
                    "ignore",
                    message="Slicing with an out-of-order index is generating",
                    category=perf_warning,
                )

        path_data = self.CONFIG.get("path_data")
        
        # ================================================================
        # PROCESSAMENTO COMUM
        # ================================================================
        # Aplica recorte espacial, se definido no config
        def _ensure_monotonic_coords(ds):
            if "time" in ds.coords:
                time = ds["time"]
                if time.size and time.values[0] > time.values[-1]:
                    ds = ds.sortby("time")
            if "lat" in ds.coords:
                lat = ds["lat"]
                if lat.size and float(lat[0]) > float(lat[-1]):
                    ds = ds.sortby("lat")
            if "lon" in ds.coords:
                lon = ds["lon"]
                if lon.size and float(lon[0]) > float(lon[-1]):
                    ds = ds.sortby("lon")
            return ds

        def _apply_spatial_subset(ds):
            """Recorta latitude/longitude usando os limites do config."""
            if "lat" in ds.coords and "lat_range" in self.CONFIG:
                lat_min, lat_max = self.CONFIG["lat_range"]
                if lat_min > lat_max:
                    lat_min, lat_max = lat_max, lat_min
                ds = ds.sel(lat=slice(lat_min, lat_max))
            if "lon" in ds.coords and "lon_range" in self.CONFIG:
                lon_min, lon_max = self.CONFIG["lon_range"]
                if lon_min > lon_max:
                    lon_min, lon_max = lon_max, lon_min
                ds = ds.sel(lon=slice(lon_min, lon_max))
            return ds

        # ================================================================
        # BLOCO PARA DADOS EXTERNOS
        # ================================================================
        if self.mode == "EXTERNO":
            print(format_log("INFO", message=f"############# {self.mode} #############"))
            var_paths_cfg = self.CONFIG.get("external_var_paths") or {}
            try:
                res = float(self.CONFIG.get("resolution", 0.5))
            except Exception:
                res = 0.5

            lat_cfg = self.CONFIG.get("lat_range", (-30.0, 30.0))
            lon_cfg = self.CONFIG.get("lon_range", (100.0, 290.0))
            lat_lower = float(min(lat_cfg))
            lat_upper = float(max(lat_cfg))
            lon_lower = float(min(lon_cfg))
            lon_upper = float(max(lon_cfg))
            target_lats = np.arange(lat_lower, lat_upper + res * 0.5, res)
            target_lons = np.arange(lon_lower, lon_upper + res * 0.5, res)
            if target_lats.size == 0:
                target_lats = np.array([lat_lower, lat_upper], dtype=float)
            if target_lons.size == 0:
                target_lons = np.array([lon_lower, lon_upper], dtype=float)

            def _load_external_individual(files_map: dict[str, list[str]], *, target_lats: np.ndarray, target_lons: np.ndarray):
                alias_map = {
                    "air": ("air", "t2m", "temp", "temperature"),
                    "slp": ("slp", "mslp", "prmsl", "pressure"),
                    "uwnd": ("uwnd", "u10", "u"),
                    "vwnd": ("vwnd", "v10", "v"),
                    "cldc": ("cldc", "tcc", "tcdc", "cloud", "cloud_cover"),
                    "sst": ("sst", "ts", "sea_surface_temperature"),
                }
                datasets = []
                for canonical, file_list in files_map.items():
                    files = [str(p) for p in file_list if p]
                    if not files:
                        continue
                    ds_var = xr.open_mfdataset(files, combine="by_coords")
                    rename_coords = {}
                    for src, dst in (("latitude", "lat"), ("longitude", "lon"), ("valid_time", "time")):
                        if src in ds_var.coords or src in ds_var.dims:
                            rename_coords[src] = dst
                    if rename_coords:
                        ds_var = ds_var.rename(rename_coords)
                    if "time" not in ds_var.coords and "time" not in ds_var.dims:
                        ds_var.close()
                        raise ValueError(format_log("ERRO", message=f"Arquivo(s) de {canonical} não possuem coordenada temporal 'time'."))

                    candidates = alias_map.get(canonical, (canonical,))
                    var_name = None
                    for cand in candidates:
                        if cand in ds_var.data_vars:
                            var_name = cand
                            break
                    if var_name is None:
                        if len(ds_var.data_vars) == 1:
                            var_name = list(ds_var.data_vars)[0]
                        else:
                            ds_var.close()
                            raise ValueError(
                                format_log(
                                    "ERRO",
                                    message=f"Não foi possível identificar a variável alvo para {canonical}. Disponíveis: {list(ds_var.data_vars)}",
                                )
                            )

                    da = ds_var[var_name]
                    extra_dims = [dim for dim in da.dims if dim not in {"time", "lat", "lon"}]
                    if extra_dims:
                        print(
                            format_log(
                                "ATENCAO",
                                message=(
                                    f"Variável {canonical} possui dimensões extras {extra_dims}; "
                                    "selecionando o primeiro índice para compatibilizar."
                                ),
                            )
                        )
                        indexers = {dim: 0 for dim in extra_dims}
                        da = da.isel(**indexers).squeeze(drop=True)
                        for dim in extra_dims:
                            if dim in da.coords:
                                da = da.drop_vars(dim, errors="ignore")
                    if "lat" in da.coords:
                        lat_coord = da["lat"]
                        if lat_coord.size and float(lat_coord[0]) > float(lat_coord[-1]):
                            da = da.sortby("lat")
                    if "lon" in da.coords:
                        lon_coord = da["lon"]
                        if lon_coord.size and float(lon_coord[0]) > float(lon_coord[-1]):
                            da = da.sortby("lon")
                        if np.any(lon_coord < 0):
                            da = da.assign_coords({"lon": ((lon_coord + 360) % 360)})
                            da = da.sortby("lon")
                    if "lat" in da.coords:
                        da = da.sel(lat=slice(lat_lower, lat_upper))
                    if "lon" in da.coords:
                        da = da.sel(lon=slice(lon_lower, lon_upper))
                    da = da.interp(lat=target_lats, lon=target_lons, method="nearest").compute()
                    if canonical == "cldc" and float(da.notnull().mean().mean().item()) == 0.0:
                        print(format_log("ATENCAO", message="Dados de nebulosidade ficaram vazios após recorte/interpolação."))
                    da = da.rename(canonical)
                    datasets.append(da.to_dataset())
                    ds_var.close()

                if not datasets:
                    raise ValueError(format_log("ERRO", message="Nenhum arquivo válido encontrado para o modo EXTERNO."))
                return xr.merge(datasets, compat="override", join="outer")

            if var_paths_cfg:
                print(format_log("INFO", message="Carregando arquivos externos individuais por variável."))
                ds = _load_external_individual(var_paths_cfg, target_lats=target_lats, target_lons=target_lons)
            else:
                if not path_data:
                    raise ValueError(format_log("ERRO", message="MEI_EXTERNO_PATH_DATA não informado e nenhum arquivo individual disponível."))
                print(format_log("INFO", message=f"Carregando datasets externos de: {path_data}"))
                ds = xr.open_mfdataset(path_data, combine="by_coords")

            self._validate_dates(ds)

            # Renomeação segura das variáveis (compatibilidade externo → MEI)
            rename_map = {
                "latitude": "lat",
                "longitude": "lon",
                "valid_time": "time",
                "u10": "uwnd",
                "v10": "vwnd",
                "t2m": "air",
                "tcc": "cldc",
                "msl": "slp"
            }
            valid_map = {k: v for k, v in rename_map.items() if k in ds.variables or k in ds.coords}
            if valid_map:
                ds = ds.rename(valid_map)

            ds = _ensure_monotonic_coords(ds)

            # Lê resolução configurável (default = 0.5°)
            print(format_log("INFO", message=f"Usando resolução configurada: {res}°"))

            # --- Funções auxiliares do pré-processamento externo ---
            def normalize_lon(ds):
                lon_name = "lon" if "lon" in ds.coords else ("longitude" if "longitude" in ds.coords else None)
                if lon_name is None:
                    return ds
                lon = ds[lon_name]
                if np.any(lon < 0):
                    ds = ds.assign_coords({lon_name: ((lon + 360) % 360)})
                ds = ds.sortby(lon_name)
                if lon_name != "lon":
                    ds = ds.rename({lon_name: "lon"})
                return ds

            # --- Normalização de coordenadas ---
            ds = normalize_lon(ds)
            ds = _ensure_monotonic_coords(ds)
            ds = _apply_spatial_subset(ds)

            # Interpola para a grade regular configurada
            lons = np.arange(ds.lon.min().values, ds.lon.max().values, res)
            lats = np.arange(ds.lat.min().values, ds.lat.max().values, res)
            ds = ds.interp(lat=lats, lon=lons, method="nearest")
            
            if "time" in ds.dims:
                ds = ds.chunk({"time": -1})

            var_interp = ds.interpolate_na(dim="time", method="linear", limit=4)
            clim = ds.mean("time")
            var_filled = var_interp.fillna(clim)

            print(format_log("INFO", message=f"Pré-processamento dado externo concluído: grade reamostrada ({res}° x {res}°)."))
            self.name = "EXTERNO"

        # ================================================================
        # BLOCO PARA DADOS NOAA (PADRÃO)
        # ================================================================
        else:
            # print(format_log("INFO", message=f"############# {self.mode} #############"))
            print(format_log("INFO", message=f"Carregando datasets ICOADS/PSL NOAA..."))
            ds = xr.open_mfdataset(self.CONFIG["path_data"], combine="by_coords")
            ds = _ensure_monotonic_coords(ds)
            ds = _apply_spatial_subset(ds)
            # ds = ds.sel(time=slice(series_start, series_end))

            var_interp = ds.interpolate_na(dim="time", method="linear", limit=4)
            clim = ds.mean("time")
            var_filled = var_interp.fillna(clim)
            self.name = "PSL(NOAA)"

        # ================================================================
        # CÁLCULO DE CLIMATOLOGIA, ANOMALIAS E PADRONIZAÇÃO
        # ================================================================
        print(format_log("INFO", message=f"Calculando climatologia e anomalias..."))

        base_clim = self.CONFIG["base_climatology"]
        
        base_series = self.CONFIG["base_series"]
      
        
        climatology = (
            var_filled.sel(time=slice(*base_clim))
            .groupby("time.month")
            .mean("time")
        )

        anomalies = (
            var_filled.sel(time=slice(*base_series))
            .groupby("time.month")
            - climatology
        )

        std = anomalies.std("time")
        anomalies = anomalies.where(np.abs(anomalies) <= 4.5 * std)
        print(format_log("INFO", message=f"Padronizando série..."))

        standardized = anomalies / std
        bimonthly = (
            standardized.sel(time=slice(*base_series))
            .rolling(time=2, center=True)
            .mean()
        )

        print(format_log("INFO", message=f"Pré-processamento e padronização concluídos."))
        return bimonthly, standardized
    
    def _clusterization(self, da, v):
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import squareform
        import numpy as np
        import xarray as xr        
        import warnings
        warnings.filterwarnings("ignore")

        similarity_threshold = 0.6
  
        stacked = da.stack(points=("lat", "lon"))

        valid_thresh = 0.95
        if self.mode == "EXTERNO" and v == "cldc":
            cfg_thresh = self.CONFIG.get("cloud_valid_threshold")
            try:
                valid_thresh = float(cfg_thresh) if cfg_thresh not in (None, "") else 0.5
            except Exception:
                valid_thresh = 0.5
        valid_mask = (stacked.notnull().mean("time") > valid_thresh).compute()
        stacked = stacked.isel(points=valid_mask)

        valid_mask2 = (stacked.std("time") > 0).compute()
        stacked = stacked.isel(points=valid_mask2)

        n_points = stacked.sizes.get("points", 0)
        if n_points == 0:
            print(format_log("ATENCAO", message=f"{v}: nenhum grid válido após limpeza; usando série média vazia."))
            empty = np.zeros((da.sizes.get("time", 0), 1))
            return xr.DataArray(
                empty,
                dims=["time", "cluster"],
                coords={"time": da.time, "cluster": [1]},
            )
        if n_points == 1:
            print(format_log("INFO", message=f"{v}: apenas um ponto válido encontrado; pulando clusterização."))
            single = stacked.isel(points=0).values[:, None]
            return xr.DataArray(
                single,
                dims=["time", "cluster"],
                coords={"time": da.time, "cluster": [1]},
            )

        X = stacked.values

        corr = np.corrcoef(X.T)

        dist = 1 - np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)

        Z = linkage(squareform(dist, checks=False), method="average")
        labels = fcluster(Z, t=1 - similarity_threshold, criterion="distance")

        clusters = []
        for i in np.unique(labels):
            mask = labels == i
            clusters.append(X[:, mask].mean(axis=1))

        print(format_log("INFO", message=f"{v}: {len(np.unique(labels))} clusters encontrados."))
            
        return xr.DataArray(
            np.array(clusters).T,
            dims=["time", "cluster"],
            coords={"time": da.time, "cluster": np.arange(1, len(np.unique(labels)) + 1)}
        )
    
    def _prepare_for_pca(self, clusters_dict):
        import numpy as np
        print(format_log("INFO", message=f"Preparando dados para EOF..."))
         
        series = []
        for var, arr in clusters_dict.items():
            std = arr.std("time")
            std = std.where(std > 0, other=1.0)
            data = arr / std
            series.append(np.nan_to_num(data.values, nan=0.0, posinf=0.0, neginf=0.0))
        return np.concatenate(series, axis=1)


    def _run_pca(self, X):
        from sklearn.decomposition import PCA
        
        n_components = 1
        print(format_log("INFO", message=f"Rodando EOF (n_components={n_components})..."))
        
        pca = PCA(n_components=n_components)
        pcs = pca.fit_transform(X)
  
        print(format_log("INFO", message=f"EOF concluído."))
        

        return pcs, pca


    def _seasonal_standardization(self, pc1, time_index):
        import pandas as pd
        print(format_log("INFO", message=f"Filtro sazonal PC1..."))
        
        pc1_series = pd.Series(pc1[:, 0], index=time_index)
        
        standardized = pc1_series.groupby(pc1_series.index.month).transform(
            lambda x: (x - x.mean()) / x.std() if x.std() != 0 else np.nan
        )
    
        if np.all(np.isnan(standardized)):
            raise ValueError("Filtro sazonal falhou devido a dados insuficientes, inclua um intervalo na série maior ou igual a 1 ano.")


        return standardized
    
    def _plot_mei_bar(self, MEI):
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        from pathlib import Path
        import matplotlib.image as mpimg

        """
        Plota o índice MEI em formato de barras.
        - Barras vermelhas (tom suave) para valores positivos (El Niño)
        - Barras azuis (tom suave) para valores negativos (La Niña)
        - Insere logo no canto inferior direito (se fornecido)
        """

        # Caminho da logo relativo ao projeto, independente do cwd
        logo_path = Path(__file__).resolve().parent.parent / "utils" / "atmosmarine.png"
    

        title = f"Multivariate ENSO Index (MEI)"
        fig, ax = plt.subplots(figsize=(12, 4))

        # cores condicionais (mais suaves)
        MEI = MEI.fillna(0.0)
        colors = ["#d7191c" if v > 0 else"#2c7bb6" for v in MEI]

        values = MEI.to_numpy()
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)

        ax.bar(MEI.index, values, color=colors, width=50)

        # linha zero
        ax.axhline(0, color="k", linewidth=1)
        ymax = np.nanmax(values) if values.size else 0.0
        ymin = np.nanmin(values) if values.size else 0.0
        lim = max(abs(ymax), abs(ymin))  
        ax.set_ylim(-lim-1,lim+1)  

        # labels
        ax.set_ylabel("Desvio Padronizado")
        ax.set_title(title, fontsize=14, weight='bold')

        # grade
        ax.grid(True, axis="y", linestyle="--", alpha=0.6)

        # eixo x (anos)
        ax.xaxis.set_major_locator(mdates.YearLocator(5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

        # remover bordas
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # inserir logo, se existir
        if logo_path.exists():
            try:
                img = mpimg.imread(str(logo_path))
                ab = AnnotationBbox(
                    OffsetImage(img, zoom=0.04),   # ajuste do tamanho
                    (0.999, 0.21),                 # posição relativa ao eixo
                    xycoords="axes fraction",
                    frameon=False,
                    box_alignment=(1, 1),          # ancora canto superior direito da logo
                    zorder=10
                )
                ax.add_artist(ab)
            except Exception as e:
                print(format_log("ATENCAO", message=f"Falha ao inserir logo: {e}"))
        else:
            print(format_log("ATENCAO", message=f"Logo não encontrada: {logo_path}"))
        plt.tight_layout()
        plt.savefig(self.PATH_MEI_PLOT, dpi=300)
        

        pass

    def _export_mei_format(self, MEI):
        import pandas as pd

        print(format_log("INFO", message=f"Gerando tabela bimensal do MEI em memória."))

        bim_names = [
            "DECJAN", "JANFEB", "FEBMAR", "MARAPR", "APRMAY", "MAYJUN",
            "JUNJUL", "JULAUG", "AUGSEP", "SEPOCT", "OCTNOV", "NOVDEC"
        ]
        self._bimester_names = tuple(bim_names)
        df = pd.DataFrame({"YEAR": MEI.index.year, "MONTH": MEI.index.month, "MEI": MEI.values})
        month_to_label = {
            12: "DECJAN", 1: "JANFEB", 2: "FEBMAR", 3: "MARAPR", 4: "APRMAY", 5: "MAYJUN",
            6: "JUNJUL", 7: "JULAUG", 8: "AUGSEP", 9: "SEPOCT", 10: "OCTNOV", 11: "NOVDEC"
        }
        df["PERIOD"] = df["MONTH"].map(month_to_label)
        df.loc[df["MONTH"] == 12, "YEAR"] += 1
        wide = df.pivot(index="YEAR", columns="PERIOD", values="MEI")
        missing = [period for period in bim_names if period not in wide.columns]
        for period in missing:
            wide[period] = float("nan")
        wide = wide[bim_names]
        wide.index.name = "YEAR"

        return wide

    def _baixar_mei_noaa(self, url: str) -> pd.DataFrame:
        import requests
        import re
        import pandas as pd
        from io import StringIO
        """
        Baixa a tabela MEI 'old' do NOAA em HTML, extrai e retorna DataFrame
        com colunas: YEAR, DECJAN, JANFEB, ..., NOVDEC
        """

        resp = requests.get(url)
        resp.raise_for_status()
        html = resp.text

        # Extrai conteúdo do bloco <pre>...</pre>
        pre_text = re.search(r"<pre>(.*?)</pre>", html, re.S).group(1)
        lines = pre_text.strip().splitlines()

        # Localiza cabeçalho
        header_idx = next(i for i, line in enumerate(lines) if line.startswith("YEAR"))
        header = lines[header_idx].split()

        # Filtra apenas linhas completas
        data_lines = []
        for line in lines[header_idx+1:]:
            if re.match(r"^\d{4}", line):
                cols = re.split(r"\s+", line.strip())
                if len(cols) == len(header):
                    data_lines.append("\t".join(cols))

        # Converte para DataFrame
        csv_text = "\n".join(data_lines)
        df = pd.read_csv(StringIO(csv_text), sep="\t", names=header)
        df["YEAR"] = df["YEAR"].astype(int)

        return df
    
    def _comparar_mei(self, buffer, mei_wide):
        import numpy as np
        from tabulate import tabulate
        import pandas as pd

        def _log_and_buffer(msg: str):
            # print(format_log("INFO", message=msg))
            
            buffer.write(msg + "\n")

        """
        Baixa dados do MEI (versão old) do NOAA em HTML, converte para CSV
        e compara com o MEI calculado.
        """
        if mei_wide is None:
            raise ValueError("_comparar_mei requer os dados calculados do MEI em formato tabular.")

        cache_csv = self.PATH_MEI_CACHE_REF
        combined_csv = getattr(self, "PATH_MEI_CSV_COMBINED", self.PATH_MEI_CSV_CALC)

        ref = None
        try:
            ref = self._baixar_mei_noaa(self.CONFIG['base_url_table'])
            ref.to_csv(cache_csv, sep=";", index=False)
            _log_and_buffer(f"MEI NOAA baixado da web e salvo em cache: {cache_csv}")
        except Exception as e:
            print(format_log("ATENCAO", message=f"Falha ao baixar MEI NOAA ({e}). Tentando cache local..."))

            if cache_csv.exists():
                ref = pd.read_csv(cache_csv, sep=";")
                _log_and_buffer(f"MEI NOAA carregado do cache: {cache_csv}")
            else:
                print(format_log("CACHE", message=f"Cache MEI NOAA ausente e download indisponível →"))
                raise

        bim_order = getattr(
            self,
            "_bimester_names",
            (
                "DECJAN", "JANFEB", "FEBMAR", "MARAPR", "APRMAY", "MAYJUN",
                "JUNJUL", "JULAUG", "AUGSEP", "SEPOCT", "OCTNOV", "NOVDEC"
            ),
        )

        # Dados calculados em memória (pivot por bimestre)
        if not isinstance(mei_wide, pd.DataFrame):
            raise TypeError("_comparar_mei espera um DataFrame para mei_wide.")
        mei = mei_wide.copy()
        if mei.index.name != "YEAR":
            mei.index.name = "YEAR"

        # Dados de referência NOAA (já carregados ou vindos do cache)
        if "YEAR" in ref.columns:
            ref = ref.set_index("YEAR")

        def _align_bimesters(df: pd.DataFrame) -> pd.DataFrame:
            aligned = df.copy()
            for col in bim_order:
                if col not in aligned.columns:
                    aligned[col] = np.nan
            return aligned.loc[:, bim_order]

        mei = _align_bimesters(mei)
        ref = _align_bimesters(ref)

        # Interseção dos anos
        idx = ref.index.intersection(mei.index)
        diff = ref.loc[idx] - mei

        # Métricas gerais
        rmse_geral = np.sqrt((diff**2).mean().mean())
        bias_geral = diff.mean().mean()
        std_geral = diff.stack().std()
        mae_geral = np.abs(diff).mean().mean()

        # Métricas bimensais
        metrics_bimensais = pd.DataFrame({
            "RMSE": np.sqrt((diff**2).mean()),
            "Bias": diff.mean(),
            "Desvio Padrão": diff.std()
        })

        # Correlação
        s1, s2 = ref.stack(), mei.stack()
        df_corr = pd.concat([s1, s2], axis=1, keys=["NOAA", "PCA"]).dropna()
        corr_geral = df_corr["NOAA"].corr(df_corr["PCA"])
        corr_bimensal = ref.corrwith(mei)

        # _log_and_buffer("\n=== Correlação ===")
        # _log_and_buffer("Correlação geral: {corr_geral:.3f}")
        _log_and_buffer(tabulate(
            corr_bimensal.reset_index().rename(columns={0: "Correlação"}),
            headers=["Estação", "Correlação"],
            tablefmt="psql",
            floatfmt=".3f"
        ))

        flat = pd.concat([ref.loc[idx].stack(), mei.loc[idx].stack()], axis=1, keys=["NOAA", "CALC"]).dropna()
        n_registros = int(len(flat))
        if n_registros >= 2:
            slope, intercept = np.polyfit(flat["NOAA"].values, flat["CALC"].values, 1)
        else:
            slope, intercept = float("nan"), float("nan")
        r2 = float(corr_geral ** 2) if np.isfinite(corr_geral) else float("nan")
        metrics_row = {
            "fonte": "MEI_ICOADS_vs_NOAA",
            "data_inicio": self.CONFIG["base_series"][0],
            "data_fim": self.CONFIG["base_series"][1],
            "n_registros": n_registros,
            "rmse": float(rmse_geral),
            "mae": float(mae_geral),
            "bias": float(bias_geral),
            "corr": float(corr_geral),
            "r2": r2,
            "slope": float(slope),
            "intercept": float(intercept),
            "desv_pad_erro": float(std_geral),
        }
        pd.DataFrame([metrics_row]).to_csv(self.PATH_MEI_METRICAS, index=False, float_format="%.4f")

        print("[ESTATÍSTICA] === Métricas gerais do MEI Calculado ===")
        print(f"RMSE: {float(rmse_geral):.3f} | MAE: {float(mae_geral):.3f} | Viés: {float(bias_geral):+.3f}")
        print(f"Correlação (r): {float(corr_geral):.3f} | R²: {r2:.3f} | slope: {slope:.3f} | intercept: {intercept:+.3f}")


        print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas gerais do MEI →", destino=f"{self.PATH_MEI_METRICAS}"))

        metrics_bi_out = metrics_bimensais.copy()
        metrics_bi_out.index.name = "bimestre"
        metrics_bi_out.to_csv(self.PATH_MEI_METRICAS_BIM, float_format="%.4f")

        print(format_log("SALVO", item=f"Arquivo CSV com métricas estatísticas bimensais do MEI →", destino=f"{self.PATH_MEI_METRICAS_BIM}"))
        
        # Gera arquivo combinado com MEI calculado e referência NOAA
        years_union = sorted(set(mei.index).union(ref.index))
        mei_union = mei.reindex(years_union)
        ref_union = ref.reindex(years_union)
        
        # mantém só os anos onde o MEI tem pelo menos 1 valor não nulo
        valid_years = mei_union.dropna(how="all").index

        mei_intersec = mei_union.loc[valid_years]
        ref_intersec = ref_union.loc[valid_years]

        combined_long = pd.concat(
            [
                mei_intersec.stack(dropna=False).rename("MEI_CALC"),
                ref_intersec.stack(dropna=False).rename("MEI_PSL"),
            ],
            axis=1,
        ).reset_index()
        combined_long = combined_long.rename(columns={"YEAR": "ano", "level_1": "bimestre"})
        combined_long["bimestre"] = pd.Categorical(combined_long["bimestre"], categories=bim_order, ordered=True)
        combined_long["diferenca"] = (combined_long["MEI_CALC"] - combined_long["MEI_PSL"]).round(3)
        combined_long = combined_long.sort_values(["ano", "bimestre"]).dropna(subset=["MEI_CALC", "MEI_PSL"], how="all").reset_index(drop=True)
        combined_long["ano"] = combined_long["ano"].astype("Int64")
        combined_long["bimestre"] = combined_long["bimestre"].astype(str)
        combined_long.to_csv(combined_csv, index=False, float_format="%.3f", na_rep="")
        print(format_log("SALVO", item="Tabela combinada MEI (cálculo vs referência) →", destino=f"{combined_csv}"))
        pass

    def run(self):
        import time
        import numpy as np
        import io
        from pathlib import Path 

        start_total = time.time()
        buffer = io.StringIO()

        print(format_log("INFO", message=f"Iniciando processamento MEI..."))

        # NOVA CONDIÇÃO → verificar se o usuário forneceu dados externos
        path_data = self.CONFIG.get("path_data")
        external_var_paths = self.CONFIG.get("external_var_paths") if self.mode == "EXTERNO" else None

        using_external_path = False
        if path_data:
            path_str = str(path_data)
            path_obj = Path(path_str)
            if path_obj.exists():
                if path_obj.is_dir():
                    print(format_log("INFO", message=f"Usando dados externos fornecidos em: {path_obj}"))
                    self.CONFIG["path_data"] = str(path_obj / "*.nc")
                else:
                    print(format_log("INFO", message=f"Usando arquivo externo fornecido: {path_obj}"))
                    self.CONFIG["path_data"] = str(path_obj)
                using_external_path = True
            elif any(sym in path_str for sym in "*?[]"):
                print(format_log("INFO", message=f"Usando padrão externo: {path_str}"))
                self.CONFIG["path_data"] = path_str
                using_external_path = True

        if self.mode == "EXTERNO" and external_var_paths and not using_external_path:
            print(format_log("INFO", message="Usando arquivos externos individuais fornecidos no config."))  # já tratados depois
        elif not using_external_path:
            print(format_log("INFO", message=f"Usando dados NOAA padrão → ICOADS."))
            self._download_psl(self.CONFIG["psl_base_url"], self.CONFIG["psl_vars"])
            self._ensure_data(self.CONFIG)

        if self.mode in {"TESTE", "EXTERNO"}:
            try:
                self._plot_regiao_mei_bbox(self.base_series_suffix)
            except Exception as exc:
                print(format_log("ATENCAO", message=f"Falha ao plotar região espacial do MEI: {exc}"))

        # processamento normal
        bimonthly, standardized = self._load_and_preprocess()
        print(format_log("INFO", message=f"Executando clusterização para todas as variáveis..."))

        clusters = {var: self._clusterization(standardized[var], var)
                    for var in standardized}

        X = np.nan_to_num(self._prepare_for_pca(clusters), nan=0.0)
        pcs, pca = self._run_pca(X)
        MEI = self._seasonal_standardization(pcs, bimonthly.time.to_index())

        self._plot_mei_bar(MEI)
        mei_tabular = self._export_mei_format(MEI)

        print(format_log("INFO", message=f"MEI calculado e salvo."))
        print(format_log("INFO", message=f"Comparando com MEI de referência NOAA..."))

        self._comparar_mei(buffer, mei_tabular)
