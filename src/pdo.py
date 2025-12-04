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
from .atm_tools import validate_config_PDO
from src.logging import format_log
class PDO:
    def __init__(self, cfg: dict | None = None):
        validate_config_PDO(cfg)
        self.cfg = cfg or {}
        self.SUF_EXEC = _dt.datetime.now().strftime("%Y%m")

        # ----------------- Pastas base -----------------
        self.DATA_DIR = Path("data"); self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_ROOT = self.DATA_DIR / "cache"
        self.CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR = self.CACHE_ROOT / "PDO"
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.NCEI_CACHE = self.CACHE_DIR / "ersst.v5.pdo.dat"

        legacy_sources = [
            self.DATA_DIR / "ersst.v5.pdo.dat",
            self.CACHE_ROOT / "ersst.v5.pdo.dat",
        ]
        for legacy in legacy_sources:
            if legacy.exists():
                if not self.NCEI_CACHE.exists():
                    try:
                        shutil.move(legacy, self.NCEI_CACHE)
                        print(format_log("CACHE", action="Arquivo PDO oficial migrado", path=str(self.NCEI_CACHE)))
                    except Exception:
                        try:
                            shutil.copy2(legacy, self.NCEI_CACHE)
                            print(format_log("CACHE", action="Arquivo PDO oficial copiado", path=str(self.NCEI_CACHE)))
                        except Exception:
                            pass
                try:
                    legacy.unlink()
                except Exception:
                    pass

        # ----------------- Arquivos e URLs -----------------
        self.ersst_nc       = self.DATA_DIR / "ersst_v5.nc"
        self.url_ersstv5    = "https://downloads.psl.noaa.gov/Datasets/noaa.ersst.v5/sst.mnmean.nc"

        # URLs oficiais/fallback
        self.official_pdo_path     = "https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat"

        # ----------------- Modo -----------------
        self.modo = str(self.cfg.get("PDO_MODO", "REFERENCIA")).strip().upper()
        if self.modo == "VALIDACAO":
            self.modo = "REFERENCIA"

        # ----------------- Pastas de saída -----------------
        base = OUTPUT_ROOT / "PDO"
        if self.modo == "REFERENCIA":
            raiz = base / "REFERENCIA"
        elif self.modo == "TESTE":
            nome_teste = self._slug(self.cfg.get("PDO_TESTE_NOME", "sem_nome"))
            raiz = base / f"TESTE_{nome_teste}"
        elif self.modo == "EXTERNO":
            nome_ext = self._slug(self.cfg.get("PDO_EXTERNO_NOME", "EXTERNO"))
            raiz = base / f"EXTERNO_{nome_ext}"
        else:
            raiz = base / "OUTROS"

        self.OUT_DIR = raiz
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR_tables = self.OUT_DIR
        self.OUT_DIR_figs   = self.OUT_DIR
        self.OUT_DIR_valida = self.OUT_DIR

        print(format_log("INFO", message=f"PDO inicializado em modo {self.modo} → outputs em {self.OUT_DIR}"))

        # Garante presença/atualização do ERSSTv5 quando o fluxo depende dele
        self._ensure_core_inputs()

    # ----------------- Dados auxiliares -----------------
    def _ensure_core_inputs(self):
        """
        Garante que os arquivos de entrada necessários estejam disponíveis.
        No modo EXTERNO o usuário fornece o NetCDF, então o download é opcional.
        """
        if self.modo in {"REFERENCIA", "TESTE"}:
            self._download_nc_with_checks(self.url_ersstv5, self.ersst_nc, "ERSSTv5")

    # ----------------- Pré-processamento SST -----------------
    @staticmethod
    def _to_month_start(time_index):
        return pd.to_datetime(pd.DatetimeIndex(time_index).to_period("M").to_timestamp())

    @staticmethod
    def _normalize_lon(sst):
        """Normaliza longitude para 0–360 e ordena lat/lon."""
        if "lon" not in sst.coords:
            raise ValueError("Dataset não possui coordenada 'lon'.")
        sst = sst.assign_coords(lon=(sst.lon % 360))
        return sst.sortby("lon")

    def _compute_anomalies(self, sst: xr.DataArray, clima_ini: str, clima_fim: str) -> xr.DataArray:
        """Remove climatologia mensal (base climatológica)."""
        sst_clim = sst.sel(time=slice(clima_ini, clima_fim))
        if sst_clim.time.size == 0:
            raise ValueError(
                f"[ERRO] Nenhum dado encontrado no período {clima_ini} → {clima_fim}. "
                f"Datas disponíveis: {sst.time.values[0]} → {sst.time.values[-1]}"
            )
        clima = sst_clim.groupby("time.month").mean("time")
        return sst.groupby("time.month") - clima

    def _remove_global_mean(self, anom: xr.DataArray) -> xr.DataArray:
        """Remove anomalia média global (area-weighted)."""
        coslat = np.cos(np.deg2rad(anom.lat))
        weights = xr.DataArray(coslat, coords={"lat": anom.lat}, dims=("lat",)).where(~anom.isnull())
        weight_sum = weights.sum(("lat", "lon"), skipna=True)
        global_mean = (anom * weights).sum(("lat", "lon"), skipna=True) / weight_sum
        return anom - global_mean

    @staticmethod
    def _slice_lat(data: xr.DataArray, lat_min: float, lat_max: float) -> xr.DataArray:
        """Recorta a latitude considerando ordenação crescente/decrescente."""
        if data.lat[0] > data.lat[-1]:
            return data.sel(lat=slice(lat_max, lat_min))
        return data.sel(lat=slice(lat_min, lat_max))

    def _prepare_region(self, anom: xr.DataArray, lat_min: float = 20.0, lat_max: float = 70.0,
                        lon_min: float = 110.0, lon_max: float = 260.0) -> xr.DataArray:
        """Seleciona a região alvo para o cálculo do EOF."""
        region = self._slice_lat(anom, lat_min, lat_max)
        region = region.sel(lon=slice(lon_min, lon_max))
        if region.lat.size == 0 or region.lon.size == 0:
            raise ValueError("[ERRO] Recorte (lat/lon) resultou em grade vazia.")
        return region

    def _leading_eof(self, region_anom: xr.DataArray):
        """
        Calcula o primeiro EOF e o respectivo PC (PDO) com ponderação por sqrt(cos(lat)).

        Retorna:
            pdo_index (pd.Series), eof_map (xr.DataArray), explained_variance (float)
        """
        coslat = np.cos(np.deg2rad(region_anom.lat)).clip(min=0.0)
        lat_weights = np.sqrt(coslat)
        weighted = region_anom * lat_weights
        stacked = weighted.stack(points=("lat", "lon"))
        # remove pontos completamente vazios
        stacked = stacked.dropna("points", how="all")
        if stacked.points.size == 0:
            raise ValueError("[ERRO] Nenhum ponto válido para cálculo do EOF.")
        X = stacked.transpose("time", "points").values
        X = np.nan_to_num(X, nan=0.0)
        # Remove média temporal residual
        X = X - X.mean(axis=0, keepdims=True)
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        pc = U[:, 0] * S[0]
        eof_vals = Vt[0]
        explained = float((S[0] ** 2) / (S ** 2).sum()) if S.size else np.nan
        points_idx = stacked.points.to_index()
        eof_stack = xr.DataArray(eof_vals, coords={"points": points_idx}, dims=("points",))
        eof_map = eof_stack.unstack("points")
        pdo_series = pd.Series(pc, index=pd.to_datetime(region_anom.time.values), name="PDO")
        pdo_series = pdo_series - pdo_series.mean()
        std = pdo_series.std(ddof=0)
        if std > 0:
            pdo_series /= std
        pdo_series.index.name = "time"

        # Ajuste de sinal baseado em região de referência (Pacífico Leste Norte)
        lat_vals = eof_map.lat.values
        lon_vals = (eof_map.lon.values % 360.0)

        east_lat = (lat_vals >= 25.0) & (lat_vals <= 45.0)
        east_lon = (lon_vals >= 200.0) & (lon_vals <= 240.0)
        west_lat = (lat_vals >= 25.0) & (lat_vals <= 45.0)
        west_lon = (lon_vals >= 150.0) & (lon_vals <= 190.0)

        east_vals = eof_map.values[np.ix_(east_lat, east_lon)]
        west_vals = eof_map.values[np.ix_(west_lat, west_lon)]

        east_mean = np.nanmean(east_vals) if east_vals.size else np.nan
        west_mean = np.nanmean(west_vals) if west_vals.size else np.nan

        if np.isnan(east_mean) or np.isnan(west_mean):
            contrast = np.nanmean(eof_map.values)
        else:
            contrast = east_mean - west_mean

        if np.isnan(contrast):
            contrast = 0.0

        if contrast < 0:
            pdo_series *= -1
            eof_map = (-1.0) * eof_map

        return pdo_series, eof_map, explained

    @staticmethod
    def _http_head(url: str) -> dict:
        try:
            req = urllib.request.Request(url, method="HEAD")
        except TypeError:
            req = urllib.request.Request(url)
            req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(req, timeout=60) as resp:
            return dict(resp.headers)

    def _remote_last_modified(self, url: str) -> datetime | None:
        try:
            headers = self._http_head(url)
            lm = headers.get("Last-Modified")
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
                    ts = pd.to_datetime(ds["time"].values)
                    tmin = pd.Timestamp(ts.min()).date()
                    tmax = pd.Timestamp(ts.max()).date()
                    print(format_log("INFO", message=f"{label}: cobertura temporal {tmin} → {tmax}"))
                else:
                    print(format_log("INFO", message=f"{label}: variável 'time' ausente; não foi possível verificar cobertura temporal."))
        except Exception as exc:
            print(format_log("ATENCAO", message=f"{label}: falha ao ler cobertura temporal ({exc})"))
    # ----------------- Helpers -----------------
    @staticmethod
    def _slug(s: str) -> str:
        return re.sub(r'[^a-zA-Z0-9_-]+', '', str(s).replace(" ", "_"))

    @staticmethod
    def series_to_ms(s):
        idx = pd.to_datetime(s.index)
        ms = pd.DatetimeIndex(idx).to_period('M').to_timestamp(how='start')
        s2 = pd.Series(s.values, index=ms).sort_index()
        s2 = s2.replace([-9999, -99.99, 9999], np.nan)
        s2 = s2.where(s2.abs() <= 90, np.nan)
        if s2.index.has_duplicates:
            s2 = s2.groupby(level=0).mean()
        s2.index = pd.DatetimeIndex(s2.index, name='time')
        return s2
    @staticmethod
    def _parse_year12(txt):
        rows = []
        for line in txt.splitlines():
            line = line.strip()
            if re.match(r'^\d{4}\s', line):
                p = line.replace(',', ' ').split()
                if len(p) >= 13:
                    yr = int(p[0])
                    for m in range(1, 13):
                        try:
                            v = float(p[m])
                            if abs(v) >= 9000 or abs(v) > 90:
                                v = np.nan
                        except Exception:
                            v = np.nan
                        rows.append({'time': pd.Timestamp(yr, m, 1), 'v': v})
        if not rows:
            raise ValueError("Formato 'ano + 12 colunas' não reconhecido.")
        df = pd.DataFrame(rows).set_index('time').sort_index()
        return PDO.series_to_ms(df['v'])


    # ----------------- PDO Oficial (NCEI) -----------------
    def read_ncei_official(self, path_or_url=None, *, log_download: bool = True):
        target = path_or_url or self.official_pdo_path
        cache_file = self.NCEI_CACHE
        txt = None

        if str(target).startswith(("http://", "https://")):
            try:
                with urllib.request.urlopen(target, timeout=30) as resp:
                    txt = resp.read().decode("utf-8", "ignore")
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(txt, encoding="utf-8")
                    if log_download:
                        print(format_log("CACHE", action="PDO oficial atualizado", path=str(cache_file)))
                except Exception:
                    pass
            except Exception as e:
                if cache_file.exists():
                    print(format_log("ATENCAO", message=f"Falha ao baixar PDO oficial ({e}); usando cache local {cache_file}."))
                    txt = cache_file.read_text(encoding="utf-8", errors="ignore")
                else:
                    print(format_log("ATENCAO", message=f"Falha ao baixar PDO oficial ({e}); sem cache disponível."))
                    return None
        else:
            try:
                txt = Path(target).read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(format_log("ERRO", message=f"Falha ao ler arquivo PDO oficial {target}: {e}"))
                return None

        if not txt:
            print(format_log("ATENCAO", message="Conteúdo vazio ao ler PDO oficial."))
            return None
        return self._parse_year12(txt)


    # ----------------- Métodos run (REFERENCIA, TESTE, EXTERNO) -----------------
    def run(self):
        if self.modo == "REFERENCIA":
            self._run_referencia()
        elif self.modo == "TESTE":
            self._run_teste()
        elif self.modo == "EXTERNO":
            self._run_externo()
        else:
            print(format_log("ERRO", message=f"Modo PDO inválido: {self.modo}"))

    def _run_referencia(self):
        print(format_log("INFO", message="Rodando PDO Modo REFERÊNCIA"))

        ds = xr.open_dataset(self.ersst_nc)
        if "latitude" in ds.coords:
            ds = ds.rename({"latitude": "lat"})
        if "longitude" in ds.coords:
            ds = ds.rename({"longitude": "lon"})
        sst = ds["sst"]
        sst = self._normalize_lon(sst)
        sst = sst.assign_coords(time=self._to_month_start(sst.time.values))

        base_ini, base_fim = "1981-01", "2010-12"
        sst_anom = self._compute_anomalies(sst, base_ini, base_fim)
        sst_anom = self._remove_global_mean(sst_anom)
        print(format_log(
            "INFO",
            message=f"PDO REFERENCIA utilizando base climatológica {base_ini}:{base_fim} "
                    f"na região lat 20–70°N, lon 110–260°E."
        ))

        self._last_bounds = (110, 260, 20, 70)
        region = self._prepare_region(sst_anom, lat_min=20, lat_max=70, lon_min=110, lon_max=260)

        ncei = self.read_ncei_official(self.official_pdo_path)
        if ncei is not None:
            ncei = self.series_to_ms(ncei)

        pdo, eof_map, explained = self._leading_eof(region)

        eof_path = self.OUT_DIR / f"PDO_EOF_{self.SUF_EXEC}.nc"
        eof_map.name = "PDO_EOF1"
        eof_map.to_netcdf(eof_path)
        print(format_log("SALVO", item=f"EOF principal Modo REFERENCIA com {explained:.2%} variância explicada →", destino=str(eof_path)))

        clim_range = f"{base_ini}:{base_fim}"
        self._plot_eof_variance_map(
            eof_map,
            explained,
            modo="REFERENCIA",
            dataset_nome="ERSSTv5",
            clim_range=clim_range,
            lat_bounds=(20, 70),
            lon_bounds=(110, 260),
        )

        if ncei is not None:
            df_out = pd.concat(
                [pdo.rename("PDO_calc"), ncei.rename("PDO_NCEI")],
                axis=1,
                join="inner"
            ).round(3)
        else:
            df_out = pd.DataFrame({"PDO_calc": pdo}).round(3)
        df_out = df_out.rename(columns={"PDO_calc": "PDO_CALC"})
        if "PDO_NCEI" in df_out.columns:
            df_out["diferenca"] = (df_out["PDO_CALC"] - df_out["PDO_NCEI"]).round(3)
        else:
            df_out["diferenca"] = np.nan
        df_out.index.name = "data"
        df_out = df_out.reset_index()
        out_csv = self.OUT_DIR_tables / f"PDO_indice-mensal_CALCvsNCEI_{self.SUF_EXEC}.csv"
        df_out.to_csv(out_csv, index=False, date_format="%Y-%m-%d")
        print(format_log("SALVO", item="Tabela PDO (EOF) →", destino=str(out_csv)))

        self.validar_vs_ncei(pdo, label="REFERENCIA")
        self.plot_pdo_timeseries(pdo, label="REFERENCIA")



    def _run_teste(self):
        print(format_log("INFO", message="Rodando PDO Modo TESTE"))

        ds = xr.open_dataset(self.ersst_nc)
        if "latitude" in ds.coords:
            ds = ds.rename({"latitude": "lat"})
        if "longitude" in ds.coords:
            ds = ds.rename({"longitude": "lon"})
        sst = ds["sst"]
        sst = self._normalize_lon(sst)
        sst = sst.assign_coords(time=self._to_month_start(sst.time.values))

        lat_cfg_min = float(self.cfg.get("PDO_TESTE_LAT_MIN", 20))
        lat_cfg_max = float(self.cfg.get("PDO_TESTE_LAT_MAX", 70))
        lon_cfg_min = float(self.cfg.get("PDO_TESTE_LON_MIN", 110))
        lon_cfg_max = float(self.cfg.get("PDO_TESTE_LON_MAX", 260))
        lat_min, lat_max = min(lat_cfg_min, lat_cfg_max), max(lat_cfg_min, lat_cfg_max)
        lon_min, lon_max = min(lon_cfg_min, lon_cfg_max), max(lon_cfg_min, lon_cfg_max)
        self._last_bounds = (lon_min, lon_max, lat_min, lat_max)

        clima_cfg = str(self.cfg.get("PDO_TESTE_BASE_CLIMA", "1981-01:2010-12"))
        if ":" not in clima_cfg:
            raise ValueError(f"[ERRO] PDO_TESTE_BASE_CLIMA inválido: {clima_cfg}")
        clima_ini, clima_fim = [c.strip() for c in clima_cfg.split(":", 1)]

        sst_anom = self._compute_anomalies(sst, clima_ini, clima_fim)
        sst_anom = self._remove_global_mean(sst_anom)
        print(format_log(
            "INFO",
            message=(
                f"PDO TESTE utilizando base climatológica {clima_ini}:{clima_fim} "
                f"na região lat {lat_min}–{lat_max}°, lon {lon_min}–{lon_max}°."
            )
        ))
        region = self._prepare_region(sst_anom, lat_min=lat_min, lat_max=lat_max,
                                      lon_min=lon_min, lon_max=lon_max)

        ncei = self.read_ncei_official(self.official_pdo_path)
        if ncei is not None:
            ncei = self.series_to_ms(ncei)

        pdo, eof_map, explained = self._leading_eof(region)

        eof_path = self.OUT_DIR / f"PDO_EOF_{self.SUF_EXEC}.nc"
        eof_map.name = "PDO_EOF1"
        eof_map.to_netcdf(eof_path)
        print(format_log("SALVO", item=f"EOF principal Modo TESTE com {explained:.2%} variância explicada →", destino=str(eof_path)))

        clim_range = f"{clima_ini}:{clima_fim}"
        self._plot_eof_variance_map(
            eof_map,
            explained,
            modo="TESTE",
            dataset_nome="ERSSTv5",
            clim_range=clim_range,
            lat_bounds=(lat_min, lat_max),
            lon_bounds=(lon_min, lon_max),
        )

        if ncei is not None:
            df_out = pd.concat(
                [pdo.rename("PDO_calc"), ncei.rename("PDO_NCEI")],
                axis=1,
                join="inner"
            ).round(3)
        else:
            df_out = pd.DataFrame({"PDO_calc": pdo}).round(3)
        df_out = df_out.rename(columns={"PDO_calc": "PDO_CALC"})
        if "PDO_NCEI" in df_out.columns:
            df_out["diferenca"] = (df_out["PDO_CALC"] - df_out["PDO_NCEI"]).round(3)
        else:
            df_out["diferenca"] = np.nan
        df_out.index.name = "data"
        df_out = df_out.reset_index()
        out_csv = self.OUT_DIR_tables / f"PDO_indice-mensal_CALCvsNCEI_{self.SUF_EXEC}.csv"
        df_out.to_csv(out_csv, index=False, date_format="%Y-%m-%d")
        print(format_log("SALVO", item="Tabela PDO TESTE (EOF) →", destino=str(out_csv)))

        label = f"TESTE_{self.cfg.get('PDO_TESTE_NOME','sem_nome')}"
        self.validar_vs_ncei(pdo, label=label)
        self.plot_pdo_timeseries(pdo, label=label)


    def _run_externo(self):
        print(format_log("INFO", message="Rodando PDO Modo EXTERNO"))

        nome = str(self.cfg.get("PDO_EXTERNO_NOME", "EXTERNO"))
        caminho = Path(str(self.cfg.get("PDO_EXTERNO_CAMINHO", ""))).expanduser()
        if not caminho.exists():
            print(format_log("ERRO", message=f"Arquivo externo não encontrado: {caminho}"))
            return

        clima_cfg = str(self.cfg.get("PDO_EXTERNO_BASE_CLIMA", "1981-01:2010-12"))
        if ":" not in clima_cfg:
            raise ValueError(f"[ERRO] PDO_EXTERNO_BASE_CLIMA inválido: {clima_cfg}")
        clima_ini, clima_fim = [c.strip() for c in clima_cfg.split(":", 1)]

        lat_cfg_min = float(self.cfg.get("PDO_EXTERNO_LAT_MIN", 20))
        lat_cfg_max = float(self.cfg.get("PDO_EXTERNO_LAT_MAX", 70))
        lon_cfg_min = float(self.cfg.get("PDO_EXTERNO_LON_MIN", 110))
        lon_cfg_max = float(self.cfg.get("PDO_EXTERNO_LON_MAX", 260))
        lat_min, lat_max = min(lat_cfg_min, lat_cfg_max), max(lat_cfg_min, lat_cfg_max)
        lon_min, lon_max = min(lon_cfg_min, lon_cfg_max), max(lon_cfg_min, lon_cfg_max)
        self._last_bounds = (lon_min, lon_max, lat_min, lat_max)

        ds = xr.open_dataset(caminho)
        coord_map = {}
        if "valid_time" in ds.coords:
            coord_map["valid_time"] = "time"
        if "latitude" in ds.coords:
            coord_map["latitude"] = "lat"
        if "longitude" in ds.coords:
            coord_map["longitude"] = "lon"
        if "nav_lat" in ds.coords:
            coord_map["nav_lat"] = "lat"
        if "nav_lon" in ds.coords:
            coord_map["nav_lon"] = "lon"
        if coord_map:
            ds = ds.rename(coord_map)

        var_candidates = ["sst", "tsm", "tos", "sea_surface_temperature"]
        var_sst = next((v for v in var_candidates if v in ds.data_vars), None)
        if var_sst is None:
            raise ValueError(f"[ERRO] Nenhuma variável de SST encontrada em {list(ds.data_vars)}")

        sst = ds[var_sst]
        if not np.issubdtype(sst.time.dtype, np.datetime64):
            try:
                sst = xr.decode_cf(sst.to_dataset(name="sst"))["sst"]
            except Exception:
                print(format_log("ATENCAO", message="decode_cf falhou; forçando calendário mensal fixo."))
                sst = sst.assign_coords(time=pd.date_range("1900-01", periods=sst.sizes["time"], freq="MS"))

        sst = sst.assign_coords(time=self._to_month_start(sst.time.values))
        sst = sst.sortby("time")
        if sst.get_index("time").duplicated().any():
            mask = ~sst.get_index("time").duplicated(keep="first")
            sst = sst.isel(time=np.where(mask)[0])
        sst = sst.dropna("time", how="all")
        sst = self._normalize_lon(sst)
        sst = sst.sortby("lat")

        sst_anom = self._compute_anomalies(sst, clima_ini, clima_fim)
        sst_anom = self._remove_global_mean(sst_anom)
        region = self._prepare_region(sst_anom, lat_min=lat_min, lat_max=lat_max,
                                      lon_min=lon_min, lon_max=lon_max)
        print(format_log(
            "INFO",
            message=(
                f"PDO EXTERNO utilizando base climatológica {clima_ini}:{clima_fim} "
                f"na região lat {lat_min}–{lat_max}°, lon {lon_min}–{lon_max}°."
            )
        ))

        ncei = self.read_ncei_official(self.official_pdo_path)
        if ncei is not None:
            ncei = self.series_to_ms(ncei)

        pdo, eof_map, explained = self._leading_eof(region)

        eof_path = self.OUT_DIR / f"PDO_EOF_{self.SUF_EXEC}.nc"
        eof_map.name = "PDO_EOF1"
        eof_map.to_netcdf(eof_path)
        print(format_log("SALVO", item=f"EOF principal Modo EXTERNO com {explained:.2%} variância explicada →", destino=str(eof_path)))

        clim_range = f"{clima_ini}:{clima_fim}"
        self._plot_eof_variance_map(
            eof_map,
            explained,
            modo="EXTERNO",
            dataset_nome=nome,
            clim_range=clim_range,
            lat_bounds=(lat_min, lat_max),
            lon_bounds=(lon_min, lon_max),
        )

        if ncei is not None:
            df_out = pd.concat(
                [pdo.rename("PDO_calc"), ncei.rename("PDO_NCEI")],
                axis=1,
                join="inner"
            ).round(3)
        else:
            df_out = pd.DataFrame({"PDO_calc": pdo}).round(3)
        df_out = df_out.rename(columns={"PDO_calc": "PDO_CALC"})
        if "PDO_NCEI" in df_out.columns:
            df_out["diferenca"] = (df_out["PDO_CALC"] - df_out["PDO_NCEI"]).round(3)
        else:
            df_out["diferenca"] = np.nan
        df_out.index.name = "data"
        df_out = df_out.reset_index()
        out_csv = self.OUT_DIR_tables / f"PDO_indice-mensal_CALCvsNCEI_{self.SUF_EXEC}.csv"
        df_out.to_csv(out_csv, index=False, date_format="%Y-%m-%d")
        print(format_log("SALVO", item="Tabela PDO EXTERNO (EOF) →", destino=str(out_csv)))

        label = f"EXTERNO_{self._slug(nome)}"
        self.validar_vs_ncei(pdo, label=label)
        self.plot_pdo_timeseries(pdo, label=label)


    def plot_pdo_timeseries(self, serie: pd.Series, label: str = "PDO Calculado"):
        """
        Plota a série temporal do índice PDO calculado em estilo semelhante ao gráfico oficial NOAA.
        Adiciona logotipo se disponível.
        """
        if serie is None or serie.empty:
            print(format_log("ATENCAO", message="Série PDO vazia — não será plotada."))
            return

        fig, ax = plt.subplots(figsize=(14, 5))

        # Plotando positivo em vermelho e negativo em azul (como NOAA)
        serie_pos = serie.where(serie >= 0)
        serie_neg = serie.where(serie < 0)
        ax.bar(serie_pos.index, serie_pos.values, color="red", width=25, align="center", label="PDO positivo")
        ax.bar(serie_neg.index, serie_neg.values, color="blue", width=25, align="center", label="PDO negativo")

        
        # Ajuste de limites no eixo X para garantir início/fim corretos
        xmin, xmax = serie.index.min(), serie.index.max()
        ax.set_xlim([xmin, xmax])

        # Eixos e título
        ax.set_ylabel("PDO", fontsize=12)
        ax.set_xlabel("Ano", fontsize=12)
        ax.set_title(f"Oscilação Decadal do Pacífico (PDO) — Calculado com dados de TSM {label}", fontsize=14)

        # Grade discreta
        ax.grid(True, linestyle="--", alpha=0.5)

        # Logo (se existir)
        logo_path = Path("utils/atmosmarine.png")
        if logo_path.exists():
            img = mpimg.imread(str(logo_path))
            ab = AnnotationBbox(
                OffsetImage(img, zoom=0.04),
                (0.12, 0.14),             # posição no gráfico (eixo relativo)
                xycoords="axes fraction",
                box_alignment=(1, 1),
                frameon=False,
                zorder=10,
            )
            ax.add_artist(ab)

        # Ajustar layout
        plt.tight_layout()

        # Caminho de saída
        fpath = self.OUT_DIR_figs / f"PDO_serie-temporal_CALC_{self.SUF_EXEC}.png"
        plt.savefig(fpath, dpi=300, bbox_inches="tight")
        plt.close()
        print(format_log("SALVO", item="Figura série temporal PDO →", destino=str(fpath)))

    def plot_comparativo(self, pdo_gerado: pd.Series):
        # Lê a série PDO oficial do NCEI
        ncei = self.read_ncei_official(self.official_pdo_path, log_download=False)
        if ncei is None:
            print(format_log("ATENCAO", message="PDO oficial NCEI não carregou — nenhum comparativo gerado."))
            return

        # Alinha as séries
        pdo_g, pdo_n = pdo_gerado.align(ncei, join="inner")

        print(format_log("INFO", message="Alinhando séries para o comparativo PDO."))
        msg_calc = (
            f"PDO gerado: {pdo_gerado.index.min()} → {pdo_gerado.index.max()} "
            f"| n={len(pdo_gerado)} | NaNs={pdo_gerado.isna().sum()}"
        )
        print(format_log("INFO", message=msg_calc))
        msg_ref = (
            f"PDO oficial: {ncei.index.min()} → {ncei.index.max()} "
            f"| n={len(ncei)} | NaNs={ncei.isna().sum()}"
        )
        print(format_log("INFO", message=msg_ref))
        print(format_log("INFO", message=f"Interseção resultante: {len(pdo_g)} meses"))

        if pdo_g.empty or pdo_n.empty:
            print(format_log("ATENCAO", message="Séries alinhadas vazias — comparativo não será gerado."))
            return

        # Calcular viés (diferença ponto a ponto)
        bias = pdo_g - pdo_n

        # --- Plotagem com dois painéis ---
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 7),
            gridspec_kw={'height_ratios': [3, 1]}, sharex=True
        )

        # Painel superior: séries
        ax1.plot(pdo_g.index, pdo_g.values, label="PDO Calculado", color="blue")
        ax1.plot(pdo_n.index, pdo_n.values, label="PDO Oficial (NCEI)", color="red", linestyle="--")
        ax1.set_ylabel("Índice PDO")
        ax1.set_title("Comparativo PDO: Calculado (azul) vs Oficial NCEI (vermelho)")
        ax1.legend()
        ax1.grid(True, linestyle="--", alpha=0.5)

        # Painel inferior: viés
        ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax2.plot(bias.index, bias.values, color="gray", label="Viés (Calculado - Oficial)")
        ax2.set_ylabel("Viés")
        ax2.set_xlabel("Ano")
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend()

        # Logo
        logo_path = Path("src/atmosmarine.png")
        if logo_path.exists():
            import matplotlib.image as mpimg
            from matplotlib.offsetbox import OffsetImage, AnnotationBbox
            img = mpimg.imread(str(logo_path))
            ab = AnnotationBbox(
                OffsetImage(img, zoom=0.04),
                (0.52, 0.12),  # canto inferior direito
                xycoords="axes fraction",
                box_alignment=(1, 0),
                frameon=False,
                zorder=10,
            )
            ax1.add_artist(ab)

        plt.tight_layout()

        # Caminho de saída
        fpath = self.OUT_DIR_figs / f"PDO_serie-temporal_CALCvsNCEI_{self.SUF_EXEC}.png"
        plt.savefig(fpath, dpi=300, bbox_inches="tight")
        plt.close()
        print(format_log("SALVO", item="Figura comparativo PDO vs NCEI →", destino=str(fpath)))

    def _plot_comparativo_bias(self, pdo_calc: pd.Series, pdo_ref: pd.Series, label: str):
        """Plota comparação entre PDO calculado e oficial + série de viés."""
        bias = pdo_calc - pdo_ref

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 7),
            gridspec_kw={'height_ratios': [3, 1]}, sharex=True
        )

        # Painel superior
        ax1.plot(pdo_calc.index, pdo_calc.values, label=f"PDO Calculado", color="blue")
        ax1.plot(pdo_ref.index, pdo_ref.values, label="PDO NCEI", color="red", linestyle="--")
        ax1.set_ylabel("Índice PDO")
        ax1.set_title(f"Série Temporal Comparativa entre o Índice PDO Calculado (azul) vs Oficial do NCEI (vermelho)")
        ax1.legend()
        ax1.grid(True, linestyle="--", alpha=0.5)

        # Painel inferior
        ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax2.plot(bias.index, bias.values, color="gray", label="Viés (Calculado - Oficial)")
        ax2.set_ylabel("Viés")
        ax2.set_xlabel("Ano")
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend()

        # === Ajuste: alinhar origem no eixo temporal ===
        xmin = min(pdo_calc.index.min(), pdo_ref.index.min())
        xmax = max(pdo_calc.index.max(), pdo_ref.index.max())
        ax1.set_xlim([xmin, xmax])  # força início no primeiro ponto disponível
        ax2.set_xlim([xmin, xmax])  # mesmo limite para bias

        # Logo
        logo_path = Path("src/atmosmarine.png")
        if logo_path.exists():
            import matplotlib.image as mpimg
            from matplotlib.offsetbox import OffsetImage, AnnotationBbox
            img = mpimg.imread(str(logo_path))
            ab = AnnotationBbox(
                OffsetImage(img, zoom=0.04),
                (0.12, 0.02), xycoords="axes fraction",
                box_alignment=(1, 0), frameon=False, zorder=10,
            )
            ax1.add_artist(ab)

        # plt.tight_layout()
        # fpath = self.OUT_DIR_figs / f"PDO_CALCvsNCEI_{label}_{self.SUF_EXEC}.png"
        # plt.savefig(fpath, dpi=300, bbox_inches="tight")
        # plt.close()
        # print(f"[PLOTAGEM] Comparativo PDO + Viés salvo em {fpath}")

       
    
    def validar_vs_ncei(self, serie: pd.Series, label: str = "ERSSTv5"):
        """Valida uma série PDO contra o NCEI e salva métricas + gráfico comparativo."""

        ncei = self.read_ncei_official(self.official_pdo_path, log_download=False)
        if ncei is None:
            print(format_log("ATENCAO", message="PDO oficial NCEI não carregou — sem validação."))
            return

        # Alinhar séries
        s1, s2 = serie.align(ncei, join="inner")
        if s1.empty or s2.empty:
            print(format_log("ATENCAO", message="Séries alinhadas vazias — sem validação."))
            return

        # -------------------------
        # Plot comparativo + viés
        # -------------------------
        self._plot_comparativo_bias(s1, s2, label)

        # -------------------------
        # Métricas estatísticas
        # -------------------------
        from sklearn.metrics import mean_squared_error, mean_absolute_error
        import scipy.stats as stats

        diff = s1.values - s2.values
        rmse = np.sqrt(mean_squared_error(s2, s1))
        mae = mean_absolute_error(s2, s1)
        bias = np.mean(diff)
        corr, _ = stats.pearsonr(s1.values, s2.values)
        slope, intercept, r_val, _, _ = stats.linregress(s2.values, s1.values)
        r2 = r_val**2
        std_err = np.std(diff, ddof=1)

        row = {
            "fonte": f"{label} vs NCEI",
            "data_inicio": str(s1.index.min().date()),
            "data_fim": str(s1.index.max().date()),
            "n_registros": int(len(s1)),
            "rmse": round(rmse, 3),
            "mae": round(mae, 3),
            "bias": round(bias, 3),
            "corr": round(corr, 3),
            "r2": round(r2, 3),
            "slope": round(slope, 3),
            "intercept": round(intercept, 3),
            "desv_pad_erro": round(std_err, 3),
        }
        cols_order = [
            "fonte", "data_inicio", "data_fim", "n_registros",
            "rmse", "mae", "bias", "corr", "r2", "slope", "intercept", "desv_pad_erro",
        ]
        df_metrics = pd.DataFrame([row])
        df_metrics = df_metrics[[c for c in cols_order if c in df_metrics.columns] + [c for c in df_metrics.columns if c not in cols_order]]

        # -------------------------
        # Ajuste do nome de saída
        # -------------------------
        if self.modo == "TESTE":
            teste_nome = self.cfg.get("PDO_TESTE_NOME", "sem_nome")
            fname = f"PDO_metricas_estatisticas_{self.SUF_EXEC}.csv"
        else:
            fname = f"PDO_metricas_estatisticas_{self.SUF_EXEC}.csv"

        out_csv = self.OUT_DIR_valida / fname
        df_metrics.to_csv(out_csv, index=False)
        print(format_log("SALVO", item="Métricas PDO salvas →", destino=str(out_csv)))


        # --- Novo: também gera o comparativo + bias ---
        self._plot_comparativo_bias(s1, s2, label)

    
    def _plot_eof_variance_map(
        self,
        eof_map: xr.DataArray,
        explained: float,
        modo: str = "REFERENCIA",
        dataset_nome: str = "TSM",
        clim_range: str = "",
        lat_bounds: tuple[float, float] = (20, 70),
        lon_bounds: tuple[float, float] = (110, 260),
    ):
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        from matplotlib.patches import Polygon
        from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

        fig, ax = plt.subplots(figsize=(12, 6),
                            subplot_kw={'projection': ccrs.PlateCarree(central_longitude=180)})

        ax.set_extent([80, 280, 0, 90], crs=ccrs.PlateCarree())
        ax.coastlines(resolution="110m", linewidth=0.8)
        ax.add_feature(cfeature.BORDERS, linewidth=0.5)

        lons = (eof_map.lon.values + 360) % 360
        lons = np.sort(lons)
        lats = eof_map.lat.values

        pcm = ax.pcolormesh(
            lons,
            lats,
            eof_map,
            cmap="RdBu_r",
            shading="auto",
            transform=ccrs.PlateCarree(),
        )

        # polígono de limites
        if hasattr(self, "_last_bounds"):
            lon0, lon1, lat0, lat1 = self._last_bounds
            poly_coords = [(lon0, lat0), (lon1, lat0),
                        (lon1, lat1), (lon0, lat1), (lon0, lat0)]
            poly = Polygon(poly_coords, closed=True,
                        edgecolor="black", facecolor="none",
                        linewidth=1.5, linestyle="--",
                        transform=ccrs.PlateCarree())
            ax.add_patch(poly)

        ax.xaxis.set_major_formatter(LongitudeFormatter(zero_direction_label=True))
        ax.yaxis.set_major_formatter(LatitudeFormatter())
        ax.set_xticks(np.arange(80, 281, 20), crs=ccrs.PlateCarree())
        ax.set_yticks(np.arange(0, 91, 10), crs=ccrs.PlateCarree())

        cbar = plt.colorbar(pcm, ax=ax, orientation="vertical", shrink=0.7, pad=0.05)
        cbar.set_label("EOF1 (adimensional)")

        ax.set_title(
            f"PDO EOF1 | TSM {dataset_nome} | Base {clim_range} | Var. explicada {explained:.1%}",
            fontsize=10,
        )

        fpath = self.OUT_DIR_figs / f"PDO_EOF_{self.SUF_EXEC}.png"
        plt.savefig(fpath, dpi=300, bbox_inches="tight")
        plt.close()
        print(format_log("SALVO", item="Mapa EOF1 PDO →", destino=str(fpath)))
