# Управление зависимостями и готовностью в Podman

## Определения

**Зависимости контейнеров** — порядок запуска и связи между компонентами приложения (например, бэкенд требует запущенной БД).

**Готовность сервиса (Readiness)** — состояние приложения внутри контейнера, когда оно не просто запущено как процесс, но и готово принимать входящие соединения (например, база данных завершила инициализацию).

**Notify=healthy** — параметр Quadlet/systemd, который позволяет системе инициализации считать сервис запущенным только после того, как его внутренний **Healthcheck** вернет статус `healthy`.

## Основные концепции

### Проблема "Запущен ≠ Готов"

В Podman (как и в Docker) запуск контейнера происходит почти мгновенно, но сервисы внутри (PostgreSQL, Java-приложения) требуют времени на инициализацию.
- `podman run` завершается, как только процесс стартовал.
- Зависимый сервис может упасть с ошибкой подключения, если попытается соединиться слишком рано.

### Разница с Docker Compose

В Docker Compose директива `depends_on` управляет только **порядком запуска**. В нативном Podman (CLI) прямого аналога этой директивы нет. Управление зависимостями делегируется либо логике приложения, либо системному менеджеру (**systemd**).

## Методы обеспечения связности (Connectivity)

Прежде чем ждать готовности, нужно обеспечить видимость контейнеров.

### 1. Через пользовательские сети
Контейнеры общаются по именам через встроенный DNS-резолвер (**Aardvark**).
```bash
podman network create mynet
podman run -d --name db --network mynet ...
podman run --network mynet app-image  # обращение к 'db:5432'
```

### 2. Через Поды (Pod)
Все контейнеры в поде разделяют `localhost`.
```bash
podman pod create --name mypod
podman run -d --pod mypod --name db ...
podman run --pod mypod app-image      # обращение к 'localhost:5432'
```
*Важно: Внутри пода обращение по именам сервисов через DNS не работает, используется только localhost.*

## Методы обеспечения готовности

### 1. Скрипты ожидания (Wait-logic)
Простейший способ — цикл в `entrypoint` или команде запуска.
```bash
# Пример использования pg_isready внутри пода
podman run --rm --pod mypod postgres \
  sh -c 'until pg_isready -h localhost -p 5432; do sleep 1; done; echo "DB is ready!"'
```
Этот метод универсален, но создает "засорение" команд запуска.

### 2. Интеграция с systemd и Quadlet (Рекомендуется)
Использование параметров `Requires`, `After` и механизма уведомлений о здоровье.

**Схема работы:**
1. systemd запускает `db.service`.
2. Podman выполняет `HealthCmd`.
3. При статусе `healthy` Podman отправляет сигнал в systemd.
4. systemd считает `db.service` активным и запускает `app.service`.

#### Пример конфигурации Quadlet

**db.container**
```ini
[Unit]
Description=Database with Healthcheck

[Container]
Image=docker.io/library/postgres:16
Environment=POSTGRES_PASSWORD=secret
HealthCmd=pg_isready -U postgres
HealthInterval=5s
HealthRetries=5
# Ключевой параметр для связки со статусом сервиса
Notify=healthy

[Install]
WantedBy=multi-user.target
```

**app.container**
```ini
[Unit]
Description=Application depends on DB
Requires=db.service
After=db.service

[Container]
Image=docker.io/library/my-app:latest
# Несмотря на зависимости в systemd, рекомендуется сохранять 
# легкую проверку готовности в самом приложении
```

## Практические рекомендации

1. **Иерархия контроля**:
   - **systemd** управляет порядком запуска (Start Order).
   - **Healthcheck** проверяет реальное состояние (Status).
   - **Приложение** должно уметь ждать зависимости (Resilience).
2. **Используйте Pods для тесной связности**: Если сервисы всегда запускаются вместе и делят ресурсы, объединяйте их в Pod.
3. **Notify=healthy — стандарт для продакшена**: Это наиболее "чистый" способ реализации `depends_on` в экосистеме Podman.

## Дополнительная информация

### См. также
- **[Поды в Podman](./podman_pods.md)** — общая сеть и ресурсы.
- **[Проверки состояния (Healthcheck)](./podman_healthchecks.md)** — настройка команд проверки.
- **[Миграция с Docker](./migration-from-docker.md)** — переход с Compose на Quadlet.
- **[Podman Compose](./podman-compose.md)** — как работает `depends_on` в Compose-файлах.
