# Docker Swarm: Справочник CLI

## Определения

**CLI (Command Line Interface, интерфейс командной строки)** — основной инструмент Docker для управления Swarm-кластером. Все операции выполняются через подкоманды `docker`.

**Контекст выполнения (Manager CLI context)** — область действия команд; большинство операций по управлению кластером (node, service, stack) доступны только на узлах с ролью менеджера.

## Базовые концепции

### Иерахия команд

Команды управления Swarm организованы логически по уровням абстракции:

| Уровень | Команда | Назначение |
|---|---|---|
| Кластер | `docker swarm` | Инициализация, присоединение и настройка параметров кластера |
| Узлы | `docker node` | Управление жизненным циклом узлов (роли, статусы, удаление) |
| Сервисы | `docker service` | Создание, масштабирование и обновление отдельных сервисов |
| Стеки | `docker stack` | Развертывание многоконтейнерных приложений (stacks) |
| Сети | `docker network` | Управление оверлейными сетями (overlay networks) |
| Секреты | `docker secret` | Управление чувствительными данными |
| Конфигурации | `docker config` | Управление файлами конфигураций |

### Требования к правам доступа

- **Роль менеджера:** Команды `swarm`, `node`, `secret`, `config` и `stack` требуют выполнения на узле-менеджере.
- **Любой узел:** Команды `service ps` или `network inspect` доступны для чтения на всех узлах (при наличии прав на Docker socket).
- **Дистанционное управление:** Для управления кластером с локальной машины рекомендуется использовать `docker context` (проброс SSH на менеджер).

## Практические сценарии

### Инициализация и расширение кластера

#### Создание Swarm-кластера

```bash
# Инициализация первого менеджера
docker swarm init --advertise-addr <MANAGER-IP>
```

**Ключевые параметры:**

- `--advertise-addr` — IP-адрес, который будет анонсирован другим узлам для связи (обязателен, если у хоста несколько интерфейсов).
- `--listen-addr` — адрес и порт, которые слушает демон Swarm (по умолчанию `:2377`).

#### Присоединение узлов

```bash
# Получение команды с токеном для рабочих узлов (workers)
docker swarm join-token worker

# Получение команды с токеном для менеджеров
docker swarm join-token manager

# Выполнение на целевом узле
docker swarm join --token <TOKEN> <MANAGER-IP>:2377
```

#### Вывод узлов из кластера

```bash
# На рабочем узле (добровольный выход)
docker swarm leave

# На менеджере (требует принудительного подтверждения)
docker swarm leave --force

# Удаление записи об узле из списка кластера (на менеджере)
docker node rm <NODE-ID>
```

### Управление узлами кластера

#### Информация об узлах

```bash
# Список всех узлов в кластере
docker node ls

# Детальные данные об узле в читаемом формате
docker node inspect --pretty <NODE-ID>

# Список задач (контейнеров), запущенных на конкретном узле
docker node ps <NODE-ID>
```

#### Изменение ролей и статусов

```bash
# Повышение рабочего узла до менеджера
docker node promote <NODE-ID>

# Понижение менеджера до рабочего узла
docker node demote <NODE-ID>

# Перевод узла в режим обслуживания (задачи будут перенесены)
docker node update --availability drain <NODE-ID>

# Возврат узла в активное состояние
docker node update --availability active <NODE-ID>
```

### Управление сервисами Swarm

#### Создание и конфигурация

```bash
# Базовый запуск сервиса
docker service create --name web --replicas 3 nginx:1.26.3

# Запуск с публикацией портов (Routing Mesh)
docker service create --name web --publish 80:80 --replicas 3 nginx:1.26.3

# Ограничение ресурсов
docker service create --name app \
  --reserve-memory 512m \
  --limit-memory 1g \
  --reserve-cpu 0.5 \
  --limit-cpu 1.0 \
  myapp:latest

# Установка ограничений размещения (placement constraints)
docker service create --name db \
  --constraint 'node.labels.type == database' \
  postgres:15
```

#### Мониторинг и масштабирование

```bash
# Список активных сервисов
docker service ls

# Проверка распределения реплик по узлам
docker service ps <SERVICE_NAME>

# Просмотр логов сервиса (агрегированных со всех реплик)
docker service logs -f <SERVICE_NAME>

# Масштабирование (изменение количества реплик)
docker service scale web=10
```

#### Обновление и откат (Rolling Update)

```bash
# Обновить образ сервиса
docker service update --image nginx:1.27 web

# Обновление с контролем процесса
docker service update \
  --image myapp:v2 \
  --update-parallelism 2 \
  --update-delay 10s \
  --update-failure-action rollback \
  my-service

# Быстрый откат к предыдущей конфигурации
docker service rollback my-service
```

### Работа со стеками (Stacks)

Стеки позволяют развертывать приложения на основе файлов `docker-compose.yml`.

```bash
# Развертывание или обновление стека
docker stack deploy -c docker-compose.yml myapp

# Просмотр состояния стека
docker stack ls
docker stack services myapp

# Удаление всего стека (сервисов и сетей)
docker stack rm myapp
```

### Сетевое взаимодействие

Подробности реализации оверлейных сетей в **[swarm_networking.md](./swarm_networking.md)**.

```bash
# Создание сети для межхостового взаимодействия
docker network create --driver=overlay my-network

# Создание зашифрованной сети (IPsec)
docker network create --driver=overlay --opt encrypted secure-net
```

### Управление секретами и конфигурациями

Подробное руководство — в **[swarm_secrets_configs.md](./swarm_secrets_configs.md)**.

```bash
# Создание секрета
echo "password123" | docker secret create db_password -

# Создание конфигурации из файла
docker config create app_conf ./config.yaml
```

## Дополнительная информация

### Диагностика кластера

| Задача | Команда |
|---|---|
| Статус Swarm на текущем узле | `docker info \| grep Swarm` |
| Поиск ошибок планировщика | `docker service ps --no-trunc <svc>` |
| Проверка событий кластера | `docker events --filter type=node` |
| Просмотр версии и API | `docker version` |

### Смотрите также

- **[Основные концепции Docker Swarm](./swarm_core_concepts.md)**
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)**
