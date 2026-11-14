# Home Assistant: MQTT e notificações (pt-BR)

A Pi publica estado, heartbeat e eventos no Mosquitto da LAN; o Home Assistant
2026.11 cria as entidades por MQTT Discovery e envia push pelo Companion. O acesso
externo continua pelo HA/Cloudflare. Não exponha 1883 à Internet. O cliente usa
somente a stdlib do Python 3.7: não instala paho, mosquitto-clients ou pip.
Tudo vem desligado. A instalação não inicia nem habilita o serviço sem `--start`.

## Preparar o HA e o broker

Habilite a integração MQTT do HA conectada ao add-on Mosquitto. Crie um usuário
MQTT dedicado em Configurações > Pessoas > Usuários (ative o modo avançado do
perfil se necessário), sem privilégios administrativos; alternativamente use um
login dedicado na configuração `logins` do add-on, conforme a versão instalada.
Use `<USUARIO_MQTT>` e `<SENHA_MQTT>` apenas como placeholders neste documento.
Não reutilize a conta administrativa do HA.

ACL sugerida para esse usuário (adapte `baba`, prefixos e configuração de ACL do
add-on; o usuário do próprio HA precisa ler esses tópicos e publicar comandos):

```text
user <USUARIO_MQTT>
topic write babymonitor/baba/availability
topic write babymonitor/baba/state
topic write babymonitor/baba/event
topic write babymonitor/baba/snapshot
topic read babymonitor/baba/mode/set
topic write homeassistant/+/baba/+/config
```

O caminho de ACL/customização do add-on depende da instalação; aplique-o na
configuração do Mosquitto, não no repositório. Teste também que esse usuário não
consegue escrever fora da árvore permitida. MQTT sem TLS transmite credenciais
pela LAN; para TLS selecione `tls=true`, porta 8883 e `ca_file` apontando para a
CA PEM da sua instalação. Há verificação de certificado e hostname, sem opção
para desativá-la. O broker precisa oferecer TLS nessa porta.

## Configurar e instalar na Pi

Execute como o usuário da instalação (normalmente `pi`). Fora do repositório:

```sh
install -d -m 700 /home/pi/.config/babymonitor
install -m 600 /dev/null /home/pi/.config/babymonitor/mqtt.env
nano /home/pi/.config/babymonitor/mqtt.env
```

Conteúdo, substituindo os placeholders apenas na Pi:

```text
MQTT_USERNAME=<USUARIO_MQTT>
MQTT_PASSWORD=<SENHA_MQTT>
```

Formato literal `CHAVE=valor`, sem `export`, aspas ou expansão de shell. `=` no
valor é permitido, quebras de linha e espaços nas extremidades não são. A ponte
recusa arquivo dentro do checkout ou sem permissão exatamente 600. Mantenha o
arquivo pertencente ao usuário do serviço. Nunca envie esse arquivo para git ou
cole seu conteúdo em logs. A ponte não registra payloads de autenticação.

Em `config/config.json`, seção `home_assistant`, edite o `initial_value` de cada
campo (não é tabela do banco e não tem página PHP de edição):

| Campo | Padrão / uso |
|---|---|
| enabled | false; mude para true |
| host / port | host vazio; preencha IP/nome LAN do HA, porta 1883 |
| tls / ca_file | false / vazio; para TLS, true, porta 8883 e CA PEM |
| discovery_prefix | homeassistant |
| base_topic / device_id | babymonitor / baba; ID estável e único por Pi |
| heartbeat_interval | 30 segundos (5–3600) |
| event_timeout | 30 segundos; duração dos pulsos de alerta e validade dos arquivos |
| snapshot_enabled | false |
| snapshot_interval | 30 segundos entre imagens, mínimo 5 |
| snapshot_max_bytes | 262144 bytes, máximo 1048576 |
| mode_command_enabled | false |
| secrets_file | /home/pi/.config/babymonitor/mqtt.env |

```sh
./install_ha_bridge.sh
sudo systemctl enable --now bm_ha_bridge.service
sudo systemctl status bm_ha_bridge.service
journalctl -u bm_ha_bridge.service -n 50
```

A instalação existente via `setup.sh` deve estar completa (`env/envvars` e
`env/envvar_exports`). O script valida usuário e caminho, não instala pacotes,
não modifica o banco nem permissões do restante da aplicação. O serviço usa
`Restart=always`; reinicie-o após editar configuração/segredos. Desabilitado na
configuração, ele fica ocioso sem acessar o broker. Para desativar uma ponte já
ativa, pare o serviço antes de mudar `enabled` para false.

```sh
sudo systemctl stop bm_ha_bridge.service
./uninstall_ha_bridge.sh
```

A desinstalação preserva config e credenciais. Discovery/estado retidos também
permanecem no broker. Remova o device no HA e limpe seus tópicos retidos com uma
ferramenta MQTT administrativa se quiser exclusão definitiva. Ao desligar apenas
snapshot/comando e reiniciar, a ponte limpa o discovery dessas entidades opcionais.
Não mude o ID/prefixos sem limpar os antigos.

