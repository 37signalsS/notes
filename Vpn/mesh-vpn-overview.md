# Mesh-VPN решения: Nebula, Netbird, Netmaker

**Актуально для:** Nebula 1.11.x / Netbird 0.80.x / Netmaker 1.7.x

## Определения

**Mesh-VPN** — overlay-сеть, в которой каждый узел устанавливает прямое соединение с любым другим (P2P), а общий «справочник» узлов, адресов и ключей ведёт координационный сервер (control plane). **Control plane** — сервис, раздающий конфигурацию (адреса, ключи, ACL) и не участвующий в передаче пользовательских данных. **Data plane** — зашифрованный трафик между узлами; у WireGuard-совместимых решений его содержимого не видит ни координатор, ни релей. **Lighthouse (Nebula)** — узел-«справочник»: узлы сообщают ему свои публичные адреса и через него узнают адреса пиров. **Relay / DERP-узел** — промежуточный сервер, ретранслирующий уже зашифрованные пакеты, когда прямое P2P-соединение невозможно (симметричный NAT, строгий файрвол). **NAT traversal** — автоматическое «пробивание» NAT через UDP hole punching и STUN. **Overlay** — виртуальная сеть поверх реальной. **Enrollment key / setup key / preauthkey** — предварительный ключ для неинтерактивной регистрации узла у координатора. **Routing peer / Gateway** — узел overlay, публикующий в сеть ресурсы, на которых клиент не установлен (подсеть, отдельный хост, домен). **Exit node / Internet Gateway** — узел, через который трафик клиентов overlay выходит в интернет.

## Основные концепции

### Место среди уже описанных решений

В базе подробно разобраны **Tailscale/Headscale** ([tailscale.md](./tailscale.md)) и **ZeroTier** ([zerotier.md](./zerotier.md)). Настоящий материал — про self-hosted mesh-решения на базе WireGuard и собственных протоколов, которые рассматривают в контексте «что выбрать вместо коммерческого Tailscale, не уходя в публичное облако»:

| Решение | Транспорт | Control plane | Особенность | Self-hosted |
|---------|-----------|---------------|-------------|-------------|
| **Tailscale (SaaS)** | WireGuard | Tailscale Inc. | Простота, MagicDNS, SSO | Нет (кроме Headscale) |
| **Headscale** | WireGuard | self-hosted | Open-source координатор Tailscale-клиентов | Да |
| **ZeroTier** | собственный (L2) | Central / self-hosted | L2-оверлей, MOON | Да |
| **Nebula** | собственный (Noise Protocol) | self-hosted (lighthouse) | Свой CA и PKI, лёгкий демон, без внешней БД | Да |
| **Netbird** | WireGuard | self-hosted | OIDC/SSO, ACL, reverse proxy, много роутинга | Да |
| **Netmaker** | WireGuard | self-hosted | Gateways (egress/ingress), ACL, UI, MQTT | Да |

### Что общего у всех mesh-решений

- **Ключи/адреса выдаёт координатор** (или собственная PKI), узел получает конфиг готовым к использованию.
- **NAT traversal** автоматический: прямой UDP, при невозможности — relay.
- **ACL** применяются на control plane: у Tailscale — HuJSON (`grants`), у Netbird и Netmaker — политики по группам/хостам/тегам, у Nebula — распределённый firewall на узле, вычисляемый по группам из сертификата.
- **Аудит входов** на стороне координатора (см. [vpn-session-audit.md](./vpn-session-audit.md)).
- **Выход в интернет и удалённые сети** через узел: exit node у Tailscale, gateways (egress/ingress) у Netmaker, Networks и exit nodes у Netbird, `unsafe_routes` у Nebula.

### Архитектура: control plane и data plane

**Nebula** — самый легковесный из рассматриваемых. Data plane и распределённый firewall реализованы одним демоном `nebula` на каждом узле; PKI обслуживает утилита `nebula-cert`. Отдельного сервиса-control plane нет: роль «справочника» выполняют lighthouses — обычные узлы с `am_lighthouse: true`. Нет внешней БД, нет MQTT, нет REST API; вся конфигурация узла — один YAML-файл и его сертификат. Протокол Nebula построен на **Noise Protocol Framework** (ECDH, по умолчанию AES-256-GCM); это не WireGuard.

