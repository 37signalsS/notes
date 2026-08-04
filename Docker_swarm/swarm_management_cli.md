# Docker Swarm: Справочник CLI

## Определения

**CLI (Command Line Interface)** — основной инструмент Docker для управления Swarm-кластером. Все операции по оркестрации выполняются через подкоманды `docker`.

**Контекст исполнения** — область действия команд. Большинство операций по изменению состояния кластера (`node`, `service`, `stack`, `secret`, `config`) доступны только на узлах с ролью менеджера.

## Базовые концепции

### Иерархия команд

Команды управления Swarm организованы по уровням абстракции:

| Уровень | Команда | Назначение |
|---|---|---|
| Кластер | `docker swarm` | Инициализация, присоединение и глобальные настройки (CA, автоблокировка) |
| Узлы | `docker node` | Управление жизненным циклом узлов, их ролями и метками |
| Сервисы | `docker service` | Декларативное управление отдельными сервисами кластера |
| Стеки | `docker stack` | Оркестрация многоконтейнерных приложений через Compose-файлы |
| Сети | `docker network` | Управление оверлейными сетями кластера |
| Секреты | `docker secret` | Безопасное хранение чувствительных данных в Raft |
| Конфигурации | `docker config` | Управление нечувствительными данными (nginx.conf и др.) |

### Требования к правам доступа

- **Менеджеры:** Полный доступ ко всем командам управления кластером.
- **Рабочие узлы:** Могут выполнять локальные команды (например, `docker info`), но не имеют доступа к управлению сервисами или другими узлами.
- **Любой узел:** Команды `service ps` или `network inspect` технически могут быть выполнены на любом узле, если у пользователя есть права на Docker socket, но полный статус кластера виден только менеджерам.
- **Дистанционное управление:** Рекомендуется использовать `docker context` через SSH для безопасного доступа к API удаленного менеджера без открытия портов вовне.

## Практические сценарии

### Управление кластером (docker swarm)

#### Инициализация и настройка

```bash
# Инициализация первого менеджера
docker swarm init \
  --advertise-addr 192.168.1.10 \
  --data-path-addr 10.0.0.1 \
  --listen-addr 0.0.0.0:2377
# → Swarm initialized: current node (abc123def) is now a manager.
```

**Ключевые параметры:**
- `--advertise-addr` — адрес, который узел сообщает другим участникам для связи (обязателен при наличии нескольких интерфейсов).
- `--data-path-addr` — IP-адрес для VXLAN-трафика (позволяет отделить трафик данных приложений от трафика управления Raft).
- `--listen-addr` — интерфейс и порт, на котором демон слушает входящие запросы Swarm.

#### Управление безопасностью и сертификатами

```bash
# Включение автоблокировки (защита данных Raft при перезагрузке)
docker swarm update --autolock=true
# → SMTKN-1-v3q... (этот ключ необходим для запуска демона после перезагрузки)

# Разблокировка узла после перезагрузки
docker swarm unlock
# → Please enter unlock key:

# Ротация сертификатов CA кластера (обновление всех TLS-сертификатов)
docker swarm ca --rotate --cert-expiry 2160h
# → (инициирует постепенное обновление сертификатов на всех узлах)
```

#### Присоединение узлов

```bash
# Получение токена для новых рабочих узлов
docker swarm join-token worker
# → docker swarm join --token SWMTKN-1-49nj1... 192.168.1.10:2377

# Получение токена для новых менеджеров
docker swarm join-token manager
# → docker swarm join --token SWMTKN-1-58mk2... 192.168.1.10:2377

# Присоединение (выполняется на целевом узле)
docker swarm join --token <TOKEN> 192.168.1.10:2377
# → This node joined a swarm as a worker.
```

### Управление узлами (docker node)

#### Мониторинг и инспекция

