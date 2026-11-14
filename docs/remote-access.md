# Acesso remoto opcional (pt-BR)

Recomendação: **A, Home Assistant para avisos; B, Tailscale opcional para
vídeo/áudio ao vivo**. O acesso LAN continua sendo o padrão. Nada neste guia
instala ou habilita recursos automaticamente. A ponte MQTT é uma frente
separada: consulte [Home Assistant](home-assistant.md), cujo arquivo pode chegar
em outro merge. Este documento não implementa essa ponte.

Alvo: Raspberry Pi 4, Raspbian Buster armv7/armhf, Python 3.7 do sistema,
Apache/PHP 7.3 e MariaDB 10.3. Os scripts não mudam esses componentes, não
instalam dependências pip e não participam de `setup.sh`/`install_all.sh`.

## Comparação

As estimativas de consumo e latência abaixo são qualitativas, não medições da
Pi. Upload residencial, bitrate, relay, bateria e rede móvel alteram o resultado.

| Critério | A — HA: MQTT + Companion + motionEye/snapshot | B — Tailscale na Pi | C — WireGuard manual / no roteador | D — A+B |
|---|---|---|---|---|
| Portas no roteador | Nenhum encaminhamento novo; Pi fala com broker privado e HA já sai por Cloudflare | Nenhum encaminhamento manual; conexão direta por travessia NAT ou relay | Servidor em casa normalmente exige porta UDP pública (mesmo no roteador); sem isso precisa de hub externo e conexão de saída | Nenhum encaminhamento novo |
| Superfície de ataque | Pi fica privada; proteger broker, credenciais, HA e sua entrada pública com autenticação | Acrescenta daemon privilegiado e acesso dos peers autorizados; limitar ACL | Chaves, firewall e servidor VPN sob responsabilidade do dono; roteador pode tirar o daemon da Pi | Soma HA/broker e daemon VPN; separar permissões |
| Push de choro/VOX/cerca/queda | MQTT → automação → Companion; em geral segundos, sem garantia de prazo; depende da entrega push e do celular | Não fornece push por si; app OBM usa long-poll enquanto VPN e serviço estiverem ativos | Também não fornece push; long-poll pelo túnel | Companion para avisos, independentemente de abrir o vídeo/VPN no celular |
| Vídeo/áudio ao vivo | Snapshot é imagem pontual. motionEye pode integrar câmera ao HA, mas exige configurar fonte e suporte do frontend; áudio ao vivo não é garantido | Acesso HTTPS direto ao site/app existente, com os mesmos modos de áudio/vídeo | Acesso direto equivalente se rotas e firewall permitirem | Avisos/snapshot no HA; site/app via tailnet para ao vivo |
| Consumo na Pi 4 armv7 | MQTT de eventos é leve; snapshots ocasionais leves; motionEye/transcodificação contínua pode custar bastante CPU/RAM | Daemon residente + criptografia proporcional ao tráfego; sem transcodificação adicional; vídeo domina banda | Geralmente baixo com WireGuard no kernel; Buster pode exigir suporte extra; no roteador, custo VPN fora da Pi | Soma custos; evitar duas capturas/transcodificações concorrentes |
| Manutenção | Broker, automações, Companion, autenticação HA/Cloudflare e fonte de imagem | Atualizações, revisão ACL, dispositivos e expiração de credenciais | Maior: chaves, endpoints/DDNS, rotas, firewall, NAT/CGNAT e hub se necessário | Manter A e B; testar falhas separadamente |
| Conta externa | No cenário atual, Cloudflare; push padrão do Companion pode depender de serviços externos de entrega; MQTT local não exige conta cloud | Conta Tailscale/provedor de identidade; coordenação e relay externos | Protocolo não exige conta; hub/VPS/DDNS podem exigir | Dependências de A e B |

