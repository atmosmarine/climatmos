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
import os, time, shutil, urllib.request
import warnings
warnings.filterwarnings("ignore", message="Degrees of freedom <= 0 for slice.", category=RuntimeWarning)
from pathlib import Path
from glob import glob
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
import datetime as _dt
from dataclasses import dataclass

import sys
import numpy as np
import xarray as xr
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.image as mpimg
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import unicodedata
import matplotlib.dates as mdates  # <-- precisa disso

from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from typing import Tuple, Optional
import re

import os, time, shutil, urllib.request, math, sys
from matplotlib.ticker import MultipleLocator
from sklearn.linear_model import LinearRegression
from typing import Tuple, Optional
import re
import requests
from io import StringIO

# Diretório padrão para centralizar todas as saídas da aplicação
OUTPUT_ROOT = Path("outputs")
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
