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
from .atm_tools import validate_config_ONI
from src.logging import format_log

def _cfg_message(message: str) -> str:
    return format_log("ERRO_CONF", message=message)

class ONI:
    # janelas base do CPC por quinquenios
    PERIODOS_BASE = {
        (1950, 1955): (1936, 1965), (1956, 1960): (1941, 1970),
        (1961, 1965): (1946, 1975), (1966, 1970): (1951, 1980),
        (1971, 1975): (1956, 1985), (1976, 1980): (1961, 1990),
        (1981, 1985): (1966, 1995), (1986, 1990): (1971, 2000),
        (1991, 1995): (1976, 2005), (1996, 2000): (1981, 2010),
        (2001, 2005): (1986, 2015), (2006, 2010): (1991, 2020),
    }

    LABELS_TRIS = {1:"DJF",2:"JFM",3:"FMA",4:"MAM",5:"AMJ",6:"MJJ",
                   7:"JJA",8:"JAS",9:"ASO",10:"SON",11:"OND",12:"NDJ"}
    
        # ----------------- Helpers para parse seguro -----------------
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

    def _as_int(self, v, default=0) -> int:
        try:
            s = self._strip_comment(v)
            return int(float(s)) if s not in ("", None) else int(default)
        except Exception:
            return int(default)

    def _slug(self, s: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "" for ch in (s or "")) or "externo"

    def _update_base_policy(self, nino34: pd.Series):
        """Ativa a base 1996–2025 para 2011–2015 so quando:
        (a) data atual>= 2026-02-01, e (b) existe 12/2025 na serie."""
        try:
            eff = _dt.date.fromisoformat(self.NEWBASE_EFFECTIVE_DATE)
        except Exception:
            eff = _dt.date(2026, 2, 1)
        today = _dt.date.today()

        has_dec_2025 = any((idx.year == 2025 and idx.month == 12) for idx in nino34.index)
        if (today >= eff) and has_dec_2025:
            self.NEWBASE_ACTIVE = True
            self.ANO_MAX_BASE   = 2025
        else:
            self.NEWBASE_ACTIVE = False
            self.ANO_MAX_BASE   = self.ANO_MAX_BASE_DEFAULT

        # guarda limites reais da serie para adaptar pre-inicio
        self.ANO_MIN_SERIE = int(nino34.index.year.min())
        self.ANO_MAX_SERIE = int(nino34.index.year.max())

    def _warn(self, msg: str):
         print(format_log("ATENCAO", message=f"{msg}"))

    def _safe_float_cfg(self, key: str, default: float, *,
                        kind: str = "",
                        min_val: float | None = None,
                        max_val: float | None = None,
                        normalize_lon: bool = False) -> float:
        raw = self.cfg.get(key, default)
        s_raw = str(self._strip_comment(raw))

        # correcoes de digitacao comuns (—,–,− -> -) e O/o -> 0
        s_fix = (s_raw.replace("—", "-").replace("–", "-").replace("−", "-")
                    .replace("O", "0").replace("o", "0"))

        # avisa se houve correcao de caracteres ambiguos
        if s_fix != s_raw:
            self._warn(f"{key}='{s_raw}' interpretado como '{s_fix}'.")

        try:
            val = float(s_fix)
        except Exception:
            self._warn(f"{key} invalido ('{raw}') → usando valor padrão {default}.")
            val = float(default)

        # normalizacao de longitude para [-180, 180]
        if normalize_lon:
            v0 = val
            val = ((val + 180.0) % 360.0) - 180.0
            if not np.isclose(v0, val):
                self._warn(f"{key}={v0} normalizado para {val} (faixa [-180,180]).")

        # clamp opcional
        if min_val is not None and val < min_val:
            self._warn(f"{key}={val} abaixo de {min_val} → ajustando para {min_val}.")
            val = min_val
        if max_val is not None and val > max_val:
            self._warn(f"{key}={val} acima de {max_val} → ajustando para {max_val}.")
            val = max_val

        if kind.lower() == "latitude" and not (-90.0 <= val <= 90.0):
            self._warn(f"{key}={val} fora de [-90,90] → ajustando para dentro do intervalo.")
            val = max(-90.0, min(90.0, val))

        return float(val)


    def _safe_int_cfg(self, key: str, default: int, *,
                    min_val: int | None = None,
                    max_val: int | None = None) -> int:
        raw = self.cfg.get(key, default)
        s_raw = str(self._strip_comment(raw))
        s_fix = (s_raw.replace("—", "-").replace("–", "-").replace("−", "-")
                    .replace("O", "0").replace("o", "0"))

        if s_fix != s_raw:
            self._warn(f"{key}='{s_raw}' interpretado como '{s_fix}'.")

        try:
            val = int(float(s_fix))
        except Exception:
            self._warn(f"{key} invalido ('{raw}') → usando valor padrão {default}.")
            val = int(default)

        # Heuristica especial para ANO: detectar zero extra (e.g., 19200 -> 1920)
        key_lower = key.lower()
        if ("ano" in key_lower or "year" in key_lower) and (min_val is not None or max_val is not None):
            lo = min_val if min_val is not None else -10**9
            hi = max_val if max_val is not None else 10**9
            if not (lo <= val <= hi):
                # tenta corrigir removendo UM zero a direita (caso muito comum)
                if val % 10 == 0:
                    candidate = val // 10
                    if lo <= candidate <= hi:
                        self._warn(f"{key}={val} fora da faixa → interpretado como {candidate} (removido um zero).")
                        val = candidate
                    else:
                        # sem correcao plausivel -> volta pro default e sugere faixa
                        self._warn(f"{key}={val} fora da faixa [{lo},{hi}] → usando valor padrão {default}.")
                        val = int(default)
                else:
                    self._warn(f"{key}={val} fora da faixa [{lo},{hi}] → usando valor padrão {default}.")
                    val = int(default)

        # Clamp final (casos nao-ANO ou apos correcao)
        if min_val is not None and val < min_val:
            self._warn(f"{key}={val} abaixo de {min_val} → ajustando para {min_val}.")
            val = int(min_val)
        if max_val is not None and val > max_val:
            self._warn(f"{key}={val} acima de {max_val} → ajustando para {max_val}.")
            val = int(max_val)

        return int(val)


    # ------------------------- __init__ ---------------------------
    def __init__(self, cfg: dict | None = None):
        validate_config_ONI(cfg)
        self.cfg = cfg or {}
        self.SUF_EXEC = _dt.datetime.now().strftime("%Y%m")

        # Pastas base
        self.DATA_DIR = Path("data"); self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR = self.DATA_DIR / "cache"; self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.CPC_CACHE_DIR = self.CACHE_DIR / "ONI"; self.CPC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.arquivo_nc   = self.DATA_DIR / "ersst_v5.nc"
        self.url_ersstv5  = "https://downloads.psl.noaa.gov/Datasets/noaa.ersst.v5/sst.mnmean.nc"

        # ----------------- Modo -----------------
        self.MODO = str(self.cfg.get("ONI_MODO", "REFERENCIA")).strip().upper()
        if self.MODO == "VALIDACAO":
            self.MODO = "REFERENCIA"

        def _defaults_regiao():
            return (-5.0, 5.0, -170.0, -120.0)

        # ----------------- Defaults seguros (antes de usar) -----------------
        self.lat_min, self.lat_max, self.lon_min, self.lon_max = _defaults_regiao()
        self.ano_inicio   = 1949
        self.output_ano_inicio = 1950
        self.NOME_SST     = "ERSSTv5"   # <- garante que existe
        self.NOME_TESTE   = ""
        self.CAMINHO_SST  = ""
        self.PADRONIZAR_CSV = False

                # --- Controles de politica de base climatologica (dinamica) ---
        self.ANO_MAX_BASE_DEFAULT = int(self.cfg.get("ONI_ANO_MAX_BASE", 2020))  # teto CPC atual
        self.ANCORA_QUINQ         = int(self.cfg.get("ONI_ANCORA_QUINQ", 1950))  # ancora quinquenios
        self.PREMIN_POLICY        = str(self.cfg.get("ONI_PREMIN", "CLAMP")).upper()  # CLAMP|DROP|FIXED
        self.PREMIN_FIXEDBASE     = tuple(map(int, str(self.cfg.get("ONI_PREMIN_FIXEDBASE", "1901,1930")).split(",")))

        # Virada 1996–2025 para anos 2011–2015 (ativa so a partir de 2026-02-01 E se houver 12/2025 na serie)
        self.NEWBASE_EFFECTIVE_DATE = self.cfg.get("ONI_NEWBASE_EFFECTIVE_DATE", "2026-02-01")
        self.NEWBASE_ACTIVE = False
        self.ANO_MAX_BASE   = self.ANO_MAX_BASE_DEFAULT

        # Guardas dos limites reais da serie (preenchidos em _update_base_policy)
        self.ANO_MIN_SERIE = None
        self.ANO_MAX_SERIE = None

        # ----------------- Especifico por modo (sobrescreve se preciso) -----------------
        if self.MODO == "TESTE":
            # lat/lon com validacao + normalizacao
            self.lat_min = self._safe_float_cfg("ONI_TESTE_LAT_MIN", self.cfg.get("LAT_MIN", -5),
                                                kind="latitude")
            self.lat_max = self._safe_float_cfg("ONI_TESTE_LAT_MAX", self.cfg.get("LAT_MAX",  5),
                                                kind="latitude")
            self.lon_min = self._safe_float_cfg("ONI_TESTE_LON_MIN", self.cfg.get("LON_MIN", -170),
                                                normalize_lon=True)
            self.lon_max = self._safe_float_cfg("ONI_TESTE_LON_MAX", self.cfg.get("LON_MAX", -120),
                                                normalize_lon=True)

            # ano inicio com sanidade (minimo 1854 por causa do ERSST; pode ajustar)
            self.ano_inicio = self._safe_int_cfg("ONI_TESTE_ANO_INICIO", self.cfg.get("ANO_INICIO", 1949),
                                                min_val=1854, max_val=2100)
            self.output_ano_inicio = max(1950, self.ano_inicio)

            # rotulos
            self.NOME_SST = "ERSSTv5"
            self.NOME_TESTE = self._strip_comment(
                self.cfg.get("ONI_TESTE_NOME") or self.cfg.get("NOME_TESTE") or self.NOME_SST or "sem_nome"
            )
            self.CAMINHO_SST = ""
            self.PADRONIZAR_CSV = False

            # aviso rapido se lat_min > lat_max (invertido)
            if self.lat_min > self.lat_max:
                self._warn(f"ONI_LAT_MIN({self.lat_min}) > ONI_LAT_MAX({self.lat_max}); invertendo.")
                self.lat_min, self.lat_max = self.lat_max, self.lat_min


            # rotulo para nomes de arquivos/plots
            self.NOME_SST = "ERSSTv5"
            self.NOME_TESTE = self._strip_comment(
                self.cfg.get("ONI_TESTE_NOME") or self.cfg.get("NOME_TESTE") or self.NOME_SST or "sem_nome"
            )
            self.CAMINHO_SST = ""
            self.PADRONIZAR_CSV = False


        elif self.MODO == "EXTERNO":
            # Regiao nao usada, mas mantemos defaults
            self.ano_inicio = self._safe_int_cfg(
                "ONI_TESTE_ANO_INICIO", self.cfg.get("ANO_INICIO", 1949),
                min_val=1700, max_val=2100
            )
            self.output_ano_inicio = max(1950, self.ano_inicio)

            # Novo nome em PT-BR com fallback:
            label_ext = self._strip_comment(
                self.cfg.get("ONI_EXTERNO_TSM")   # nome novo
                or self.cfg.get("ONI_EXTERNO_SST")  # fallback antigo
                or self.cfg.get("ONI_NOME_TSM")
                or self.cfg.get("ONI_NOME_SST")
                or self.cfg.get("NOME_TSM")
                or self.cfg.get("NOME_SST")
                or "EXTERNO"
            )
            self.NOME_SST = label_ext or "EXTERNO"  # rotulo para paths/figuras

            # Caminho do CSV externo (com limpeza basica + ~ expansion)
            self.CAMINHO_SST = self._strip_comment(
                self.cfg.get("ONI_EXTERNO_CAMINHO_TSM") or self.cfg.get("ONI_EXTERNO_CAMINHO") or ""
            )
            if self.CAMINHO_SST:
                _p = Path(self.CAMINHO_SST).expanduser()
                if not _p.exists():
                    self._warn(f"ONI_EXTERNO_CAMINHO_TSM nao existe: {self.CAMINHO_SST}")
            self.PADRONIZAR_CSV = False

        # ----------------- Pastas de saida -----------------
        base = OUTPUT_ROOT / "ONI"
        if self.MODO == "REFERENCIA":
            raiz = base / "REFERENCIA"
        elif self.MODO == "TESTE":
            raiz = base / f"TESTE_{self._slug(self.NOME_TESTE)}"
        else:  # EXTERNO
            raiz = base / f"EXTERNO_{self._slug(self.NOME_SST)}"  # usa o rotulo ja resolvido

        self.OUT_DIR = raiz
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.OUT_DIR_tables = self.OUT_DIR
        self.OUT_DIR_figs   = self.OUT_DIR
        self.OUT_DIR_valida = self.OUT_DIR

        # ----------------- Tags/paths que dependem de NOME_SST -----------------
        self.tag = self._slug(self.NOME_SST)
        self.csv_sst_path = self.OUT_DIR_tables / f"ONI_TSM-media-nino34_{self.SUF_EXEC}.csv"

        self.ds = None
        return


    def _slug(self, s: str) -> str:
        """Slug seguro para nomes de arquivo."""
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "" for ch in s)


    # ======== ORQUESTRAcaO ========
    def run(self):
        if self.MODO == "EXTERNO":
            if not self.CAMINHO_SST:
                raise ValueError(_cfg_message("ONI_EXTERNO_CAMINHO_TSM nao informado no modo EXTERNO"))

            nino34 = self._carregar_sst_csv(Path(self.CAMINHO_SST))
            if self.PADRONIZAR_CSV:
                self._salvar_sst_csv(nino34, self.csv_sst_path)
                print(format_log("ATENCAO", message=f"CSV externo padronizado em: {self.csv_sst_path}"))
            self._update_base_policy(nino34)
        else:
            # (REFERENCIA ou TESTE) -> ERSSTv5
            self._download()

            # Se nao houver arquivo local apos tentativa de download, nao quebra:
            if not self.arquivo_nc.exists():
                print(format_log("ATENCAO", message="Arquivo TSM ERSSTv5 indisponível na fonte e nenhuma cópia local encontrada"))
                print(format_log("ATENCAO", message="Impossível calcular ONI nos modos REFERENCIA e TESTE"))
                return

            self._open_dataset()
            nino34_total = self._recorte_oni()

            suffix = self._sufixo_nome(nino34_total)
            csv_sst_suffix = self.OUT_DIR_tables / f"ONI_TSM-media-nino34_{self.SUF_EXEC}.csv"
            self._salvar_sst_csv(nino34_total, csv_sst_suffix)
            nino34 = self._carregar_sst_csv(csv_sst_suffix)
            self._update_base_policy(nino34)

        suffix  = self._sufixo_nome(nino34)
        oni_raw = self._media_movel_trimestre(nino34)
        oni_final = self._anomalia_trimestral(oni_raw)
        tabela = self._tabela_trimestral(oni_final)

        produtos = self._produtos_oni(suffix, tabela, nino34)

        if self.MODO == "TESTE":
            try:
                self._plot_regiao_oni_bbox(suffix)
            except Exception as e:
                print(format_log("ERRO", message=f"Falha ao plotar região ONI no modo TESTE: {e}"))

        seasonal_df = produtos.get("seasonal_df")
        if seasonal_df is None or seasonal_df.empty:
            print(format_log("ERRO", message="Série trimestral do ONI vazia para validação."))
            return

        # Validação nunca deve abortar execução se cair
        try:
            self._validacao(seasonal_df, suffix)
        except Exception as e:
            print(format_log("ATENCAO", message=f"Validação CPC pulada: {e}"))


    # ======== DOWNLOAD/ABERTURA ========
    def _download(self):
        print(format_log("INFO", message=f"Verificando o arquivo de TSM ERSSTv5"))

        lm_remote_ts = None
        size_remote = None
        head_ok = False
        try:
            req = urllib.request.Request(self.url_ersstv5, method="HEAD")
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
                    f"({e.__class__.__name__}) para saber se existe versão mais nova do ERSSTv5. "
                    "Usaremos a versão atual local."
                ),
            ))

        # Se ja existe local, decide se precisa atualizar
        if self.arquivo_nc.exists():
            if head_ok and lm_remote_ts is not None:
                mtime_local = os.path.getmtime(self.arquivo_nc)
                tamanhos_batem = (size_remote is None) or (self.arquivo_nc.stat().st_size == size_remote)
                if mtime_local >= lm_remote_ts and tamanhos_batem:
                    print(format_log("INFO", message="Arquivo ERSSTv5 local está atualizado – sem necessidade de download."))
                    return
                else:
                    print(format_log("INFO", message="Versão disponível no servidor possivelmente mais atual → atualizando ERSSTv5."))
            else:
                print(format_log("INFO", message="Sem informações do arquivo remoto → utilizando arquivo local existente."))
                return

        # Precisa baixar (ou nao existe localmente)
        print(format_log("DOWNLOAD", target="ERSSTv5", dest=str(self.arquivo_nc), reason="Iniciando o download..."))

        try:
            tmp_file, _ = urllib.request.urlretrieve(self.url_ersstv5)
            shutil.move(tmp_file, self.arquivo_nc)
            print(format_log("DOWNLOAD", target="ERSSTv5", dest=str(self.arquivo_nc), reason="download concluído!"))
        except Exception as e:
            if self.arquivo_nc.exists():
                print(format_log(
                    "ATENCAO",
                    message=f"Falha ao baixar ERSSTv5 ({e.__class__.__name__}: {e}). Usando cópia local existente.",
                ))
                return
            # Sem copia local: nao quebra — apenas informa e deixa o caller decidir (run() ja trata)
            print(format_log(
                "ERRO",
                message=f"ERSSTv5 indisponível ({e.__class__.__name__}: {e}) e nenhuma cópia local foi encontrada.",
            ))
            return
    
    def _open_dataset(self):
        print(format_log("INFO", message=f"Abrindo NetCDF: {self.arquivo_nc}"))
        self.ds = xr.open_dataset(self.arquivo_nc)


    # ======== CaLCULOS (ERSST -> serie TOTAL) ========
    def _recorte_oni(self) -> pd.Series:
        """Retorna serie mensal media (TOTAL) de SST na Nino‑3.4 como pandas.Series."""
        if self.ds is None:
            raise RuntimeError(format_log("ERRO", message="Dataset ERSSTv5 não carregado antes do recorte da Região do Niño 3.4."))
        ds = self.ds
        lat_name = "lat" if "lat" in ds.coords else "latitude"
        lon_name = "lon" if "lon" in ds.coords else "longitude"

        lat_min, lat_max = self.lat_min, self.lat_max
        lon_min, lon_max = self.lon_min, self.lon_max

        # ---- normalizacao de longitudes para o sistema do dataset ----
        lon_vals = ds[lon_name]
        Lmin = float(lon_vals.min())   # 0 se 0..360; -180 se -180..180
        Lmax = float(lon_vals.max())   # 360-delta ou 180

        def to_ds_lon(v):
            if Lmin >= 0:             # dataset 0..360
                v = v % 360.0
                return v if v >= 0 else v + 360.0
            else:                     # dataset -180..180
                return ((v + 180.0) % 360.0) - 180.0

        a = to_ds_lon(lon_min)
        b = to_ds_lon(lon_max)

        # selecao em latitude (dataset geralmente decrescente em lat)
        lat_slice = slice(lat_max, lat_min)

        # ---- selecao em longitude com suporte a wrap-around ----
        if a <= b:
            # faixa "normal", continua
            subset = ds.sel({lat_name: lat_slice, lon_name: slice(a, b)})
        else:
            # wrap-around: concatena [a..max] com [min..b]
            left  = ds.sel({lat_name: lat_slice, lon_name: slice(a, Lmax)})
            right = ds.sel({lat_name: lat_slice, lon_name: slice(Lmin, b)})
            subset = xr.concat([left, right], dim=lon_name, data_vars="minimal", coords="minimal")


        weights = np.cos(np.deg2rad(subset[lat_name]))
        sst = subset["sst"]
        nino34 = sst.weighted(weights).mean(dim=[lat_name, lon_name])
        return nino34.to_series()

    # ======== NEW: IO da serie em CSV ========
    def _salvar_sst_csv(self, serie_total: pd.Series, path_csv: Path):
        """
        Salva a serie mensal TOTAL (Nino‑3.4) em CSV com cabecalho:
        ano;mes;tsm
        """
        df = (
            serie_total.dropna()
                       .rename("tsm")
                       .to_frame()
        )
        df["ano"] = df.index.year
        df["mes"] = df.index.month
        out = df[["ano", "mes", "tsm"]].reset_index(drop=True)
        path_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path_csv, sep=",", index=False)
        print(format_log("SALVO", item=f"Série temporal da TSM na região do Niño‑3.4 →", destino=f"{path_csv}"))
 
    def _carregar_sst_csv(self, path_csv: Path) -> pd.Series:
        """
        Le CSV (ano;mes;tsm) e retorna pandas.Series TOTAL indexada por data (YYYY‑MM‑01).
        """
        if not Path(path_csv).exists():
            raise FileNotFoundError(f"CSV nao encontrado: {path_csv}")

        df = pd.read_csv(path_csv, sep=None, engine="python")
        # normalizar nomes de colunas
        cols = {c.lower().strip(): c for c in df.columns}
        col_ano = cols.get("ano") or cols.get("year")
        col_mes = cols.get("mes") or cols.get("month")
        col_val = cols.get("tsm") or cols.get("sst_nino34") or cols.get("sst")

        if not (col_ano and col_mes and col_val):
            raise RuntimeError(format_log("ERRO", message="arquivo CSV deve conter as colunas: 'ano', 'mes', 'tsm'."))

        df = df.rename(columns={col_ano: "ano", col_mes: "mes", col_val: "sst"})
        df = df.dropna(subset=["ano", "mes", "sst"])
        df["ano"] = df["ano"].astype(int)
        df["mes"] = df["mes"].astype(int)
        df["sst"] = pd.to_numeric(df["sst"], errors="coerce")
        df = df.dropna(subset=["sst"])
        # criar indice de datas (dia 1 de cada mes)
        datas = pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=1))
        serie = pd.Series(df["sst"].values, index=datas).sort_index()
        return serie

    def _sufixo_nome(self, nino34: pd.Series) -> str:
        last_date = nino34.dropna().index.max()
        suffix = f"{last_date.month:02d}{last_date.year}"
        return suffix

    def _media_movel_trimestre(self, nino34: pd.Series) -> pd.Series:
        """Media movel 3 meses (TOTAL). Mantem pontos com pelo menos 2 meses validos."""

        return nino34.rolling(window=3, center=True, min_periods=2).mean()

        # mm3 = nino34.rolling(3, center=True).mean()
        # mm3 = mm3[mm3.rolling(3, center=True).count() >= 2]
        # return mm3

    def _periodo_base(self, ano: int, ano_max: int, ano_min_dados: int | None = None) -> tuple[int, int] | None:
        """
        Retorna (b_ini, b_fim) de 30 anos para calcular a climatologia:
        * 2016+  -> 1991–2020 (ate 2031)
        * 2011–2015 -> 1991–2020, mas troca para 1996–2025 se NEWBASE_ACTIVE=True (a partir de 02/2026 e com 12/2025 disponivel)
        * 1950–2010 -> usa PERIODOS_BASE existente (compatibilidade)
        * <1950   -> gera quinquenios 'a la CPC' e ajusta as bordas reais da serie (CSV/ERSST)
        * < inicio da serie -> aplica politica PREMIN: CLAMP (padrao), DROP ou FIXED(1901–1930, p.ex.)
        O intervalo final e sempre de 30 anos inclusivos.
        """
        # 1) Pos-2010 (regras operacionais)
        if ano >= 2016:
            return 1991, 2020
        if 2011 <= ano <= 2015:
            return (1996, 2025) if getattr(self, "NEWBASE_ACTIVE", False) else (1991, 2020)

        # 2) Tenta o dicionario oficial (1950..2010)
        for (i, f), (b_i, b_f) in self.PERIODOS_BASE.items():
            if i <= ano <= f:
                return b_i, min(b_f, ano_max)

        # 3) Fora do dicionario -> periodo antigo (pre-1950) ou CSV muito antigo
        if ano_min_dados is None:
            ano_min_dados = getattr(self, "ANO_MIN_SERIE", 1854)
        hard_min = ano_min_dados
        hard_max = min(ano_max, getattr(self, "ANO_MAX_BASE", 2020))

        # 3a) Ano anterior ao inicio da serie: aplica politica
        if ano < hard_min:
            pol = getattr(self, "PREMIN_POLICY", "CLAMP")
            if pol == "DROP":
                return None
            if pol == "FIXED":
                b_ini, b_fim = self.PREMIN_FIXEDBASE
                b_ini = max(b_ini, hard_min); b_fim = min(b_fim, hard_max)
                # normaliza para 30 anos
                if (b_fim - b_ini + 1) < 30:
                    b_ini = max(hard_min, min(b_ini, hard_max - 29))
                    b_fim = b_ini + 29
                return b_ini, b_fim
            # CLAMP: primeiro bloco completo dentro da serie
            return hard_min, min(hard_min + 29, hard_max)

        # 3b) Gera quinquenio "a la CPC" para o ano alvo
        anchor = getattr(self, "ANCORA_QUINQ", 1950)
        start  = ano - ((ano - anchor) % 5)   # inicio do quinquenio contendo 'ano'
        endblk = start + 4

        # Janela alvo 'CPC-like': [start-15, endblk+10] -> 30 anos
        b_ini = start - 15
        b_fim = endblk + 10

        # 3c) Aparos as bordas disponiveis e recomposicao para 30 anos inclusivos
        if b_ini < hard_min:
            b_ini = hard_min
            b_fim = b_ini + 29
        if b_fim > hard_max:
            b_fim = hard_max
            b_ini = b_fim - 29

        if (b_fim - b_ini + 1) != 30:
            span = 30
            mid  = max(hard_min + span//2, min((b_ini + b_fim)//2, hard_max - span//2))
            b_ini = int(mid - (span//2) + 1)
            b_fim = b_ini + span - 1

        return int(b_ini), int(b_fim)

    def _anomalia_trimestral(self, oni_raw: pd.Series) -> pd.Series:
        """ANOM = TOTAL(3m) - climatologia mensal no periodo-base CPC variavel (30 anos)."""
        if oni_raw.empty:
            return oni_raw

        anom_list = []
        idx = oni_raw.index
        ano_max = int(idx.year.max())
        ano_min = int(idx.year.min())

        # vetores auxiliares para mascara rapida
        anos  = idx.year.to_numpy()
        meses = idx.month.to_numpy()

        for data, total in oni_raw.items():
            if pd.isna(total):
                anom_list.append(np.nan)
                continue

            # escolhe base adequada (dinamica). Pode retornar None se PREMIN=DROP
            base = self._periodo_base(data.year, ano_max, ano_min_dados=ano_min)
            if base is None:
                anom_list.append(np.nan)
                continue

            b_ini, b_fim = base

            # mesma logica mensal do CPC: media do MES dentro da janela de 30 anos
            mask = ((anos >= b_ini) & (anos <= b_fim) & (meses == data.month))
            if not mask.any():
                anom_list.append(np.nan)
                continue

            clim = float(oni_raw[mask].mean())
            if np.isnan(clim):
                anom_list.append(np.nan)
                continue

            anom_list.append(total - clim)

        oni_final = pd.Series(anom_list, index=oni_raw.index).round(1)
        return oni_final

    def _tabela_trimestral(self, oni_final: pd.Series) -> pd.DataFrame:
        """Retorna tabela larga (Year, DJF..NDJ) com valores formatados em string."""
        labels = self.LABELS_TRIS
        tabela = pd.DataFrame(columns=["Year"] + list(labels.values()))
        for data, val in oni_final.items():
            ano, mes = data.year, data.month
            if pd.isna(val):
                continue
            if mes == 12:
                ref_ano, tri = ano, "NDJ"
            elif mes == 1:
                ref_ano, tri = ano, "DJF"
            else:
                ref_ano, tri = ano, labels[mes]

            if ref_ano not in tabela["Year"].values:
                linha_vazia = {"Year": ref_ano, **{l: "" for l in labels.values()}}
                tabela = pd.concat([tabela, pd.DataFrame([linha_vazia])], ignore_index=True)

            idx = tabela.index[tabela["Year"] == ref_ano][0]
            tabela.at[idx, tri] = f"{val:.1f}"

        tabela = tabela.query("Year >= @self.output_ano_inicio").reset_index(drop=True)
        return tabela
    
    # ======== PRODUTOS ========
    def _produtos_oni(self, suffix: str, tabela: pd.DataFrame, nino34: pd.Series):

        # 1) CSV mensal derivado
        monthly_csv_path = self._exportar_mensal_de_tabela(tabela)

        # 2) DataFrame trimestral (para validação e plots)
        seasonal_df = self._montar_trimestral_df(tabela)

        # 3) Gráficos trimestrais (tabela e série)
        self._plot_tabela_png(suffix, tabela)
        self._plot_timeseries_png(suffix, tabela)

        return {
            "monthly_csv": monthly_csv_path,
            "seasonal_df": seasonal_df,
        }

    def _exportar_mensal_de_tabela(self, tabela: pd.DataFrame) -> Path:
        """
        Converte a tabela trimestral (DataFrame) em série mensal e salva CSV.
        """
        season_to_month = {
            "DJF": 1,  "JFM": 2,  "FMA": 3,  "MAM": 4,
            "AMJ": 5,  "MJJ": 6,  "JJA": 7,  "JAS": 8,
            "ASO": 9,  "SON": 10, "OND": 11, "NDJ": 12,
        }
        seasons = list(season_to_month.keys())

        df = tabela.copy()
        cols = ["Year"] + [c for c in df.columns if c in seasons]
        df = df[cols].copy()

        m = df.melt(id_vars="Year", var_name="TRIM", value_name="oni").dropna(subset=["oni"])
        m = m[m["TRIM"].isin(seasons)].copy()

        m["month"] = m["TRIM"].map(season_to_month).astype(int)
        m["Year"] = pd.to_numeric(m["Year"], errors="coerce").astype("Int64")
        m = m.dropna(subset=["Year"])
        m["Year"] = m["Year"].astype(int)
        m["date"] = pd.to_datetime(dict(year=m["Year"], month=m["month"], day=1))
        m["oni"] = pd.to_numeric(m["oni"], errors="coerce")

        out = m[m["Year"] >= self.output_ano_inicio][["date", "oni"]].sort_values("date").reset_index(drop=True)
        out.loc[np.isclose(out["oni"], 0.0, equal_nan=False), "oni"] = 0.0

        out_path = self.OUT_DIR_tables / f"ONI_indice-mensal_{self.tag}_{self.SUF_EXEC}.csv"
        out = out.rename(columns={"date": "data"})
        out.to_csv(out_path, index=False, float_format="%.3f")
        data_series = pd.to_datetime(out["data"])
        periodo = f"{data_series.min().date()} → {data_series.max().date()}"
        print(format_log("SALVO", item="Arquivo CSV do ONI mensal para utilizar no OMJ →", destino=f"{out_path} | período: {periodo}"))
        return out_path


    def _montar_trimestral_df(self, tabela: pd.DataFrame) -> pd.DataFrame:
        seasons = list(self.LABELS_TRIS.values())
        cols = ["Year"] + [c for c in tabela.columns if c in seasons]
        df = tabela[cols].copy()
        melted = (
            df.melt(id_vars="Year", var_name="TRIM", value_name="ONI")
              .dropna(subset=["ONI"])
        )
        melted["Year"] = pd.to_numeric(melted["Year"], errors="coerce").astype("Int64")
        melted = melted.dropna(subset=["Year"])
        melted["Year"] = melted["Year"].astype(int)
        melted["ONI"] = pd.to_numeric(melted["ONI"].astype(str).str.replace(",", "."), errors="coerce")
        melted = melted.dropna(subset=["ONI"])
        order_map = {season: idx for idx, season in enumerate(seasons)}
        melted = melted[melted["TRIM"].isin(order_map)].copy()
        melted["order"] = melted["TRIM"].map(order_map)
        seasonal_df = (melted[melted["Year"] >= self.output_ano_inicio]
                       .rename(columns={"Year": "YR"})
                       .sort_values(["YR", "order"])
                       .drop(columns=["order"])
                       .reset_index(drop=True))
        return seasonal_df


    def _plot_tabela_png(self, suffix: str, tabela: pd.DataFrame):
        trimestres = list(self.LABELS_TRIS.values())

        table_txt, txt_colors, txt_weight = [], [], []
        for idx, row in tabela.iterrows():
            if idx % 10 == 0:
                table_txt.append(["Year"] + trimestres)
                txt_colors.append(["black"] * 13)
                txt_weight.append(["bold"] * 13)

            ano = int(row["Year"])
            linha_txt  = [str(ano)]
            linha_col  = ["black"]
            linha_wght = ["normal"]
            neutro = True

            for tri in trimestres:
                cell = row[tri]
                if cell == "":
                    linha_txt.append("")
                    linha_col.append("black")
                    linha_wght.append("normal")
                    continue
                val = float(str(cell).replace(",", "."))
                linha_txt.append(f"{val:+.1f}")
                if val >= 0.5:
                    cor, peso = "red", "bold"
                    neutro = False
                elif val <= -0.5:
                    cor, peso = "blue", "bold"
                    neutro = False
                else:
                    cor, peso = "black", "normal"
                linha_col.append(cor)
                linha_wght.append(peso)

            if neutro:
                linha_wght = ["normal"] * 13

            table_txt.append(linha_txt)
            txt_colors.append(linha_col)
            txt_weight.append(linha_wght)

        n_rows = len(table_txt)
        fig_h  = 0.18 * n_rows + 1
        fig, ax = plt.subplots(figsize=(11, fig_h))
        ax.axis("off")
        tbl = ax.table(cellText=table_txt, cellLoc="center",
                       colWidths=[0.08] + [0.07] * 12, loc="upper left")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)

        for (i, j), cell in tbl.get_celld().items():
            cell.set_height(0.18 / fig_h)
            txt = cell.get_text()
            txt.set_color(txt_colors[i][j])
            txt.set_fontweight(txt_weight[i][j])

        plt.tight_layout()
        png_tab = self.OUT_DIR_figs / f"ONI_tabela-trimestral_CALC_{self.SUF_EXEC}.png"
        plt.savefig(png_tab, dpi=300, bbox_inches="tight")
        plt.close()
        print(format_log("SALVO", item="Figura da tabela do ONI trimestral →", destino=str(png_tab)))


    def _plot_timeseries_png(self, suffix: str, tabela: pd.DataFrame):

        tabela = tabela.assign(**{
            c: pd.to_numeric(tabela[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
            for c in tabela.columns if c != "Year"
        })
        long = tabela.melt(id_vars="Year", var_name="Tri", value_name="ONI")
        long["Year"] = pd.to_numeric(long["Year"], errors="coerce", downcast="integer")
        long["ONI"]  = pd.to_numeric(long["ONI"],  errors="coerce")
        long = long.dropna(subset=["ONI"])

        centro = {"DJF":1,"JFM":2,"FMA":3,"MAM":4,"AMJ":5,"MJJ":6,
                "JJA":7,"JAS":8,"ASO":9,"SON":10,"OND":11,"NDJ":12}
        long["Month"] = long["Tri"].map(centro)
        long["Date"]  = pd.to_datetime(dict(year=long.Year, month=long.Month, day=15))

        plot = long[long.Date.dt.year >= self.output_ano_inicio].sort_values("Date")
        if plot.empty:
            print(format_log("ATENCAO", message="Série vazia após filtro por ano_inicio → gráfico não será gerado."))
            return

        # Eixo X e Y
        x = plot.Date.to_numpy()
        y = plot.ONI.to_numpy()

        pos_mask = y >= 0
        neg_mask = y <= 0

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.xaxis_date()

        # areas coloridas
        ax.fill_between(x, y, 0, where=pos_mask, interpolate=True, alpha=0.25, color="red", zorder=1)
        ax.fill_between(x, y, 0, where=neg_mask, interpolate=True, alpha=0.25, color="blue", zorder=1)

        # Linha base e linha do indice
        ax.plot(x, y, color="0.35", linewidth=1.0, alpha=0.6, zorder=2)
        ax.axhline(0, linewidth=0.9, color="black", zorder=2)
        ax.axhline( 0.5, linewidth=2.0, color="red", linestyle="--", alpha=0.6, zorder=2)
        ax.axhline(-0.5, linewidth=2.0, color="blue", linestyle="--", alpha=0.6, zorder=2)

        # Ajustes de limites (sem espaco no inicio/fim)
        ax.set_xlim(x[0], x[-1])
        ax.margins(x=0)

        ax.set_ylim(-3, 3)
        ax.set_ylabel("índice Oceânico Nino (ONI)")

        ini = plot["Date"].min()
        fim = plot["Date"].max()
        ax.set_title(f"Série Temporal do índice Oceanico Nino (ONI) — {ini:%m-%Y} a {fim:%m-%Y}")

        ax.grid(True, linestyle="--", alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator(5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        fig.autofmt_xdate()
        fig.tight_layout()

        # Logo
        logo_path = Path("utils/atmosmarine.png")
        if logo_path.exists():
            img = mpimg.imread(str(logo_path))
            ab = AnnotationBbox(
                OffsetImage(img, zoom=0.04),
                (0.12, 0.14),
                xycoords="axes fraction",
                box_alignment=(1, 1),
                frameon=False,
                zorder=10,
            )
            ax.add_artist(ab)

        ts_path = self.OUT_DIR_figs / f"ONI_serie-temporal_CALC_{self.SUF_EXEC}.png"
        fig.savefig(ts_path, dpi=300, bbox_inches="tight")
        plt.close()
        print(format_log("SALVO", item="Figura da série temporal do ONI trimestral →", destino=str(ts_path)))


    def _validacao(self, oni_seasonal_df: pd.DataFrame, suffix: str):
        URL_CPC = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

        cache_dir = getattr(self, "CPC_CACHE_DIR", self.DATA_DIR / "cache" / "cpc")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_csv = list(cache_dir.glob("ONI_CPC_trimestral*.csv"))
        cached_txt = list(cache_dir.glob("ONI_CPC_trimestral*.txt"))
        legacy_dir = self.DATA_DIR / "cache" / "ONI"
        if legacy_dir.exists():
            cached_csv += list(legacy_dir.glob("ONI_CPC_trimestral*.csv"))
            cached_txt += list(legacy_dir.glob("ONI_CPC_trimestral*.txt"))
        cached_list = sorted(cached_csv + cached_txt, key=lambda p: p.stat().st_mtime)
        latest_cache = cached_list[-1] if cached_list else None

        lm_remote_ts = None
        head_ok = False
        try:
            req = urllib.request.Request(URL_CPC, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                lm = r.headers.get("Last-Modified")
                if lm:
                    lm_remote_ts = parsedate_to_datetime(lm).timestamp()
                head_ok = True
        except Exception as e:
            print(format_log(
                "ATENCAO",
                message=(
                    "Não foi possível consultar metadados no servidor do CPC "
                    f"({e.__class__.__name__}). Usaremos o cache disponível, se existir."
                ),
            ))

        seasons = list(self.LABELS_TRIS.values())
        order_map = {season: idx for idx, season in enumerate(seasons)}
        month_to_season = {1: "DJF", 2: "JFM", 3: "FMA", 4: "MAM", 5: "AMJ", 6: "MJJ",
                           7: "JJA", 8: "JAS", 9: "ASO", 10: "SON", 11: "OND", 12: "NDJ"}

        def _load_cpc(path: Path) -> pd.DataFrame:
            if path.suffix.lower() == ".csv":
                df = pd.read_csv(path)
            else:
                df = pd.read_csv(
                    path,
                    sep=r"\s+",
                    header=None,
                    names=["TRIM", "YR", "TOTAL", "ANOM"],
                    comment="#",
                    dtype=str,
                )
            col_map = {c.upper(): c for c in df.columns}
            if {"TRIM", "YR"}.issubset(col_map.keys()):
                season_key = col_map["TRIM"]
            elif {"MON", "YR"}.issubset(col_map.keys()):
                season_key = col_map["MON"]
            else:
                raise RuntimeError(format_log("ERRO", message=f"Arquivo {path} não possui colunas de período (TRIM) e YR."))

            

            value_key = None
            for candidate in ("ANOM", "ONI", "TOTAL"):
                if candidate in col_map:
                    value_key = col_map[candidate]
                    break
            if value_key is None:
                raise RuntimeError(format_log("ERRO", message=f"Arquivo {path} não possui coluna com valores de ONI/ANOM."))


            df = df.rename(columns={
                col_map["YR"]: "YR",
                season_key: "TRIM",
                value_key: "ONI",
            })
            df = df[pd.to_numeric(df["YR"], errors="coerce").notna()]
            df["YR"] = df["YR"].astype(int)
            df["TRIM"] = df["TRIM"].astype(str).str.strip().str.upper()
            if df["TRIM"].str.isdigit().any():
                df.loc[df["TRIM"].str.isdigit(), "TRIM"] = df.loc[df["TRIM"].str.isdigit(), "TRIM"].astype(int).map(month_to_season)
            df["ONI"] = pd.to_numeric(df["ONI"], errors="coerce")
            df = df.dropna(subset=["ONI"])
            df = df[df["TRIM"].isin(order_map)].copy()
            return df[["YR", "TRIM", "ONI"]]

        def _write_cpc(df: pd.DataFrame, dst: Path) -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(dst, index=False, float_format="%.3f")

        need_download = True
        cpc_df: pd.DataFrame | None = None

        def _use_cache(path: Path, reason: str) -> None:
            nonlocal cpc_df, need_download
            print(format_log("INFO", message=f"Usando ONI CPC presente em cache → {reason}: {path.name}"))
            cpc_df = _load_cpc(path)
            need_download = False

        if latest_cache and head_ok and lm_remote_ts is not None:
            if os.path.getmtime(latest_cache) >= lm_remote_ts:
                _use_cache(latest_cache, "arquivo em cache está atualizado!")
        elif latest_cache and not head_ok:
            _use_cache(latest_cache, "falha no HEAD")

        if need_download:
            try:
                tmp_txt = cache_dir / "ONI_CPC_trimestral.tmp.txt"
                print(format_log("DOWNLOAD", target="ONI CPC", dest=str(tmp_txt), reason="download oficial"))
                urllib.request.urlretrieve(URL_CPC, tmp_txt)
                cpc_df = _load_cpc(tmp_txt)
                tmp_txt.unlink(missing_ok=True)
            except Exception as e:
                if latest_cache:
                    print(format_log(
                        "ATENCAO",
                        message=f"Falha ao baixar ONI CPC ({e.__class__.__name__}: {e}). Reutilizando cache {latest_cache.name}.",
                    ))
                    cpc_df = _load_cpc(latest_cache)
                else:
                    print(format_log(
                        "ATENCAO",
                        message="Fontes CPC indisponíveis e nenhum cache local encontrado — validação será pulada.",
                    ))
                    return

        if cpc_df is None or cpc_df.empty:
            print(format_log("ATENCAO", message="Série CPC vazia — validação será pulada."))
            return

        cache_csv = cache_dir / "ONI_CPC_trimestral.csv"
        for legacy_file in cache_dir.glob("ONI_CPC_trimestral_*.csv"):
            if legacy_file != cache_csv:
                legacy_file.unlink(missing_ok=True)
        for legacy_txt in cache_dir.glob("ONI_CPC_trimestral_*.txt"):
            legacy_txt.unlink(missing_ok=True)
        _write_cpc(cpc_df, cache_csv)
        print(format_log("SALVO", item="ONI CPC em cache →", destino=str(cache_csv)))

        calc_df = oni_seasonal_df.copy()
        col_map = {c.upper(): c for c in calc_df.columns}
        required_calc = {"YR", "TRIM", "ONI"}
        if not required_calc.issubset(col_map.keys()):
            raise RuntimeError(format_log("ERRO", message="Série calculada não possui colunas YR/TRIM/ONI."))
        calc_df = calc_df.rename(columns={
            col_map["YR"]: "YR",
            col_map["TRIM"]: "TRIM",
            col_map["ONI"]: "ONI_calc",
        })
        calc_df = calc_df.dropna(subset=["YR", "TRIM", "ONI_calc"])
        calc_df["YR"] = pd.to_numeric(calc_df["YR"], errors="coerce").astype("Int64")
        calc_df = calc_df.dropna(subset=["YR"])
        calc_df["YR"] = calc_df["YR"].astype(int)
        calc_df["TRIM"] = calc_df["TRIM"].astype(str).str.upper()
        calc_df["ONI_calc"] = pd.to_numeric(calc_df["ONI_calc"], errors="coerce")
        calc_df = calc_df.dropna(subset=["ONI_calc"])

        cpc_df = cpc_df.rename(columns={"ONI": "ONI_cpc"})
        cmp = (calc_df.merge(cpc_df, on=["YR", "TRIM"], how="inner")
                        .query("YR >= @self.output_ano_inicio"))

        if cmp.empty:
            print(format_log("ATENCAO", message="Nada para validar contra CPC no período selecionado."))
            return

        cmp["diff"] = cmp["ONI_calc"] - cmp["ONI_cpc"]
        cmp["order"] = cmp["TRIM"].map(order_map)
        cmp = cmp.sort_values(["YR", "order"]).drop(columns=["order"]).reset_index(drop=True)

        rmse = float(np.sqrt((cmp["diff"] ** 2).mean()))
        mae = float(np.abs(cmp["diff"]).mean())
        bias = float(cmp["diff"].mean())
        r = float(cmp["ONI_calc"].corr(cmp["ONI_cpc"]))
        r2 = float(r * r) if not np.isnan(r) else np.nan
        if len(cmp) >= 2 and not np.allclose(cmp["ONI_cpc"], cmp["ONI_cpc"].iloc[0]):
            slope, intercept = np.polyfit(cmp["ONI_cpc"].to_numpy(), cmp["ONI_calc"].to_numpy(), 1)
        else:
            slope, intercept = np.nan, np.nan
        std_diff = float(cmp["diff"].std(ddof=1))
        nmeses = int(len(cmp))
        yr0, yr1 = int(cmp["YR"].min()), int(cmp["YR"].max())

        print("[ESTATÍSTICA] === Validação Calculado x CPC para o ONI trimestral ===")
        print(f"RMSE: {rmse:.3f} | MAE: {mae:.3f} | Viés: {bias:+.3f}")
        print(f"Correlação (r): {r:.3f} | R²: {r2:.3f} | slope: {slope:.3f} | intercept: {intercept:+.3f}")

        diff_csv = self.OUT_DIR_valida / f"ONI_serie-temporal_CALCvsCPC_{self.SUF_EXEC}.csv"
        cmp_export = (
            cmp.rename(columns={
                "YR": "ANO",
                "ONI_calc": "ONI_CALC",
                "ONI_cpc": "ONI_CPC",
                "diff": "diferenca",
            })[["ANO", "TRIM", "ONI_CALC", "ONI_CPC", "diferenca"]]
        )
        cmp_export.to_csv(diff_csv, index=False, float_format="%.3f")
        print(format_log("SALVO", item="Arquivo CSV de comparação entre o ONI Calculado vs CPC →", destino=str(diff_csv)))

        stats_csv = self.OUT_DIR_valida / f"ONI_metricas_estatisticas_{self.SUF_EXEC}.csv"
        row = {
            "fonte": self.NOME_SST,
            "data_inicio": int(yr0),
            "data_fim": int(yr1),
            "n_registros": int(nmeses),
            "rmse": round(rmse, 4),
            "mae": round(mae, 4),
            "bias": round(bias, 4),
            "corr": round(r, 4),
            "r2": round(r2, 4),
            "slope": round(slope, 4),
            "intercept": round(intercept, 4),
            "desv_pad_erro": round(std_diff, 4),
        }
        cols_order = [
            "fonte", "data_inicio", "data_fim", "n_registros",
            "rmse", "mae", "bias", "corr", "r2", "slope", "intercept", "desv_pad_erro",
        ]
        df_stats = pd.DataFrame([row])
        df_stats = df_stats[[c for c in cols_order if c in df_stats.columns] + [c for c in df_stats.columns if c not in cols_order]]
        df_stats.to_csv(stats_csv, index=False, float_format="%.3f")
        print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do ONI →", destino=str(stats_csv)))


    def _plot_regiao_oni_bbox(self, suffix):
        # normaliza lat/lon para exibicao
        lat_min, lat_max = sorted([float(self.lat_min), float(self.lat_max)])
        lon_min, lon_max = float(self.lon_min), float(self.lon_max)

        def to_pm180(v: float) -> float:
            return ((v + 180.0) % 360.0) - 180.0

        a = to_pm180(lon_min)
        b = to_pm180(lon_max)

        try:
            #  IMPORTAR AQUI
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
                f"Região de recorte do ONI | lat: {lat_min:g}..{lat_max:g}, "
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
                f"Região de recorte ONI {self._slug(self.NOME_TESTE)} | lat: {lat_min:g}..{lat_max:g}, "
                f"lon: {lon_min:g}..{lon_max:g}\n(visualizacao simplificada)"
            )

        out = self.OUT_DIR_figs / f"ONI_regiao_{self._slug(self.NOME_TESTE or self.tag)}_{self.SUF_EXEC}.png"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(format_log("SALVO", item=f"Região do Niño‑3.4 salvo em:", destino=f"{out}"))
