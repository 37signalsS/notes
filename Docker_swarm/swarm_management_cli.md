# Docker Swarm: CLI Reference

## Определения

**CLI (Command Line Interface)** — интерфейс командной строки Docker для управления Swarm-кластером. Все команды выполняются через `docker <subcommand>`.

**Manager CLI context** — контекст выполнения команд: большинство команд управления кластером доступны только с узлов-менеджеров.

## Базовые концепции

### Иерархия команд

Команды управления Swarm организованы по уровням:

| Уровень | Команда | Описание |
|---|---|---|
| Кластер | `docker swarm` | Инициализация, присоединение, покидание кластера |
| Узлы | `docker node` | Управление узлами (роли, статус, удаление) |
| Сервисы | `docker service` | Создание, масштабирование, обновление сервисов |
| Стек | `docker stack` | Развертывание многоконтейнерных приложений |
| Сети | `docker network` | Управление overlay-сетями |
| Секреты | `docker secret` | Управление секретами |
| Конфигурации | `docker config` | Управление конфигурациями |

### Требования к выполнению

- **Менеджер:** Команды `swarm`, `node`, `secret`, `config` требуют роли менеджера
- **Любой узел:** Команды `service ps`, `network inspect` доступны на всех узлах
- **CLI context:** Для удаленного управления используйте `docker context` (см. **[CI_CD/swarm_setup.md](./CI_CD/swarm_setup.md)**)

## Практические сценарии

### Инициализация кластера

#### Создание Swarm-кластера

```sh
# Инициализация на менеджере
docker swarm init --advertise-addr <MANAGER-IP>
```

**Параметры:**
- `--advertise-addr` — IP-адрес для связи с другими узлами (обязательно для многохостовых конфигураций)
- `--listen-addr` — адрес прослушивания (по умолчанию `:2377`)

#### Присоединение узлов

```sh
# Получить токен для worker
docker swarm join-token worker

# Получить токен для manager
docker swarm join-token manager

# Присоединиться к кластеру (на рабочем узле)
docker swarm join --token <TOKEN> <MANAGER-IP>:2377
```

#### Вывод из кластера

```sh
# Покинуть кластер (рабочий узел)
docker swarm leave

# Покинуть кластер (менеджер, требует --force)
docker swarm leave --force

# Принудительно удалить узел (с менеджера)
docker node rm <NODE-ID>
```

### Управление узлами

#### Просмотр информации

```sh
# Список узлов
docker node ls

# Детальная информация об узле
docker node inspect --pretty <NODE-ID>

# Задачи на узле
docker node ps <NODE-ID>
```

#### Изменение ролей

```sh
# Повысить worker до manager
docker node promote <NODE-ID>

# Понизить manager до worker
docker node demote <NODE-ID>
```

**Важно:** Изменение ролей менеджеров может временно повлиять на кворум.

#### Дренаж узла (обслуживание)

```sh
# Пометить узел как недоступный
docker node update --availability drain <NODE-ID>

# Вернуть узел в строй
docker node update --availability active <NODE-ID>
```

Задачи с drained-узла автоматически перемещаются на другие узлы.

### Управление сервисами

#### Создание сервиса

```sh
# Базовый сервис
docker service create --name web --replicas 3 nginx:1.26.3

# С публикацией портов
docker service create --name web --publish 80:80 --replicas 3 nginx:1.26.3

# С ограничениями ресурсов
docker service create --name app \
  --reserve-memory 512m \
  --limit-memory 1g \
  --reserve-cpu 0.5 \
  --limit-cpu 1.0 \
  myapp:latest

# С placement constraints
docker service create --name db \
  --constraint 'node.labels.type == database' \
  postgres:15
```

#### Мониторинг сервисов

```sh
# Список сервисов
docker service ls

# Задачи сервиса (распределение по узлам)
docker service ps <SERVICE_NAME>

# Журналы сервиса
docker service logs <SERVICE_NAME>

# Журналы с деталями
docker service logs --follow --details <SERVICE_NAME>
```

