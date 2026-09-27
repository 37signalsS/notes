# Mesh-VPN решения: Nebula, Netbird, Netmaker

## Определения

**Mesh-VPN** — сеть, где каждый узел соединяется с каждым напрямую (P2P), а общий «справочник» узлов и ключей ведёт координационный сервер (control plane). **Control plane** — сервер, раздающий конфигурацию (адреса, ключи, ACL) без участия в передаче пользовательских данных. **Lighthouse (Nebula)** — аналог координатора: узлы регистрируют у него свои публичные адреса, договариваются о прямом P2P. **Relay / DERP-узел** — промежуточный сервер для трафика, когда прямое соединение невозможно (симметричный NAT, строгий файрвол). **Overlay** — виртуальная сеть поверх реальной.

## Основные концепции

### Место среди уже описанных решений

В базе подробно разобраны **Tailscale/Headscale** ([tailscale.md](./tailscale.md)) и **ZeroTier** ([zerotier.md](./zerotier.md)). Настоящий материал — про остальные self-hosted mesh-решения на базе WireGuard, которые часто спрашивают в контексте «что выбрать вместо коммерческого Tailscale, не уходя в облако»:

| Решение | Транспорт | Control plane | Особенность | Self-hosted |
|---------|-----------|---------------|-------------|-------------|
| **Tailscale (SaaS)** | WireGuard | Tailscale Inc. | Простота, MagicDNS, SSO | Нет (кроме Headscale) |
| **Headscale** | WireGuard | self-hosted | Open-source координатор Tailscale | Да |
| **ZeroTier** | собственный (L2) | Central / self-hosted | L2-оверлей, MOON | Да |
| **Nebula** | собственный (NebulaCipher) | self-hosted (Lighthouse) | Свой CA и протокол, «старый» Slack | Да |
| **Netbird** | WireGuard | self-hosted | OIDC/SSO, ACL, много роутейнга | Да |
| **Netmaker** | WireGuard | self-hosted | Egress/Access gateways, политики, UI | Да |

### Что общего у всех mesh-решений

- **Ключи/адреса выдаёт координатор** (или собственная PKI), узел получает конфиг готовым к использованию.
- **NAT traversal** автоматический: прямой UDP, при невозможности — relay.
- **ACL** задаются в файле (HuJSON у Tailscale, YAML у Netbird, политики у Netmaker), применяются на control plane.
- **Аудит входов** на стороне координатора (см. [vpn-session-audit.md](./vpn-session-audit.md)).
- **Exit Node / Egress** — настройка выхода всего трафика через определённый узел доступна во всех.

### Критерии выбора (продакшен)

- **Регламентный контур без облака** → Headscale, Netbird, Netmaker (self-hosted), ZeroTier self-hosted.
- **Нужен SSO/MFA из коробки** → Netbird, Headscale (OIDC, см. [vpn-authentication.md](./vpn-authentication.md)).
- **L2-протоколы (ARP, широковещательные), legacy-интеграции** → ZeroTier (единственный L2).
- **Полный контроль над протоколом и автономность** → Nebula (собственный CA, лёгкий демон, не требует внешней БД).
- **Мегамасштаб и UI для не-админов** → Netmaker (панель, API, политики).

## Практические сценарии

### 1. Nebula: развёртывание с собственным CA

Nebula (от команды Slack) состоит из `lighthouse`-сервера и `nebula`-агентов. Минимальная топология «концентратор → 2 клиента», вся настройка — пара конфигов.

```bash
# Установка
sudo curl -fsSL https://github.com/slackhq/nebula/releases/download/v1.9.5/nebula-linux-amd64.tar.gz | tar xz
sudo install -m 0755 nebula /usr/local/bin/

# Генерация CA и сертификатов узлов
cd /etc/nebula && nebula-cert ca -name "Corp Mesh"
nebula-cert sign -name "lighthouse" -ip "10.10.0.1/24"
nebula-cert sign -name "node-1"     -ip "10.10.0.2/24"

# /etc/nebula/config.yml (упрощённо)
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/lighthouse.crt
  key: /etc/nebula/lighthouse.key
static_host_map:
  "10.10.0.1": ["203.0.113.10:4242"]
lighthouse:
  am_lighthouse: true
  serve_dns: false
listen:
  host: 0.0.0.0
  port: 4242
```

```bash
sudo systemctl enable --now nebula
sudo nebula -config /etc/nebula/config.yml   # на агенте — со своим сертификатом
```

Проверка mesh-связности:

```bash
nebula-cert print -json -in-pub /etc/nebula/ca.crt
ping 10.10.0.2   # прямое P2P через lightоuse
```

### 2. Netbird: self-hosted macOS/Linux флоат с OIDC

Netbird — координатор + relay на базе WireGuard, самохостится (Go). Ключевая ценность — SSO и политики без конфигурации пиров на клиентах.

```yaml
# docker-compose.yml (упрощённо, полная схема — официальный репозиторий)
services:
  dashboard:
    image: netbirdio/dashboard:v0.40.0
  management:
    image: netbirdio/management:v0.40.0
    environment:
      - NB_AUTH_OIDC_CONFIG_ENDPOINT=<https://idp.example.com/realms/corp>
      - NB_AUTH_OIDC_CLIENT_ID=netbird
    volumes:
      - ./management:/var/lib/netbird
  signal:
    image: netbirdio/signal:v0.40.0
  relay:
    image: netbirdio/relay:v0.40.0
```

Клиент после входа через IdP получает IP из пула координатора, доступ управляется политиками (по host, group, tags) — аналог HuJSON-ACL из [tailscale.md](./tailscale.md), но в UI.

### 3. Netmaker: контроль над WireGuard с egress

Netmaker крутит реальные WireGuard-интерфейсы и добавляет к ним командный слой.

```bash
# Установка сервера (проверено на v0.20+)
sudo curl -sfL https://raw.githubusercontent.com/gravitl/netmaker/master/scripts/netmaker-install.sh | sudo bash
# В браузере: http://netmaker.example.com → создать сеть, ключ доступа
# Клиент: NETCLIENT, wireguard = host
sudo curl -sfL https://raw.githubusercontent.com/gravitl/netclient/main/install.sh | sudo bash
sudo netclient join --token <TOKEN> --server netmaker.example.com:443
```

Типовые опции: **egress gateway** (вся сеть клиента через узел), **ingress gateway** (доступ в удалённый LAN), **access policies** по группам. Из коробки — интеграция с SSoT-инвентарём через API.

### 4. Когда mesh-VPN вместо классического WireGuard

| Критерий | WireGuard вручную | Mesh-VPN (Nebula/Netbird/Netmaker) |
|----------|-------------------|------------------------------------|
| Число узлов | до ~20-50 приемлемо | десятки-сотни и выше |
| SSO/отзыв доступа | ручные процедуры (см. [key-management](./wireguard-key-management.md)) | из коробки через координатор |
| ACL между узлами | файрвол вручную | политики на control plane |
| Аудит | снимки + NFLOG (см. [session-audit](./vpn-session-audit.md)) | логи координатора + SSO |
| Сложность инфраструктуры | минимальная | + координатор, БД, relay |

## Дополнительная информация

- **[Vpn/tailscale.md](./tailscale.md)** — Headscale как координатор Tailscale-клиентов, MagicDNS, ACL
- **[Vpn/zerotier.md](./zerotier.md)** — L2-оверлей, MOON, controller self-hosted
- **[Vpn/vpn-authentication.md](./vpn-authentication.md)** — SSO/MFA через OIDC для mesh-контроллеров