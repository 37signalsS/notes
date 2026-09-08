# Proxmox Service Discovery

## Определения

**Proxmox Service Discovery** — инструмент с открытым исходным кодом для автоматического обнаружения виртуальных машин в кластере Proxmox через DNS. Приложение периодически опрашивает API Proxmox и создает DNS-записи типа A, позволяя другим сервисам находить VM по именам или тегам.

**Репозиторий:** [itcaat/proxmox-service-discovery](https://github.com/itcaat/proxmox-service-discovery)

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

1. **Подключение к API:** Приложение аутентифицируется в Proxmox через API-токен (не интерактивный логин)

2. **Опрос кластера (цикл N секунд, по умолчанию 60s):**
   - Получение списка всех узлов (нод) кластера
   - Для каждого узла — список виртуальных машин
   - Для каждой VM — конфигурация (имя, IP-адрес)
   - Для каждого узла — информация о сетевых интерфейсах

3. **Генерация DNS-записей:**
   - Для каждой VM: `имя_машины.суффикс` → IP-адрес
   - При включенной опции `DISCOVERY_VM_TAGS`: `тег.суффикс` → IP-адрес (для всех тегов VM)
   - Для каждого узла: `имя_узла.суффикс` → IP-адрес (фильтрация по подсети)

4. **DNS-сервер:**
   - Запускается на порту 2053 (по умолчанию)
   - Отвечает на запросы с использованием созданных записей
   - При отсутствии записи — перенаправление на внешний DNS (8.8.8.8)

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

## Развертывание

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

### Настройка API-токена в Proxmox

1. **GUI:** Datacenter → Permissions → API Tokens → Add
2. **Права:** Токену достаточно Read-only доступа к нодам и VM (`PVEAuditor` или отдельные права на `/nodes/`, `/vms/`)

### DNS-запросы

```bash
# Запрос по имени VM
dig @localhost -p 2053 web-server.vm.cluster.local A +short
# → 192.168.1.100

# Запрос по тегу
dig @localhost -p 2053 database.vm.cluster.local A +short
# → 192.168.1.101
# → 192.168.1.102

# Запрос по имени узла
dig @localhost -p 2053 pve-node1.vm.cluster.local A +short
# → 192.168.1.10
```

### Интеграция с приложениями

Для использования в качестве upstream DNS достаточно указать IP сервиса и порт 2053:

```bash
# В /etc/resolv.conf
nameserver 192.168.1.50
port 2053
```

Или точечно в приложениях:

```bash
# Пример с dig
dig @192.168.1.50 -p 2053 web-server.vm.cluster.local
```

## Диагностика

### Проверка статуса

```bash
# Логи контейнера
docker logs proxmox-sd

# Тестовый запрос DNS
dig @localhost -p 2053 +short test-vm.vm.cluster.local
```

### Типичные проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| NXDOMAIN для всех записей | Неверный API-токен | Проверить `DISCOVERY_PROXMOX_TOKEN_ID` и `DISCOVERY_PROXMOX_TOKEN_SECRET` |
| Записи VM отсутствуют | Нет прав на VM | Добавить права на `/vms/` или использовать `PVEAuditor` |
| DNS не отвечает | Порт занят | Проверить `DISCOVERY_DNS_PORT` или сменить на свободный |
| IP узлов не совпадают | Фильтрация по подсети | Настроить `DISCOVERY_NODE_SUBNET` или отключить фильтр |

## Связанные темы

- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Обнаружение сервисов (обзор)](../Concepts/service-discovery-overview.md)
- [Протокол DNS](../Networking/Protocols/DNS/dns.md)