#### Масштабирование

```sh
# Изменить количество реплик
docker service scale web=10

# Масштабирование нескольких сервисов
docker service scale web=10 api=5 db=3
```

#### Обновление (Rolling Update)

```sh
# Обновить образ
docker service update --image nginx:1.27 web

# С параметрами обновления
docker service update \
  --image myapp:v2 \
  --update-parallelism 2 \
  --update-delay 30s \
  --update-failure-action rollback \
  my-service

# Откат к предыдущей версии
docker service rollback my-service
```

**Параметры обновления:**
- `--update-parallelism` — количество реплик, обновляемых одновременно
- `--update-delay` — задержка между группами обновлений
- `--update-failure-action` — действие при ошибке (`continue`, `pause`, `rollback`)

#### Удаление сервиса

```sh
docker service rm <SERVICE_NAME>
```

### Развертывание стеков

#### Деплой стека

```sh
# Развернуть стек из docker-compose.yml
docker stack deploy -c docker-compose.yml myapp

# Проверить стек
docker stack ls
docker stack ps myapp
docker stack services myapp
```

#### Удаление стека

```sh
docker stack rm myapp
```

**Важно:** `docker stack rm` не удаляет сети и volumes, созданные стеком.

### Управление сетями

```sh
# Создать overlay-сеть
docker network create --driver=overlay my-network

# Создать сеть с шифрованием
docker network create --driver=overlay --opt encrypted my-network

# Список сетей
docker network ls

# Инспекция сети
docker network inspect my-network
```

### Секреты и конфигурации

#### Секреты

```sh
# Создать секрет из файла
echo "password123" | docker secret create db_password -

# Создать секрет из файла
docker secret create api_key ./api_key.txt

# Список секретов
docker secret ls

# Удалить секрет
docker secret rm db_password
```

#### Конфигурации

```sh
# Создать конфигурацию
docker config create app_config ./config.yaml

# Список конфигураций
docker config ls

# Удалить конфигурацию
docker config rm app_config
```

Подробное руководство — в **[swarm_secrets_configs.md](./swarm_secrets_configs.md)**.

### Отладка и диагностика

#### Информация о кластере

```sh
# Информация о Swarm
docker info | grep -A 10 "Swarm"

# Версия Docker
docker version

# Статус кластера
docker node ls
```

#### Проверка связности

```sh
# Проверка DNS (из контейнера)
docker run --rm alpine nslookup <SERVICE_NAME>

# Проверка сети
docker run --rm alpine ping <SERVICE_NAME>
```

#### Журналы

```sh
# Журналы сервиса
docker service logs --follow <SERVICE>

# Журналы с timestamp
docker service logs --timestamps <SERVICE>

# Последние N строк
docker service logs --tail 100 <SERVICE>
```

## Дополнительная информация

### Сводная таблица команд

| Задача | Команда |
|---|---|
| Инициализация | `docker swarm init` |
| Присоединение | `docker swarm join --token <TOKEN> <IP>:2377` |
| Список узлов | `docker node ls` |
| Список сервисов | `docker service ls` |
| Масштабирование | `docker service scale <svc>=<N>` |
| Обновление | `docker service update --image <img> <svc>` |
| Деплой стека | `docker stack deploy -c <file> <name>` |
| Журналы | `docker service logs <svc>` |

### Связанные документы

- **Обзор Docker Swarm** — **[docker_swarm_overview.md](./docker_swarm_overview.md)**
- **Основные концепции** — **[swarm_core_concepts.md](./swarm_core_concepts.md)**
- **Секреты и конфигурации** — **[swarm_secrets_configs.md](./swarm_secrets_configs.md)**
- **Продвинутые темы** — **[swarm_advanced_topics.md](./swarm_advanced_topics.md)**
- **Настройка CI/CD** — **[CI_CD/swarm_setup.md](./CI_CD/swarm_setup.md)**
