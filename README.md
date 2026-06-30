# ClimAtmos

## Introdução
O ClimAtmos constitui uma ferramenta científica e operacional, escrita em Python e disponibilizada em código aberto, dedicada ao cálculo automatizado de um conjunto de índices climáticos e subsazonais. Os índices atualmente incluídos são: AAO, AMO, MEI, OMJ, ONI, PDO e SOI. 
A ferramenta foi concebida para replicar os índices oficiais, permitindo a reprodução de séries históricas e recentes de forma consistente com as metodologias de referência. Além disso, o ClimAtmos possibilita a realização de experimentos com diferentes parâmetros e bases de dados utilizados nos cálculos dos índices, oferecendo recursos para geração automática de gráficos, tabelas de saída e métricas de validação.
O desenvolvimento do ClimAtmos atende a uma demanda por soluções nacionais que reduzam a dependência de produtos internacionais, ampliem a autonomia técnica das instituições brasileiras e fortaleçam a capacidade de análise da variabilidade climática em múltiplas escalas temporais.


---

### Requisitos
O ClimAtmos foi concebido para utilizar os pacotes (ou bibliotecas) Python nas versões listadas abaixo.  
Caso ocorra algum problema de compatibilidade entre versões antigas ou atuais, o usuário pode consultar a lista `requirements.txt`, presente no diretório raiz.

Recomenda-se:
- Criar um **ambiente virtual dedicado** (Python 3.10+)  
- Instalar os pacotes através do comando `pip install` ou diretamente pelo arquivo `requirements.txt`.

**Requisitos mínimos:**
- Python **3.10+** (recomendado)
- Pacotes: numpy, pandas, xarray, matplotlib, netCDF4, cftime, cartopy, requests, scikit-learn, shapely, pyproj, pyshp, pillow
- Acesso à internet (para baixar dados no primeiro uso).

---

#### 1) Lista `requirements.txt`

```text
Cartopy==0.25.0
certifi==2025.8.3
cftime==1.6.4.post1
charset-normalizer==3.4.3
contourpy==1.3.3
cycler==0.12.1
dask>=2022.12
fonttools==4.59.2
idna==3.10
joblib==1.5.2
kiwisolver==1.4.9
matplotlib==3.10.6
netCDF4==1.7.2
numpy==2.3.2
packaging==25.0
pandas==2.3.2
pillow==11.3.0
pyparsing==3.2.3
pyproj==3.7.2
pyshp==2.3.1
python-dateutil==2.9.0.post0
pytz==2025.2
pyyaml==6.0.2
requests==2.32.5
scikit-learn==1.7.2
scipy==1.16.2
shapely==2.1.2
six==1.17.0
tabulate==0.9.0
threadpoolctl==3.6.0
tzdata==2025.2
urllib3==2.5.0
xarray==2025.9.0
pytest==7.4.4

```````````
#### 2) Comandos para instalação

**Linux/MacOS**
```text

python -m venv atm   # Cria o ambiente virtual com nome “atm”
source atm/bin/activate  # Ativa o ambiente virtual
pip install -r requirements.txt  # Instala os pacotes
```````````

**Windows (PowerShell)**
```text

python -m venv atm
atm\Scripts\activate
pip install -r requirements.txt
```````````
**Componentes principais da ferramenta:**

* ClimAtmos.py: Interface de Linha de Comando (CLI) que lê as configurações fornecidas pelo usuário, instancia e executa a ferramenta.
* Arquivo de configuração: arquivo que contém as configurações definidas pelo usuário para o cálculo dos índices. O diretório conf/ contém o template do arquivo, no formato esperado para leitura pelo ClimAtmos.py, e recomenda-se utilizar este diretório para armazenamento dos arquivos de configuração utilizados para rodar a ferramenta.
* Códigos fonte: códigos dos índices e de funcionalidades comuns, contidos no diretório src/. Recomenda-se não fazer alterações neste diretório.
* Lista de requisitos do sistema: arquivo requirements.txt.
* Testes unitários: códigos para realização de testes unitários, localizados na pasta tests/.
* Diretórios de armazenamento e execução: 
    * data: diretório para armazenamento de dados de entrada, onde são salvos os arquivos que são baixados automaticamente pela ferramenta e arquivos de cache.
    * logs: diretório onde são salvos os arquivos de log das execuções do ClimAtmos. Os logs são identificados pelo índice, modo, data e hora da execução. Recomenda-se o gerenciamento deste diretório com limpeza periódica.
    * output: diretório onde são salvos os arquivos de saída de cada índice.
    * utils: diretório contendo arquivos auxiliares, incluindo o logo da AtmosMarine (.png) para inserção em figuras e exemplos de arquivos com dados sintéticos para utilização no modo EXTERNO (para consulta de formatação).

## Documentação

A documentação de operação do ClimAtmos, incluindo descrição dos módulos de cálculo, parâmetros de configuração, modos de operação e exemplos de uso, encontra-se no diretório `doc/`, no arquivo `Documentacao_ClimAtmos_v1.0.pdf`.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21072251.svg)](https://doi.org/10.5281/zenodo.21072251)


## Licença

O ClimAtmos é software livre e está licenciado sob os termos da
[GNU General Public License, versão 3 (GPLv3)](./LICENSE).

Em resumo, você pode usar, estudar, modificar e redistribuir este software.
No entanto, se você redistribuir versões modificadas ou software que incorporem
o ClimAtmos como parte integrante, essas versões também devem ser disponibilizadas
sob a GPLv3, com código-fonte acessível.

As bibliotecas de terceiros utilizadas pelo projeto permanecem licenciadas sob
seus próprios termos. Um resumo das principais dependências e respectivas
licenças pode ser encontrado em [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md).

Para detalhes completos, consulte o arquivo [LICENSE](./LICENSE).

## Contato

Em caso de dúvidas, sugestões ou relatos de problemas, entre em contato com a equipe de desenvolvimento pelo e-mail  
[atm@atmosmarine.com](mailto:atm@atmosmarine.com).










