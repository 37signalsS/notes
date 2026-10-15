# Tailscale — mesh-VPN и self-hosted контроллер Headscale

**Актуально для:** Headscale 0.29.x (клиенты Tailscale 1.86.x)

## Определения

**Tailscale** — mesh-VPN поверх WireGuard: узлы общаются напрямую (P2P по UDP), а контроль-плоскость (обмен ключами, метаданные, ACL) выполняет **координационный сервер**. **Headscale** — self-hosted координационный сервер (контроллер) для Tailscale-клиентов: позволяет держать всю контроль-плоскость на своих серверах без публичного облака. **Tailnet** — логическая сеть устройств, объединённых одним контроллером. **Exit Node** — узел, через который клиент пускает весь интернет-трафик (NAT наружу). **Subnet Router** — узел, публикующий локальные подсети в Tailnet. **MagicDNS** — автоматическая генерация имён узлов Tailnet. **DERP** — релейные серверы на случай недоступности прямого UDP между узлами. **Node key** — ключ узла, у которого есть срок действия. **Auth key (preauthkey)** — предварительный ключ для неинтерактивной регистрации узла. **Tag** — метка, закрепляемая за узлом и заменяющая пользователя-владельца.

## Основные концепции

### Архитектура и принцип работы

- При `tailscale up` узел регистрируется у контроллера, получает ключи WireGuard и список других узлов.
- Трафик между узлами идёт P2P по UDP (NAT traversal); только при невозможности прямого соединения используется релей DERP.
- С Headscale вся координация — на своих серверах; публичный Tailscale-облачный сервис не используется.

В терминах моделей это разделяется на **control plane** и **data plane**:

- **Data plane** — обычный WireGuard. Пользовательский трафик шифруется между узлами end-to-end; ни координатор, ни DERP не видят содержимого пакетов (DERP релеит уже зашифрованные пакеты).
- **Control plane** — координатор (Headscale или облако Tailscale). Он раздаёт публичные ключи узлов, формирует список пиров и компилирует фильтр-правила (ACL/policy) в per-node правила. Пользовательский трафик через него не проходит.
- Обмен между клиентом и контроллером идёт по протоколу **Noise (TS2021)** поверх HTTPS; на стороне Headscale для этого используются Noise-ключи (`noise.private_key_path`).
- **NAT traversal** реализован через STUN (`udp/3478`): узлы узнают свой публичный адрес и пробуют пробить прямой UDP (по умолчанию порт `41641`). Если не удалось ни с одной стороны — включается DERP.

### Идентичность узлов: personal и tagged

Tailscale различает два типа узлов, и это определяет их поведение в policy и при истечении ключей:

- **Personal (user-owned)** — узел принадлежит человеку (ноутбук, телефон, рабочая станция). Владелец задаётся пользователем Headscale.
- **Tagged (service)** — узел принадлежит тегу, а не пользователю (серверы, БД). Такие узлы попадают под служебного пользователя `tagged-devices`, у них по умолчанию **отключён срок действия ключа**, и есть ограничения (например, tagged-узел не может логиниться по Tailscale SSH на personal-узел).

### Терминология узлов

| Роль | Команда (клиент) | Назначение |
|------|------------------|------------|
| Обычный узел | `tailscale up` | Просто член Tailnet |
| Exit Node | `--advertise-exit-node` | Пропускает весь интернет-трафик клиентов |
| Subnet Router | `--advertise-routes=...` | Публикует локальные подсети в Tailnet |
| SSH-хост | `--ssh` | Разрешает вход по `tailscale ssh` в Tailnet |
| Tagged-узел | `--advertise-tags=tag:...` | Узел-сервис, владелец — тег, срок ключа не истекает |

## Установка и развёртывание Headscale

### Предварительные требования