**Buster não recebe atualizações regulares de segurança desde 2024**: o LTS
Debian terminou em 30/06/2024; eventuais contratos ELTS não equivalem a cobertura
automática do Raspbian instalado. Planejar migração para um sistema suportado.
Nunca expor a Pi diretamente na internet (Apache, PHP, SSH, banco ou câmera),
nem usar Cloudflare Tunnel sem autenticação para publicar seus endpoints.
Mesmo com autenticação, publicar a Pi antiga por túnel não é a recomendação.
O Cloudflare já usado pelo HA deve terminar no HA protegido, não na Pi.
Fonte: [fim do LTS Buster](https://www.debian.org/News/2024/20240615).

Para A, manter broker privado, usuário MQTT com permissões mínimas e TLS quando
necessário. O HA recebe eventos e consulta imagens pela LAN; não colocar URLs
públicas de câmera em notificações. Credenciais pertencem a arquivo **fora do
repositório**, permissão `600`, nunca a exemplos, logs ou commits. A configuração
MQTT e os avisos pertencem ao guia da ponte. Snapshot não substitui vídeo ou áudio.

C só atende à exigência de não abrir portas se o túnel doméstico sair para um
hub acessível, ou outra infraestrutura já resolver a conectividade. Hospedar o
WireGuard no roteador não elimina a necessidade de endpoint alcançável. Portanto
não é a primeira escolha para esta instalação, especialmente sob CGNAT.

## Instalar B manualmente na Pi (não executado nesta frente)

1. Revisar os scripts e a política do tailnet. Criar uma conta protegida por MFA
   e instalar o cliente Tailscale no telefone/computador do dono.
2. Na Pi, a partir da raiz da cópia do projeto, executar apenas quando decidir
   habilitar a opção:

   ```sh
   sudo bash scripts/install_tailscale.sh
   ```

   O script recusa plataformas diferentes de Raspbian Buster armhf, instala
   `ca-certificates`, `curl` e `tailscale` via APT e habilita `tailscaled`.
   Usa a chave oficial `stable/raspbian/buster.asc`, com `signed-by` restrito ao
   repositório `https://pkgs.tailscale.com/stable/raspbian buster main`.
   É idempotente: repeti-lo converge os mesmos arquivos/pacotes/serviço, sem
   refazer login ou redefinir preferências de uma instalação existente.
   Fontes APT Buster antigas podem falhar; não contornar assinatura, validade ou
   TLS para prosseguir. A disponibilidade de pacote não garante suporte ao SO.
3. Executar separadamente e autenticar pela URL exibida, em navegador confiável:

   ```sh
   sudo tailscale up --ssh=false --advertise-exit-node=false --advertise-routes= --accept-routes=false --exit-node=
   tailscale ip -4
   tailscale status
   ```

   Não há auth key embutida, lida ou impressa pelo script. O caminho adotado é
   login no navegador; não é necessário criar uma auth key. Não usar `set -x`
   nem salvar URLs de autenticação ou estado privado em logs/repositório.
   As flags desativam Tailscale SSH, anúncio/uso de exit node e rotas de sub-redes.
   Não habilitar IP forwarding, Serve ou Funnel. Se o nó já tinha outra
   configuração, revisar suas preferências e a política antes de mudar funções.
4. Aprovar apenas os dispositivos do dono e a Pi no console. Revisar expiração,
   revogação e atualizações APT periodicamente. Testar reconexão após reiniciar.

Referências oficiais: [pacotes Raspbian Buster](https://pkgs.tailscale.com/stable/#raspbian-buster)
e [`tailscale up`](https://tailscale.com/docs/reference/tailscale-cli/up).

## Restringir o tailnet

Permitir somente TCP 443 dos dispositivos do dono para a Pi. TCP 22 é opcional
para OpenSSH convencional, com chave e firewall próprios; `--ssh=false` desliga
o servidor Tailscale SSH, não o OpenSSH instalado. Não permitir MariaDB ou portas
internas de câmera. Os streams precisam permanecer atrás do HTTPS do Apache;
se houver URL absoluta apontando para `.local` ou porta interna, revisar essa
configuração antes de liberar mais portas.

Exemplo conceitual de `grants`, substituindo os placeholders por IPs Tailscale
reais dos dispositivos selecionados (não por toda a conta ou todo o tailnet):

```json
{
  "grants": [
    {
      "src": ["<IP_TAILSCALE_CELULAR_DONO>", "<IP_TAILSCALE_COMPUTADOR_DONO>"],
      "dst": ["<IP_TAILSCALE_PI>"],
      "ip": ["tcp:443"]
    }
  ]
}
```

Este modelo com placeholders não é uma política pronta para aplicar. Integrar
com a política existente, removendo permissões amplas que também atinjam a Pi:
grants/ACLs são aditivos, esta regra não nega acessos concedidos por outras.
Não manter a regra inicial que permite tudo. Para 22, adicionar uma regra
separada só do computador administrador. Validar no editor de políticas com
testes de acesso permitido e negado antes de depender do túnel.
Referência: [grants e portas](https://tailscale.com/docs/reference/syntax/grants).

## Endereço, Android, navegador e certificado

Com cliente VPN conectado ao mesmo tailnet, usar `https://<IP_TAILSCALE_PI>:443`
ou `https://<NOME_MAGICDNS_PI>:443`. Obter o IP com `tailscale ip -4` e o nome
no console; preferir o FQDN MagicDNS mostrado lá. `.local` usa mDNS da LAN e
normalmente não resolve fora de casa. MagicDNS resolve nomes privados, não cria
um certificado HTTPS confiável nem publica o site na internet.
Referência: [MagicDNS](https://tailscale.com/docs/features/magicdns).

Verificação no código em `android/app/src/main/java/org/openbabymonitor/app/`:

- `PinnedTrust.kt`, `fingerprintOf()`: SHA-256 de `certificate.encoded`, isto é,
  **certificado X.509 inteiro**, não hash da chave pública/SPKI. Reemitir o
  certificado, mesmo com a mesma chave, muda o pin e requer novo pareamento.
- `PinnedTrustManager` exige esse pin; `pinnedHostnameVerifier()` aceita o
  hostname quando usado com essa fábrica TLS. Logo, trocar LAN por IP/MagicDNS
  preserva a validação **se o servidor apresentar exatamente o mesmo certificado**.
  Não é preciso alterar o algoritmo de pinning para trocar o host.
- `MonitorApi.kt` usa essa fábrica e esse verificador nas conexões HTTPS.
  `Prefs.kt`, `baseUrl()`, monta `https://host:port`; `poll()` chama
  `/app_poll.php` nesse endereço. O long-poll funcionaria via tailnet **sem
  mudança de protocolo ou código**, desde que o host aponte para a Pi no tailnet,
  a porta seja 443, o token seja válido e a VPN esteja ativa.
- `MainActivity.kt`, `PinnedWebViewClient.onReceivedSslError()`, também compara
  o certificado recebido com o pin antes de permitir o WebView autoassinado.
- `SettingsActivity.kt` mostra o pareamento e oferece desfazer, sem editor de
  host. Na interface atual: desfazer o pareamento e refazê-lo em `SetupActivity`
  com IP/MagicDNS (campo host sem `https://` nem caminho) e porta 443. Conferir
  novamente a impressão digital por canal local confiável. Isso cria um novo
  pareamento/token; revisar dispositivos antigos no monitor. Um editor de host
  preservando pin/token seria melhoria futura do app, fora desta frente.

No navegador comum não existe o pin privado do app. IP/MagicDNS pode produzir
erro de nome e de autoridade para o certificado autoassinado. A VPN não elimina
essa validação TLS: usar confiança local gerenciada e certificado com SAN
adequado, ou o app pareado. Não ensinar a desativar globalmente validação TLS.
Trocar o certificado para adequar SAN também exige novo pareamento do Android.

O long-poll não vira push do Companion: requer serviço do app OBM, permissões
de notificações/bateria e VPN funcionando. Quedas de rede móvel e suspensão do
Android atrasam avisos. Para D, preferir Companion para alertas e abrir a VPN
para consultar ao vivo; habilitar ambos os canais pode duplicar notificações.

## Teste manual e remoção

Sem executar nesta frente, depois de uma instalação deliberada:

1. Confirmar que LAN, modos e app continuam funcionando antes de sair de casa.
2. Desligar Wi-Fi do celular, usar dados móveis e conectar a VPN. Abrir host do
   tailnet, conferir certificado/pareamento, vídeo e áudio dos modos existentes.
   Medir atraso de imagem e som e verificar CPU/memória na Pi durante o uso;
   nenhuma medição foi feita neste trabalho.
3. Gerar eventos controlados de choro/VOX/cerca/queda, sem depender de uma criança
   real, e testar aviso no Companion com tela bloqueada. Separadamente, testar
   long-poll OBM, reconexão VPN e retorno de rede; evitar confundir os dois canais.
4. Confirmar 443 permitido no dispositivo autorizado e negado em outro peer;
   confirmar 22 e demais portas negadas se não explicitamente autorizadas.
   Sem VPN, o endereço privado deve ficar inacessível pelos dados móveis.
5. Desligar VPN e confirmar que A continua entregando avisos. Testar também
   indisponibilidade de internet/HA/broker: não assumir entrega remota garantida.

Para remover B, fazer pela LAN ou console local: a conexão pela VPN vai cair.

```sh
sudo bash scripts/uninstall_tailscale.sh
```

O script para/desabilita o serviço se presente, remove o pacote e os arquivos
APT `obm-tailscale.list`/`obm-tailscale.asc` criados pelo instalador. Pode ser
repetido. Não remove fontes/chaves de instalações anteriores com outros nomes,
nem usa `autoremove`. Revogar a Pi no console Tailscale. O estado privado em
`/var/lib/tailscale` é preservado: para descartar definitivamente a identidade,
removê-lo manualmente só após revisar seu conteúdo/caminho e revogar o nó.
Esse estado nunca deve ir para backup público ou repositório. Reinstalar com
estado preservado pode retomar a identidade anterior. A ponte HA permanece
independente e deve ser removida conforme seu próprio guia.
