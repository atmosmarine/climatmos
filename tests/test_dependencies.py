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

import importlib

import pytest


# Lista com os principais módulos utilizados ao longo do projeto.
REQUIRED_MODULES = [
    ("numpy", None),
    ("pandas", None),
    ("xarray", None),
    ("matplotlib", "pyplot"),
    ("cartopy", "crs"),
    ("sklearn", "linear_model"),
    ("requests", None),
]


@pytest.mark.parametrize(("module_name", "attribute"), REQUIRED_MODULES)
def test_required_dependencies_installed(module_name: str, attribute: str | None):
    """
    Garante que os módulos essenciais do pipeline estejam disponíveis no ambiente.
    Caso o import falhe, o teste quebra evidenciando dependência ausente.
    """
    module = importlib.import_module(module_name)
    if attribute:
        getattr(module, attribute)