- Сервер с публичным IP (рекомендуется dual-stack: публичные IPv4 и IPv6).
- Headscale отдаётся по **HTTPS на порту 443** — клиент Tailscale в ряде ситуаций жёстко ожидает этот порт.
- Современный Linux/BSD, отдельный системный пользователь `headscale`, минимальные навыки работы в shell.
- Порты: `tcp/443` (HTTPS, публично), `udp/3478` (STUN, публично — при встроенном DERP), `tcp/80` (публично — только для ACME HTTP-01), `tcp/50443` (gRPC для удалённого управления CLI, публично), `tcp/9090` (metrics/debug, **только внутренняя сеть**).
- Конфигурация по умолчанию: `/etc/headscale/config.yaml`, данные — `/var/lib/headscale`, БД — SQLite.

### Вариант 1: DEB-пакет (рекомендуется)

Для Debian/Ubuntu официальный пакет сам создаёт системного пользователя, кладёт конфиг и systemd-юнит.

```bash
HEADSCALE_VERSION="0.29.5"   # без префикса v
HEADSCALE_ARCH="amd64"       # ваша архитектура
wget --output-document=headscale.deb \
  "https://github.com/juanfont/headscale/releases/download/v${HEADSCALE_VERSION}/headscale_${HEADSCALE_VERSION}_linux_${HEADSCALE_ARCH}.deb"
sudo apt install ./headscale.deb
sudo systemctl status headscale
# → ● headscale.service - Headscale control server
# →     Active: active (running) since ...
```

### Вариант 2: бинарник + systemd

```bash
# Бинарник (рекомендуемый путь — из официального release)
sudo curl -L -o /usr/bin/headscale https://github.com/juanfont/headscale/releases/latest/download/headscale_linux_amd64
sudo chmod +x /usr/bin/headscale

# Отдельный системный пользователь и каталог данных
sudo useradd --create-home --home-dir /var/lib/headscale/ --system --user-group --shell /usr/sbin/nologin headscale
sudo mkdir -p /etc/headscale
# config.yaml из репозитория соответствующего тега привести к своему домену
```

Минимальный `config.yaml` (ключи приведены к актуальному формату):

```yaml
server_url: https://headscale.example.com
listen_addr: 127.0.0.1:8080          # в проде — за reverse proxy
metrics_listen_addr: 127.0.0.1:9090
grpc_listen_addr: 127.0.0.1:50443

prefixes:
  v4: 100.64.0.0/10                  # подмножество CGNAT-диапазона Tailscale
  v6: fd7a:115c:a1e0::/48            # подмножество ULA-диапазона Tailscale
  allocation: sequential

noise:
  private_key_path: /var/lib/headscale/noise_private.key

database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
    write_ahead_log: true

policy:
  mode: file
  path: ""                           # путь к HuJSON-файлу политики

dns:
  magic_dns: true
  base_domain: example.com           # ДОЛЖЕН отличаться от домена server_url
```

> Важно: префиксы `prefixes.v4/v6` обязаны лежать внутри стандартных диапазонов Tailscale (`100.64.0.0/10` и `fd7a:115c:a1e0::/48`). Диапазоны вне этих блоков клиент не поддерживает.

Сервис `/etc/systemd/system/headscale.service`:

```ini
[Unit]
Description=Headscale control server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/headscale serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now headscale
systemctl status headscale
# → ● headscale.service - Headscale control server
# →     Active: active (running) since ...
```

Внешний доступ к координатору закрывается за reverse proxy с TLS (порт 443), а сам клиент доступается по `--login-server https://headscale.example.com`.

### Проверка

```bash
headscale configtest           # валидация config.yaml без запуска
headscale nodes list           # сервер отвечает и БД доступна
# → ID | Hostname | ... 
```

## Практические сценарии

### Регистрация нового устройства

Регистрация требует предварительно созданного пользователя Headscale:

```bash
headscale users create <user>
```

**Интерактивно (web authentication).** Клиент инициирует вход, администратор одобряет узел.

* **Linux:** выполните в терминале команду, указав адрес вашего сервера Headscale.

    ```bash
    # Замените на адрес вашего сервера, например https://headscale.magicfun.nnstd.dev
    sudo tailscale up --login-server https://headscale.example.com
    ```

    Переходите по ссылке, которую вернул терминал, и входите через `nnstd id` (если ещё не вошли) — в этом развёртывании nnstd выступает IdP. Страница печатает `Auth ID`, по которому узел одобряется на сервере.