**Netbird** — координатор с полноценным control plane. Исторически сервисы были раздельными: **management** (REST API + БД), **signal** (координация обмена адресами между пирами), **relay**, **STUN/TURN** (Coturn). В v0.29 relay переведён с TURN на собственный WebSocket/QUIC-релей, а management и signal консолидированы на порт 443 (согласование протокола по HTTP/2); в v0.65.0 всё сведено в единый контейнер `netbird-server` (management + signal + relay + STUN) с файлом `config.yaml`. Актуальный quickstart разворачивает `netbird-server` вместе с dashboard; опционально включается встроенный reverse proxy для публикации внутренних сервисов. Data plane — WireGuard: `signal` и `relay` релеят уже зашифрованные пакеты и не видят содержимого.

**Netmaker** — сервер (REST API + dashboard + MQTT-брокер) и сопутствующий стек мониторинга. На узлах демон `netclient` управляет **реальными WireGuard-интерфейсами**: overlay — это не отдельный протокол, а конфигурация WireGuard, которой дистанционно управляет сервер. Это даёт совместимость с любым клиентом WireGuard (в том числе статическим конфигом), но требует прав root на узле.

### Как узлы находят друг друга и проходят NAT

Все решения сначала пробуют установить прямое соединение, а к релею прибегают как к резерву:

- **Tailscale/Headscale** — STUN `udp/3478`, прямой UDP (по умолчанию `41641`), при неудаче — DERP ([tailscale.md](./tailscale.md)).
- **Netbird** — STUN/TURN (Coturn, `udp/3478`) и relay по WebSocket/WSS через `tcp/443`: работает там, где исходящий UDP закрыт.
- **Netmaker** — WireGuard UDP (по умолчанию `51821/udp`) и auto-relay; начиная с v1.7 доступен TCP/WSS-uplink (`tcp_proxy`) для сетей с блокировкой UDP.
- **Nebula** — обнаружение через lighthouse и периодический UDP hole punching (`punchy`); релей (`relay`) помечен экспериментальным.

### Идентичность, аутентификация и отзыв доступа

- **Nebula** — PKI: CA подписывает сертификат узла, в сертификат зашиваются Nebula-IP, имя и группы (`-groups`). Firewall на узле пропускает трафик по группам сертификата. Пользовательского слоя нет; отзыв — blocklist по отпечатку сертификата или перевыпуск CA.
- **Netbird** — OIDC/SSO (внешний IdP или встроенный Dex), setup keys для серверов и инфраструктуры как кода, ACL по группам/хостам/тегам.
- **Netmaker** — enrollment keys, синхронизация с IdP (OIDC, Okta, Google Workspace, Entra ID), роли, device approvals, MFA, теги.

### Критерии выбора (продакшен)

- **Регламентный контур без публичного облака** → Headscale, Nebula, Netbird, Netmaker, ZeroTier self-hosted.
- **Нужен SSO/MFA из коробки** → Netbird, Netmaker, Headscale (OIDC, см. [vpn-authentication.md](./vpn-authentication.md)).
- **L2-протоколы (ARP, широковещательные), legacy-интеграции** → ZeroTier (единственный L2-оверлей).
- **Минимальная инфраструктура, автономность, свой протокол и PKI** → Nebula (один демон, нет БД и MQTT).
- **UI, роли, gateways, многосегментные сети, MSP-мультитенантность** → Netmaker.
- **Reverse proxy и private services, K8s, зрелый OSS-стек** → Netbird.
- **Кросс-платформенность включая мобильные** → все; отдельные мобильные приложения есть у Nebula и ZeroTier.

## Практические сценарии

### Предварительные требования

Общее для любого self-hosted mesh-решения:

- Публично доступный узел-координатор (или lighthouse/relay) с постоянным адресом и доменным именем.
- Открытые входящие порты под протокол координатора: у Netbird — `80/tcp`, `443/tcp`, `3478/udp`; у Netmaker — `80/tcp` (ACME), `443/tcp` (UI/API/MQTT), `51821/udp` (агент); у Nebula — `4242/udp` на lighthouse.
- Linux с root/sudo; для Netbird и Netmaker дополнительно Docker с compose plugin, `jq`, `curl`.
- Планирование адресации overlay (подсеть, которую не пересекает локальная) и набора групп/тегов для политик.

### 1. Nebula: развёртывание с собственным CA

Nebula (создан в Slack, развивается Defined Networking) состоит из узла-lighthouse и обычных узлов. Вся настройка — YAML-конфиги и сертификаты.

