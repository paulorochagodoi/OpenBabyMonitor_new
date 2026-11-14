# Watchdog e heartbeat (contrato v1)

Opcional, desligado por padrão (`watchdog.enabled=false`). Não requer pacotes
novos: usa stdlib e a camada `control/database.py` já instalada (mysql.connector).
Não altera o banco. O modo vem de `modes.current`, mapeado por `config.json`.
MariaDB deve estar ativo e responder à consulta do modo com as credenciais
existentes; o watchdog nunca inclui credenciais nem mensagens de exceção no JSON/log.
Apache é consultado somente em localhost, sem proxy, com certificado autoassinado
aceito. Respostas HTTP abaixo de 500, inclusive redirecionamentos, provam resposta.

## Instalação em uma Pi já configurada

1. Como usuário BM_USER da instalação, rode `./install_watchdog.sh`.
2. Edite a seção `watchdog` em `config/config.json`: defina `enabled` como `true`.
3. Rode `sudo systemctl restart bm_watchdog.service`.
4. Confira `systemctl status bm_watchdog` e `journalctl -u bm_watchdog`.

O instalador cria `control/services/bm_watchdog.service`, liga em
`/lib/systemd/system/`, habilita e inicia a unit. Com enabled=false, o daemon
apenas sinaliza ao systemd, sem sondagens, arquivo de saúde ou recuperação.
Após editar qualquer configuração, reinicie a unit. Para desativar imediatamente,
pare a unit; para remover, rode `./uninstall_watchdog.sh` (preserva configuração e
histórico de tentativas). Os scripts não integram o setup padrão.

O sudoers do setup já concede ao grupo web start/stop/restart de cada modo.
O instalador acrescenta `/etc/sudoers.d/bm_watchdog` somente para BM_USER executar
`systemctl restart apache2` e `systemctl restart mariadb`. Não concede reboot,
shell privilegiado nem comandos genéricos. A instalação deve conservar as regras
BM_MODES do setup. Os comandos do daemon usam `sudo -n` e timeout.

## Configuração e recuperação

A seção segue os parâmetros diretos de `control`/`network`, sem tabela SQL:

| Campo | Padrão | Significado |
| --- | --- | --- |
| enabled | false | Ativa sondagens e recuperação |
| interval_s | 10 | Intervalo entre ciclos (após terminar o ciclo anterior) |
| timeout_s | 3 | Timeout de cada comando/HTTP; conexão SQL usa segundos inteiros |
| apache_url | https://localhost | Também aceita http://localhost |
| cpu_temp_max_c | 80 | Alarme a partir deste valor |
| disk_max_pct | 90 | Alarme de disco do filesystem do projeto |
| mem_max_pct | 95 | Alarme de memória, usando MemAvailable |
| hls_max_age_s | 30 | Idade máxima do index.m3u8 em videostream |
| failure_count | 3 | K falhas consecutivas antes de tentar recuperação |
| restart_limit | 3 | Máximo de tentativas por serviço na janela |
| restart_window_s | 900 | Janela móvel do limite |
| backoff_s | 30 | Base do backoff exponencial entre tentativas |

Apache, MariaDB e o modo são recuperados separadamente. Serviço de modo inativo
ou HLS parado reiniciam somente `bm_<modo>`. HLS usa `BM_PICAM_STREAM_FILE` ou
`/run/shm/picam/index.m3u8`. Fora de videostream é não aplicável. O lock
`BM_MODE_LOCK_FILE` é adquirido sem bloquear; o modo é consultado novamente antes
do restart para não disputar uma troca pela interface. Se o lock não estiver
livre ou o modo mudar, a tentativa é conservadoramente contabilizada e adiada.
O standby é exceção: seu script termina normalmente, portanto inativo não é falha.
Não é possível detectar um ffmpeg travado apenas pelo HLS do picam; esta versão
vigia a saída de streaming, não a continuidade da gravação.

Uma recuperação zera a sequência; sucesso da sonda também. Mudança de modo
interrompe a sequência do modo anterior. Tentativas, inclusive erros/timeouts,
contam no limite e são persistidas atomicamente em `health.json.restarts` ANTES
do comando. Esse arquivo não é o heartbeat: é o histórico interno de orçamento,
com timestamps por serviço. Não o apague para contornar o limite. Erros de leitura
(exceto arquivo inexistente) fazem o daemon falhar de forma conservadora.
O backoff é base × 2 elevado ao número de tentativas ainda na janela; com o padrão,
a segunda espera pelo menos 60s e a terceira 120s. Reiniciar o daemon preserva o
orçamento; a contagem de K começa novamente. Ajustes regressivos no relógio
mantêm o orçamento conservador até o horário alcançar o timestamp registrado.

