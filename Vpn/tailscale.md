# Tailscale — практическое руководство (Headscale)

## Определения

**Tailscale** — mesh-VPN поверх WireGuard: узлы общаются напрямую (P2P по UDP), а контроль-плоскость (обмен ключами, метаданные, ACL) выполняет **координационный сервер**. **Headscale** — self-hosted координационный сервер (контроллер) для Tailscale-клиентов: позволяет держать всю контроль-плоскость на своих серверах без публичного облака. **Exit Node** — узел, через который клиент пускает весь интернет-трафик (NAT наружу). **Subnet Router** — узел, публикующий локальные подсети в Tailnet. **MagicDNS** — автоматическая генерация имён узлов Tailnet. **DERP** — релейные серверы на случай недоступности прямого UDP между узлами.

## Основные концепции

### Архитектура

- При `tailscale up` узел регистрируется у контроллера, получает ключи WireGuard и список других узлов.
- Трафик между узлами идёт P2P по UDP (NAT traversal); только при невозможности прямого соединения используется релей DERP.
- С Headscale вся координация — на своих серверах; публичный Tailscale-облачный сервис не используется.

### Терминология узлов

| Роль | Команда (клиент) | Назначение |
|------|------------------|------------|
| Обычный узел | `tailscale up` | Просто член Tailnet |
| Exit Node | `--advertise-exit-node` | Пропускает весь интернет-трафик клиентов |
| Subnet Router | `--advertise-routes=...` | Публикует локальные подсети в Tailnet |
| SSH-хост | `--ssh` | Разрешает вход по `tailscale ssh` в Tailnet |

## Практические сценарии

### Регистрация нового устройства

* **Linux:**
    Выполните в терминале команду, указав адрес вашего сервера Headscale.

    ```bash
    # Замените https://headscale.example.com на адрес вашего сервера(https://headscale.magicfun.nnstd.dev)
    sudo tailscale up --login-server https://headscale.example.com

    переходишь по ссылке которую тебе дало в терминале, входишь через nnstd id (если еще не вошел), и все

    ```

    Скопируйте ключ (`mkey...`), который появится в выводе.

* **Windows / macOS / Android:**
    1. В настройках приложения найдите опцию для использования альтернативного сервера (`Use alternative coordination server`).
    2. Введите адрес вашего сервера Headscale: `https://headscale.example.com`.
    3. Нажмите `Log in` или `Подключиться`. В браузере откроется страница с ключом аутентификации.
    4. Скопируйте этот ключ (`mkey...`).

**Регистрация ключа на сервере**

Подключитесь к вашему серверу Headscale (например, по SSH) и выполните команду:

```bash
headscale nodes register --user <user> --key <key>
```

### Настройка Exit Node

Чтобы маршрутизировать весь трафик устройства через другой узел в вашей сети (exit node):

    ```bash
    sudo tailscale set --exit-node-allow-lan-access=true --exit-node=<exit-node-name>
    ```

Сделать текущий сервер exit-узлом (на самом узле):

```bash
sudo tailscale up --advertise-exit-node
```

### Subnet Router (публикация локальных подсетей)

Узел, который должен открыть свою локальную подсеть остальным участникам Tailnet:

```bash
# На узле-маршрутизаторе
sudo tailscale up --advertise-routes=192.168.1.0/24
```

Остальные узлы принимают маршруты:

```bash
sudo tailscale up --accept-routes
```

Проверка опубликованных маршрутов и их статус (approved/not approved — у контроллера):

```bash
tailscale status
# → 100.64.0.5  gw-main  linux  -  idle; 192.168.1.0/24
```

На Headscale маршруты узла-публикатора должны быть одобрены администратором:

```bash
headscale routes list
headscale routes enable --server <node-id> --route 192.168.1.0/24
```

### MagicDNS (имена узлов в Tailnet)

MagicDNS даёт каждому узлу имя (по hostname) вместо IP-адреса:

