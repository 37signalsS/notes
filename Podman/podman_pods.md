# Поды (Pods) в Podman

## Определения

**Pod (под)** — это группа из одного или нескольких контейнеров, разделяющих общие ресурсы (сеть, IPC, пространства имен PID). Эта концепция заимствована из Kubernetes и позволяет группировать тесно связанные сервисы.

**Infra-контейнер** — служебный контейнер (по умолчанию `pause`), который удерживает пространства имен (namespaces) открытыми, даже если основные контейнеры пода остановлены.

## Основные концепции

### Сетевая модель: localhost

Ключевое преимущество пода — общая сеть. Все контейнеры внутри одного пода видят друг друга через **`localhost`**.

- Нет необходимости создавать пользовательские сети (`podman network create`).
- Нет необходимости обращаться к контейнерам по их именам.
- Порты пробрасываются (publish) на уровне всего пода, а не отдельных контейнеров.

### Совместное использование ресурсов

Контейнеры в поде разделяют:

- **Network namespace**: общий IP-адрес и порты.
- **IPC namespace**: обмен данными через разделяемую память.
- **UTS namespace**: общее имя хоста.
- **PID namespace** (опционально): контейнеры могут видеть процессы друг друга.

## Практические сценарии

### 1. Создание пода через CLI

Допустим, нам нужно запустить базу данных PostgreSQL и инструмент проверки готовности (`pg_isready`) в одном поде.

```bash
# 1. Создаем под и пробрасываем порт базы данных
podman pod create --name my-db-pod -p 5432:5432

# 2. Запускаем контейнер с БД внутри пода
podman run -d --pod my-db-pod --name db -e POSTGRES_PASSWORD=secret postgres

# 3. Запускаем проверку готовности (обращаемся через localhost)
podman run --rm --pod my-db-pod postgres pg_isready -h localhost -p 5432
# → localhost:5432 - accepting connections
```

### 2. Управление через Quadlet (systemd)

Для надежного запуска групп контейнеров рекомендуется использовать Quadlet-юниты типа `.pod`.

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

## Управление зависимостями

Важно понимать: **Podman не управляет порядком запуска контейнеров внутри пода автоматически.** Если одно приложение зависит от готовности другого (например, бэкенд от БД), ответственность за ожидание лежит на вас.

**Методы решения:**

1. **Wait-логика**: использование скриптов (`wait-for-it.sh`) или циклов проверки в `entrypoint`.
2. **Healthchecks + systemd**: использование `Notify=healthy` для координации запуска сервисов.

Подробнее о реализации зависимостей: **[Зависимости и Healthchecks в Podman](./podman_healthchecks.md#зависимости-через-notifyhealthy)**.

## Дополнительная информация

### Нюансы

- **Порты**: Если два контейнера в одном поде попытаются занять один и тот же порт (например, 80), возникнет конфликт.
- **Остановка**: При остановке пода останавливаются все входящие в него контейнеры.
- **Kubernetes**: Поды в Podman можно экспортировать в манифесты Kubernetes с помощью `podman generate kube`.

### См. также

- **[Healthchecks в Podman](./podman_healthchecks.md)** — проверка готовности сервисов.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — как работают процессы `conmon` в подах.
- **[Миграция с Docker](./migration-from-docker.md)** — замена Docker Compose на поды и Quadlet.
