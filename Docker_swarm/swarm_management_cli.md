# Docker Swarm: Справочник CLI

## Определения

**CLI** — основной инструмент Docker для управления Swarm-кластером. Все операции выполняются через подкоманды `docker`.

**Контекст выполнения** — область действия команд; большинство операций по управлению кластером (`node`, `service`, `stack`) доступны только на узлах с ролью менеджера.

## Базовые концепции

### Иерархия команд

Команды управления Swarm организованы по уровням абстракции:

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
- **Дистанционное управление:** Для управления кластером с локальной машины рекомендуется использовать **[docker context](../Docker/docker_context.md)** (проброс SSH на менеджер).

## Практические сценарии

### Инициализация и расширение кластера

#### Создание Swarm-кластера

```bash
# Инициализация первого менеджера
docker swarm init --advertise-addr <MANAGER-IP>
# → Swarm initialized: current node (<ID>) is now a manager.

# Настройка автоблокировки (защита ключей шифрования при перезагрузке)
docker swarm update --autolock=true
# → (выводит ключ разблокировки)
```

**Ключевые параметры:**
- `--advertise-addr` — IP-адрес для связи между узлами (обязателен, если интерфейсов несколько).
- `--data-path-addr` — адрес для трафика оверлейных сетей (отделение управляющего трафика от прикладного).
- `--listen-addr` — адрес и порт, которые слушает демон Swarm (по умолчанию `:2377`).

#### Управление безопасностью кластера

```bash
# Разблокировка узла после перезагрузки демона (если включен autolock)
docker swarm unlock
# → Please enter unlock key:

# Просмотр и ротация сертификатов CA
docker swarm ca --rotate
# → (инициирует обновление сертификатов всех узлов)
```

#### Присоединение узлов

```bash
# Получение команды с токеном для рабочих узлов (workers)
docker swarm join-token worker
# → docker swarm join --token SWMTKN-1-... <IP>:2377

# Получение команды с токеном для менеджеров
docker swarm join-token manager
# → docker swarm join --token SWMTKN-1-... <IP>:2377

# Выполнение на целевом узле
docker swarm join --token <TOKEN> <MANAGER-IP>:2377
# → This node joined a swarm as a worker.
```

#### Вывод узлов из кластера

```bash
# На рабочем узле (добровольный выход)
docker swarm leave
# → Node left the swarm.

# На менеджере (требует принудительного подтверждения)
docker swarm leave --force
# → Node left the swarm.

# Удаление записи об узле из списка кластера (на менеджере)
docker node rm <NODE-ID>
# → <NODE-ID>
```

### Управление узлами кластера

#### Информация об узлах

```bash
# Список всех узлов в кластере
docker node ls
# → ID            HOSTNAME  STATUS  AVAILABILITY  MANAGER STATUS  ENGINE VERSION
# → abc123def *   node-1    Ready   Active        Leader          27.1.1

# Фильтрация и вывод определенных полей (удобно для скриптов)
docker node ls --format "{{.Hostname}}: {{.Status}}"
# → node-1: Ready

# Детальные данные об узле в читаемом формате
docker node inspect --pretty <NODE-ID>
```

#### Изменение ролей и статусов

```bash
# Повышение рабочего узла до менеджера
docker node promote <NODE-ID>
# → Node <NODE-ID> promoted to a manager.

# Понижение менеджера до рабочего узла
docker node demote <NODE-ID>
# → Node <NODE-ID> demoted to a worker.

# Перевод узла в режим обслуживания (drain)
docker node update --availability drain <NODE-ID>
# → <NODE-ID>
```

### Управление сервисами Swarm

#### Создание и конфигурация

```bash
# Базовый запуск сервиса
docker service create --name web --replicas 3 nginx:1.26.3
# → <SERVICE-ID>

# Запуск с публикацией портов (Routing Mesh)
docker service create --name web --publish 80:80 --replicas 3 nginx:1.26.3

# Ограничение ресурсов и Health Check
docker service create --name app \
  --reserve-memory 512m \
  --limit-memory 1g \
  --health-cmd "curl -f http://localhost/health || exit 1" \
  --health-interval 30s \
  myapp:latest
```

#### Мониторинг и масштабирование

```bash
# Список активных сервисов
docker service ls
# → ID            NAME    MODE        REPLICAS  IMAGE         PORTS
# → xyz789        web     replicated  3/3       nginx:1.26.3  *:80->80/tcp

# Проверка распределения реплик и причин сбоев
docker service ps --no-trunc web
# → (выводит полный текст ошибок, если задача не запустилась)

# Просмотр логов (агрегированных)
docker service logs -f --tail 100 web

# Масштабирование
docker service scale web=10
# → web scaled to 10
```

#### Обновление и откат

```bash
# Обновление образа и стратегии отката
docker service update \
  --image myapp:v2 \
  --update-parallelism 2 \
  --update-delay 10s \
  --rollback-parallelism 2 \
  --rollback-monitor 30s \
  my-service

# Быстрый откат
docker service rollback my-service
# → my-service
```

### Работа со стеками (Stacks)

```bash
# Развертывание или обновление стека
docker stack deploy -c docker-compose.yml myapp
# → Creating service myapp_web
# → Creating service myapp_db

# Просмотр состояния стека
docker stack services myapp
# → ID            NAME        MODE        REPLICAS  IMAGE
# → 123           myapp_web   replicated  2/2       nginx:latest
```

### Сетевое взаимодействие

```bash
# Создание оверлейной сети с поддержкой подключения внешних контейнеров
docker network create --driver=overlay --attachable my-network
# → <NETWORK-ID>

# Создание зашифрованной сети
docker network create --driver=overlay --opt encrypted secure-net
```

### Управление секретами и конфигурациями

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt
# → <SECRET-ID>

# Передача секрета существующему сервису
docker service update --secret-add db_password my-service
```

## Дополнительная информация

### Диагностика кластера

| Задача | Команда |
|---|---|
| Статус Swarm на текущем узле | `docker info \| grep Swarm` |
| Поиск ошибок планировщика | `docker service ps --no-trunc <svc>` |
| Просмотр версии и API | `docker version` |
| Проверка использования ресурсов | `docker stats` (на конкретном узле) |

### Смотрите также

- **[Основные концепции Docker Swarm](./swarm_core_concepts.md)**
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)**