```bash
# Включить DNS на клиенте
sudo tailscale up --accept-dns
# Проверка
tailscale status
# → имя узла резолвится как <hostname>.<tailnet-base>
```

Чтобы внутренние имена резолвились только внутри Tailnet и не «выглядывали» наружу, работает та же логика split DNS, что и для классических VPN: [Vpn/vpn-dns.md](./vpn-dns.md). Полную генерацию/настройку зон контроллер выполняет сам через Headscale (`dns` в `config.yaml`).

### Key Expiry и отзыв доступа

По умолчанию ключи узла имеют срок действия (~180 дней у Tailscale SaaS; длина настраивается на Headscale). После истечения узел обязан пройти re-auth.

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
```

Практическое правило: срок жизни ключа — это окно, в течение которого компрометированный ключ опасен; наоборот, короткий срок создаёт нагрузку на re-auth. Для серверов ставят unattended/долгие, для человеческих устройств — стандартные с привязкой к IdP (OIDC в [Vpn/vpn-authentication.md](./vpn-authentication.md)).

### Tailscale SSH

Tailscale умеет замещать OpenSSH-доступ внутри Tailnet (без публичных SSH-портов):

```bash
# На хосте
sudo tailscale up --ssh
# С клиента
tailscale ssh <node-name>
# → доступ по ACL, не по паролю
```

Правила доступа задаются в ACL (поле `"ssh"`).

### DERP (релей) и отказоустойчивость

Если между узлами нет прямого UDP (симметричный NAT, файрвол), Tailscale использует релейные серверы DERP. При self-hosted Headscale реле тоже можно развернуть локально; в `config.yaml` раздела `derp`, где указываются `derpmap` с self-hosted дерперами.

```yaml
derp:
  auto_update_enabled: true
  # urls: ...           # публичные DERP-карты (не обязательны)
  paths: []             # пути к пользовательским картам derpmap
  auto_update_frequency: 1m
```

Проверка фактического пути от узла до узла (direct или via DERP):

```bash
tailscale netcheck
# → Map: 103.xxx
# → Latency: DERP (NYC) 12ms; DERP (Par) 45ms
# → Direct UDP: yes (port 41641)
```

### Управление сервером Headscale

* **Создание нового пользователя:**

    ```bash
    headscale users create <username>
    ```

* **Просмотр списка всех узлов:**

    ```bash
    headscale nodes list
    ```

* **Удаление неактивного узла:**

    ```bash
    headscale nodes delete --identifier <ID>
    ```

### Управление доступом (ACL)

Правила доступа между устройствами настраиваются в файле `acl.hujson` (или `acl.json`) на сервере.

```hujson
{
  // Группы пользователей для удобного управления доступом.
  "groups": {
    "group:admins": ["user1@example.com", "misha"],
    "group:services": ["autogroup:self"],
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
      "src": ["autogroup:members"],
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

**Важно:** После внесения изменений в файл ACL перезапустите Headscale для их применения.

```bash
# Пример для Docker Compose
docker compose restart headscale

# Пример для systemd
sudo systemctl restart headscale
```

### Развёртывание Headscale на своём сервере (systemd)

```bash
# Бинарник + конфиг (рекомендуемый путь — из официального release)
sudo curl -L -o /usr/local/bin/headscale https://github.com/juanfont/headscale/releases/latest/download/headscale_linux_amd64
sudo chmod +x /usr/local/bin/headscale
mkdir -p /etc/headscale
# config.yaml из репозитория привести к своему домену и base_domain
```

Сервис `/etc/systemd/system/headscale.service`:

```ini
[Unit]
Description=Headscale control server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/headscale serve
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

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — базовый WireGuard (Tailscale использует его криптографию/туннели)
- **[Vpn/vpn-authentication.md](./vpn-authentication.md)** — SSO/MFA через OIDC для Headscale
- **[Vpn/vpn-dns.md](./vpn-dns.md)** — split DNS и MagicDNS: резолвинг внутренних имён