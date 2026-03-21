# Справочник команд: `docker network`

Этот документ представляет собой справочник по основным командам для управления сетями Docker.

### `docker network ls`

Показывает список всех сетей на хосте.

- **Использование:** `docker network ls [OPTIONS]`
- **Пример:**

  ```bash
  docker network ls
  # NETWORK ID     NAME              DRIVER    SCOPE
  # a1b2c3d4e5f6   bridge            bridge    local
  # f7e6d5c4b3a2   host              host      local
  # 1234567890ab   none              null      local
  ```

### `docker network create`

Создает новую сеть.

- **Использование:** `docker network create [OPTIONS] <имя_сети>`
- **Ключевые опции:**
  - `-d, --driver`: Драйвер для использования (по умолчанию `bridge`).
  - `--subnet`: Подсеть в формате CIDR (например, `172.20.0.0/16`).
  - `--gateway`: IP-адрес основного шлюза для подсети.
  - `--ip-range`: Диапазон IP-адресов для выдачи контейнерам (не должен пересекаться с подсетью).
  - `--internal`: Создать изолированную сеть без внешнего шлюза (только внутренняя коммуникация).
  - `--attachable`: Разрешить ручное подключение контейнеров пользователями (полезно для `docker run --network`).
  - `--label`: Метаданные для сети (например, `--label env=production`).
- **Пример:**

  ```bash
  # Создание стандартной bridge-сети
  docker network create my-bridge-net

  # Создание сети с указанием драйвера и подсети
  docker network create -d bridge --subnet=192.168.50.0/24 my-custom-net

  # Изолированная сеть (без шлюза во внешний мир)
  docker network create -d bridge --internal --subnet=172.30.0.0/16 isolated-net

  # Сеть с несколькими подсетями
  docker network create -d bridge --subnet=172.20.0.0/16 --subnet=172.21.0.0/16 multi-subnet-net
  ```

### `docker network inspect`

Отображает подробную информацию об одной или нескольких сетях в формате JSON.

- **Использование:** `docker network inspect [OPTIONS] <имя_сети>...`
- **Пример:**

  ```bash
  docker network inspect my-bridge-net
  # Вывод покажет драйвер, подсеть, шлюз и список подключенных контейнеров.
  ```

### `docker network connect`

Подключает работающий контейнер к сети.

- **Использование:** `docker network connect [OPTIONS] <сеть> <контейнер>`
- **Пример:**

  ```bash
  docker network connect my-bridge-net my-running-container
  ```

### `docker network disconnect`

Отключает контейнер от сети.

- **Использование:** `docker network disconnect [OPTIONS] <сеть> <контейнер>`
- **Пример:**

  ```bash
  docker network disconnect my-bridge-net my-running-container
  ```

### `docker network rm`

Удаляет одну или несколько сетей. Сеть не может быть удалена, если к ней подключен хотя бы один контейнер.

- **Использование:** `docker network rm <имя_сети>...`
- **Пример:**

  ```bash
  docker network rm my-bridge-net
  ```

### `docker network prune`

Удаляет все неиспользуемые сети (сети, к которым не подключен ни один контейнер).

- **Использование:** `docker network prune [OPTIONS]`
- **Пример:**

  ```bash
  docker network prune
  # Docker запросит подтверждение перед удалением.
  ```

## Практический рабочий процесс

Рассмотрим полный жизненный цикл управления сетью.

1. **Создадим свою `bridge`-сеть для изоляции приложения:**

    ```bash
    docker network create my-app-net
    ```

2. **Запустим `nginx` в новой сети:**

    ```bash
    docker run -d --name server --network my-app-net nginx
    ```

3. **Убедимся, что контейнер `server` подключен к `my-app-net`:**

    ```bash
    docker network inspect my-app-net
    # В выводе JSON в секции "Containers" будет информация о контейнере "server".
    ```

4. **Запустим второй контейнер и подключим его "на лету":**

    ```bash
    docker run -d --name client alpine sleep 3600
    docker network connect my-app-net client
    ```

    Теперь `client` может обращаться к `server` по имени (`ping server`).

5. **Отключим `client` и очистим ресурсы:**

    ```bash
    docker network disconnect my-app-net client
    docker stop server client && docker rm server client
    docker network rm my-app-net
    ```

## Дополнительная информация

- **Мульти-сетевые контейнеры**: Один контейнер может быть подключен к нескольким сетям одновременно с помощью `docker network connect`. Это позволяет организовывать сложные сценарии маршрутизации (например, backend-сеть и frontend-сеть).
- **Сетевые плагины**: Docker поддерживает сторонние сетевые драйверы, которые могут предоставлять расширенные возможности, такие как интеграция с SDN или применение сетевых политик.
- **Связанные темы:**
  - [Обзор сетевых моделей Docker](./docker_network.md) — основной справочник по Docker Networking
  - [DNS и Service Discovery](./dns_and_service_discovery.md) — как работает разрешение имен