```bash
# Бинарники (Linux amd64; есть пакеты apt/dnf/brew и образ nebulaoss/nebula)
curl -fsSL https://github.com/slackhq/nebula/releases/download/v1.11.2/nebula-linux-amd64.tar.gz | tar xz
sudo install -m 0755 nebula nebula-cert /usr/local/bin/

# CA сети: приватный ключ CA хранить offline; можно зашифровать флагом -encrypt
nebula-cert ca -name "Corp Mesh"                       # → ca.key, ca.cert

# Сертификаты узлов: в сертификат зашиваются IP, имя и группы
nebula-cert sign -name "lighthouse" -ip "10.10.0.1/24"
nebula-cert sign -name "node-1"     -ip "10.10.0.2/24" -groups "servers"
```

Конфиг lighthouse (`/etc/nebula/config.yml`):

```yaml
pki:
  ca:   /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key:  /etc/nebula/host.key
listen:
  host: 0.0.0.0
  port: 4242
lighthouse:
  am_lighthouse: true
  interval: 60
punchy:
  punch: true
firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: icmp
      host: any
```

Конфиг обычного узла:

```yaml
pki:
  ca:   /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key:  /etc/nebula/host.key
static_host_map:
  "10.10.0.1": ["203.0.113.10:4242"]   # Nebula-IP lighthouse → его публичный адрес
lighthouse:
  am_lighthouse: false
  interval: 60
  hosts:
    - "10.10.0.1"                      # Nebula-IP lighthouse, не его реальный адрес
listen:
  host: 0.0.0.0
  port: 0                              # 0 — динамический порт (рекомендуется для роуминга)
```

Пример конфигурации Nebula ожидает имена файлов `ca.crt`, `host.crt`, `host.key` — переименуйте полученные `ca.cert`, `node-1.crt`, `node-1.key` соответствующим образом. `ca.key` на узлы не копируется.

Запуск и автозагрузка:

```ini
# /etc/systemd/system/nebula.service
[Unit]
Description=Nebula overlay networking
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yml
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now nebula
```

Проверка:

```bash
sudo nebula -test -config /etc/nebula/config.yml   # проверка конфига без запуска
nebula-cert print -path /etc/nebula/host.crt        # содержимое сертификата узла
ping 10.10.0.2                                      # связность через overlay
```

### 2. Netbird: self-hosted координатор с SSO

Netbird — координатор (management + signal + relay) на Go, самохостится. Ключевая ценность — SSO и управление доступом без ручной конфигурации пиров на клиентах.

Требования: Linux VM минимум 1 CPU / 2 GB RAM, доменное имя на публичный IP, открытые `80/tcp`, `443/tcp`, `3478/udp`, установленные Docker + compose plugin, `jq`, `curl`.

```bash
# Production-ready установка: netbird-server + dashboard (+ опционально reverse proxy)
curl -fsSL https://github.com/netbirdio/netbird/releases/latest/download/getting-started.sh | bash
```

