# Проверки состояния (Healthcheck) в Podman

## Определения

**Healthcheck (Проверка состояния)** — встроенный механизм мониторинга работоспособности приложения внутри контейнера. В Podman выполнение проверок делегируется монитору `conmon` или системе инициализации **systemd**.

**Startup Healthcheck (Проверка при запуске)** — (введено в Podman 5.0) выделенная фаза проверки для приложений с длительной инициализацией. Позволяет использовать отдельную команду и интервал для этапа старта, предотвращая ложные срабатывания основного цикла.

**Liveness Healthcheck** — основной цикл проверки, который выполняется на протяжении всей жизни контейнера после успешного завершения фазы старта.

**Health Failure Action** — действие, которое Podman автоматически предпринимает при переходе контейнера в статус `unhealthy` (например, перезапуск или остановка).

**Notify=healthy** — параметр интеграции с **systemd** (Quadlet), позволяющий считать сервис успешно запущенным только после того, как внутренняя проверка вернет статус `healthy`.

---

## Основные концепции

### Специфика Podman и OCI
В отличие от Docker, где проверки управляются центральным демоном, в Podman архитектура **daemonless** накладывает свои особенности:
1. **OCI Format**: Стандарт OCI по умолчанию не поддерживает метаданные проверок внутри образа. Podman рекомендует описывать проверки в рантайме (CLI/Quadlet).
2. **Исполнение**: Проверки запускаются процессом `conmon`. Это означает, что даже при выключенном терминале или отсутствии активного соединения, проверки продолжают работать.
3. **Локальность**: Команда проверки выполняется внутри пространства имен (namespace) контейнера. Она имеет доступ к тому же сетевому стеку и файловой системе, что и приложение.

### Жизненный цикл проверки
С выходом Podman 5.x жизненный цикл разделен на два этапа:
1. **Startup Phase**: Выполняется `health-startup-cmd`. Если она проходит успешно `N` раз (параметр `success`), контейнер переходит в основную фазу.
2. **Steady State**: Выполняется основная `health-cmd`. Если количество неудач подряд превышает `retries`, срабатывает `on-failure` действие.

---

## Практические сценарии

### 1. Настройка через CLI (Podman 5.x+)
Пример для тяжелого Java-приложения, которое требует времени на прогрев и должно автоматически перезапускаться при сбое.

```bash
podman run -d \
  --name app-server \
  # Фаза старта (Startup)
  --health-startup-cmd="curl -f http://localhost:8080/ready || exit 1" \
  --health-startup-interval=5s \
  --health-startup-retries=12 \
  --health-startup-success=1 \
  # Основная фаза (Liveness)
  --health-cmd="curl -f http://localhost:8080/live || exit 1" \
  --health-interval=30s \
  --health-retries=3 \
  # Реакция на сбой
  --health-on-failure=restart \
  my-app-image
```

### 2. Использование в Quadlet (Production стандарт)
Декларативное описание в systemd-юните обеспечивает максимальную надежность.

**Файл:** `/etc/containers/systemd/api.container`
```ini
[Unit]
Description=API Service with Advanced Healthcheck
After=network-online.target

[Container]
Image=registry.example.com/api:latest
PublishPort=8080:8080

# Конфигурация Healthcheck
HealthCmd=curl -f http://localhost/health || exit 1
HealthInterval=30s
HealthRetries=3
HealthOnFailure=restart

# Интеграция с зависимостями systemd
Notify=healthy

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### 3. Работа в Rootless режиме
В rootless режиме Podman использует `slirp4netns` или `pasta` для сети. Healthcheck, выполняющий `curl http://localhost`, работает корректно, так как запускается внутри сетевого неймспейса контейнера, где `localhost` указывает на сам контейнер.

---

## Управление и диагностика

### Инспекция состояния
Podman хранит историю последних проверок. По умолчанию сохраняется только последняя, но это можно изменить.

```bash
# Просмотр статуса здоровья и последних логов
podman inspect app-server --format '{{json .State.Health}}' | jq

# Изменение параметров на лету (Podman 5.x)
podman update --health-interval=10s --health-max-log-count=5 app-server
```

### Ручной запуск и отладка
```bash
# Принудительное выполнение проверки прямо сейчас
podman healthcheck run app-server

# Мониторинг событий изменения статуса
podman events --filter event=health_status
# → 2026-07-27 ... container health_status app-server (status=unhealthy)
```

---

## Нюансы и ограничения

- **Отсутствие утилит в образе**: Если в образе (например, Distroless) нет `curl` или `wget`, используйте встроенные средства языка (например, скрипт на Python/Go) или соберите кастомную утилиту проверки.
- **Нагрузка на ресурсы**: Каждая проверка порождает новый процесс через `conmon`. При сотнях контейнеров с интервалом в `1s` это может вызвать значительную нагрузку на CPU.
- **Безопасность**: Команда проверки запускается от того же пользователя, что и основной процесс контейнера. Не используйте в `HealthCmd` команды, требующие повышения привилегий через `sudo`.
- **Healthcheck ≠ LivenessProbe (K8s)**: Хотя концепции похожи, механизмы Podman ориентированы на автономную работу или интеграцию с systemd, а не на глобальный планировщик.

---

## Дополнительная информация

### Связанные разделы
- **[Автообновление и откат](./podman_auto_update.md)** — использование Healthcheck для автоматического Rollback при неудачном обновлении.
- **[Управление зависимостями](./podman-dependencies.md)** — как `Notify=healthy` позволяет сервисам ждать готовности друг друга.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — роль `conmon` в жизненном цикле контейнера.

### Ссылки
- **[Podman Run Documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html)** (англ.) — официальный справочник по флагам `--health-*`.
- **[Quadlet upstream documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** (англ.) — параметры секции `[Container]`.
