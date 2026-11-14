# Baseline de regressão

Execute na raiz: `python -m pip install -r requirements-dev.txt` e
`python -m pytest -q tests`.

O CI usa Python 3.7 e PHP 7.3 (baseline do Raspbian Buster), em Ubuntu
22.04 com actions/setup-python e shivammathur/setup-php. O pytest 7.4.4
mantém suporte a Python 3.7. Não é necessário instalar requirements.txt.

Os testes carregam o código real de VoxTrigger com os imports de serviços e
áudio substituídos temporariamente por módulos vazios. Nenhum teste captura
áudio/vídeo ou acessa hardware, MySQL ou serviços. Os testes de configuração
usam arquivos temporários e uma leitura do JSON do repositório. Os relógios do
VOX são números explícitos; não há espera real.

O workflow compila todos os .py em control/, detection/ e config/ sem importar
os módulos, e executa php -l em todos os .php. Isso verifica sintaxe, sem
validar integração com dispositivos, bibliotecas de inferência ou Android.
O workflow Android existente continua independente.