## Entidades, eventos e limites

Device **Babá eletrônica**, com IDs únicos `obm_<device_id>_<obj>`:
Modo (Espera, Notify/Avisar, Áudio, Vídeo, VOX), Choro, VOX, Cerca virtual,
Saúde (`problem`, ON significa problema), Temperatura CPU, Último heartbeat e
Último evento. Os IDs de entidade são atribuídos pelo HA; ajuste os exemplos
abaixo aos IDs efetivos ou renomeie-os como nos exemplos.

Availability: `babymonitor/baba/availability`, `online`/`offline` retidos; Last
Will retido offline para queda abrupta, e offline no encerramento normal.
`state` é JSON retido. `event` é JSON **sem retain**, com `type`, `ts` ISO UTC e
`details` (valor e origem). Os tipos originais incluem `crying`, `babbling`,
`sound`, `transmission`, `motion`, `outside`, `awake`, `asleep`, `rec_stopped`.
Não há fila offline nem replay de eventos durante desconexão.

Polling a cada aproximadamente 0,5 s lê `.comm/event.json`, `vox_state.json` e
`fence.json`. Escritas parciais são ignoradas e relidas; arquivos antigos não
reativam alarmes. O arquivo de evento contém só o último evento: rajadas entre
duas leituras podem perder marcadores. Choro depende do EventLog já instalado
(tabela `events`, instalação de gravação/timeline); a ponte não cria tabela nem
altera detecção. VOX também usa transição para `transmitting`, e a cerca usa
`alert=motion/outside` quando configurada e no vídeo, mesmo sem EventLog.
Marcadores equivalentes com menos de 1 s entre si são agrupados.

Choro/cerca são pulsos com timeout. A cerca NÃO representa presença: `awake` e
`asleep` descrevem sono; `motion` é movimento dentro da área e `outside` movimento
fora. VOX fica ligado durante `transmitting`, com expiração de arquivo obsoleto;
isso inclui o hang time de silêncio do detector. O modo vem do mesmo banco do
site, lido por PHP CLI a cada heartbeat; mudanças podem levar até esse intervalo.
O select opcional aceita somente os cinco nomes internos de modo, usa
`site/src/mode.php::switchMode()` com a trava existente e ignora comandos MQTT
retidos. Não usa HTTP, sessão web ou um caminho alternativo de systemctl.

Se `.comm/health.json` existir, são usados `ts`, `ok`, `mode`, `checks`,
`cpu_temp_c`, `undervoltage` e demais campos. Saúde acusa problema também com
arquivo mais velho que 180 s, subtensão ou CPU >=80 °C. Sem esse arquivo, a ponte
lê modo via PHP e temperatura via sysfs; não infere subtensão. Heartbeat indica a
vida da ponte, não garante todos os periféricos: confira também Saúde. Falhas de
conexão usam backoff 2, 4, 8, 16, 32, 60 s, reiniciado após conexão estável por
60 s. Estados/discovery são republicados ao reconectar; PUBACK tem timeout.

## Imagem: motionEye e a Pi são fontes distintas

A câmera motionEye do quarto no HA **não vem da Pi**. A Pi não alimenta motionEye;
a HLS da Pi exige sessão e é cifrada. Não aponte a integração de câmera do HA para
a URL HLS autenticada do site.

A opção leve para ver a Pi no HA é `snapshot_enabled=true`: câmera MQTT recebe
JPEG somente em eventos de choro/VOX/cerca enquanto o modo é `videostream`.
Como `snapshot.php`, usa ffmpeg lendo o arquivo local `BM_PICAM_STREAM_FILE`,
incluindo suporte ao HLS cifrado local. Não exige sessão HTTP. Limita a 640 px,
8 s de processo, tamanho configurado e frequência; falha sem derrubar detecção.
Não retém a imagem no broker; o HA pode manter a última recebida, que não é vídeo
ao vivo. Como choro/VOX normalmente rodam em outros modos, a maior fonte de
snapshots no vídeo será a cerca. Não publica fotos em espera ou áudio.

## Automações (YAML)

Substitua IDs de entidades, serviço de celular, tópicos e caminho do painel.
As automações abaixo vão em `automations.yaml` (ou editor YAML individual sem o
hífen externo). Ative notificações e canal no Companion. Android: `priority`
high e `ttl: 0`; crie/ajuste o canal `Baba critica` para importância alta e, se
desejado, permita ignorar Não perturbe nas configurações do Android. Não é uma
garantia de entrega ou som. No iOS, configure permissão de alertas críticos e use
as opções de som crítico documentadas pelo Companion em vez de canal Android.

