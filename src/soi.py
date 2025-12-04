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
from .atm_tools import validate_config_SOI
from src.logging import format_log

def _cfg_message(message: str) -> str:
    return format_log("ERRO_CONF", message=message)


class SOI:
    """
    indice SOI com tres modos:
      (A) REFERENCIA (padrao): 
          - CRU/UEA (RJ87, base 1951–1980) e valida contra 'soi_3dp.dat'
          - CPC: le os blocos 'STANDARDIZED DATA' (Darwin/Tahiti) e 'DIFF_STD' em /indices/soi,
            aplica a 2nda normalizacao via MSD (1981–2010, ddof=0) e valida.
      (B) TESTE:
          - Rodar RJ87 e CPC alterando a base climatologica a partir de SOI_BASES=YYYY-MM:YYYY-MM
            (CPC mantem os Z do site e so altera a MSD).
      (C) EXTERNO:
          - Ler SLP externos (Tahiti/Darwin) dos caminhos informados e calcular RJ87 e CPC
            com a base SOI_BASES. No CPC, faz tambem a 1nda padronizacao (Z) a partir dos SLP externos.
    """

    # URLs padrao
    CRU_DAR = "https://crudata.uea.ac.uk/cru/data/soi/soi_dar.dat"
    CRU_TAH = "https://crudata.uea.ac.uk/cru/data/soi/soi_tah.dat"
    CRU_SOI_3DP = "https://crudata.uea.ac.uk/cru/data/soi/soi_3dp.dat"

    CPC_DAR = "https://www.cpc.ncep.noaa.gov/data/indices/darwin"
    CPC_TAH = "https://www.cpc.ncep.noaa.gov/data/indices/tahiti"
    CPC_SOI = "https://www.cpc.ncep.noaa.gov/data/indices/soi"

    # Base CRU que replica o 3dp
    BASE_CRU = "1951-01:1980-12"
    # Base CPC (MSD) e graus de liberdade populacional (ddof=0)
    CPC_BASE_START = "1981-01-01"
    CPC_BASE_END   = "2010-12-31"

    # Regexes auxiliares
    _YEAR_LINE_RE  = re.compile(r"^\s*(?:18|19|20)\d{2}\b")
    _NUMS_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")
    _NUMS_INT_RE   = re.compile(r"-?\d+")

    # ---------- utilitarios ----------
    @staticmethod
    def _strip_inline_comment(val: str) -> str:
        s = str(val or "")
        for sep in ("#", ";", "//"):
            if sep in s:
                s = s.split(sep, 1)[0]
        return s.strip()

    @staticmethod
    def _upper_unaccent(s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFD", s)
        s = s.encode("ascii", "ignore").decode("ascii")
        return s.upper().strip()

    def _last_suffix(self, *series: pd.Series) -> str:
        idxs = []
        for s in series:
            if s is not None and not s.dropna().empty:
                idxs.append(s.dropna().index.max())
        if not idxs:
            return "NA"
        last_date = max(idxs)
        return f"{last_date:%Y%m}"


    # ---------- exportacao ----------
    def _series_to_year12_df(self, s: pd.Series,
                             y0: int | None = None,
                             y1: int | None = None,
                             ndigits: int = 2) -> pd.DataFrame:
        s = s.dropna().copy()
        s.index = s.index.to_period("M").to_timestamp(how="start")
        if y0 is None:
            y0 = int(s.index.year.min())
        if y1 is None:
            y1 = int(s.index.year.max())
        df = (
            s.to_frame("SOI")
             .assign(Year=lambda d: d.index.year, Month=lambda d: d.index.month)
             .pivot(index="Year", columns="Month", values="SOI")
             .reindex(index=range(y0, y1 + 1), columns=range(1, 13))
        )
        df.index.name = "Year"
        return df.round(ndigits)

    def _resolve_base_interval(self, metodo: str) -> tuple[str, str]:
        """
        Retorna o intervalo base (inicio, fim) em formato YYYY-MM-DD para um método.
        - REFERENCIA: usa as bases fixas oficiais.
        - TESTE: usa SOI_TESTE_BASE_CLIMA (ou padrao se ausente).
        - EXTERNO: usa SOI_EXTERNO_BASE_CLIMA (ou padrao se ausente).
        """
        metodo = (metodo or "CRU").upper()
        if self.MODO == "REFERENCIA":
            if metodo.startswith("CRU"):
                return self._default_base("CRU")
            return self.CPC_BASE_START, self.CPC_BASE_END

        if self.MODO == "TESTE":
            return self._parse_base_range(self.BASE_CUSTOM, metodo)

        if self.MODO == "EXTERNO":
            return self._parse_base_range(self.BASE_EXTERNO, metodo)

        return self._default_base(metodo)

    # ---------- setup ----------
    def __init__(self, cfg: dict | None = None):
        validate_config_SOI(cfg)
        self.cfg = cfg or {}

        # Sufixo unico desta execucao (YYYYMM)
        self.SUF_EXEC = datetime.now().strftime("%Y%m")

        # Pasta base de dados
        self.DATA_DIR = Path("data")

        # Primeiro, determina o modo
        raw_modo = self._strip_inline_comment(self.cfg.get("SOI_MODO", "REFERENCIA"))
        self.MODO = self._upper_unaccent(raw_modo)  # REFERENCIA | TESTE | EXTERNO
       
        self.OUT_DIR = OUTPUT_ROOT / "SOI" / self.MODO
        self.OUT_TAB = None
        self.OUT_FIG = None
        self.OUT_VAL = None

        # Bases e arquivos externos
        self.BASE_CUSTOM = self._strip_inline_comment(self.cfg.get("SOI_TESTE_BASE_CLIMA", ""))
        if self.MODO != "TESTE":
            self.BASE_CUSTOM = ""
        # Configuracoes para o modo EXTERNO
        self.BASE_EXTERNO   = self._strip_inline_comment(self.cfg.get("SOI_EXTERNO_BASE_CLIMA", ""))
        self.EXT_METODO     = self._upper_unaccent(self._strip_inline_comment(self.cfg.get("SOI_EXTERNO_METODO", "TODOS")))
        self.EXT_NOME       = self._strip_inline_comment(self.cfg.get("SOI_EXTERNO_NOME", "EXTERNO"))
        self.EXT_TAH        = self._strip_inline_comment(self.cfg.get("SOI_EXTERNO_TAHITI", ""))
        self.EXT_DAR        = self._strip_inline_comment(self.cfg.get("SOI_EXTERNO_DARWIN", ""))

        # # Log de setup
        # print(
        #     f"[SETUP] SOI_MODO={self.MODO} | BASE={self.BASE_CUSTOM or '(padrao)'} "
        #     f"| EXT_TAH={'ok' if self.EXT_TAH else 'nenhum'} | EXT_DAR={'ok' if self.EXT_DAR else 'nenhum'} "
        #     f"| SUF_EXEC={self.SUF_EXEC}"
        # )

    def _parse_base_range(self, base_str: str, metodo: str = "CRU") -> tuple[str, str]:
        """
        Tenta interpretar string de intervalo 'YYYY-MM:YYYY-MM' de forma robusta.
        - Corrige 'O/o' -> '0'
        - Aceita variacoes como YYYY/MM, YYYY_MM, YYYYMM
        - Se invalido ou fora do periodo esperado, usa padrao do metodo
        """
        if not base_str:
            return self._default_base(metodo)

        original = base_str
        s = base_str.strip().upper().replace("O", "0")  # troca O/o por zero
        s = re.sub(r"[^\d:-]", "-", s)                 # normaliza separadores para '-'

        # Tenta achar padroes AAAA-MM
        match = re.findall(r"(\d{4})[-_:/]?(\d{2})", s)
        if len(match) >= 2:
            a0, m0 = match[0]
            a1, m1 = match[1]
            try:
                start = pd.to_datetime(f"{a0}-{m0}-01")
                end   = pd.to_datetime(f"{a1}-{m1}-01") + pd.offsets.MonthEnd(1)
                # Validacao basica
                if start.year < 1850 or end.year > 2100 or start >= end:
                    print(format_log("ATENCAO", message=f"Intervalo {original!r} inválido (fora da faixa) - usando padrão {metodo}."))

                    return self._default_base(metodo)
                if original != f"{a0}-{m0}:{a1}-{m1}":
                    print(format_log("INFO", message=f"Base climatologica '{original}' corrigida para '{a0}-{m0}:{a1}-{m1}'"))
                return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            except Exception:
                pass

        # Se nada funcionou -> padrao
        print(format_log("ATENCAO", message=f"Base climatologica '{original}' nao reconhecida, usando padrao {metodo}."))
        return self._default_base(metodo)

    def _default_base(self, metodo: str) -> tuple[str, str]:
        """Retorna base padrao por metodologia"""
        if metodo.upper().startswith("CRU"):
            return "1951-01-01", "1980-12-31"
        else:  # CPC (PADRONIZADO ou ANOMALIA)
            return "1981-01-01", "2010-12-31"


    def _read_slp_csv(self, path: str) -> pd.Series:
        """
        Le CSV com colunas (ano|year);(mes|month);(slp|pressao|slp_hpa).
        Retorna Serie mensal em hPa indexada por primeiro dia do mes.
        """
        df = pd.read_csv(path, sep=None, engine="python")
        cols = {c.lower().strip(): c for c in df.columns}
        y = cols.get("ano") or cols.get("year")
        m = cols.get("mes") or cols.get("month")
        v = cols.get("slp") or cols.get("pressao") or cols.get("pnmm")
        if not (y and m and v):
            raise ValueError(_cfg_message("CSV externo precisa de colunas: ano/mes/slp (ou year/month/slp)."))

        df = df.rename(columns={y: "ano", m: "mes", v: "slp"})
        df["ano"] = df["ano"].astype(int)
        df["mes"] = df["mes"].astype(int)
        df["slp"] = pd.to_numeric(df["slp"], errors="coerce")
        df = df.dropna(subset=["slp"])
        idx = pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=1))
        return pd.Series(df["slp"].values, index=idx).sort_index()

    def _get_text(self, path_or_url: str) -> str:
        """
        Retorna conteudo de arquivo local ou URL.
        Sempre prioriza internet. Se falhar, usa cache local em data/cache/.
        Nunca quebra: retorna "" se nada estiver disponivel.
        """
        # pasta de cache global fora da classe
        cache_dir = Path("data") / "cache" / "SOI"
        cache_dir.mkdir(parents=True, exist_ok=True)
        data_dir = Path("data")
        special_local_names = {"darwin", "tahiti", "soi_dar.dat", "soi_tah.dat"}

        # 1. Se for caminho local explicito
        p = Path(path_or_url)
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(format_log("ERRO", message=f"Falha ao abrir {p}: {e}"))

                return ""

        # 2. Se for URL
        if path_or_url.startswith("http"):
            url_name = Path(urlparse(path_or_url).path).name or "download"
            if url_name in special_local_names:
                fname = data_dir / url_name
            else:
                fname = cache_dir / url_name
            fname.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(path_or_url) as f:
                    data = f.read().decode("utf-8")
                # salva cache atualizado
                fname.write_text(data, encoding="utf-8")
                print(
                    format_log(
                        "DOWNLOAD",
                        target=url_name or path_or_url,
                        dest=str(fname),
                        reason="Cache atualizado com sucesso",
                    )
                )
                return data
            except Exception as e:
                print(format_log("ATENCAO", message=f"Não foi possível acessar {path_or_url}: {e}"))

                if fname.exists():
                    print(format_log("INFO", message=f"Usando versão local em cache: {fname}"))

                    return fname.read_text(encoding="utf-8", errors="ignore")
                else:
                    print(format_log("ERRO", message=f"Nenhum cache encontrado para {fname.name}. Pulando."))

                    return ""

        # 3. Se nao for arquivo nem URL
        print(format_log("ATENCAO", message=f"Caminho inválido: {path_or_url}"))
        return ""

    def _safe_text(self, path_or_url: str, label: str) -> str:
        """
        Wrapper do _get_text que retorna "" se nao houver fonte.
        Se a string vier vazia, da um aviso e permite pular o calculo sem quebrar.
        """
        txt = self._get_text(path_or_url)
        if not txt:
            print(format_log("ATENCAO", message=f"Pulando {label}: fonte indisponível (sem internet/cache/local)."))
        return txt

    @classmethod
    def _parse_matrix(cls, txt: str, use_float=True, missing_to_nan=None) -> pd.Series:
        data = []
        for ln in txt.splitlines():
            if not ln.strip():
                continue
            if cls._YEAR_LINE_RE.match(ln):
                nums = (cls._NUMS_FLOAT_RE.findall(ln) if use_float else cls._NUMS_INT_RE.findall(ln))
                if len(nums) >= 13:
                    yr = int(nums[0]); vals = nums[1:13]
                    for m, raw in enumerate(vals, start=1):
                        v = float(raw)
                        if missing_to_nan is not None and v <= missing_to_nan:
                            v = np.nan
                        data.append((pd.Timestamp(year=yr, month=m, day=1), v))
        return pd.Series(dict(data)).sort_index() if data else pd.Series(dtype=float)

    @classmethod
    def _parse_cru_slp(cls, txt: str) -> pd.Series:
        """CRU: inteiros em decimos de hPa; -990 = missing -> hPa."""
        years, months, values = [], [], []
        for ln in txt.splitlines():
            if cls._YEAR_LINE_RE.match(ln):
                nums = cls._NUMS_INT_RE.findall(ln)
                if len(nums) >= 13:
                    yr = int(nums[0])
                    for m, raw in enumerate(nums[1:13], start=1):
                        v = float(raw)
                        val = np.nan if v == -990 else v / 10.0
                        years.append(yr); months.append(m); values.append(val)
        if not years:
            return pd.Series(dtype=float)
        idx = pd.to_datetime({"year": years, "month": months, "day": 1})
        return pd.Series(values, index=idx).sort_index()

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().upper())

    @classmethod
    def _collect_after_anchor(cls, lines: list[str], anchor_idx: int) -> str:
        i = anchor_idx + 1
        n = len(lines)
        # avancar ate cabecalho YEAR
        while i < n and not cls._norm(lines[i]).startswith("YEAR "):
            i += 1
        if i >= n:
            return ""
        i += 1
        rows = []
        while i < n:
            ln = lines[i]
            if cls._YEAR_LINE_RE.match(ln or ""):
                rows.append(ln)
            elif cls._norm(ln).endswith("SEA LEVEL PRESS") or "(STAND TAHITI - STAND DARWIN)" in cls._norm(ln) \
                 or "SOUTHERN OSCILLATION INDEX" in cls._norm(ln):
                break
            i += 1
        return "\n".join(rows)

    @classmethod
    def _extract_station_std(cls, page_txt: str, station: str) -> pd.Series:
        lines = [ln.rstrip("\r") for ln in page_txt.splitlines()]
        idxs = [i for i, ln in enumerate(lines) if f"{station.upper()} SEA LEVEL PRESS" in cls._norm(ln)]
        if not idxs:
            return pd.Series(dtype=float)
        anchor = None
        for i in idxs:
            for j in range(i + 1, min(i + 4, len(lines))):
                if "STANDARDIZED" in cls._norm(lines[j]) and "DATA" in cls._norm(lines[j]):
                    anchor = i
                    break
            if anchor is not None:
                break
        if anchor is None:
            return pd.Series(dtype=float)
        block = cls._collect_after_anchor(lines, anchor)
        return cls._parse_matrix(block, use_float=True, missing_to_nan=-99)
    
    @classmethod
    def _extract_station_anom(cls, page_txt: str, station: str) -> pd.Series:
        """
        Extrai o bloco 'ANOMALY' da pagina CPC para a estacao indicada (TAHITI ou DARWIN).
        Retorna Serie mensal de anomalias em hPa.
        """
        lines = [ln.rstrip("\r") for ln in page_txt.splitlines()]
        idxs = [i for i, ln in enumerate(lines) if f"{station.upper()} SEA LEVEL PRESS" in cls._norm(ln)]
        if not idxs:
            return pd.Series(dtype=float)

        anchor = None
        for i in idxs:
            for j in range(i + 1, min(i + 4, len(lines))):
                if "ANOMALY" in cls._norm(lines[j]):
                    anchor = i
                    break
            if anchor is not None:
                break

        if anchor is None:
            print(format_log("ATENCAO", message=f"Bloco ANOMALY não encontrado para {station}."))

            return pd.Series(dtype=float)

        block = cls._collect_after_anchor(lines, anchor)
        s = cls._parse_matrix(block, use_float=True, missing_to_nan=-99)
        if not s.empty:
            s.index = pd.to_datetime(s.index)
        return s

    @classmethod
    def _extract_station_slp(cls, page_txt: str, station: str) -> pd.Series:
        """
        Extrai o bloco principal de pressão ao nível do mar (SLP) das páginas CPC.
        Retorna série mensal em hPa. Usa heurísticas para evitar confundir com
        os blocos de anomalias ou dados padronizados.
        """
        lines = [ln.rstrip("\r") for ln in page_txt.splitlines()]
        idxs = [i for i, ln in enumerate(lines) if station.upper() in cls._norm(ln) and "SEA LEVEL PRESS" in cls._norm(ln)]
        if not idxs:
            return pd.Series(dtype=float)

        anchor = None
        for i in idxs:
            window = [cls._norm(lines[j]) for j in range(i, min(i + 6, len(lines)))]
            # ignora blocos que explicitamente tratam de ANOMALY ou STANDARDIZED
            if any("ANOMAL" in w or "STANDARDIZED" in w for w in window):
                continue
            if any("SEA LEVEL PRESS" in w for w in window):
                anchor = i
                break

        if anchor is None:
            return pd.Series(dtype=float)

        block = cls._collect_after_anchor(lines, anchor)
        s = cls._parse_matrix(block, use_float=True, missing_to_nan=-99)
        if not s.empty:
            s.index = pd.to_datetime(s.index)
        return s


    @classmethod
    def _extract_diff_std(cls, soi_txt: str) -> pd.Series:
        lines = [ln.rstrip("\r") for ln in soi_txt.splitlines()]
        idxs = [i for i, ln in enumerate(lines)
                if "(STAND TAHITI - STAND DARWIN) SEA LEVEL PRESS" in cls._norm(ln)]
        if not idxs:
            return pd.Series(dtype=float)
        anchor = None
        for i in idxs:
            for j in range(i + 1, min(i + 4, len(lines))):
                if "STANDARDIZED" in cls._norm(lines[j]) and "DATA" in cls._norm(lines[j]):
                    anchor = i
                    break
            if anchor is not None:
                break
        if anchor is None:
            return pd.Series(dtype=float)
        block = cls._collect_after_anchor(lines, anchor)
        return cls._parse_matrix(block, use_float=True, missing_to_nan=-99)

    @classmethod
    def _extract_diff_anom(cls, soi_txt: str) -> pd.Series:
        """
        Extrai o bloco CPC (STAND TAHITI - STAND DARWIN) SEA LEVEL PRESS ANOMALY.
        Esses dados representam a diferenca Z(Tahiti) - Z(Darwin) sem a 2nda normalizacao (MSD).
        """
        lines = [ln.rstrip("\r") for ln in soi_txt.splitlines()]
        anchor = None

        for i, ln in enumerate(lines):
            norm_ln = cls._norm(ln)
            if "(STAND TAHITI - STAND DARWIN)" in norm_ln and "SEA LEVEL PRESS" in norm_ln:
                # Verifica se a mesma linha ja contem ANOMALY
                if "ANOMALY" in norm_ln:
                    anchor = i
                    break
                # Caso contrario, checa a proxima linha
                elif i+1 < len(lines) and "ANOMALY" in cls._norm(lines[i+1]):
                    anchor = i
                    break

        if anchor is None:
            print(format_log("ATENCAO", message=f"Bloco CPC_ANOMALIA nao encontrado no texto."))
            return pd.Series(dtype=float)

        block = cls._collect_after_anchor(lines, anchor)
        s = cls._parse_matrix(block, use_float=True, missing_to_nan=-99)
        if not s.empty:
            s.index = pd.to_datetime(s.index)  # garante DatetimeIndex
        return s


    # ------------------- nucleo RJ87 (CRU) -------------------
    @staticmethod
    def _monthly_standardize(series: pd.Series, base_start: str, base_end: str,
                            ddof_month: int = 1, pairwise_base: bool = True) -> pd.Series:
        """
        Padroniza por mes-do-ano (Z-score), base opcionalmente 'pairwise'.
        Mantem o DatetimeIndex original.
        """
        if pairwise_base:
            mask = (series.index >= base_start) & (series.index <= base_end) & series.notna()
            base = series[mask]
        else:
            base = series.loc[base_start:base_end]

        mu = base.groupby(base.index.month).mean()
        sd = base.groupby(base.index.month).std(ddof=ddof_month).replace(0, np.nan)

        months = series.index.month
        z = (series.values - mu.reindex(months).values) / sd.reindex(months).values
        return pd.Series(z, index=series.index)
    
    @staticmethod
    def _monthly_anomaly(series: pd.Series, base_start: str, base_end: str) -> pd.Series:
        """
        Calcula anomalias mensais (valor - media mensal da base climatica).
        Mantem o DatetimeIndex original.
        """
        # climatologia mensal na base
        base = series.loc[base_start:base_end]
        clim = base.groupby(base.index.month).mean()

        # vetor de meses da serie
        months = series.index.month

        # anomalia = valor - climatologia daquele mes
        anom = series.values - clim.reindex(months).values
        return pd.Series(anom, index=series.index)


    @classmethod
    def _compute_cru_soi(cls, tah_slp: pd.Series, dar_slp: pd.Series,
                         base: str, ddof_month: int = 1, ddof_s2: int = 1,
                         pairwise_base: bool = True, s2_by_month: bool = True,
                         round_3dp: bool = False) -> pd.Series:
        base_start, base_end = base.split(":")
        z_tah = cls._monthly_standardize(tah_slp, base_start, base_end, ddof_month, pairwise_base)
        z_dar = cls._monthly_standardize(dar_slp, base_start, base_end, ddof_month, pairwise_base)
        diff = z_tah - z_dar  # Tahiti − Darwin
        if s2_by_month:
            sub = diff.loc[base_start:base_end]
            sd2 = sub.groupby(sub.index.month).std(ddof=ddof_s2)
            soi = diff / sd2.reindex(diff.index.month).values
        else:
            s = diff.loc[base_start:base_end].std(ddof=ddof_s2)
            soi = diff / s
        if round_3dp:
            soi = soi.round(3)
        return soi.rename("SOI_CRU_calc")

    # ------------------- metricas (CSV unico/blocks) -------------------
    def _write_metrics_csv(self, rows: list[dict], filename: str) -> None:
        """
        Salva uma lista de dicionarios (linhas) em CSV unico.
        """
        if not rows:
            print(format_log("ERRO", message=f"Sem métricas estatísticas para salvar."))

            return
        df = pd.DataFrame(rows)
        out = self.OUT_VAL / filename
        df.to_csv(out, index=False, float_format="%.6f")
        print(format_log("SALVO", item=f"Arquivo CSV com as métricas estatísticas salvo →", destino=f"{out}"))


    def _write_blocks_metrics(
        self,
        s_calc: pd.Series,
        s_ref: pd.Series,
        out_path: Path,
        window_months: int = 120,
        step_months: int = 12,
    ):
        """
        Calcula metricas por blocos deslizantes (ex.: 120 meses com passo 12) e escreve CSV.
        Este e o conteudo do 'VALIDACAO_CPC_soi_calc_vs_cpc_blocks.csv'.
        """
        df = pd.concat([s_calc.rename("calc"), s_ref.rename("ref")], axis=1).dropna()
        if df.empty:
            print(format_log("ATENCAO", message=f"Séries vazias para os blocos deslizantes: {out_path.name}"))

            return
        dates = df.index.sort_values()
        rows = []
        i = 0
        while i < len(dates):
            start = dates[i]
            end = start + pd.DateOffset(months=window_months - 1)
            blk = df.loc[(df.index >= start) & (df.index <= end)]
            if len(blk) >= max(24, window_months // 4):
                diff = blk["calc"] - blk["ref"]
                rmse = float(np.sqrt((diff**2).mean()))
                mae  = float(np.abs(diff).mean())
                bias = float(diff.mean())
                r    = float(blk["calc"].corr(blk["ref"]))
                slope, intercept = np.polyfit(blk["ref"].to_numpy(), blk["calc"].to_numpy(), 1)
                rows.append({
                    "data_inicio": f"{start:%Y-%m}",
                    "data_fim": f"{blk.index.max():%Y-%m}",
                    "n_registros": int(len(blk)),
                    "rmse": rmse,
                    "mae": mae,
                    "bias": bias,
                    "corr": r,
                    "r2": float(r*r) if np.isfinite(r) else np.nan,
                    "slope": float(slope),
                    "intercept": float(intercept),
                    "desv_pad_erro": float(diff.std(ddof=1))
                })
            i += step_months
        pd.DataFrame(rows).to_csv(out_path, index=False, float_format="%.6f")
        print(format_log("SALVO", item=f"Arquivo CSV com as métricas estatísticas do bloco deslizante →", destino=f"{out_path}"))


    # ------------------- run -------------------
    def run(self) -> None:
        self.SUF_EXEC = datetime.now().strftime("%Y%m")
        modo = (self.MODO or "REFERENCIA").upper()

        def _format_metrics_df(data: list[dict]) -> pd.DataFrame:
            df = pd.DataFrame(data)
            cols_order = [
                "metodo", "fonte", "data_inicio", "data_fim", "n_registros",
                "rmse", "mae", "bias", "corr", "r2", "slope", "intercept", "desv_pad_erro",
            ]
            ordered = [c for c in cols_order if c in df.columns]
            return df[ordered + [c for c in df.columns if c not in ordered]]

        # ====== MODO PADRaO (REFERENCIA) ======
        if modo == "REFERENCIA":
            self.OUT_DIR = OUTPUT_ROOT / "SOI" / "REFERENCIA"
            self.OUT_DIR.mkdir(parents=True, exist_ok=True)
            self.OUT_TAB = self.OUT_FIG = self.OUT_VAL = self.OUT_DIR

            opt = self._upper_unaccent(self.cfg.get("SOI_REFERENCIA_METODO", "TODOS"))
            print(format_log("INFO", message=f"Método escolhido: {opt}"))

            rows = []   # armazena metricas de cada bloco rodado

            # ===== CRU =====
            if opt in ("CRU", "TODOS"):
                print(format_log("INFO", message="Iniciando o calculo do SOI/CRU"))
                tah_txt = self._safe_text(self.CRU_TAH, "CRU TAHITI")
                dar_txt = self._safe_text(self.CRU_DAR, "CRU DARWIN")
                if not tah_txt or not dar_txt:
                    return  # interrompe este calculo e segue com outros metodos
                soi3_txt = self._get_text(self.CRU_SOI_3DP)

                tah_slp = self._parse_cru_slp(tah_txt)
                dar_slp = self._parse_cru_slp(dar_txt)
                soi_cru = self._compute_cru_soi(tah_slp, dar_slp, base=self.BASE_CRU)
                soi3 = self._parse_matrix(soi3_txt, use_float=True, missing_to_nan=-99).rename("SOI_CRU_3dp")

                suf = self._last_suffix(tah_slp, dar_slp)

                # Comparacao calc vs ref
                cru = pd.concat([soi_cru.rename("SOI_CRU_CALC"), soi3.rename("SOI_CRU")], axis=1).dropna()
                cru["diferenca"] = (cru["SOI_CRU_CALC"] - cru["SOI_CRU"]).round(3)
                cru.index.name = "data"
                cru_csv = self.OUT_TAB / f"SOI_CALCvsCRU_{self.SUF_EXEC}.csv"
                cru.to_csv(cru_csv, float_format="%.3f", date_format="%Y-%m")

                # # Tabelas oficiais
                # self._export_official_formats(soi_cru, "CRU", self.SUF_EXEC)

                # Figura
                self._plot_timeseries_png(
                    series=soi_cru,
                    suffix=f"serie-temporal_CRU_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método Ropelewski & Jones (1987) (CRU) - Base {self.BASE_CRU}"
                )

                # Metricas
                m_cru = self._compute_stats(soi_cru, soi3, label="Validacao CRU")
                if m_cru:
                    rows.append({"metodo": "CRU_RJ87", **m_cru})

            # ===== CPC PADRONIZADO =====
            if opt in ("CPC_PADRONIZADO", "TODOS"):
                print(format_log("INFO", message="Iniciando o calculo do SOI/CPC PADRONIZADO"))
                

                dar_cpc_txt = self._safe_text(self.CPC_DAR, "CPC DARWIN")
                tah_cpc_txt = self._safe_text(self.CPC_TAH, "CPC TAHITI")
                if not dar_cpc_txt or not tah_cpc_txt:
                    return
                soi_cpc_txt = self._get_text(self.CPC_SOI)

                z_dar = self._extract_station_std(dar_cpc_txt, "DARWIN").rename("Z_DAR")
                z_tah = self._extract_station_std(tah_cpc_txt, "TAHITI").rename("Z_TAH")
                zdiff = (z_tah - z_dar).rename("CPC_Zdiff")
                diff_std = self._extract_diff_std(soi_cpc_txt).rename("SOI_CPC_PADRONIZADO")

                # 2nda normalizacao CPC (MSD 81–10, ddof=0)
                mask = (zdiff.index >= self.CPC_BASE_START) & (zdiff.index <= self.CPC_BASE_END)
                msd = zdiff[mask].std(ddof=0)
                soi_cpc = (zdiff / msd).rename("SOI_CPC_PADRONIZADO_CALC")

                suf = self._last_suffix(z_tah, z_dar)

                # Comparacao calc vs ref
                cpc = pd.concat([soi_cpc, diff_std], axis=1).dropna(how="all")
                cpc["diferenca"] = (cpc["SOI_CPC_PADRONIZADO_CALC"] - cpc["SOI_CPC_PADRONIZADO"]).round(3)
                cpc.index.name = "data"
                cpc_csv = self.OUT_TAB / f"SOI_CALCvsCPC_PADRONIZADO_{self.SUF_EXEC}.csv"
                cpc.to_csv(cpc_csv, float_format="%.3f", date_format="%Y-%m")

                # # Tabelas oficiais
                # self._export_official_formats(soi_cpc, "CPC_PADRONIZADO", self.SUF_EXEC)

                # Figura
                self._plot_timeseries_png(
                    series=soi_cpc,
                    suffix=f"serie-temporal_CPC_PADRONIZADO_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title="Índice de Oscilação Sul (SOI) - Método Padronizado do CPC - Base 1981-01:2010-12"
                )

                # Metricas
                m_cpc = self._compute_stats(soi_cpc, diff_std, label="Validacao CPC_PADRONIZADO")
                if m_cpc:
                    rows.append({"metodo": "CPC_PADRONIZADO", **m_cpc})

            # ===== CPC ANOMALIA =====
            if opt in ("CPC_ANOMALIA", "TODOS"):
                print(format_log("INFO", message="Iniciando o calculo do SOI/CPC ANOMALIA (Sem Padronização)"))

                # --- 1. Ler paginas de Darwin/Tahiti (CPC) e extrair ANOMALY ---
                dar_cpc_txt = self._safe_text(self.CPC_DAR, "CPC DARWIN")
                tah_cpc_txt = self._safe_text(self.CPC_TAH, "CPC TAHITI")
                if not dar_cpc_txt or not tah_cpc_txt:
                    return
                soi_cpc_txt = self._get_text(self.CPC_SOI)

                anom_dar = self._extract_station_anom(dar_cpc_txt, "DARWIN").rename("ANOM_DAR")
                anom_tah = self._extract_station_anom(tah_cpc_txt, "TAHITI").rename("ANOM_TAH")

                # --- 2. Calcular localmente a diferenca (Tahiti − Darwin) ---
                soi_cpc_anom_calc = (anom_tah - anom_dar).rename("SOI_CPC_ANOMALIA_CALC")

                # --- 3. Extrair serie de referencia (ANOMALY) do CPC_SOI ---
                soi_cpc_anom_ref = self._extract_diff_anom(soi_cpc_txt).rename("SOI_CPC_ANOMALIA")

                # --- 4. Comparacao calc vs ref ---
                cpc_anom = pd.concat([soi_cpc_anom_calc, soi_cpc_anom_ref], axis=1).dropna(how="all")
                cpc_anom.index.name = "data"
                cpc_anom["diferenca"] = (cpc_anom["SOI_CPC_ANOMALIA_CALC"] - cpc_anom["SOI_CPC_ANOMALIA"]).round(3)
                cpc_anom_csv = self.OUT_TAB / f"SOI_CALCvsCPC_ANOMALIA_{self.SUF_EXEC}.csv"
                cpc_anom.to_csv(cpc_anom_csv, float_format="%.3f", date_format="%Y-%m", index_label="data")
                print(format_log("SALVO", item="Arquivo comparativo CSV - SOI calculado vs CPC no método CPC ANOMALIA →", destino=f"{cpc_anom_csv}"))


                # # --- 5. Tabelas oficiais (com a serie calculada) ---
                # if not soi_cpc_anom_calc.dropna().empty:
                #     self._export_official_formats(soi_cpc_anom_calc, "CPC_ANOMALIA", self.SUF_EXEC)
                # else:
                #     print(format_log("ATENCAO", message="Série CPC ANOMALIA calculada esta vazia - não foi exportado para o formato oficial."))


                # --- 6. Figura ---
                self._plot_timeseries_png(
                    series=soi_cpc_anom_calc,
                    suffix=f"serie-temporal_CPC_ANOMALIA_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-6, 6),
                    title="Índice de Oscilação Sul (SOI) - Método Anomalias do CPC (Sem Padronização) - Base 1981-01:2010-12"
                )

                # --- 7. Metricas ---
                m_cpc_anom = self._compute_stats(
                    soi_cpc_anom_calc, soi_cpc_anom_ref,
                    label="Validacao CPC_ANOMALIA"
                )
                if m_cpc_anom:
                    rows.append({"metodo": "CPC_ANOMALIA", **m_cpc_anom})


            # ----- CSV uNICO DE MeTRICAS -----
            if rows:
                suf = self._last_suffix()
                out = self.OUT_VAL / f"SOI_metricas_estatisticas_{opt}_{self.SUF_EXEC}.csv"
                _format_metrics_df(rows).to_csv(out, index=False, float_format="%.3f")
                print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do SOI →", destino=(out)))
                

            return


        # ====== MODO TESTE (bases custom) ======
        if modo == "TESTE":
            if not self.BASE_CUSTOM:
                raise ValueError("SOI_MODO=TESTE requer SOI_TESTE_BASE_CLIMA=YYYY-MM:YYYY-MM")

            # le nome definido no config
            nome_teste = self.cfg.get("SOI_TESTE_NOME", "").strip()
            if nome_teste:
                self.OUT_DIR = OUTPUT_ROOT / "SOI" / f"TESTE_{nome_teste}"
            else:
                self.OUT_DIR = OUTPUT_ROOT / "SOI" / "TESTE_PADRAO"
                print(format_log("ATENCAO", message=f"SOI_TESTE_NOME nao definido no arquivo de configuração → usando TESTE_PADRAO"))


            # redefine subpastas
            self.OUT_DIR.mkdir(parents=True, exist_ok=True)
            self.OUT_TAB = self.OUT_FIG = self.OUT_VAL = self.OUT_DIR

            opt = self._upper_unaccent(self.cfg.get("SOI_TESTE_METODO", "TODOS"))
            print(format_log("INFO", message=f"Método escolhido: {opt}"))
            rows = []


            # --- CRU (RJ87) ---
            if opt in ("CRU", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_CUSTOM, metodo="CRU")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CRU no modo TESTE com a base {base_str_pretty}"))

                tah_txt = self._get_text(self.CRU_TAH)
                dar_txt = self._get_text(self.CRU_DAR)
                tah_slp = self._parse_cru_slp(tah_txt)
                dar_slp = self._parse_cru_slp(dar_txt)
                soi_cru = self._compute_cru_soi(
                    tah_slp, dar_slp,
                    base=f"{base_start}:{base_end}",
                    ddof_month=1, ddof_s2=1,
                    pairwise_base=True, s2_by_month=True, round_3dp=False
                )
                # Forca inicio em 1866
                soi_cru = soi_cru[soi_cru.index >= "1866-01"]
                soi3_txt = self._get_text(self.CRU_SOI_3DP)
                soi3 = self._parse_matrix(soi3_txt, use_float=True, missing_to_nan=-99).rename("SOI_CRU")
                cru_df = pd.concat([soi_cru.rename("SOI_CRU_CALC"), soi3], axis=1).dropna(how="all")
                cru_df["diferenca"] = (cru_df["SOI_CRU_CALC"] - cru_df["SOI_CRU"]).round(3)
                cru_df.index.name = "data"
                cru_csv = self.OUT_TAB / f"SOI_serie-temporal_CRU_{self.SUF_EXEC}.csv"
                cru_df.to_csv(cru_csv, float_format="%.3f", date_format="%Y-%m")
                self._plot_timeseries_png(
                    series=soi_cru,
                    suffix=f"serie.temporal_CRU_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método Ropelewski & Jones (1987) (CRU) - Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_cru, "CRU", self.SUF_EXEC)

                # validacao contra CRU 3dp
                m_cru = self._compute_stats(soi_cru, soi3.rename("SOI_CRU_3dp"), label="Teste RJ87 calculado (CRU) vs CRU_3dp")
                if m_cru:
                    rows.append({"metodo": "CRU_TESTE", **m_cru})

            # --- CPC PADRONIZADO ---
            if opt in ("CPC_PADRONIZADO", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_CUSTOM, metodo="CPC_PADRONIZADO")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CPC PADRONIZADO no modo TESTE com a base {base_str_pretty}"))

                dar_cpc_txt = self._get_text(self.CPC_DAR)
                tah_cpc_txt = self._get_text(self.CPC_TAH)
                slp_dar = self._extract_station_slp(dar_cpc_txt, "DARWIN").rename("SLP_DAR")
                slp_tah = self._extract_station_slp(tah_cpc_txt, "TAHITI").rename("SLP_TAH")
                if slp_dar.dropna().empty or slp_tah.dropna().empty:
                    print(format_log(
                        "ATENCAO",
                        message="SLP bruto do CPC indisponível; utilizando dados padronizados fornecidos pelo CPC (base 1981-2010)."
                    ))
                    z_dar = self._extract_station_std(dar_cpc_txt, "DARWIN").rename("Z_DAR")
                    z_tah = self._extract_station_std(tah_cpc_txt, "TAHITI").rename("Z_TAH")
                else:
                    z_dar = self._monthly_standardize(
                        slp_dar, base_start, base_end,
                        ddof_month=0, pairwise_base=True
                    ).rename("Z_DAR")
                    z_tah = self._monthly_standardize(
                        slp_tah, base_start, base_end,
                        ddof_month=0, pairwise_base=True
                    ).rename("Z_TAH")
                zdiff = (z_tah - z_dar).rename("Zdiff")
                msd = zdiff.loc[base_start:base_end].std(ddof=0)
                soi_cpc = (zdiff / msd).rename("SOI_CPC_PADRONIZADO_CALC")
                cpc_csv = self.OUT_TAB / f"SOI_serie-temporal_CPC_PADRONIZADO_{self.SUF_EXEC}.csv"
                self._plot_timeseries_png(
                    series=soi_cpc,
                    suffix=f"serie.temporal_CPC_PADRONIZADO_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método Padronizado do CPC - Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_cpc, "CPC_PADRONIZADO", self.SUF_EXEC)

                # validacao contra CPC_STD
                soi_cpc_txt = self._get_text(self.CPC_SOI)
                diff_std = self._extract_diff_std(soi_cpc_txt).rename("SOI_CPC_PADRONIZADO")
                cpc_df = pd.concat([soi_cpc, diff_std], axis=1).dropna(how="all")
                cpc_df["diferenca"] = (cpc_df["SOI_CPC_PADRONIZADO_CALC"] - cpc_df["SOI_CPC_PADRONIZADO"]).round(3)
                cpc_df.index.name = "data"
                cpc_df.to_csv(cpc_csv, float_format="%.3f", date_format="%Y-%m")
                m_cpc = self._compute_stats(soi_cpc, diff_std, label="Teste CPC vs CPC_DIFF_STD")
                if m_cpc:
                    rows.append({"metodo": "CPC_PADRONIZADO_TESTE", **m_cpc})

            # --- CPC ANOMALIA ---
            if opt in ("CPC_ANOMALIA", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_CUSTOM, metodo="CPC_ANOMALIA")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CPC ANOMALIA no modo TESTE com a base {base_str_pretty}"))
                dar_cpc_txt = self._get_text(self.CPC_DAR)
                tah_cpc_txt = self._get_text(self.CPC_TAH)
                slp_dar = self._extract_station_slp(dar_cpc_txt, "DARWIN").rename("SLP_DAR")
                slp_tah = self._extract_station_slp(tah_cpc_txt, "TAHITI").rename("SLP_TAH")
                if slp_dar.dropna().empty or slp_tah.dropna().empty:
                    print(format_log(
                        "ATENCAO",
                        message="SLP bruto do CPC indisponível; utilizando anomalias fornecidas pelo CPC (base original)."
                    ))
                    anom_dar = self._extract_station_anom(dar_cpc_txt, "DARWIN").rename("ANOM_DAR")
                    anom_tah = self._extract_station_anom(tah_cpc_txt, "TAHITI").rename("ANOM_TAH")
                else:
                    anom_dar = self._monthly_anomaly(slp_dar, base_start, base_end).rename("ANOM_DAR")
                    anom_tah = self._monthly_anomaly(slp_tah, base_start, base_end).rename("ANOM_TAH")
                soi_anom = (anom_tah - anom_dar).rename("SOI_CPC_ANOMALIA_CALC")
                cpc_anom_csv = self.OUT_TAB / f"SOI_serie-temporal_CPC_ANOMALIA_{self.SUF_EXEC}.csv"
                self._plot_timeseries_png(
                    series=soi_anom,
                    suffix=f"serie.temporal_CPC_ANOMALIA_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-6, 6),
                    title=f"Índice de Oscilação Sul (SOI) - Método das Anomalias do CPC (Sem Padronização) - Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_anom, "CPC_ANOMALIA_TESTE", self.SUF_EXEC, metodo_base="CPC_ANOMALIA")

                # validacao contra CPC_ANOM
                soi_cpc_txt = self._get_text(self.CPC_SOI)
                diff_anom = self._extract_diff_anom(soi_cpc_txt).rename("SOI_CPC_ANOMALIA")
                cpc_anom_df = pd.concat([soi_anom, diff_anom], axis=1).dropna(how="all")
                cpc_anom_df["diferenca"] = (cpc_anom_df["SOI_CPC_ANOMALIA_CALC"] - cpc_anom_df["SOI_CPC_ANOMALIA"]).round(3)
                cpc_anom_df.index.name = "data"
                cpc_anom_df.to_csv(cpc_anom_csv, float_format="%.3f", date_format="%Y-%m")
                m_cpc_anom = self._compute_stats(soi_anom, diff_anom, label="Teste CPC vs CPC_DIFF_ANOM")
                if m_cpc_anom:
                    rows.append({"metodo": "CPC_ANOMALIA_TESTE", **m_cpc_anom})

            # --- CSV unico com metricas ---
            if rows:
                out = self.OUT_VAL / f"SOI_metricas_estatisticas_{opt}_{self.SUF_EXEC}.csv"
                _format_metrics_df(rows).to_csv(out, index=False, float_format="%.3f")
                print(format_log("SALVO", item=f"Arquivo CSV com as métricas estatísticas do SOI (TESTE) →", destino=f"{out}"))
            return


        # ====== MODO EXTERNO (SLP externos + base custom) ======
        if modo == "EXTERNO":
            if not (self.BASE_EXTERNO and Path(self.EXT_TAH).exists() and Path(self.EXT_DAR).exists()):
                print(format_log("ATENCAO", message=f"Dados externos com a PNMM em Tahiti e Darwin não encontrado ou base não definida."))
                return


            # le nome do config
            nome_ext = self.cfg.get("SOI_EXTERNO_NOME", "").strip()
            if nome_ext:
                self.OUT_DIR = OUTPUT_ROOT / "SOI" / f"EXTERNO_{nome_ext}"
            else:
                self.OUT_DIR = OUTPUT_ROOT / "SOI" / "EXTERNO_PADRAO"
                print(format_log("ATENCAO", message=f"SOI_EXTERNO_NOME nao definido no arquivo de configuração → usando EXTERNO_PADRAO"))

            # redefine subpastas
            self.OUT_DIR.mkdir(parents=True, exist_ok=True)
            self.OUT_TAB = self.OUT_FIG = self.OUT_VAL = self.OUT_DIR

            opt = self.EXT_METODO
            tag2 = self.EXT_NOME
            print(format_log("INFO", message=f"Método escolhido no modo EXTERNO: {opt} | Fonte={tag2}"))


            rows = []   # metricas acumuladas

            # --- CRU/EXTERNO (RJ87) ---
            if opt in ("CRU", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_EXTERNO, metodo="CRU")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CRU no modo EXTERNO {tag2} com a base {base_str_pretty}"))

                tah_slp = self._read_slp_csv(self.EXT_TAH)
                dar_slp = self._read_slp_csv(self.EXT_DAR)
                soi_cru_ext = self._compute_cru_soi(
                    tah_slp, dar_slp,
                    base=f"{base_start}:{base_end}",
                    ddof_month=1, ddof_s2=1,
                    pairwise_base=True, s2_by_month=True, round_3dp=False
                )
                soi3_txt = self._get_text(self.CRU_SOI_3DP)
                soi3 = self._parse_matrix(soi3_txt, use_float=True, missing_to_nan=-99).rename("SOI_CRU")
                soi3 = soi3.reindex(soi_cru_ext.index)
                cru_ext_df = pd.concat([soi_cru_ext.rename("SOI_CRU_CALC"), soi3], axis=1)
                cru_ext_df = cru_ext_df.dropna(subset=["SOI_CRU_CALC"])
                cru_ext_df["diferenca"] = (cru_ext_df["SOI_CRU_CALC"] - cru_ext_df["SOI_CRU"]).round(3)
                cru_ext_df.index.name = "data"
                cru_csv = self.OUT_TAB / f"SOI_serie.temporal_CRU_{self.SUF_EXEC}.csv"
                cru_ext_df.to_csv(cru_csv, float_format="%.3f", date_format="%Y-%m")

                self._plot_timeseries_png(
                    series=soi_cru_ext,
                    suffix=f"serie.temporal_CRU_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método Ropelewski & Jones (1987) (CRU) - com dados {tag2} – Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_cru_ext, f"CRU", self.SUF_EXEC, metodo_base="CRU")

                # validacao contra CRU 3dp
                m_cru = self._compute_stats(soi_cru_ext, soi3.rename("SOI_CRU_3dp"), label=f"Externo {tag2} CRU vs CRU_3dp")
                if m_cru:
                    rows.append({"metodo": f"CRU_EXTERNO", **m_cru})

            # --- CPC PADRONIZADO/EXTERNO ---
            if opt in ("CPC_PADRONIZADO", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_EXTERNO, metodo="CPC_PADRONIZADO")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CPC PADRONIZADO no modo EXTERNO {tag2} com a base {base_str_pretty}"))
                tah_slp = self._read_slp_csv(self.EXT_TAH)
                dar_slp = self._read_slp_csv(self.EXT_DAR)
                z_tah = self._monthly_standardize(tah_slp, base_start, base_end, ddof_month=0, pairwise_base=True)
                z_dar = self._monthly_standardize(dar_slp, base_start, base_end, ddof_month=0, pairwise_base=True)
                zdiff = (z_tah - z_dar).rename("Zdiff_ext")
                msd = zdiff.loc[base_start:base_end].std(ddof=0)
                soi_cpc_ext = (zdiff / msd).rename("SOI_CPC_PADRONIZADO_CALC")

                cpc_csv = self.OUT_TAB / f"SOI_serie.temporal_CPC_PADRONIZADO_{self.SUF_EXEC}.csv"

                self._plot_timeseries_png(
                    series=soi_cpc_ext,
                    suffix=f"serie.temporal_CPC_PADRONIZADO_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método Padronizado do CPC - com dados {tag2} – Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_cpc_ext, f"CPC_PADRONIZADO", self.SUF_EXEC, metodo_base="CPC_PADRONIZADO")

                # validacao contra CPC_STD
                soi_cpc_txt = self._get_text(self.CPC_SOI)
                diff_std = self._extract_diff_std(soi_cpc_txt).rename("SOI_CPC_PADRONIZADO")
                diff_std = diff_std.reindex(soi_cpc_ext.index)
                cpc_ext_df = pd.concat([soi_cpc_ext, diff_std], axis=1)
                cpc_ext_df = cpc_ext_df.dropna(subset=["SOI_CPC_PADRONIZADO_CALC"])
                cpc_ext_df["diferenca"] = (cpc_ext_df["SOI_CPC_PADRONIZADO_CALC"] - cpc_ext_df["SOI_CPC_PADRONIZADO"]).round(3)
                cpc_ext_df.index.name = "data"
                cpc_ext_df.to_csv(cpc_csv, float_format="%.3f", date_format="%Y-%m")
                m_cpc = self._compute_stats(soi_cpc_ext, diff_std, label=f"Externo {tag2} CPC vs CPC_DIFF_STD")
                if m_cpc:
                    rows.append({"metodo": f"CPC_PADRONIZADO_EXTERNO", **m_cpc})

            # --- CPC ANOMALIA/EXTERNO ---
            if opt in ("CPC_ANOMALIA", "TODOS"):
                base_start, base_end = self._parse_base_range(self.BASE_EXTERNO, metodo="CPC_ANOMALIA")
                base_str_pretty = f"{base_start[:7]}–{base_end[:7]}"
                tag = f"{base_start[:7]}a{base_end[:7]}".replace("-", "")
                print(format_log("INFO", message=f"Iniciando o calculo do SOI/CPC ANOMALIA no modo EXTERNO {tag2} com a base {base_str_pretty}"))
                tah_slp = self._read_slp_csv(self.EXT_TAH)
                dar_slp = self._read_slp_csv(self.EXT_DAR)
                anom_tah = self._monthly_anomaly(tah_slp, base_start, base_end).rename("ANOM_TAH_EXT")
                anom_dar = self._monthly_anomaly(dar_slp, base_start, base_end).rename("ANOM_DAR_EXT")
                soi_anom_ext = (anom_tah - anom_dar).rename("SOI_CPC_ANOMALIA_CALC")

                cpc_anom_csv = self.OUT_TAB / f"SOI_serie.temporal_CPC_ANOMALIA_{self.SUF_EXEC}.csv"

                self._plot_timeseries_png(
                    series=soi_anom_ext,
                    suffix=f"serie.temporal_CPC_ANOMALIA_{self.SUF_EXEC}",
                    ano_inicio=1950,
                    ylim=(-4, 4),
                    title=f"Índice de Oscilação Sul (SOI) - Método das Anomalias do CPC (Sem Padronização) - com dados {tag2} – Base {base_str_pretty}"
                )
                # self._export_official_formats(soi_anom_ext, f"CPC_ANOMALIA", self.SUF_EXEC, metodo_base="CPC_ANOMALIA")

                # validacao contra CPC_ANOM
                soi_cpc_txt = self._get_text(self.CPC_SOI)
                diff_anom = self._extract_diff_anom(soi_cpc_txt).rename("SOI_CPC_ANOMALIA")
                diff_anom = diff_anom.reindex(soi_anom_ext.index)
                cpc_anom_ext_df = pd.concat([soi_anom_ext, diff_anom], axis=1)
                cpc_anom_ext_df = cpc_anom_ext_df.dropna(subset=["SOI_CPC_ANOMALIA_CALC"])
                cpc_anom_ext_df["diferenca"] = (cpc_anom_ext_df["SOI_CPC_ANOMALIA_CALC"] - cpc_anom_ext_df["SOI_CPC_ANOMALIA"]).round(3)
                cpc_anom_ext_df.index.name = "data"
                cpc_anom_ext_df.to_csv(cpc_anom_csv, float_format="%.3f", date_format="%Y-%m")
                m_cpc_anom = self._compute_stats(soi_anom_ext, diff_anom, label=f"Externo {tag2} CPC vs CPC_DIFF_ANOM")
                if m_cpc_anom:
                    rows.append({"metodo": f"CPC_ANOMALIA_EXTERNO", **m_cpc_anom})

            # --- CSV unico com metricas ---
            if rows:
                out = self.OUT_VAL / f"SOI_metricas_estatisticas_{opt}_{self.SUF_EXEC}.csv"
                _format_metrics_df(rows).to_csv(out, index=False, float_format="%.3f")
                print(format_log("SALVO", item="Arquivo CSV com métricas estatísticas do SOI (EXTERNO) →", destino=str(out)))

            return


    # ================== FUNcoES PADRaO (estatistica e plotagem) ==================
    def _compute_stats(self, s_calc: pd.Series, s_ref: pd.Series,
                       label: str = "Validacao", units: str = "",
                       name_calc: str = "ANOM_calc", name_ref: str = "ANOM_ref") -> dict:
        """
        Calcula metricas padrao (RMSE, MAE, Vies, r, R^2, slope/intercept, desvio padrão do erro, N, período).
        Espera duas Series mensais alinhadas no tempo.
        """
        cmp = pd.concat({name_calc: s_calc, name_ref: s_ref}, axis=1).dropna()
        if cmp.empty:
            print(f"[ESTATÍSTICA] === Validação SOI calculado pelo método {label} ===")
            print("Séries sem sobreposição suficiente.")
            return {}

        cmp["diff"] = cmp[name_calc] - cmp[name_ref]
        cmp["YR"]   = cmp.index.year

        rmse = float(np.sqrt((cmp["diff"]**2).mean()))
        mae  = float(np.abs(cmp["diff"]).mean())
        bias = float(cmp["diff"].mean())
        r    = float(cmp[name_calc].corr(cmp[name_ref]))     # Pearson
        r2   = float(r*r) if not np.isnan(r) else np.nan

        # Regressao linear: calc = slope * ref + intercept
        x = cmp[name_ref].to_numpy()
        y = cmp[name_calc].to_numpy()
        slope, intercept = np.polyfit(x, y, 1)

        desv_pad_erro = float(cmp["diff"].std(ddof=1))
        nmeses   = int(len(cmp))
        yr0, yr1 = int(cmp["YR"].min()), int(cmp["YR"].max())

        print(f"[ESTATÍSTICA] === Validação SOI calculado pelo método {label} ===")
        print(f"Periodo comparado: {yr0}–{yr1} ({nmeses} meses)")
        if units:
            print(f"RMSE: {rmse:.3f} {units} | MAE: {mae:.3f} {units} | Viés: {bias:+.3f} {units}")
            print(f"Correlação (r): {r:.3f} | R²: {r2:.3f} | slope: {slope:.3f} | intercept: {intercept:+.3f} {units}")
        else:
            print(f"RMSE: {rmse:.3f} | MAE: {mae:.3f} | Viés: {bias:+.3f}")
            print(f"Correlação (r): {r:.3f} | R²: {r2:.3f} | slope: {slope:.3f} | intercept: {intercept:+.3f}")
        print(f"Desvio-padrão do erro (diff): {desv_pad_erro:.3f}")

        return {
            "data_inicio": yr0,
            "data_fim": yr1,
            "n_registros": nmeses,
            "rmse": rmse,
            "mae": mae,
            "bias": bias,
            "corr": r,
            "r2": r2,
            "slope": float(slope),
            "intercept": float(intercept),
            "desv_pad_erro": desv_pad_erro,
        }

    def _plot_timeseries_png(self, series: pd.Series, suffix: str,
                             ano_inicio: int = 1950,
                             ylim: tuple | None = (-4, 4),
                             title: str | None = None,
                             ylabel: str = "Índice de Oscilação Sul (SOI)",
                             logo_path: str = "utils/atmosmarine.png"
                             ) -> None:
        """
        Plot mensal ao estilo do ONI, mas para SOI (mensal).
        Positivos em AZUL e negativos em VERMELHO, com logo.
        """
        sr = series.dropna()
        if sr.empty:
            print(format_log("ERRO", message=f"A série está vazia → O gráfico não será gerado."))
            return

        sr = sr[sr.index.year >= ano_inicio]
        if sr.empty:
            print(format_log("ERRO", message=f"A série vazia após filtro pelo ano_inicio → O gráfico não será gerado."))

            return

        x = sr.index.to_pydatetime()
        y = sr.to_numpy()
        pos_mask = y >= 0
        neg_mask = y <= 0

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.xaxis_date()


        # areas sombreadas (positivos azul, negativos vermelho)
        ax.fill_between(x, y, 0, where=pos_mask, interpolate=True, alpha=0.25, color="blue", zorder=1)
        ax.fill_between(x, y, 0, where=neg_mask, interpolate=True, alpha=0.25, color="red", zorder=1)

        # Linha da serie e linha zero
        ax.plot(x, y, color="0.35", linewidth=1.0, alpha=0.7, zorder=2)
        ax.set_xlim(sr.index.min(), sr.index.max())

        ax.axhline(0, linewidth=0.9, color="black", zorder=2)

        # Limiar tipico +ou-1.0 (tracejado)
        ax.axhline(+1.0, linewidth=1.5, color="blue", linestyle="--", alpha=0.6, zorder=2)
        ax.axhline(-1.0, linewidth=1.5, color="red", linestyle="--", alpha=0.6, zorder=2)

        # Eixos/labels
        if ylim is not None:
            ax.set_ylim(*ylim)
        last_year = int(sr.index.year.max())
        if title is None:
            title = f"Serie Temporal de {ano_inicio} até {last_year} do Índice de Oscilação Sul (SOI)"
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.xaxis.set_major_locator(mdates.YearLocator(5))   # ticks a cada 5 anos
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        fig.autofmt_xdate()
        fig.tight_layout()

        # Logo
        lp = Path(logo_path)
        if lp.exists():
            try:
                img = mpimg.imread(str(lp))
                ab = AnnotationBbox(
                    OffsetImage(img, zoom=0.04),
                    (0.12, 0.14),             # posicao (fracao do eixo)
                    xycoords="axes fraction",
                    frameon=False,
                    box_alignment=(1, 1),
                    zorder=10
                )
                ax.add_artist(ab)
            except Exception as e:
                print(format_log("ERRO", message=f"Falha ao inserir o LOGO: {e}."))

        else:
            print(format_log("ERRO", message=f"LOGO NÃO ENCONTRADO: {lp}"))


        out = self.OUT_FIG / f"SOI_{suffix}.png"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(format_log("SALVO", item="Figura da série temporal salva →", destino=f"{out}"))

    @staticmethod
    def _rng_str(s: pd.Series) -> str:
        if s is None or s.dropna().empty:
            return "vazio"
        return f"{s.index.min():%Y-%m} -> {s.index.max():%Y-%m} (N={s.notna().sum()})"