Скрипт спросит вариант reverse proxy (по умолчанию Traefik с автоматическим TLS от Let's Encrypt) и предложит встроенный NetBird Proxy. Аутентификация из коробки — встроенный Dex (локальные пользователи); внешний OIDC-провайдер (Keycloak, Authentik, Zitadel, Entra ID и др.) подключается через дашборд. После установки первый пользователь создаётся на странице `/setup`.

Неинтерактивная установка (CI/Terraform/cloud-init):

```bash
export NETBIRD_DOMAIN=netbird.example.com
export NETBIRD_LETSENCRYPT_EMAIL=admin@example.com
export NETBIRD_NON_INTERACTIVE=true
curl -fsSL https://github.com/netbirdio/netbird/releases/latest/download/getting-started.sh | bash
```

Подключение узла и проверка:

```bash
netbird up                                        # SSO-вход через браузер
# или неинтерактивно, по setup key (серверы, IaC):
netbird up --setup-key <SETUP_KEY> --management-url https://netbird.example.com

netbird status                                    # состояние соединения и пиров
ip addr show wt0                                  # Linux: интерфейс Netbird (macOS — utun100)
```

Политики доступа (по группам, хостам, тегам) задаются в UI — аналог HuJSON-ACL из [tailscale.md](./tailscale.md). Setup keys и posture-проверки используются для неинтерактивного онбординга. Публикация внутренних подсетей и сервисов выполняется через объект **Network** (routing peer + ресурсы + access policy), выход в интернет — через exit node (см. сценарий 4). С v0.60.0 доступен identity-aware SSH: встроенный SSH-сервер на узле (`netbird up --allow-server-ssh`) с аутентификацией через IdP и без открытия порта 22 в интернет.

### 3. Netmaker: WireGuard с gateways и UI

Netmaker управляет реальными WireGuard-интерфейсами через netclient и добавляет командный слой (UI, API, MQTT).

Требования: Ubuntu 24.04 (рекомендуется), публичный статический IP, домен; минимум 1 GB RAM / 1 CPU (для продакшена — 2 GB / 2 CPU); firewall `80/tcp`, `443/tcp`, `51821/udp`.

```bash
# Community Edition
sudo wget -qO /root/nm-quick.sh https://raw.githubusercontent.com/gravitl/netmaker/master/scripts/nm-quick.sh \
  && sudo chmod +x /root/nm-quick.sh && sudo /root/nm-quick.sh

# Pro Edition — тот же скрипт с флагом -p
```

Скрипт разворачивает сервер и стек мониторинга. Важно использовать собственный домен: авто-генерируемый `nip.io`-домен ограничен по rate-limit у провайдера сертификатов и может привести к сбою установки.

Клиент netclient (пример для Debian/Ubuntu):

```bash
curl -sL 'https://apt.netmaker.org/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/netmaker-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/netmaker-keyring.gpg] https://apt.netmaker.org stable main" \
  | sudo tee /etc/apt/sources.list.d/netclient.list
sudo apt update && sudo apt install netclient

netclient join -t <ENROLLMENT_TOKEN>    # подключить узел к сети по enrollment key
netclient list                          # список сетей узла
```

Типовые опции: **gateways** (egress в удалённые сети, internet gateway), **access policies (ACL)** по группам/хостам/тегам/IP, **auto-relay** для NAT, **TCP/WSS-uplink** при блокировке UDP, DNS. Начиная с v1.7 доступны MSP-мультитенантность и интеграции с EDR/MDM для posture-проверок.

### 4. Удалённый доступ: маршруты, exit nodes и gateways

Все решения публикуют в overlay подсети, где нет клиента mesh (clientless-узлы), и умеют выпускать пользовательский трафик в интернет через выбранный узел. Механика различается.

**Nebula — `unsafe_routes`.** Маршрут к внешней (не-Nebula) сети задаётся на клиентах, а `via` ссылается на Nebula-IP узла-шлюза. Критично: в сертификате `via`-узла эта подсеть должна быть объявлена через `-subnets`, иначе он молча откажется маршрутизировать.

```bash
# Сертификат узла-шлюза с объявленной подсетью (на хосте, где доступен ca.key)
nebula-cert sign -name "gateway" -ip "10.10.0.5/24" -subnets "172.16.1.0/24"
```

Узел-шлюз должен иметь `net.ipv4.ip_forward=1`; клиенты добавляют маршрут:

```yaml
tun:
  unsafe_routes:
    - route: 172.16.1.0/24
      via: 10.10.0.5        # Nebula-IP шлюза
      metric: 100
      install: true         # установить маршрут в системной таблице
```

С версии 1.10.0 `unsafe_routes` поддерживает ECMP: несколько `via` на один `route` (с весами) дают балансировку и автоматический failover.

Firewall Nebula по умолчанию запрещает весь входящий и исходящий трафик; правила ссылаются на группы из сертификата (`-groups`). Встроенный DNS включается на lighthouse флагом `serve_dns` и отвечает на `A`/`TXT`-запросы об известных ему хостах:

```yaml
# на lighthouse
lighthouse:
  am_lighthouse: true
  serve_dns: true
  dns:
    host: 0.0.0.0
    port: 53
firewall:
  inbound:
    - port: 53
      proto: udp
      group: any          # разрешить DNS-запросы к lighthouse из overlay
```

Клиенты опрашивают lighthouse напрямую: `dig @10.10.0.1 web01 A` вернёт Nebula-IP узла `web01`.

**Netbird — Networks и exit nodes.** Удалённый доступ строится на объекте **Network**: routing peer (клиент Netbird внутри приватной сети) публикует ресурсы (IP, подсеть, домен или wildcard-домен), а access policy определяет, каким группам-источникам они видны. Модель Zero Trust: ресурс недоступен, пока политика не разрешит. Для выхода в интернет служит частный случай маршрута — **exit node** (`0.0.0.0/0`), распространяемый по группам.

```bash
netbird networks ls                                   # какие Networks видит клиент
netbird up --setup-key <SETUP_KEY> --management-url https://netbird.example.com
netbird up --block-lan-access                         # exit node: не выпускать трафик в его локальную LAN
```

> Прежняя Route-модель (раздельные Distribution/ACL Groups) объявлена deprecated: все сценарии, кроме exit nodes, перенесены в Networks.

**Netmaker — gateways.** Gateway — публично доступный узел сети, служащий точкой входа и/или relay. Варианты: **Internet Gateway** (full-tunnel выход в интернет, только Linux), **WireGuard-конфиги** для clientless-устройств (роутеры, IoT), **HA gateways** (автовыбор и failover с v1.2.0; проверка доступности каждые ~30 с) и **Auto-Relay** (Pro) — выбор relay с наименьшей задержкой. Clientless-устройства подключаются по сгенерированному conf-файлу:

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 100.70.101.254/32
DNS = 1.1.1.1
[Peer]
PublicKey = <gateway_public_key>
AllowedIPs = 100.70.101.0/24, 192.168.1.0/24
Endpoint = <gateway_public_ip>:443
PersistentKeepalive = 20
```

### 5. Когда mesh-VPN вместо классического WireGuard

| Критерий | WireGuard вручную | Mesh-VPN (Nebula/Netbird/Netmaker) |
|----------|-------------------|------------------------------------|
| Число узлов | до ~20-50 приемлемо | десятки-сотни и выше |
| SSO/отзыв доступа | ручные процедуры (см. [wireguard-key-management.md](./wireguard-key-management.md)) | из коробки через координатор |
| ACL между узлами | файрвол вручную | политики на control plane |
| Аудит | снимки + NFLOG (см. [vpn-session-audit.md](./vpn-session-audit.md)) | логи координатора + SSO |
| Сложность инфраструктуры | минимальная | + координатор, БД, relay |

## Устранение неисправностей

### Нет прямого соединения, весь трафик через relay

Признак: высокий и стабильно большой RTT, трафик к пиру идёт через релей вместо P2P. Причины: симметричный NAT, блокировка исходящего UDP, единственный и перегруженный релей. Диагностика: `tailscale netcheck` (Tailscale), `netbird status` (Netbird), статус связности узла в UI Netmaker, логи lighthouse/punchy у Nebula. Решения: разрешить UDP на периметре, добавить релей (или включить TCP/WSS-uplink у Netmaker v1.7+), проверить, что lighthouse/relay доступен по своему порту.

### Узел не регистрируется у координатора

- Проверить DNS домена координатора и доступность портов (для Netbird — `443/tcp`, `3478/udp`; для Netmaker — `443/tcp`, `51821/udp`).
- Netbird: корректность `--management-url` и действительность setup key.
- Netmaker: валидность enrollment token и доступность `api.<domain>`.
- Nebula: узел должен знать lighthouse в `static_host_map` и `lighthouse.hosts`, а CA-сертификат узла — совпадать с CA сети.

### Внутренние имена (DNS) не резолвятся

Проверьте, что на узле включён DNS координатора (Netbird/Netmaker) или MagicDNS (Tailscale); у Nebula — `lighthouse.serve_dns`. Отдельно проверьте split-DNS и системный резолвер — см. [vpn-dns.md](./vpn-dns.md).

### Связь пропала после смены ключа или сертификата

- Nebula: истёк срок сертификата (по умолчанию — год от CA) либо выполнена ротация CA без перевыпуска сертификатов узлов. Перевыпустить сертификаты.
- WireGuard-решения: координатор перевыпустил ключ — узел нужно перерегистрировать; ручной `PublicKey` больше не совпадает.

### Мелкие пакеты ходят, крупные TCP-сессии «зависают»

Признак MTU/фрагментации в overlay. Снизить MTU туннеля (у Nebula по умолчанию `1300`), включить MSS clamping/PMTUD. Расчёт и диагностика — [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md).

## Лучшие практики

- **Отказоустойчивость координации:** минимум два lighthouse (Nebula) и несколько координаторов/relay; не оставляйте единственный узел, через который идёт вся ретрансляция.
- **CA и ключи:** приватный ключ CA Nebula храните offline и/или зашифрованным (флаг `-encrypt`); планируйте ротацию до истечения срока (по умолчанию CA — 1 год).
- **Firewall по умолчанию запрещает:** у Nebula явно перечисляйте разрешённый inbound по группам, не открывайте лишнее.
- **Проверяйте прямые соединения:** если значительная часть трафика идёт через релей, ищите причину (UDP, NAT), а не лечите увеличением релеев.
- **Резервное копирование control plane:** БД management (Netbird, Netmaker), конфигурация и `turnserver.conf`, каталог данных координатора. Перед апгрейдом — обязательно.
- **SSO/MFA и короткоживущие ключи:** привязка узлов к IdP, ограниченный срок setup/enrollment keys для IaC — см. [vpn-authentication.md](./vpn-authentication.md).
- **Мониторинг:** состояние handshake/пиров, доступность relay и координатора, свежесть сессий — см. [vpn-monitoring.md](./vpn-monitoring.md); у Nebula есть сбор метрик в Prometheus/Graphite, у Netmaker — встроенный стек.
- **Обновления по release notes:** у Netmaker миграции БД применяются на старт и не откатываются; обновляться пошагово между соседними стабильными версиями.

## Очистка и вывод узлов из эксплуатации

Отзыв доступа к overlay и удаление самого решения — разные операции; порядок: сначала отозвать узел у координатора, затем деинсталлировать агент.

**Nebula.**

```bash
sudo systemctl disable --now nebula
sudo rm /etc/systemd/system/nebula.service
sudo systemctl daemon-reload
sudo rm -rf /etc/nebula /usr/local/bin/nebula /usr/local/bin/nebula-cert
```

Отозвать узел без перевыпуска CA можно, добавив SHA его сертификата в `pki.blocklist` в конфигах остальных узлов (приватный ключ CA для этого не нужен — он требуется только для подписи новых сертификатов). Перевыпуск CA отзывает все выданные сертификаты разом, если узел недоступен для правки конфигов.

**Netbird.** `netbird down` отключает узел, но не удаляет сервис; удаление сервиса:

```bash
netbird down
sudo netbird service uninstall     # удаляет сервис, но не конфигурацию и не бинарник
sudo rm -rf /var/lib/netbird /usr/local/bin/netbird
```

После этого удалите пир в dashboard, иначе он останется в списке узлов.

**Netmaker.**

```bash
# На узле
sudo netclient leave <network>     # выйти из сети (или apt remove netclient)
sudo netclient uninstall           # полностью удалить агент

# На сервере (quickstart-развёртывание)
sudo docker compose -f docker-compose.quickstart.yml down --volumes
```

Тома БД при `down --volumes` удаляются безвозвратно — предварительно сделайте резервную копию. Сеть в UI нельзя удалить, пока в ней остаются узлы: сначала выведите их командой `netclient leave`.

## Дополнительная информация

- **[Vpn/tailscale.md](./tailscale.md)** — Headscale как координатор Tailscale-клиентов, MagicDNS, ACL
- **[Vpn/zerotier.md](./zerotier.md)** — L2-оверлей, MOON, controller self-hosted
- **[Vpn/wireguard.md](./wireguard.md)** — базовый WireGuard: туннели, маршрутизация, эксплуатация
- **[Vpn/wireguard-key-management.md](./wireguard-key-management.md)** — инвентарь, ротация ключей, флот клиентов
- **[Vpn/vpn-authentication.md](./vpn-authentication.md)** — SSO/MFA через OIDC для mesh-контроллеров
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — аудит и журналирование сессий
- **[Vpn/vpn-dns.md](./vpn-dns.md)** — split DNS и внутренние имена в туннелях
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — метрики, SLI/SLO и алертинг для VPN
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — overhead, MSS clamping, диагностика фрагментации
- **Nebula:** [документация](https://nebula.defined.net/docs/), [конфигурация](https://nebula.defined.net/docs/config/), [GitHub](https://github.com/slackhq/nebula)
- **Netbird:** [self-hosting](https://docs.netbird.io/selfhosted/selfhosted-quickstart), [GitHub](https://github.com/netbirdio/netbird)
- **Netmaker:** [документация](https://learn.netmaker.io/), [netclient](https://learn.netmaker.io/getting-started/server-and-client-management/client-installation/netclient-installation), [GitHub](https://github.com/gravitl/netmaker)