```bash
# Список всех узлов с фильтрацией по статусу
docker node ls --filter "role=manager"
# → ID            HOSTNAME  STATUS  AVAILABILITY  MANAGER STATUS  ENGINE VERSION
# → abc123def *   node-1    Ready   Active        Leader          27.1.1

# Форматированный вывод (удобно для скриптов)
docker node ls --format "{{.Hostname}}: {{.Status}}"
# → node-1: Ready

# Детальная информация в читаемом виде
docker node inspect --pretty <NODE_ID>
# → ID: abc123def...
# → Hostname: node-1
# → Status: State: Ready, Availability: Active
```

#### Изменение состояния и ролей

```bash
# Повышение рабочего узла до менеджера
docker node promote worker-1
# → Node worker-1 promoted to a manager.

# Перевод узла в режим обслуживания (Drain)
docker node update --availability drain worker-1
# → worker-1
# Пояснение: все задачи на этом узле будут остановлены и пересозданы на других доступных узлах.
```

### Управление сервисами (docker service)

#### Создание и отладка

```bash
# Создание сервиса с лимитами и Health Check
docker service create --name api \
  --replicas 3 \
  --reserve-memory 256m --limit-memory 512m \
  --health-cmd "curl -f http://localhost/health || exit 1" \
  myapp:v1
# → xyz789...

# Поиск причин падения задач (флаг --no-trunc показывает полную ошибку)
docker service ps --no-trunc api
# → (выводит детали, например: "non-zero exit code 139" или "No such image")

# Просмотр логов
# -f: следовать за логом (follow)
# --tail 100: показать последние 100 строк
docker service logs -f --tail 100 api
```

#### Масштабирование и обновление

```bash
# Инспекция статуса обновления (Go-template для JSON)
docker service inspect --format '{{json .UpdateStatus}}' api | jq
# → { "State": "completed", "StartedAt": "...", "CompletedAt": "..." }

# Обновление с контролем параллелизма
docker service update --image myapp:v2 --update-parallelism 2 api
# → api
```

### Работа со стеками (docker stack)

```bash
# Развертывание стека
# --with-registry-auth: передает данные аутентификации из локального Docker-клиента 
# на все узлы Swarm (необходимо для скачивания образов из частных реестров).
docker stack deploy -c docker-compose.yml --with-registry-auth prod_stack
# → Creating network prod_stack_default
# → Creating service prod_stack_web

# Список сервисов в стеке
docker stack services prod_stack
# → ID            NAME             MODE        REPLICAS  IMAGE
# → 123           prod_stack_web   replicated  2/2       nginx:latest
```

### Секреты и конфигурации (docker secret/config)

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt
# → abc456...

# Список секретов с фильтром по метке
docker secret ls --filter "label=env=prod"
# → ID      NAME           DRIVER    CREATED    UPDATED
```

## Дополнительная информация

### Продвинутая диагностика через CLI

| Задача | Команда |
|---|---|
| Статус Swarm на текущем узле | `docker info --format '{{json .Swarm}}'` |
| Проверка кворума Raft | `docker info --format '{{json .Swarm.RemoteManagers}}'` |
| Детальный аудит узла | `docker node inspect <NODE_ID> --format '{{json .Status}}'` |
| Ошибки планировщика | `docker service ps --no-trunc <SERVICE> --filter "desired-state=shutdown"` |

### Полезные флаги фильтрации (`--filter`)

- `id`: Поиск по точному ID или префиксу.
- `label`: Поиск по метаданным (например, `label=app=web`).
- `name`: Поиск по части имени.
- `role`: Фильтрация узлов по роли (`manager` или `worker`).

### Смотрите также

- **[Основные концепции Docker Swarm](./swarm_core_concepts.md)** — теория Raft, кворум и жизненный цикл задач.
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)** — управление через `docker network`.
- **[Секреты и конфигурации](./swarm_secrets_configs.md)** — подробности управления данными.
- **[Развертывание стеков](./swarm_stack_deployment.md)** — детальное использование `docker stack`.