* **Windows / macOS / Android:**
    1. В настройках приложения найдите опцию для использования альтернативного сервера (`Use alternative coordination server`).
    2. Введите адрес вашего сервера Headscale (например, `https://headscale.magicfun.nnstd.dev`).
    3. Нажмите `Log in` или `Подключиться`. В браузере откроется страница с идентификатором регистрации.

**Одобрение на сервере** — подключитесь к серверу Headscale (например, по SSH) и выполните:

```bash
headscale auth register --user <user> --auth-id <AUTH_ID>
# → Node <hostname> registered
```

> Команда `headscale nodes register --user <user> --key <MACHINE_KEY>` устарела (помечена deprecated) — используйте `headscale auth register --auth-id`.

**Неинтерактивно (pre-authenticated key).** Подходит для автоматизации. Ключ по умолчанию одноразовый и живёт 1 час.

```bash
# Узнать USER_ID
headscale users list
# Создать ключ пользователю (или tagged-ключ)
headscale preauthkeys create --user <USER_ID>
#    или: headscale preauthkeys create --tags tag:server

# На клиенте
sudo tailscale up --login-server https://headscale.example.com --authkey <YOUR_AUTH_KEY>
```

### Настройка Exit Node

Чтобы маршрутизировать весь трафик устройства через другой узел в вашей сети (exit node):

```bash
sudo tailscale set --exit-node-allow-lan-access=true --exit-node=<exit-node-name>
```

Сделать текущий сервер exit-узлом (на самом узле):

```bash
sudo tailscale up --advertise-exit-node
# Если узел уже зарегистрирован:
sudo tailscale set --advertise-exit-node
```

Далее на узле нужно включить IP forwarding, а на контроллере — одобрить маршрут `0.0.0.0/0` (см. раздел «Subnet Router»; для exit-узла достаточно одобрить IPv4 или IPv6, второй одобрится автоматически):

```bash
headscale nodes list-routes
# → ID | Hostname | Approved | Available | Serving (Primary)
# → 1  | myexit   |          | 0.0.0.0/0 |
headscale nodes approve-routes --identifier 1 --routes 0.0.0.0/0
# → Node updated
```

### Subnet Router (публикация локальных подсетей)

Узел, который должен открыть свою локальную подсеть остальным участникам Tailnet:

```bash
# На узле-маршрутизаторе
sudo tailscale up --advertise-routes=192.168.1.0/24
# Если узел уже зарегистрирован:
sudo tailscale set --advertise-routes=192.168.1.0/24

# Включить IP forwarding (пример для Linux)
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1
```

Остальные узлы принимают маршруты:

```bash
sudo tailscale up --accept-routes
# или на зарегистрированном узле:
sudo tailscale set --accept-routes
```

Проверка опубликованных маршрутов и их статус (approved/not approved — у контроллера):

```bash
tailscale status
# → 100.64.0.5  gw-main  linux  -  idle; 192.168.1.0/24
```

На Headscale маршруты узла-публикатора должны быть одобрены администратором:

```bash
headscale nodes list-routes
headscale nodes approve-routes --identifier <node-id> --routes 192.168.1.0/24
# → Node updated
```

> Актуальные команды — `headscale nodes list-routes` (алиас `routes`) и `headscale nodes approve-routes --identifier <ID> --routes <CIDR,...>`. Старые `headscale routes list` / `headscale routes enable` больше не применяются.

**Автоматическое одобрение** (HA и парки маршрутизаторов) задаётся секцией `autoApprovers` в policy: тег `tag:router` с маршрутом в `autoApprovers.routes`, тег `tag:exit` — в `autoApprovers.exitNode`.

### MagicDNS (имена узлов в Tailnet)

MagicDNS даёт каждому узлу имя (по hostname) вместо IP-адреса. Управляется секцией `dns` в `config.yaml` и включён на клиенте по умолчанию (`--accept-dns=true`).

```bash
# Включить DNS на клиенте
sudo tailscale up --accept-dns
# Проверка
tailscale status
# → имя узла резолвится как <hostname>.<base_domain>
```

Ключевые параметры `dns`:

