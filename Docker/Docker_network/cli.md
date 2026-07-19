# Управление сетями Docker: CLI-справочник

## Определения

- **`docker network`**: Набор команд CLI (Command Line Interface — интерфейс командной строки) для управления жизненным циклом сетей Docker.
- **Сеть (Network)**: Виртуальный коммутатор, обеспечивающий связь между контейнерами (endpoints).
- **Драйвер сети (Network Driver)**: Плагин, реализующий сетевую логику (`bridge`, `host`, `overlay`, `macvlan`, `ipvlan`, `none`).
- **IPAM (IP Address Management)**: Система управления адресным пространством (подсети, шлюзы, диапазоны IP).
- **CIDR (Classless Inter-Domain Routing)**: Метод безклассовой адресации для определения границ подсетей (например, `192.168.1.0/24`).
- **DNS (Domain Name System)**: Система разрешения доменных имён; в Docker обеспечивает поиск контейнеров по имени или алиасу.

## Основные концепции

### Команды управления

| Команда | Назначение | Ключевые флаги / Фильтры |
| :--- | :--- | :--- |
| `ls` | Список сетей | `--filter` (`driver`, `type`, `name`, `scope`), `--format`, `--no-trunc` |
| `create` | Создание сети | `-d` (драйвер), `--subnet`, `--gateway`, `--internal`, `--attachable` |
| `inspect` | Детальная информация | `--format` (Go-шаблоны), `-f` |
| `connect` | Подключение контейнера | `--ip`, `--ip6`, `--alias`, `--link` (legacy) |
| `disconnect` | Отключение контейнера | `-f` (force — принудительно) |
| `rm` | Удаление сети | Удаляет только неиспользуемые сети |
| `prune` | Очистка системы | `--filter` (например, `until=24h`), `-f` |

### Расширенные опции `docker network create`

- **Управление IP (IPAM):**
  - `--subnet`: Определяет подсеть в формате CIDR.
  - `--gateway`: Указывает адрес шлюза.
  - `--ip-range`: Ограничивает диапазон выдаваемых IP-адресов внутри подсети.
  - `--aux-address`: Резервирует IP-адреса для внешних нужд (например, `--aux-address="my-router=192.168.1.5"`).
- **Параметры драйвера (`-o, --opt`):**
  - `com.docker.network.bridge.name`: Кастомное имя интерфейса на хосте (только для `bridge`).
  - `com.docker.network.bridge.enable_icc`: Включение/выключение связи между контейнерами (Inter-Container Communication).
  - `com.docker.network.bridge.enable_ip_masquerade`: Включение NAT (Network Address Translation) для выхода в интернет.
- **Особенности Swarm/Overlay:**
  - `--attachable`: Позволяет подключать обычные контейнеры (не сервисы) к `overlay`-сетям.
  - `--encrypted`: Включает шифрование трафика (IPsec) на уровне данных.
  - `--scope`: Область видимости сети (`local` или `swarm`).

## Практические сценарии

### Работа со списком и фильтрация

**Поиск всех bridge-сетей:**

```bash
docker network ls --filter driver=bridge
# → NETWORK ID     NAME      DRIVER    SCOPE
# → a1b2c3d4e5f6   bridge    bridge    local
```

**Вывод только имён сетей (для автоматизации):**

```bash
docker network ls --format "{{.Name}}"
# → bridge
# → host
# → none
```

### Сложное создание сети

**Создание bridge-сети с кастомным именем интерфейса и ограниченным диапазоном IP:**

```bash
docker network create -d bridge \
  --subnet=10.10.0.0/16 \
  --ip-range=10.10.10.0/24 \
  --gateway=10.10.0.1 \
  -o com.docker.network.bridge.name=br-prod \
  prod-net
```

**Создание сети с поддержкой IPv6:**

```bash
docker network create --ipv6 --subnet=2001:db8:1::/64 ipv6-net
```

### Управление подключениями контейнеров

**Подключение контейнера со статическим IP и сетевым алиасом:**

```bash
# Контейнер будет доступен в сети по имени "db-master"
docker network connect --ip 10.10.10.50 --alias db-master prod-net my-app-container
```

**Инспекция конкретных параметров (например, IP-адреса контейнера в сети):**

```bash
docker network inspect prod-net --format '{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{end}}'
# → my-app-container: 10.10.10.50/16
```

### Жизненный цикл: отладочный сценарий

1. **Создание изолированной сети:**

   ```bash
   docker network create --internal isolated-net
   ```

2. **Запуск контейнера-сервера:**

   ```bash
   docker run -d --name secret-api --network isolated-net hashicorp/http-echo -text="hello"
   ```

3. **Подключение клиента "на лету" для диагностики:**

   ```bash
   docker run -d --name debugger alpine sleep 3600
   docker network connect isolated-net debugger
   ```

4. **Проверка связи:**

   ```bash
   docker exec debugger wget -qO- http://secret-api:5678
   # → hello
   ```

5. **Принудительное отключение и удаление:**

   ```bash
   docker network disconnect -f isolated-net debugger
   docker network rm isolated-net
   # Примечание: secret-api должен быть остановлен/удален перед удалением сети
   ```

## Дополнительная информация

### Нюансы и ограничения

- **Сеть `none`**: Невозможно подключить контейнер к другим сетям, если он запущен с `--network none`.
- **Сеть `host`**: Контейнер разделяет сетевой стек с хостом; флаг `--ip` или `--alias` игнорируются.
- **Конфликты подсетей**: Docker не позволяет создавать сети с пересекающимися подсетями на одном хосте.
- **Лимиты**: По умолчанию в одной bridge-сети может быть до 1024 контейнеров (ограничение bridge-драйвера).

**Смотрите также:**

- [Обзор сетевых моделей Docker](./docker_network.md)
- [Сетевой драйвер bridge](./drivers/bridge.md)
- [Сетевой драйвер overlay](./drivers/overlay.md)
