# Поды в Podman

## Определения

**Под (Pod)** — это группа из одного или нескольких контейнеров, разделяющих общие ресурсы (сеть, IPC, пространства имен PID). Эта концепция заимствована из Kubernetes и позволяет группировать тесно связанные сервисы в единую логическую единицу.

**Infra-контейнер** — служебный контейнер (по умолчанию `pause`), который удерживает пространства имен (namespaces) открытыми, даже если основные контейнеры пода остановлены. Он является "фундаментом" пода.

## Основные концепции

### Сетевая модель: localhost

Ключевое преимущество пода — общая сеть. Все контейнеры внутри одного пода видят друг друга через **`localhost`**.

- Нет необходимости создавать пользовательские сети (`podman network create`).
- Нет необходимости обращаться к контейнерам по их именам через DNS.
- Порты пробрасываются (publish) на уровне всего пода, а не отдельных контейнеров.

### Совместное использование ресурсов

Контейнеры в поде разделяют:

- **Network namespace**: общий IP-адрес и порты.
- **IPC namespace**: обмен данными через разделяемую память (shared memory).
- **UTS namespace**: общее имя хоста (hostname).
- **PID namespace** (опционально): контейнеры могут видеть процессы друг друга при включении флага `--share pid`.

### Жизненный цикл

- При создании пода создается infra-контейнер.
- Остановка пода останавливает все контейнеры внутри него.
- Удаление пода удаляет все связанные с ним контейнеры.

## Практические сценарии

### 1. Создание пода и запуск контейнеров через CLI

Пример запуска базы данных PostgreSQL и инструмента проверки её готовности (`pg_isready`) в одном поде.

```bash
# Создание пода с пробросом порта
podman pod create --name my-db-pod -p 5432:5432

# Запуск контейнера БД внутри пода
podman run -d --pod my-db-pod --name db -e POSTGRES_PASSWORD=secret postgres

# Проверка готовности (обращение через localhost внутри пода)
podman run --rm --pod my-db-pod postgres pg_isready -h localhost -p 5432
# → localhost:5432 - accepting connections
```

### 2. Управление через Quadlet (systemd)

Для надежного запуска в production рекомендуется использовать Quadlet-юниты типа `.pod`.

**Файл:** `/etc/containers/systemd/app.pod`

```ini
[Unit]
Description=Application Pod
[Pod]
PodName=mypod
PublishPort=8080:8080
PublishPort=5432:5432
[Install]
WantedBy=multi-user.target
```

**Файл:** `/etc/containers/systemd/db.container`

```ini
[Unit]
Description=Database Container
[Container]
Pod=app.pod
Image=postgres
Environment=POSTGRES_PASSWORD=secret
```

### 3. Интеграция с Kubernetes

Podman позволяет экспортировать поды в Kubernetes-манифесты и запускать их обратно.

```bash
# Генерация YAML манифеста из существующего пода (Podman 4.3+)
podman kube generate my-db-pod > my-db.yaml

# Запуск пода из Kubernetes манифеста
podman kube play my-db.yaml
```

> **Примечание:** В версиях Podman до 4.3 использовались команды `podman generate kube` и `podman play kube`. Сейчас они считаются устаревшими (deprecated) в пользу группы команд `podman kube`.

## Дополнительная информация

### Управление зависимостями

Podman не управляет порядком запуска контейнеров внутри пода автоматически. Если бэкенд зависит от БД, необходимо реализовать проверку готовности.

- **Wait-логика**: использование скриптов в `entrypoint` (например, `wait-for-it.sh`).
- **Healthchecks + systemd**: использование `Notify=healthy` в Quadlet.

Подробнее: **[Управление зависимостями и готовностью](./podman-dependencies.md)**.

### Нюансы и ограничения

- **Конфликты портов**: если два контейнера в одном поде попытаются занять один и тот же порт, возникнет ошибка.
- **Resource Limits**: лимиты ресурсов (CPU, Memory) могут применяться как к отдельным контейнерам, так и к поду в целом.
- **Daemonless**: поды работают без центрального демона, управление осуществляется через процессы `conmon`. Подробнее: **[Daemonless архитектура](./podman_daemonless_architecture.md)**.

### См. также

- **[Healthchecks в Podman](./podman_healthchecks.md)** — механизмы проверки состояния.
- **[Миграция с Docker](./migration-from-docker.md)** — замена Docker Compose на поды.
- **[Podman Compose](./podman-compose.md)** — использование Compose-файлов для управления подами.
