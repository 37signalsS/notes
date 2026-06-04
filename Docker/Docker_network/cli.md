# Управление сетями Docker: CLI-справочник

## Определения

- **`docker network`**: Набор команд CLI (Command Line Interface) для управления сетями Docker — создание, инспекция, подключение/отключение контейнеров, удаление.
- **Сеть (Network)**: Программный коммутатор, объединяющий конечные точки (endpoints) контейнеров для обмена данными.
- **Драйвер сети**: Плагин, определяющий тип сети (`bridge`, `overlay`, `host`, `macvlan`, `ipvlan`, `none`).

## Основные концепции

### Команды управления

| Команда | Назначение |
| :--- | :--- |
| `docker network ls` | Список всех сетей на хосте |
| `docker network create` | Создание новой сети с указанием драйвера и параметров |
| `docker network inspect` | Детальная информация о сети в формате JSON (JavaScript Object Notation) |
| `docker network connect` | Подключение работающего контейнера к сети |
| `docker network disconnect` | Отключение контейнера от сети |
| `docker network rm` | Удаление одной или нескольких сетей |
| `docker network prune` | Удаление всех неиспользуемых сетей |

### Ключевые опции `docker network create`

- `-d, --driver <driver>`: Драйвер сети (по умолчанию `bridge`).
- `--subnet <CIDR>`: Подсеть в формате CIDR (Classless Inter-Domain Routing) (например, `172.20.0.0/16`).
- `--gateway <IP>`: IP-адрес (Internet Protocol) шлюза для подсети.
- `--ip-range <CIDR>`: Диапазон IP-адресов для контейнеров (не должен пересекаться с `--subnet`).
- `--internal`: Изолированная сеть без внешнего шлюза (только внутренняя коммуникация).
- `--attachable`: Разрешить ручное подключение контейнеров (`docker run --network`).
- `--label <key>=<value>`: Метаданные сети (например, `env=production`).

## Практические сценарии

### Базовые операции

**Список сетей:**

```bash
docker network ls
# → NETWORK ID     NAME      DRIVER    SCOPE
# → a1b2c3d4e5f6   bridge    bridge    local
# → f7e6d5c4b3a2   host      host      local
# → 1234567890ab   none      null      local
```

**Создание сети:**

```bash
# Стандартная bridge-сеть
docker network create my-bridge-net

# Сеть с указанием подсети
docker network create -d bridge --subnet=192.168.50.0/24 my-custom-net

# Изолированная сеть (без выхода во внешний мир)
docker network create -d bridge --internal --subnet=172.30.0.0/16 isolated-net

# Сеть с несколькими подсетями
docker network create -d bridge --subnet=172.20.0.0/16 --subnet=172.21.0.0/16 multi-subnet-net
```

**Инспекция сети:**

```bash
docker network inspect my-bridge-net
# → Вывод: драйвер, подсеть, шлюз, список подключенных контейнеров
```

**Удаление сети:**

```bash
docker network rm my-bridge-net
# → Ошибка, если к сети подключен хотя бы один контейнер
```

**Очистка неиспользуемых сетей:**

```bash
docker network prune
# → Требует подтверждения
```

### Полный жизненный цикл сети

1. **Создание сети для приложения:**

   ```bash
   docker network create my-app-net
   ```

2. **Запуск контейнера в сети:**

   ```bash
   docker run -d --name server --network my-app-net nginx
   ```

3. **Проверка подключения:**

   ```bash
   docker network inspect my-app-net
   # → Секция "Containers" покажет контейнер "server"
   ```

4. **Подключение второго контейнера "на лету":**

   ```bash
   docker run -d --name client alpine sleep 3600
   docker network connect my-app-net client
   # Теперь client может обращаться к server по имени: ping server
   ```

5. **Отключение и очистка:**

   ```bash
   docker network disconnect my-app-net client
   docker stop server client && docker rm server client
   docker network rm my-app-net
   ```

### Мульти-сетевые контейнеры

Один контейнер может быть подключен к нескольким сетям одновременно:

```bash
# Контейнер в двух сетях
docker run -d --name router --network frontend-net alpine sleep 3600
docker network connect backend-net router

# router имеет интерфейсы в обеих сетях и может маршрутизировать трафик
```

**Сценарий использования:** Разделение frontend/backend трафика, организация DMZ (Demilitarized Zone), шлюзы между сетями.

## Дополнительная информация

Сторонние сетевые драйверы предоставляют расширенные возможности: интеграция с SDN (Software-Defined Networking), применение сетевых политик, подключение к внешним оркестраторам.

**Смотрите также:**

- [Обзор сетевых моделей Docker](./docker_network.md)
- [DNS и Service Discovery](./dns_and_service_discovery.md)