```yaml
dns:
  magic_dns: true
  base_domain: example.com        # FQDN без завершающей точки; != домен server_url
  override_local_dns: true        # перезаписывать локальные DNS настройки узла
  nameservers:
    global:
      - 1.1.1.1
    split: {}                     # split DNS: домен -> свои резолверы
  search_domains: []
  extra_records:                  # дополнительные A/AAAA-записи (например, сервисы за reverse proxy)
    - name: "grafana.myvpn.example.com"
      type: "A"
      value: "100.64.0.3"
```

Дополнительные записи можно также читать из файла (`dns.extra_records_path`) — Headscale подхватывает изменения без рестарта. Проверка:

```bash
dig +short grafana.myvpn.example.com
# → 100.64.0.3
```

Чтобы внутренние имена резолвились только внутри Tailnet и не «выглядывали» наружу, работает та же логика split DNS, что и для классических VPN: [Vpn/vpn-dns.md](./vpn-dns.md). Полную генерацию/настройку зон контроллер выполняет сам через Headscale (`dns` в `config.yaml`).

### Теги

Теги назначаются при регистрации (флаг `--advertise-tags` или tagged-preauthkey) либо администратором после:

```bash
headscale nodes list                          # покажет ID и текущие теги
headscale nodes tag -i <NODE_ID> -t tag:server,tag:prod
```

Владельцы тегов задаются в секции `tagOwners` policy (кто вправе регистрировать узлы с этим тегом). Перевод tagged-узла обратно в personal-узел — через `--advertise-tags=` и `--force-reauth`.

### Key Expiry и отзыв доступа

По умолчанию на SaaS-плоскости Tailscale node key имеет срок действия **180 дней**; у tagged-узлов срок по умолчанию отключён. В Headscale срок задаётся параметром `node.expiry` (по умолчанию `0` — бессрочно; `4320h` соответствует 180 дням). После истечения узел обязан пройти re-auth.

```bash
# Проверить оставшееся время жизни ключа
tailscale status --json | jq '.Self.Expires'
# → 2024-11-05T12:00:00Z

# Принудительная повторная аутентификация до истечения
sudo tailscale up --force-reauth

# Отзыв узла на Headscale (немедленно лишает истёкших разрешений на serve/connect)
headscale nodes delete --identifier <ID>
# Срок действия конкретного узла (установка/проверка) — опция сервера:
headscale nodes expire --identifier <ID>
# → Node expired
headscale nodes expire --identifier <ID> --disable   # отключить истечение (узел бессрочный)
```

Практическое правило: срок жизни ключа — это окно, в течение которого компрометированный ключ опасен; наоборот, короткий срок создаёт нагрузку на re-auth. Для серверов ставят unattended/долгие (или tagged-узлы), для человеческих устройств — стандартные с привязкой к IdP (OIDC в [Vpn/vpn-authentication.md](./vpn-authentication.md)).

### Tailscale SSH

Tailscale умеет замещать OpenSSH-доступ внутри Tailnet (без публичных SSH-портов):

```bash
# На хосте
sudo tailscale up --ssh
# С клиента
tailscale ssh <node-name>
# → доступ по ACL, не по паролю
```

Правила доступа задаются в policy (секция `"ssh"`):

```json
{
  "ssh": [
    {
      "action": "accept",
      "src": ["group:admins"],
      "dst": ["tag:server"],
      "users": ["root", "autogroup:nonroot"]
    }
  ]
}
```

### DERP (релей) и отказоустойчивость

Если между узлами нет прямого UDP (симметричный NAT, файрвол), Tailscale использует релейные серверы DERP. При self-hosted Headscale доступен **встроенный DERP-сервер**, который включается в секции `derp` конфигурации.

```yaml
derp:
  server:
    enabled: true                 # встроенный DERP (server_url ДОЛЖЕН быть https)
    region_code: "headscale"
    region_name: "Headscale Embedded DERP"
    verify_clients: true          # релеить только узлам своего Tailnet
    stun_listen_addr: "0.0.0.0:3478"
    ipv4: 198.51.100.1            # публичные адреса — для стабильности
    ipv6: 2001:db8::1
  urls:
    - https://controlplane.tailscale.com/derpmap/default   # публичные DERP Tailscale
  paths: []                       # собственные карты derpmap (YAML)
  auto_update_enabled: true
  update_frequency: 3h
```