Recursos só geram alerta: nunca provocam restart. Bits atuais 0–3 de throttling
marcam falha; bits históricos são informativos. `undervoltage` é o bit 0 atual,
não o histórico bit 16. Sensores ausentes ficam null e não impedem sondagens;
falhas ao ler memória/disco fazem o daemon falhar, ficando o heartbeat stale.
Reinícios e transições de falha/recuperação vão para o journal. Não há envio de
alertas externo: o endpoint/JSON permite que HA/MQTT ou uptime consumam o estado.

## JSON e função de heartbeat

`control/.comm/health.json` é substituído atomicamente (arquivo temporário no
mesmo diretório, flush, fsync e rename). Permissão 0640, grupo da unit = grupo web.
Leitores devem abrir e decodificar de novo a cada leitura; não manter o descritor.

| Campo | Tipo | Contrato |
| --- | --- | --- |
| ts | number | Epoch em segundos no início da amostra; **heartbeat** |
| uptime_s | number | Segundos monotônicos desde a inicialização do daemon |
| mode | string | standby/listen/audiostream/videostream/vox ou unknown |
| ok | boolean | Todas as sondagens atuais passaram (não espera K) |
| checks | object | apache, mariadb, mode_service, stream, resources |
| checks.*.ok | boolean | Resultado atual |
| checks.*.detail | string | Texto diagnóstico sem segredos; não fazer parsing |
| cpu_temp_c | number/null | Temperatura da CPU |
| throttled | string/null | Máscara hexadecimal, ex. 0x0, inclui histórico |
| undervoltage | boolean/null | Subtensão atual |
| disk_used_pct | number | Percentual usado (0–100) |
| mem_used_pct | number | Percentual indisponível (0–100) |
| restarts | object | Serviço → número de tentativas na última hora |
| version | string | Versão do esquema: "1" |
| interval_s | number | Intervalo para cálculo de expiração |

Consumidores devem tolerar novos campos/checks e usar `ts` como heartbeat:
`stale = now - ts > 3 * interval_s` (também stale se arquivo ausente, inválido ou
no futuro). Agende intervalos/timeouts de modo que um ciclo normal não dure três
intervalos. O health registra o resultado ANTES do restart; a recuperação será
visível na amostra seguinte. O daemon manda READY=1 e WATCHDOG=1 via NOTIFY_SOCKET
(stdlib, incluindo sockets abstratos). WatchdogSec=120 cobre sondagens padrão;
aumente-o caso configure timeouts maiores. Durante espera, sinaliza a cada ≤5s.
Se travar, systemd o reinicia com Restart=always e RestartSec=15; StartLimitBurst=5
em 900s evita crash loops (após corrigir: `sudo systemctl reset-failed bm_watchdog`).

## Endpoint e verificação manual

GET `/health.php` sem sessão retorna **somente** ok, ts, mode, stale. Com sessão
válida do site (`isLoggedIn()`), retorna o documento completo mais stale; quando
stale, ok=false. HTTP 200 saudável, 503 falha/stale; métodos diferentes de GET
retornam 405. Cache desabilitado. A leitura não conecta ao banco nem exige login.
Não coloque o JSON completo em URLs públicas ou exemplos de logs externos.

Em ambiente de teste na Pi (interrompe o monitoramento):

1. Compare `curl -k https://localhost/health.php` com a resposta na aba Network
   do navegador autenticado. Anônimo deve ter exatamente quatro campos.
2. Pare Apache ou MariaDB separadamente; após K ciclos confira um restart no
   journal e recuperação. O endpoint fica indisponível durante a queda do Apache.
3. Em videostream, suspenda picam com SIGSTOP; após idade máxima + K ciclos,
   confira restart apenas de bm_videostream. Não faça isso com um bebê monitorado.
4. Faça trocas de modo na interface e confira ausência de restart do modo antigo.
5. Pare o watchdog, aguarde mais de 3 intervalos, consulte o endpoint: 503/stale.
6. Suspenda apenas o processo watchdog com SIGSTOP; aguarde WatchdogSec e confira
   o systemd reiniciando o daemon. Em crash loop, corrija a causa e reset-failed.
7. Use uma configuração de teste com limite baixo e uma falha mantida; confirme
   que o journal respeita janela/backoff mesmo após reiniciar o watchdog.

Não há testes automatizados PHP de integração: os casos de sessão, códigos HTTP
e expiração acima são manuais. Python é testado com fakes, sem Pi/rede/systemctl.

## Watchdog de hardware (opcional, separado)

`./install_watchdog.sh --hardware-watchdog` cria exclusivamente
`/etc/systemd/system.conf.d/bm-watchdog.conf` com `[Manager] RuntimeWatchdogSec=15`.
É equivalente à configuração em system.conf, sem editar o arquivo global.
Aplica-se em reboot planejado. Não é necessário para o daemon e fica desligado
por padrão. Exige `/dev/watchdog` funcional (Pi 4). **PID 1 pode reiniciar a Pi se
o sistema travar**; o daemon Python nunca solicita reboot. Remover o drop-in pelo
uninstaller também exige reboot planejado. Não sobrescreva configurações de
hardware watchdog administradas fora deste instalador.
