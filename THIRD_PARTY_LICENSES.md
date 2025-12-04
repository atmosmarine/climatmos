# Third-party licenses

O software **ClimAtmos**, desenvolvido pela **Atmosmarine**, é distribuído sob os termos da  
[GNU General Public License v3.0 (GPLv3)](./LICENSE).

Além do código próprio do ClimAtmos, o projeto faz uso de diversas bibliotecas de terceiros,
que permanecem licenciadas sob seus **próprios termos originais**.  
Este documento lista os principais pacotes declarados em `requirements.txt`, suas versões e
um resumo das licenças correspondentes.

As informações abaixo têm caráter **informativo**.  
Para qualquer uso que exija rigor jurídico, consulte sempre:

- O arquivo de licença oficial de cada projeto (normalmente `LICENSE` no repositório deles); e  
- A licença principal do ClimAtmos em `LICENSE` (GPLv3).

Todas as bibliotecas listadas abaixo utilizam licenças permissivas ou copyleft fraco
(BSD, MIT, Apache-2.0, MPL-2.0, PSF-like etc.), compatíveis com a distribuição do ClimAtmos
sob GPLv3.

| Pacote             | Versão        | Licença (resumo)                                  | URL do projeto                                   |
|--------------------|--------------|---------------------------------------------------|--------------------------------------------------|
| Cartopy            | 0.25.0       | BSD-3-Clause                                      | https://scitools.org.uk/cartopy/                 |
| certifi            | 2025.8.3     | Mozilla Public License 2.0 (MPL-2.0)              | https://github.com/certifi/python-certifi        |
| cftime             | 1.6.4.post1  | MIT                                               | https://unidata.github.io/cftime/                |
| charset-normalizer | 3.4.3        | MIT                                               | https://github.com/Ousret/charset_normalizer     |
| contourpy          | 1.3.3        | BSD-3-Clause                                      | https://github.com/contourpy/contourpy           |
| cycler             | 0.12.1       | BSD-3-Clause                                      | https://github.com/matplotlib/cycler             |
| dask               | ≥2022.12     | BSD-3-Clause (“New BSD”)                          | https://www.dask.org/                            |
| fonttools          | 4.59.2       | MIT                                               | https://github.com/fonttools/fonttools           |
| idna               | 3.10         | BSD-like (3-Clause)                               | https://github.com/kjd/idna                      |
| joblib             | 1.5.2        | BSD-3-Clause                                      | https://joblib.readthedocs.io/                   |
| kiwisolver         | 1.4.9        | Modified BSD (BSD-3-Clause)                       | https://github.com/nucleic/kiwi                  |
| matplotlib         | 3.10.6       | Matplotlib License (PSF-based, BSD-compatível)    | https://matplotlib.org/                          |
| netCDF4            | 1.7.2        | MIT                                               | https://github.com/Unidata/netcdf4-python        |
| numpy              | 2.3.2        | Modified BSD (BSD-3-Clause)                       | https://numpy.org/                               |
| packaging          | 25.0         | Apache-2.0 / BSD                                  | https://github.com/pypa/packaging                |
| pandas             | 2.3.2        | BSD-3-Clause                                      | https://pandas.pydata.org/                       |
| pillow             | 11.3.0       | “Pillow License” (HPND, BSD-compatível)           | https://python-pillow.org/                       |
| pyparsing          | 3.2.3        | MIT                                               | https://github.com/pyparsing/pyparsing           |
| pyproj             | 3.7.2        | MIT                                               | https://github.com/pyproj4/pyproj                |
| pyshp              | 2.3.1        | MIT                                               | https://github.com/GeospatialPython/pyshp        |
| python-dateutil    | 2.9.0.post0  | Dual license (inclui BSD-like; ver LICENSE)       | https://github.com/dateutil/dateutil             |
| pytz               | 2025.2       | MIT                                               | https://pythonhosted.org/pytz/                   |
| pyyaml             | 6.0.2        | MIT                                               | https://pyyaml.org/                              |
| requests           | 2.32.5       | Apache License 2.0                                | https://github.com/psf/requests                  |
| scikit-learn       | 1.7.2        | BSD-3-Clause                                      | https://scikit-learn.org/                        |
| scipy              | 1.16.2       | BSD-3-Clause                                      | https://scipy.org/                               |
| shapely            | 2.1.2        | BSD-3-Clause                                      | https://github.com/shapely/shapely               |
| six                | 1.17.0       | MIT                                               | https://github.com/benjaminp/six                 |
| tabulate           | 0.9.0        | MIT                                               | https://github.com/astanin/python-tabulate       |
| threadpoolctl      | 3.6.0        | BSD-3-Clause                                      | https://github.com/joblib/threadpoolctl          |
| tzdata             | 2025.2       | Apache-2.0                                        | https://github.com/python/tzdata                 |
| urllib3            | 2.5.0        | MIT                                               | https://github.com/urllib3/urllib3               |
| xarray             | 2025.9.0     | Apache License 2.0                                | https://github.com/pydata/xarray                 |
| pytest             | 7.4.4        | MIT                                               | https://docs.pytest.org/                         |

> **Nota:** esta tabela cobre apenas as dependências listadas explicitamente em `requirements.txt`.  
> Outras dependências transitivas podem ser instaladas por pip/conda e permanecem licenciadas sob seus respectivos termos originais.