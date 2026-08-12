# Проверки состояния (Healthcheck) в Podman

## Определения

**Healthcheck (Проверка состояния)** — встроенный механизм мониторинга работоспособности приложения внутри контейнера. В Podman выполнение проверок делегируется монитору `conmon` или системе инициализации **systemd** (через Quadlet).

**Startup Healthcheck (Проверка при запуске)** — (введено в Podman 5.0, расширено в 6.x) фаза «входного контроля» для приложений с длительной инициализацией. Является блокирующим механизмом (Gate): основной цикл проверок не начнется, пока фаза старта не завершится успешно.

**Liveness Healthcheck** — основной цикл проверки, выполняемый на протяжении всей жизни контейнера после успешного завершения Startup-фазы.

**Health Failure Action** — действие, которое Podman автоматически предпринимает при переходе контейнера в статус `unhealthy`. Поддерживаемые значения: `none` (только смена статуса), `restart` (перезапуск контейнера), `kill` (остановка) или `reboot` (перезагрузка хоста — требует привилегий).

**Notify=healthy** — параметр интеграции с **systemd** (Quadlet), позволяющий считать сервис успешно запущенным только после того, как внутренняя проверка вернет статус `healthy`.

---

## Основные концепции

### Специфика архитектуры
В Podman архитектура **daemonless** определяет способ работы проверок:
1. **Отсутствие центрального демона**: В отличие от Docker, где за проверками следит демон, в Podman за каждую проверку отвечает процесс `conmon`. Если контейнер запущен через systemd, за состоянием следит сама система инициализации.
2. **Форматы образов**: По умолчанию Podman использует OCI-образы, которые не хранят метаданные проверок (в отличие от Docker-формата). Рекомендуется всегда описывать проверки на уровне рантайма (CLI или Quadlet).
3. **Логика Gating (Шлюзование)**: С версии 6.x подчеркивается роль Startup Healthcheck как шлюза. Пока `--health-startup-cmd` не вернет успех согласно параметру `--health-startup-success`, основная `--health-cmd` даже не будет запущена, что экономит ресурсы и предотвращает ложные алерты.

### Динамическое управление (Podman 6.x+)
Podman теперь позволяет изменять параметры Healthcheck для **уже запущенных** контейнеров без их перезапуска с помощью команды `podman update`. Это касается интервалов, количества попыток и даже самой команды проверки.

---

## Практические сценарии

### 1. Настройка через CLI с управлением логами
Пример для приложения, требующего детальной диагностики и управления размером логов.

```bash
podman run -d \
  --name app-server \
  # Фаза старта (Startup Gate)
  --health-startup-cmd="curl -f http://localhost:8080/ready || exit 1" \
  --health-startup-interval=5s \
  --health-startup-success=1 \
  # Основная фаза
  --health-cmd="curl -f http://localhost:8080/live || exit 1" \
  --health-interval=30s \
  --health-retries=3 \
  # Управление логами (Podman 6.x)
  --health-log-destination=/var/log/app-health.log \
  --health-max-log-count=10 \
  --health-max-log-size=500 \
  # Реакция на сбой
  --health-on-failure=restart \
  my-app-image
```

### 2. Использование в Quadlet (Production стандарт)
Декларативное описание в systemd-юните обеспечивает максимальную надежность и интеграцию с зависимостями.

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

# Настройки Startup (Podman 5.0+)
HealthStartupCmd=curl -f http://localhost/init || exit 1
HealthStartupInterval=5s
HealthStartupRetries=10

# Интеграция с зависимостями systemd
Notify=healthy

[Service]
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### 3. Динамическое обновление параметров
Изменение интервала проверки «на лету» для работающего контейнера.

```bash
# Ускорение проверок при подозрении на нестабильность
podman update --health-interval=5s --health-retries=5 app-server

# Отключение проверок полностью
podman update --no-healthcheck app-server
```

### 4. Проверки в составе Подов (Pods)
В Podman Healthcheck может быть настроен как для отдельного контейнера внутри пода, так и влиять на статус всего пода.
- Если критически важный контейнер в поде переходит в `unhealthy`, действие `restart` затронет только этот контейнер.
- Для мониторинга пода в целом используйте внешние инструменты или связку с systemd-юнитом пода.

---

## Управление и диагностика

### Инспекция состояния и Startup-фазы
Podman 6.x расширил вывод `inspect`, добавив детальную информацию о фазе запуска.

```bash
# Просмотр статуса и истории последних проверок
podman inspect app-server --format '{{json .State.Health}}' | jq

# Проверка параметров Startup-фазы
podman inspect app-server --format '{{json .Config.StartupHealthCheck}}' | jq
```

### Ручной запуск и отладка
```bash
# Принудительное выполнение проверки прямо сейчас (независимо от интервала)
podman healthcheck run app-server

# Отладка с полным выводом логов (stdout/stderr команды проверки)
podman --log-level debug healthcheck run app-server
```

### Мониторинг событий
```bash
podman events --filter event=health_status
# → container health_status app-server (status=unhealthy)
```

---

## Нюансы и ограничения

- **Отсутствие утилит в образе**: В Distroless или Scratch образах часто нет `curl`. Используйте `/dev/tcp/localhost/8080` (в bash) или специализированные бинарные файлы-чекеры.
- **Производительность**: Каждый запуск `HealthCmd` — это новый процесс. Избегайте интервалов менее 1 секунды при большом количестве контейнеров.
- **Сетевой контекст**: В Rootless-режиме (через `pasta` или `slirp4netns`) проверка всегда выполняется внутри сетевого неймспейса, поэтому `localhost` внутри `HealthCmd` всегда указывает на сам контейнер.
- **Хранение логов**: По умолчанию Podman хранит историю проверок в памяти (или SQLite). Использование `--health-log-destination` позволяет вынести это в файлы для долгосрочного анализа.

---

## Дополнительная информация

### Связанные разделы
- **[Автообновление и откат](./podman_auto_update.md)** — использование Healthcheck для безопасного деплоя.
- **[Управление зависимостями](./podman-dependencies.md)** — как `Notify=healthy` заменяет `depends_on`.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — глубокое описание работы `conmon`.

### Ссылки
- **[Podman Update Documentation](https://docs.podman.io/en/latest/markdown/podman-update.1.html)** (англ.) — параметры динамического изменения конфигурации.
- **[Podman Healthcheck Run](https://docs.podman.io/en/latest/markdown/podman-healthcheck-run.1.html)** (англ.) — ручное управление проверками.
- **[Quadlet upstream documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)** (англ.) — справочник параметров секции `[Container]`.
