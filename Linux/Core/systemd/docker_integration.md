# Интеграция Docker и systemd

## Определения

* **Интеграция Docker с systemd** — это архитектурный подход, при котором жизненный цикл Docker-контейнеров управляется системой инициализации `systemd` на хост-системе. В этом сценарии каждый контейнер или группа связанных контейнеров описывается как стандартный юнит-файл (unit file) сервиса `systemd`.
* **sdnotify** — протокол уведомления `systemd` о готовности или состоянии приложения. Используется для синхронизации запуска зависимых служб.
* **Drop-in файлы** — дополнительные конфигурационные файлы в директории `.service.d/`, позволяющие переопределять параметры юнита без модификации основного файла.

## Основные концепции

### Преимущества управления через systemd

* **Управление зависимостями** — контейнеры запускаются строго после готовности необходимых системных ресурсов (сеть, монтирование) или других служб (база данных на хосте).
* **Единый интерфейс управления** — использование стандартных команд `systemctl` и `journalctl` для всех компонентов системы.
* **Автоматическое восстановление** — гибкая настройка политик перезапуска (`Restart=on-failure`, `RestartSec`).
* **Ограничение ресурсов** — использование нативных механизмов `cgroups` через параметры юнита (`MemoryMax`, `CPUQuota`).
* **Централизованное логирование** — вывод контейнеров автоматически направляется в `journald`.

### Ключевые параметры юнита для Docker

При интеграции Docker и systemd критически важно правильно настроить параметры завершения и уведомления:

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| **`Type=notify`** | Ожидание сигнала готовности от приложения. | Использовать, если приложение в контейнере поддерживает `sdnotify`. |
| **`KillMode=none`** | `systemd` не убивает процессы при остановке юнита. | Рекомендуется для Docker, так как `docker stop` сам управляет сигналами. |
| **`Delegate=yes`** | Позволяет контейнеру управлять собственными под-cgroups. | Обязательно для вложенной контейнеризации или сложных лимитов. |
| **`EnvironmentFile=`** | Загрузка переменных окружения из внешнего файла. | Удобно для хранения настроек и секретов. |

## Практические сценарии

### 1. Создание юнит-файла для одиночного контейнера

Путь: `/etc/systemd/system/docker-app.service`

```ini
[Unit]
Description=My Docker Application
Requires=docker.service
After=docker.service

[Service]
Restart=always
# Загрузка переменных окружения
EnvironmentFile=-/etc/default/docker-app

# Очистка перед запуском (игнорируем ошибки, если контейнера нет)
ExecStartPre=-/usr/bin/docker stop %n
ExecStartPre=-/usr/bin/docker rm %n
# Принудительное скачивание свежего образа
ExecStartPre=/usr/bin/docker pull my-repo/my-app:latest

# Запуск контейнера
ExecStart=/usr/bin/docker run --rm --name %n \
    --env-file /etc/default/docker-app \
    -p 8080:80 \
    my-repo/my-app:latest

# Корректная остановка
ExecStop=/usr/bin/docker stop %n

[Install]
WantedBy=multi-user.target
```
*Примечание: `%n` в имени — это автоматическая подстановка имени юнита.*

### 2. Запуск Docker Compose через systemd

Для управления стеком сервисов удобно использовать `docker-compose`.

```ini
[Unit]
Description=Docker Compose Application Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/my-stack

ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down

[Install]
WantedBy=multi-user.target
```

### 3. Управление и диагностика

```bash
# Перечитать конфигурацию
sudo systemctl daemon-reload
# → обновление кэша systemd

# Активация и запуск
sudo systemctl enable --now docker-app.service
# → запуск контейнера и настройка автозагрузки

# Просмотр логов в реальном времени
journalctl -u docker-app.service -f
# → вывод логов контейнера из journald
```

## Дополнительная информация

### Сравнение с Podman

В отличие от Docker, **Podman** имеет нативную интеграцию с systemd через технологию **Quadlet**, которая позволяет описывать контейнеры в `.container` файлах, автоматически генерируя юниты.
Подробнее см. **[Подман: Автообновление и откат контейнеров](../../../Podman/podman_auto_update.md)**.

### Анти-паттерн: Systemd внутри Docker

Запуск `systemd` внутри контейнера (как PID 1) крайне не рекомендуется, так как это нарушает принцип изоляции и требует привилегированного режима.
Подробнее см. **[Systemd в Docker](../../../Docker/docker_systemd.md)**.

### См. также

* [Обзор юнитов systemd](./systemd_units_overview.md)
* [Управление службами (systemctl)](./service_management.md)
* [Журналирование через journald](../../SystemAdministration/Logging/journald.md)
