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

import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

if "src" not in sys.modules:
    pkg = ModuleType("src")
    pkg.__path__ = [str(_SRC)]
    sys.modules["src"] = pkg

if "cartopy" not in sys.modules:
    mock_crs = SimpleNamespace(PlateCarree=lambda *args, **kwargs: None)
    mock_feature = SimpleNamespace(
        LAND=None,
        OCEAN=None,
        COASTLINE=None,
        BORDERS=None,
    )
    sys.modules["cartopy"] = SimpleNamespace(crs=mock_crs, feature=mock_feature)
    sys.modules["cartopy.crs"] = mock_crs
    sys.modules["cartopy.feature"] = mock_feature