```yaml
- alias: Babá - choro ou VOX
  triggers:
    - trigger: state
      entity_id:
        - binary_sensor.baba_choro
        - binary_sensor.baba_vox
      to: 'on'
  actions:
    - action: notify.mobile_app_<seu_celular>
      data:
        title: Babá eletrônica
        message: 'Som detectado no quarto'
        data:
          priority: high
          ttl: 0
          channel: Baba critica
          # Opcional: remova se snapshot MQTT não estiver habilitado.
          image: /api/camera_proxy/camera.baba_snapshot
          actions:
            - action: URI
              title: Abrir painel
              uri: /lovelace/baba
  mode: single

- alias: Babá - offline ou heartbeat atrasado
  triggers:
    - trigger: mqtt
      topic: babymonitor/baba/availability
      payload: offline
      id: offline
    - trigger: template
      value_template: >-
        {{ as_timestamp(now()) -
           as_timestamp(states('sensor.baba_ultimo_heartbeat'), 0) > 180 }}
      for: '00:00:05'
  actions:
    - choose:
        - conditions: "{{ trigger.id == 'offline' }}"
          sequence:
            - wait_for_trigger:
                - trigger: mqtt
                  topic: babymonitor/baba/availability
                  payload: online
              timeout: '00:02:00'
              continue_on_timeout: true
            - condition: template
              value_template: '{{ not wait.completed }}'
    - action: notify.mobile_app_<seu_celular>
      data:
        title: Babá eletrônica offline
        message: Verifique alimentação, Wi-Fi e a ponte MQTT.
  mode: single

- alias: Babá - saúde
  triggers:
    - trigger: state
      entity_id: binary_sensor.baba_saude
      to: 'on'
      for: '00:00:30'
    - trigger: numeric_state
      entity_id: sensor.baba_temperatura_cpu
      above: 80
      for: '00:01:00'
  actions:
    - action: notify.mobile_app_<seu_celular>
      data:
        title: Verifique a babá eletrônica
        message: 'Falha de saúde, subtensão ou temperatura elevada. Consulte health.json e alimentação.'
  mode: single
```

O trigger MQTT aguarda offline e cancela o alerta se online chegar em dois minutos;
o template também cobre ausência de heartbeat. `unknown`/`unavailable` é tratado
como ausência. Durante partida do HA pode gerar alerta se a Pi não publicar.
A imagem é opcional: só existe após um evento no vídeo e pode ser antiga. O
Companion precisa conseguir buscar a imagem pelo HA autenticado; teste fora da
LAN usando seu acesso externo. A ação abre o painel já publicado no HA.

Cartão Lovelace (o Logbook/Histórico do HA precisa registrar essas entidades):

```yaml
type: vertical-stack
cards:
  - type: picture-entity
    entity: camera.motioneye_quarto
    camera_view: live
    name: Quarto (motionEye)
  - type: entities
    title: Babá eletrônica
    entities:
      - sensor.baba_modo
      - binary_sensor.baba_choro
      - binary_sensor.baba_vox
      - binary_sensor.baba_cerca_virtual
      - binary_sensor.baba_saude
      - sensor.baba_temperatura_cpu
      - sensor.baba_ultimo_heartbeat
  # Opcional: câmera MQTT da Pi, habilitada por arquivo.
  - type: picture-entity
    entity: camera.baba_snapshot
    name: Pi - último evento
  - type: logbook
    hours_to_show: 12
    entities:
      - sensor.baba_ultimo_evento
      - binary_sensor.baba_choro
      - binary_sensor.baba_vox
      - binary_sensor.baba_cerca_virtual
```

O Logbook mostra mudanças de estado, não é uma fila completa de eventos iguais
consecutivos. Para histórico exato de cada JSON, use automação MQTT no tópico
`event` para seu armazenamento de preferência; a timeline local continua sendo
a fonte dos eventos registrados no banco.

## Verificação manual

1. Reinicie a ponte configurada e veja device/discovery no HA, disponibilidade
   online e heartbeat a cada 30 s. Confirme modo Notify/Avisar para `listen`.
2. Dispare choro em listen, VOX em vox e movimento dentro/fora da cerca no vídeo.
   Veja `event` via “Escutar um tópico” da integração MQTT e ON/OFF das entidades.
   Confira expiração dos pulsos e que asleep/awake não ligam Cerca virtual.
3. Com snapshots habilitados, teste evento no vídeo; confira JPEG, intervalo e
   ausência de publicações em outro modo. Teste imagem/push com celular fora da LAN.
4. Habilite select, teste cinco modos e verifique o site; payload inválido e
   comando retido não devem trocar modo. Depois desabilite e reinicie.
5. Pare normalmente: offline imediato. Simule queda abrupta do processo/rede:
   offline após timeout MQTT/keepalive e push após dois minutos. Verifique
   reconexão e nova publicação de estado/discovery, sem replay de eventos velhos.
6. Com a frente de saúde instalada, simule dados de teste de subtensão/temperatura
   no contrato health.json; sem ela, confira fallback e ausência de dependência.

Referências oficiais: [MQTT Discovery](https://www.home-assistant.io/integrations/mqtt/),
[sensor MQTT](https://www.home-assistant.io/integrations/sensor.mqtt/),
[notificações críticas Companion](https://companion.home-assistant.io/docs/notifications/critical-notifications/).