> Прежний вид секции (`auto_update_enabled`/`paths` без `derp.server`) описывал старый формат. Актуальный формат — вложенный блок `derp.server`; при его отключении узлы используют набор DERP из `urls`.

Если убрать публичные DERP (`urls: []`) и оставить только встроенный, сервер становится единой точкой отказа. Проверка фактического пути от узла до узла (direct или via DERP):

```bash
tailscale netcheck
# → Map: 103.xxx
# → Latency: DERP (NYC) 12ms; DERP (Par) 45ms
# → Direct UDP: yes (port 41641)

# Карта DERP и связь со встроенным DERP Headscale
tailscale debug derp-map
tailscale debug derp headscale
```

### Управление сервером Headscale

* **Создание нового пользователя:**

    ```bash
    headscale users create <username>
    ```

* **Просмотр списка пользователей и узлов:**

    ```bash
    headscale users list
    headscale nodes list
    ```

* **Создание preauthkey:**

    ```bash
    headscale preauthkeys create --user <USER_ID>
    ```

* **Удаление неактивного узла:**

    ```bash
    headscale nodes delete --identifier <ID>
    ```

### Управление доступом (Policy)

Правила доступа между устройствами настраиваются в HuJSON-файле policy, путь к которому указывается в `policy.path` (`policy.mode: file`). Рекомендуемый формат — **grants**; старые **ACLs** (`action: accept`) считаются legacy и новых возможностей не получат. Без заданной policy действует режим allow-all.

**Grants (рекомендуется):**

```hujson
{
  "tagOwners": {
    "tag:server": ["group:admins"],
  },

  "hosts": {
    "monitoring": "100.64.0.1",
    "kaguya-exit-node": "100.64.0.2",
  },

  "grants": [
    // Администраторы имеют доступ ко всем устройствам и портам.
    {
      "src": ["group:admins"],
      "dst": ["*"],
      "ip": ["*"],
    },
    // Разрешить всем в сети использовать exit-node.
    {
      "src": ["autogroup:member"],
      "dst": ["kaguya-exit-node"],
      "ip": ["*"],
    },
  ],
}
```

**ACLs (legacy, но поддерживаются):**

```hujson
{
  // Группы пользователей для удобного управления доступом.
  "groups": {
    "group:admins": ["user1@example.com", "misha"],
  },

  // Определения хостов для статических IP или псевдонимов.
  "hosts": {
    "monitoring": "100.64.0.1",
    "kaguya-exit-node": "100.64.0.2",
  },

  // Основной раздел с правилами доступа.
  "acls": [
    // Администраторы имеют доступ ко всем устройствам.
    {
      "action": "accept",
      "src": ["group:admins"],
      "dst": ["*:*"],
    },
    // Разрешить всем в сети использовать exit-node.
    {
      "action": "accept",
      "src": ["autogroup:member"],
      "dst": ["kaguya-exit-node:*"],
    },
  ],

  // Тесты для проверки правил ACL (опционально).
  "tests": [
    {
      "src": "misha",
      "accept": ["monitoring:80"],
      "deny": ["100.64.0.3:22"],
    },
  ],
}
```

**Важно:** Headscale перечитывает policy при перезагрузке, а не автоматически. Примените изменения без полного перезапуска:

```bash
sudo systemctl reload headscale
# или сигналом напрямую:
sudo kill -HUP $(pidof headscale)
```

Результат обработки policy пишется в лог. При использовании Docker Compose перезапуск контейнера обязателен.

### Мониторинг и аудит

- Метрики и debug-эндпоинт Headscale — на `metrics_listen_addr` (`/metrics`, `/debug`); держите их во внутренней сети.
- Аудит входов ведёт координатор: OIDC-login, регистрация узла, удаление; см. [Vpn/vpn-session-audit.md](./vpn-session-audit.md).
- Метрики и алертинг по состоянию туннелей — [Vpn/vpn-monitoring.md](./vpn-monitoring.md).

