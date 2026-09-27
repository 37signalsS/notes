# Proxmox Service Discovery

## Определения

**Proxmox Service Discovery** — инструмент с открытым исходным кодом для автоматического обнаружения виртуальных машин в кластере Proxmox через DNS. Приложение периодически опрашивает API Proxmox и создает DNS-записи типа A, позволяя другим сервисам находить VM по именам или тегам.

**Репозиторий:** [itcaat/proxmox-service-discovery](https://github.com/itcaat/proxmox-service-discovery)

**API-токен Proxmox** — пара `token_id@realm!token_name` и секретный ключ, используемая для аутентификации в REST API PVE без интерактивного входа. Подробнее о создании и правах: [Proxmox VE — Обзор и базовые концепции](./proxmox_overview.md#управление-ресурсами-и-правами).

**PVEAuditor** — встроенная роль Proxmox с правами только на чтение (read-only) для большинства объектов кластера: ноды, ВМ, контейнеры, хранилища, сеть. Рекомендуемый минимальный набор прав для Service Discovery.

**ACL (Access Control List)** — механизм разграничения прав в Proxmox, позволяющий делегировать доступ к отдельным путям API (`/nodes/`, `/vms/`, `/storage/`) пользователям или токенам.

**DNS Fallback** — внешний DNS-сервер (например, `8.8.8.8`), на который перенаправляются запросы, для которых нет локальной записи в Service Discovery. Позволяет резолвить как внутренние имена VM, так и публичные домены через один порт.

**Суффикс домена (Domain Suffix)** — DNS-суффикс, добавляемый к именам VM и тегов. Например, суффикс `vm.cluster.local` превращает имя `web-server` в запись `web-server.vm.cluster.local`.

## Мотивация

- Изучение Go при работе с API Proxmox
- Решение проблемы отсутствия встроенного Service Discovery в Proxmox Cluster

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                 Proxmox Service Discovery                    │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Proxmox API  │───>│   Discovery  │───>│  DNS Server  │  │
│  │  (токен)     │    │   Engine     │    │  (порт 2053) │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                              │                    │         │
│                              v                    v         │
│                     ┌──────────────┐    ┌──────────────┐   │
│                     │   Network    │    │  External    │   │
│                     │   Interfaces │    │  DNS (fallback)│  │
│                     └──────────────┘    └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Принцип работы

### Flow аутентификации и опроса

```
┌─────────────┐      HTTPS 8006       ┌──────────────────┐
│  Service    │◄─────────────────────►│   Proxmox API    │
│  Discovery  │  X-Auth-Token: <SECRET_5e4c4c20>   │  pveproxy / pvedaemon │
│  Container  │                       └──────────────────┘
│  (Go binary)│
      │
      │ polling loop (default 60s)
      ▼
┌───────────────────────────────────────────────────────┐
│  1. GET /api2/json/nodes                               │
│     → список всех узлов кластера                       │
│  2. For each node: GET /api2/json/nodes/<node>/qemu    │
│     или /lxc                                           │
│     → список ВМ/контейнеров                            │
│  3. For each VM: GET /api2/json/nodes/<node>/qemu/<vmid>/config/current
│     → поле `ip0`, `ip1`... и `tags`                    │
│  4. For each node: GET /api2/json/nodes/<node>/network │
│     → интерфейсы и IP узлов                            │
└───────────────────────────────────────────────────────┘
      │
      │ in-memory state
      ▼
┌───────────────────────────────────────────────────────┐
│  DNS Record Generation:                                │
│  - <vmname>.<suffix> → <vm-ip>                        │
│  - <tag>.<suffix> → <vm-ip> (если DISCOVERY_VM_TAGS) │
│  - <nodename>.<suffix> → <node-ip> (если subnet match)│
└───────────────────────────────────────────────────────┘
      │
      │ UDP/TCP 53
      ▼
┌─────────────┐
│  DNS Clients│
│  (apps, OS)│
└─────────────┘
```

### Почему API-токен, а не пароль

- Токен привязан к конкретному пользователю/роли и имеет минимальный набор прав.
- Можно создавать несколько токенов с разными правами для разных сервисов.
- Токен можно отозвать инстансно без смены пароля пользователя.
- Поддерживает ограничение по源 IP через Proxmox ACL.
- Идеально подходит для automation: неинтерактивная аутентификация, отсутствие prompts.

### Генерация DNS-записей: детали

1. **Записи по имени VM**: `имя_машины.суффикс` → первый найденный IPv4 в конфигурации интерфейсов VM (`ip0`, `ip1`, ...). Если VM имеет несколько интерфейсов — создается запись только для первого с configured IP.

2. **Записи по тегам** (`DISCOVERY_VM_TAGS=true`): каждый тег VM превращается в отдельную A-запись. Теги разделяются точкой с запятой в Proxmox (`web;prod;us-east`). Убедитесь, что теги не содержат недопустимых для DNS символов.

3. **Записи по узлам**: `имя_узла.суффикс` → IP интерфейса узла. Фильтрация по `DISCOVERY_NODE_SUBNET` позволяет включать только адреса из конкретной подсети (например, management-сеть).

4. **TTL записей**: по умолчанию TTL равен интервалу опроса (`DISCOVERY_INTERVAL`). Это означает, что при падении VM запись "протухает" максимум через 60 секунд. Для чувствительных сервисов уменьшите интервал до 15–30 секунд.

### Особенности работы с кластером

- При опросе кластера Service Discovery опрашивает ВСЕ ноды, независимо от того, какая нода является точкой входа для API.
- Если VM migrates между нодами, следующая итерация опроса корректно обновит IP-адрес в DNS.
- Статус ВМ (running/stopped) НЕ учитывается — если у stopped VM настроен статический IP, он будет опубликован в DNS. Для фильтрации используйте теги или кастомные скрипты.

## Переменные окружения

| Переменная | Описание | Обязательно |
|:---|:---|:---:|
| `DISCOVERY_PROXMOX_HOST` | Адрес Proxmox Host (например, `https://pve.example.com:8006`) | Да |
| `DISCOVERY_PROXMOX_TOKEN_ID` | ID API-токена Proxmox | Да |
| `DISCOVERY_PROXMOX_TOKEN_SECRET` | Secret API-токена | Да |
| `DISCOVERY_INTERVAL` | Интервал опроса в секундах (по умолчанию 60) | Нет |
| `DISCOVERY_DNS_PORT` | Порт DNS-сервера (по умолчанию 2053) | Нет |
| `DISCOVERY_DOMAIN_SUFFIX` | Суффикс домена для записей (по умолчанию `cluster.local`) | Нет |
| `DISCOVERY_VM_TAGS` | Создавать записи по тегам VM (`true`/`false`) | Нет |
| `DISCOVERY_NODE_SUBNET` | Фильтрация IP узлов по подсети (CIDR) | Нет |
| `DISCOVERY_EXTERNAL_DNS` | Внешний DNS для fallback (по умолчанию `8.8.8.8`) | Нет |

### Дополнительные переменные и нюансы

- **Имя токена (`DISCOVERY_PROXMOX_TOKEN_ID`)**: обычно записывается как `user@realm!token-name`, например `automation@pam!sd-reader`. Реalm `pam` — встроенная система аутентификации Proxmox.
- **Секрет (`DISCOVERY_PROXMOX_TOKEN_SECRET`)**: длинная строка из буквенно-цифровых символов. Храните его в vault/Ansible Vault, а не в открытом docker-compose.
- **Порт 2053**: выбран не случайно — стандартный DNS (53) часто требует root-прав, а 2053 позволяет запускать контейнер без привилегий. Убедитесь, что firewall/cluster security group разрешает UDP/53 или UDP/2053 между клиентами и сервисом.
- **Fallback DNS**: если клиенты должны резолвить как внутренние имена VM, так и интернет-домены, настройте upstream DNS аккуратно. Рекомендуется использовать локальный кэширующий resolver (dnsmasq, systemd-resolved) как `DISCOVERY_EXTERNAL_DNS`, а не публичный `8.8.8.8` напрямую, чтобы снизить латентность.

## Архитектура

### Docker

```yaml
version: '3.8'
services:
  proxmox-sd:
    image: ghcr.io/itcaat/proxmox-service-discovery:latest
    container_name: proxmox-sd
    restart: unless-stopped
    ports:
      - "2053:2053/udp"   # DNS
      - "2053:2053/tcp"   # DNS over TCP
    environment:
      - DISCOVERY_PROXMOX_HOST=https://pve.example.com:8006
      - DISCOVERY_PROXMOX_TOKEN_ID=automation@pam!sd-reader
      - DISCOVERY_PROXMOX_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      - DISCOVERY_INTERVAL=60
      - DISCOVERY_DOMAIN_SUFFIX=vm.cluster.local
      - DISCOVERY_VM_TAGS=true
      - DISCOVERY_NODE_SUBNET=192.168.1.0/24
      - DISCOVERY_EXTERNAL_DNS=8.8.8.8
    network_mode: host
```

### Бинарный файл

```bash
# Скачивание
curl -LO https://github.com/itcaat/proxmox-service-discovery/releases/latest/download/proxmox-service-discovery_linux_amd64.tar.gz
tar -xzf proxmox-service-discovery_linux_amd64.tar.gz

# Запуск
DISCOVERY_PROXMOX_HOST=https://pve.example.com:8006 \
DISCOVERY_PROXMOX_TOKEN_ID=automation@pam!sd-reader \
DISCOVERY_PROXMOX_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
DISCOVERY_DOMAIN_SUFFIX=vm.cluster.local \
./proxmox-service-discovery
```

## Примеры использования

### Сценарий 1: Создание API-токена с минимальными правами

#### Через GUI

1. **Datacenter → Permissions → API Tokens → Add**
2. **User:** выберите отдельного пользователя (например, `automation@pam`) или создайте нового.
3. **Token name:** `sd-reader`.
4. **Права:** минимально необходимы:
   - `/nodes/` — `Audit` (read)
   - `/vms/` — `Audit` (read)
   - ИЛИ назначьте роль `PVEAuditor` на путь `/` (только если доверяете сервису).
5. **Скопируйте секрет** сразу после создания — повторный показ невозможен.

#### Через CLI (pveum)

```bash
# 1. Создаем пользователя (если еще нет)
pveum useradd automation@pam --comment "Service Discovery automation"

# 2. Создаем токен
pveum user token add automation@pam sd-reader --comment "Proxmox SD reader" --privsep 0

# → Вывод содержит полный token_id и secret.
# → Сохраните secret в vault: ansible-vault edit secrets.yml

# 3. Проверяем токен
pveum user token list automation@pam
# → Token ID: sd-reader
# → Privilege separation: disabled

# 4. Тестируем доступ (должен вернуть 200 OK)
curl -k -H "Authorization: PVEAPIToken=automation@pam!sd-reader=<SECRET_5e4c4c20>" \
  https://pve1.example.com:8006/api2/json/nodes
# → [{"node":"pve1",...},...]
```

### Сценарий 2: Базовый DNS-запрос и верификация

```bash
# Проверка, что DNS отвечает
dig @127.0.0.1 -p 2053 vm.cluster.local SOA +noall +authority
# → vm.cluster.local. 60 IN SOA ns1.vm.cluster.local. admin.vm.cluster.local. ...

# Запрос по имени VM
dig @127.0.0.1 -p 2053 web-server.vm.cluster.local A +short
# → 192.168.10.25

# Запрос по тегу (если DISCOVERY_VM_TAGS=true)
dig @127.0.0.1 -p 2053 prod.vm.cluster.local A +short
# → 192.168.10.25
# → 192.168.10.26

# Запрос по имени узла
dig @127.0.0.1 -p 2053 pve1.vm.cluster.local A +short
# → 192.168.10.10

# Проверка fallback на внешний DNS
dig @127.0.0.1 -p 2053 google.com A +short
# → 142.250.80.46
```

### Сценарий 3: Интеграция с systemd-resolved

На хосте с systemd-resolved (современные Ubuntu/Debian/RHEL):

```bash
# 1. Создаем файл resolved.conf.d
sudo mkdir -p /etc/systemd/resolved.conf.d
cat <<'EOF' | sudo tee /etc/systemd/resolved.conf.d/proxmox-sd.conf
[Resolve]
DNS=127.0.0.1
DNS=192.168.1.50
Port=2053
Domains=vm.cluster.local
EOF

# 2. Перезапускаем resolved
sudo systemctl restart systemd-resolved

# 3. Проверяем
resolvectl query web-server.vm.cluster.local
# → web-server.vm.cluster.local: 192.168.10.25

# 4. Проверяем, что остальные домены резолвятся через fallback
resolvectl query google.com
```

### Сценарий 4: Интеграция с приложениями

#### PostgreSQL

```ini
# postgresql.conf
# Для подключения к реплике по имени
primary_conninfo = 'host=pg-primary.vm.cluster.local port=5432 user=replicator'
```

#### Ansible Inventory

```ini
# inventory.ini
[proxmox_vms]
web01 ansible_host=web-server.vm.cluster.local
db01 ansible_host=database.vm.cluster.local

[proxmox_vms:vars]
ansible_user=root
ansible_ssh_private_key_file=~/.ssh/id_rsa
```

#### Nginx upstream

```nginx
upstream backend {
    server web-server.vm.cluster.local:8080;
    server api-server.vm.cluster.local:8080;
}

server {
    listen 80;
    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
    }
}
```

#### Keepalived / VRRP

```bash
# В конфигурации keepalived можно использовать DNS-имена для проверки
vrrp_script check_web {
    script "curl -sf http://web-server.vm.cluster.local:8080/health"
    interval 2
    weight 20
}
```

### Сценарий 5: Мониторинг доступности DNS

```bash
# 1. Blackbox-проверка через curl/dig
watch -n 10 'dig @127.0.0.1 -p 2053 web-server.vm.cluster.local +short'

# 2. Проверка через systemd timer (если systemd-сервис)
systemctl status proxmox-sd
journalctl -u proxmox-sd --since "1 hour ago" | grep -i error

# 3. Exporter-метрики (если используется Prometheus Blackbox Exporter)
# config.yml:
modules:
  dns_udp:
    prober: dns
    timeout: 5s
    dns:
      query_name: "web-server.vm.cluster.local"
      query_type: "A"
      server: "192.168.1.50:2053"
```

### Сценарий 6: Тестирование отказоустойчивости

```bash
# 1. Останавливаем Service Discovery
docker stop proxmox-sd

# 2. Проверяем, что клиенты переключаются на fallback DNS
dig @192.168.1.50 web-server.vm.cluster.local
# → должен вернуться старый кэшированный IP (если есть) или NXDOMAIN

# 3. Перезапускаем Service Discovery
docker start proxmox-sd

# 4. Ждем 1 polling cycle + 5 секунд
sleep 65

# 5. Проверяем актуальность записи
dig @127.0.0.1 -p 2053 web-server.vm.cluster.local A +short
# → новый актуальный IP
```

## Диагностика и устранение неполадок

### 1. NXDOMAIN для всех записей

**Симптомы:** `dig` возвращает `NXDOMAIN` или `SERVFAIL` для всех внутренних имен.

**Причины и решения:**

| Причина | Диагностика | Решение |
|:---|:---|:---|
| Неверный/просроченный токен | `journalctl -u proxmox-sd \| grep -i auth` | Создайте новый токен, обновите секрет |
| API Proxmox недоступен | `curl -k https://pve1:8006/api2/json/version` | Проверьте сеть, firewall, сертификат |
| Нет прав на `/nodes/` или `/vms/` | `curl -H "Authorization: PVEAPIToken=..." /api2/json/nodes` | Назначьте роль `PVEAuditor` или отдельные права |
| Неверный `DISCOVERY_PROXMOX_HOST` | `echo $DISCOVERY_PROXMOX_HOST` | Укажите полный URL с `https://` и портом 8006 |

```bash
# Быстрая проверка токена
curl -k -H "Authorization: PVEAPIToken=automation@pam!sd-reader=<SECRET_5e4c4c20>" \
  https://pve1.example.com:8006/api2/json/version
# → {"version":"8.1.4",...}
```

### 2. Записи VM отсутствуют, но API работает

**Симптомы:** `dig` возвращает `NXDOMAIN` только для VM, узлы резолвятся.

**Причины:**
- У VM нет настроенных IP-адресов в `ip0`, `ip1` (QEMU agent не установлен или не запущен).
- VM остановлена, но ожидалась запись только для running VM.

**Решения:**
```bash
# Проверка конфигурации VM
curl -k -H "Authorization: PVEAPIToken=..." \
  https://pve1:8006/api2/json/nodes/pve1/qemu/1001/config/current | jq .ip0

# Установите QEMU Guest Agent в VM и запустите сервис
# В Proxmox GUI: VM → Options → QEMU Guest Agent → включить
```

### 3. DNS не отвечает

**Симптомы:** `dig @127.0.0.1 -p 2053 ...` возвращает `connection refused`.

**Диагностика:**
```bash
# Статус контейнера/сервиса
docker ps --filter name=proxmox-sd
docker logs proxmox-sd --tail 50

# Если systemd-сервис
systemctl status proxmox-sd
journalctl -u proxmox-sd -n 50

# Порт занят
ss -lunp | grep 2053
# → Если занят другим процессом, измените DISCOVERY_DNS_PORT
```

### 4. Устаревшие IP-адреса (Stale Records)

**Симптомы:** После миграции/переименования VM DNS возвращает старый IP.

**Причины:**
- Интервал опроса слишком большой (`DISCOVERY_INTERVAL=300`).
- Кэширование DNS на стороне клиента (TTL=300с).

**Решения:**
```bash
# Уменьшите интервал опроса
DISCOVERY_INTERVAL=15

# На клиенте снизьте TTL кэша
resolvectl revert-conf
sudo resolvectl dns eth0 127.0.0.1:2053
sudo resolvectl domain eth0 "~vm.cluster.local"

# Или в systemd-resolved.conf
# DNS=127.0.0.1:2053
# Domains=vm.cluster.local
```

### 5. Случайные потери пакетов DNS

**Симптомы:** `dig` иногда возвращает `TIMEOUT` или `SERVFAIL`.

**Причины:**
- Контейнер без `network_mode: host` не может ответить на запросы из внешней сети.
- Firewall блокирует UDP/2053.
- Proxmox API возвращает 500/503 при высокой нагрузке.

**Решения:**
```bash
# Проверка firewall
sudo iptables -L -n | grep 2053
sudo nft list ruleset | grep 2053

# Проверка доступности API под нагрузкой
for i in {1..10}; do curl -k -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: PVEAPIToken=..." https://pve1:8006/api2/json/nodes; echo; done
```

### 6. Записи по тегам не создаются

**Причины:**
- `DISCOVERY_VM_TAGS` не установлен в `true`.
- Теги содержат недопустимые символы для DNS (пробелы, underscore).

**Решения:**
```bash
# Проверка тегов VM
pvesh get /nodes/pve1/qemu/1001/config/current | jq .tags
# → "web;prod;us-east"

# Убедитесь, что переменная окружения установлена
echo $DISCOVERY_VM_TAGS
# → true

# Если теги с underscores, используйте только alphanum + hyphens
```

### 7. Конфликты имен (Duplicate Names)

**Симптомы:** Две VM имеют одинаковое имя, но разные IP.

**Поведение:** Service Discovery создает только одну запись (последняя обработанная VM побеждает). Это не-deterministic поведение.

**Решение:** Убедитесь, что имена VM уникальны в рамках кластера. Для дублированных имен используйте теги или суффиксы.

### 8. TLS-ошибки при обращении к API

**Симптомы:** `curl: (60) SSL certificate problem: self signed certificate`.

**Решение:**
```bash
# Для тестирования: отключение проверки (-k)
curl -k -H "Authorization: PVEAPIToken=..." https://pve1:8006/api2/json/nodes

# Для production: добавьте сертификат Proxmox CA в trust store
sudo cp /etc/pve/pve-root-ca.pem /usr/local/share/ca-certificates/pve-root-ca.crt
sudo update-ca-certificates
```

## Лучшие практики

### Безопасность

- **Минимальные права:** Используйте отдельного пользователя с ролью `PVEAuditor` или кастомными правами только на `/nodes/` и `/vms/`. Никогда не используйте токен `root@pam`.
- **Секреты:** Храните `DISCOVERY_PROXMOX_TOKEN_SECRET` в vault/Ansible Vault/HashiCorp Vault, а не в docker-compose или systemd-файле в открытом виде.
- **Сетевой доступ:** Ограничьте доступ к порту 2053 только доверенными подсетями через firewall (`iptables`/`nftables`/`pve-firewall`).
- **TLS:** Всегда используйте `https://` для `DISCOVERY_PROXMOX_HOST`. Добавьте CA-сертификат Proxmox в trust store, чтобы не использовать `-k`/`insecure` в production.
- **Ротация токенов:** Периодически ротируйте токены (раз в 90 дней). При компрометации — немедленно отзовите токен через GUI или `pveum user token delete automation@pam sd-reader`.

### Производительность и стабильность

- **Интервал опроса:** Для production используйте 15–30 секунд. Значения меньше 10s могут создавать лишнюю нагрузку на API Proxmox при большом количестве VM.
- **Количество Service Discovery инстансов:** Развертывайте 2+ инстанса для HA. В Kubernetes используйте `replicas: 2` с `hostNetwork: true` и `NodePort`/`LoadBalancer`.
- **Кэширование DNS на клиентах:** Настройте `systemd-resolved` или `dnsmasq` как локальный кэширующий резолвер перед Service Discovery. Это снизит латентность и нагрузку.
- **Мониторинг:** Настройте алерты на:
  - Доступность DNS (`dig` проверка каждые 30s).
  - Ошибки в логах Service Discovery (`journalctl -u proxmox-sd --since "1 hour ago"`).
  - Срок действия токена Proxmox (обычно токены не expire, но при ротации — проверка).

### Сеть и топология

- **Порт 2053 vs 53:** Используйте 2053, чтобы избежать конфликтов с systemd-resolved и не требовать root. На клиентах явно указывайте порт через `resolv.conf` или `resolvectl`.
- **Fallback DNS:** Вместо публичного `8.8.8.8` используйте локальный кэширующий resolver. Это уменьшает зависимость от внешнего интернета и снижает латентность.
- **Split-horizon DNS:** Если требуется, чтобы разные подсети видели разные записи, разверните два экземпляра Service Discovery с разными `DISCOVERY_NODE_SUBNET` и `DISCOVERY_DOMAIN_SUFFIX`.

### Обслуживание

- **Обновления:** Проверяйте релизы на GitHub. Обновляйте бинарный файл или тег образа в docker-compose. Тестируйте в staging перед production.
- **Резервное копирование:** Сохраняйте конфигурацию (docker-compose.yml, .env, systemd unit) в git/Ansible.
- **Тестирование восстановления:** Периодически проверяйте, что Service Discovery корректно обновляет записи после миграции VM или изменения IP.

## Граничные случаи и ограничения

### 1. Остановленные VM

**Поведение:** Если VM остановлена, но в конфигурации есть `ip0`, запись будет опубликована в DNS.

**Решение:** Используйте теги для маркировки (`running-only`) и фильтруйте на стороне клиента, или доработайте Service Discovery под ваши нужды.

### 2. Динамические IP (DHCP)

**Поведение:** Если VM получает IP по DHCP, Service Discovery публикует текущий IP. При смене IP запись обновится только через `DISCOVERY_INTERVAL` секунд.

**Решение:** Уменьшите интервал до 15–30s. Для критичных сервисов используйте статические IP или DHCP-reservations.

### 3. Несколько интерфейсов у VM

**Поведение:** Service Discovery берет первый configured IP из `ip0`, `ip1`, ... Остальные интерфейсы игнорируются.

**Решение:** Если нужен доступ к конкретному интерфейсу, используйте кастомные теги или модифицируйте инструмент под ваши нужды.

### 4. Имена VM с недопустимыми символами

**Поведение:** ПроXMox разрешает имена VM с underscores и пробелами, но DNS не допускает таких символов в A-записях.

**Решение:** Используйте только alphanumeric и hyphens в именах VM. Для legacy-имен используйте теги.

### 5. Большие кластеры (100+ VM)

**Поведение:** При 100+ VM и интервале 15s нагрузка на API Proxmox составляет ~7 запросов/сек (4 запроса на VM + overhead). Это допустимо для большинства сред.

**Оптимизации:**
- Увеличьте интервал до 30–60s.
- Разверните 2+ инстанса Service Discovery с разделением ответственности (например, по группам VM).
- Используйте локальный кэш DNS на стороне клиентов.

### 6. Миграция VM между нодами

**Поведение:** При live-migration IP VM не меняется, запись остается валидной. При cold-migration с изменением IP — запись обновится через `DISCOVERY_INTERVAL`.

**Решение:** Для нулевого простоя используйте статические IP или DHCP-reservations, привязанные к MAC-адресу VM.

### 7. Сеть с ограниченным MTU

**Поведение:** DNS-запросы и ответы малы (обычно <512 байт для UDP). MTU обычно не является проблемой.

**Решение:** Если используете VPN/туннели с низким MTU, убедитесь, что DNS-пакеты фрагментируются корректно.

### 8. Конфликт портов

**Симптомы:** `bind: address already in use` при запуске Service Discovery.

**Решение:**
```bash
# Найдите процесс, занимающий порт
sudo ss -lunp | grep 2053

# Измените порт в переменной окружения
DISCOVERY_DNS_PORT=2054
```

### 9. Отказ Proxmox API

**Поведение:** При недоступности API Service Discovery продолжает отвечать на DNS-запросы из кэша (in-memory state). Новые/обновленные записи не появляются.

**Решение:** Настройте мониторинг доступности API (`curl` проверка) и алерты. При долгом простое — переключитесь на статический DNS.

### 10. Резолвинг внешних доменов через Service Discovery

**Поведение:** Если `DISCOVERY_EXTERNAL_DNS` настроен, Service Discovery перенаправляет запросы для неизвестных имен на внешний DNS.

**Ограничения:**
- Запросы к внешним доменам проходят через Service Discovery, добавляя latency (~1–5ms).
- При высокой нагрузке на Service Discovery внешние запросы могут замедляться.

**Решение:** На клиентах используйте локальный кэширующий resolver (systemd-resolved) как основной, а Service Discovery укажите только для домена `vm.cluster.local`.

## Связанные темы

- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Обнаружение сервисов (обзор)](../Concepts/service-discovery-overview.md)
- [Протокол DNS](../Networking/Protocols/DNS/dns.md)