## Troubleshooting

### Нет прямого соединения, трафик идёт через DERP

Причина: симметричный NAT или блокировка UDP. Диагностика и решения:

```bash
tailscale netcheck                 # смотрим Direct UDP и доступные DERP
sudo ss -lunp | grep 41641         # слушает ли клиент свой UDP-порт
```

- Открыть исходящий/входящий `udp/41641` (или включить `randomizeClientPort` в policy).
- Проверить, что встроенный DERP поднят и доступен `udp/3478` (STUN) и `tcp/443`.
- Держать публичные DERP Tailscale в `derp.urls`, чтобы был запасной путь.

### Маршрут (subnet/exit) не работает

- Маршрут не одобрен на контроллере: `headscale nodes list-routes` → `headscale nodes approve-routes`.
- На клиенте не включён приём маршрутов: `tailscale set --accept-routes`.
- На узле-маршрутизаторе не включён IP forwarding (`net.ipv4.ip_forward=1`) или отсутствует NAT (MASQUERADE) для exit-узла.
- Правило объявлено после регистрации, но не применено: используйте `tailscale set --advertise-routes=...`.

### MagicDNS не резолвит имена

- На клиенте выключен DNS: `tailscale set --accept-dns=true`.
- `dns.base_domain` совпадает с доменом `server_url` — так нельзя, домены должны различаться.
- Конфликт с локальным `systemd-resolved`: проверьте `resolvectl status` и split-настройки `dns.nameservers.split`.

### Узел недоступен после смены ключа

Node key истёк (по умолчанию 180 дней на SaaS; в Headscale — `node.expiry`). Требуется re-auth:

```bash
sudo tailscale up --force-reauth
# либо бессрочный ключ на сервере:
headscale nodes expire --identifier <ID> --disable
```

### `tailscale up` не связывается с контроллером

- Проверить доступность `https://headscale.example.com`, действующий TLS-сертификат и reverse proxy.
- Убедиться, что клиент запущен с `--login-server https://...` (иначе уходит в облако Tailscale).
- На сервере валидировать конфиг: `headscale configtest`.

## Best Practices

- **Серверы — tagged-узлами.** Тег снимает привязку к человеку и отключает истечение ключа; удобно для subnet router и exit node.
- **Истечение ключей:** для людей — конечный срок (привязка к IdP/OIDC), для серверов — либо `--disable`, либо tagged-узел.
- **Policy:** предпочитайте `grants`; для маршрутизаторов используйте `autoApprovers`, чтобы не одобрять маршруты руками.
- **Отказоустойчивость:** держите минимум два subnet router/exit node на одинаковые префиксы (HA включается автоматически при наличии 2+ узлов) и не оставляйте единственный встроенный DERP без запасного.
- **Backup перед апгрейдом:** обязателен — миграции БД применяются на старт. Копируйте `/etc/headscale` и `/var/lib/headscale` (SQLite `db.sqlite`). Обновляться только пошагово между соседними стабильными версиями.
- **Firewall:** публично — `tcp/443`, `udp/3478` (при встроенном DERP), `tcp/80` (ACME только), `tcp/50443` (gRPC); `tcp/9090` — только внутренняя сеть.
- **SSO/MFA:** OIDC-привязка узла к IdP — [Vpn/vpn-authentication.md](./vpn-authentication.md).

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — базовый WireGuard (Tailscale использует его криптографию/туннели)
- **[Vpn/vpn-authentication.md](./vpn-authentication.md)** — SSO/MFA через OIDC для Headscale
- **[Vpn/vpn-dns.md](./vpn-dns.md)** — split DNS и MagicDNS: резолвинг внутренних имён
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — аудит сессий и логов координатора
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — наблюдаемость VPN-туннелей
- **[Vpn/mesh-vpn-overview.md](./mesh-vpn-overview.md)** — место Tailscale/Headscale среди mesh-решений (Nebula, Netbird, Netmaker)
- **[Vpn/zerotier.md](./zerotier.md)** — альтернативный mesh-VPN с L2-оверлеем
