# Интеграция Docker и systemd: Управление юнитами

## Определения

* **Интеграция Docker с systemd** — архитектурный подход, при котором внешняя система инициализации (`systemd`) управляет жизненным циклом Docker-контейнеров на хосте. В этой модели контейнер рассматривается как стандартная системная служба.
* **`sdnotify`** — протокол уведомления о готовности (READY=1), позволяющий приложению внутри контейнера сообщить `systemd` об успешном запуске для разблокировки зависимых служб.
* **Делегирование (Delegation)** — механизм cgroup v2, позволяющий менеджеру процессов (PID 1) передать управление определенной веткой иерархии ресурсов (CGroup) дочернему процессу (Docker daemon), что необходимо для корректной работы лимитов внутри контейнера.

## Основные концепции

### Преимущества внешнего управления

1.  **Нативная оркестрация зависимостей:** Использование `After=`, `Requires=` и `Wants=` для связки контейнеров с базами данных на хосте, точками монтирования или сетевыми интерфейсами.
2.  **Централизованная диагностика:** Команды `systemctl status` и `journalctl -u` предоставляют полную картину состояния приложения без необходимости переключения контекста на Docker CLI.
3.  **Гибкая политика перезапуска:** Настройка `StartLimitIntervalSec` и `StartLimitBurst` предотвращает бесконечные циклы перезапуска при фатальных ошибках.
4.  **Безопасная очистка:** Автоматическое удаление контейнеров при остановке (`--rm`) гарантирует отсутствие конфликтов имен при следующем запуске.

### Глубокая настройка параметров юнита

| Директива | Назначение | Техническое обоснование |
| :--- | :--- | :--- |
| **`Delegate=yes`** | Управление cgroups | Обязательно для Docker в режиме cgroup v2. Позволяет Docker создавать под-cgroups для процессов контейнера без конфликтов с `systemd`. |
| **`KillMode=mixed`** | Режим завершения | Отправляет SIGTERM только основному процессу (`docker run`), позволяя Docker daemon корректно остановить контейнер. В режиме `control-group` systemd может убить прокси-процессы раньше времени. |
| **`Type=notify`** | Уведомление о готовности | Если приложение поддерживает `sdnotify`, systemd будет ждать сигнала READY перед запуском зависимых юнитов. Требует проброса сокета. |
| **`EnvironmentFile=`** | Конфигурация | Позволяет выносить настройки (порты, теги образов) в отдельный файл (например, `/etc/default/myapp`), не меняя сам юнит. |

## Практические сценарии

### 1. Эталонный юнит для контейнера (Production)

Путь: `/etc/systemd/system/app-container.service`

```ini
[Unit]
Description=My App Production Container
Requires=docker.service
After=docker.service network-online.target
Wants=docker.socket

[Service]
Restart=on-failure
RestartSec=10
TimeoutStartSec=0
# Делегирование управления ресурсами
Delegate=yes
EnvironmentFile=-/etc/default/app-container

# Предварительная очистка и подготовка
ExecStartPre=-/usr/bin/docker stop %n
ExecStartPre=-/usr/bin/docker rm %n
ExecStartPre=/usr/bin/docker pull ${IMAGE_TAG}

# Запуск. Имя контейнера совпадает с именем юнита (%n)
ExecStart=/usr/bin/docker run --rm --name %n \
    --env-file /etc/default/app-container \
    -p ${HOST_PORT}:80 \
    ${IMAGE_TAG}

# Вежливая остановка. Время ожидания (timeout) задается флагом -t
ExecStop=/usr/bin/docker stop -t 10 %n

[Install]
WantedBy=multi-user.target
```

### 2. Использование Docker Compose как системной службы

Идеально для многокомпонентных приложений на одном узле.

```ini
[Unit]
Description=Docker Compose Stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/myapp-stack

# Запуск в фоновом режиме
ExecStart=/usr/bin/docker compose up -d --remove-orphans
# Остановка и очистка томов при необходимости
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

### 3. Настройка уведомлений (sdnotify)

Для использования `Type=notify` в контейнере необходимо пробросить путь к сокету уведомлений:
1.  Установите `NotifyAccess=all` в юните.
2.  Пробросьте `$NOTIFY_SOCKET` в контейнер как переменную окружения.
3.  Монтируйте сокет: `-v /run/systemd/notify:/run/systemd/notify`.

## Диагностика и управление

```bash
# Проверка влияния Delegate на иерархию cgroups
systemd-cgls --unit app-container.service

# Чтение журналов с метаданными Docker
journalctl -u app-container.service -o json | jq '._KERNEL_DEVICE'

# Проверка статуса сокета Docker, от которого зависит юнит
systemctl status docker.socket
```

## Дополнительная информация

### Сравнение с нативной интеграцией Podman

В отличие от Docker, **Podman** предлагает более совершенную интеграцию через генератор **Quadlet**. Он исключает необходимость ручного написания сложных `ExecStartPre`, автоматически обрабатывая зависимости и жизненный цикл.
Подробнее: **[Podman: Автообновление и Quadlet](../../../Podman/podman_auto_update.md)**.

### Анти-паттерны

*   **Использование `Restart=always` в Docker и в Systemd одновременно:** Может привести к конфликтам при попытке Docker перезапустить контейнер, пока systemd считает его упавшим. Рекомендуется отключать `restart: always` в Docker при использовании systemd.
*   **Systemd внутри Docker:** Запуск systemd как PID 1 внутри контейнера — это отдельная задача со своими рисками. Подробнее см. **[Systemd в Docker](../../../Docker/docker_systemd.md)**.

### См. также

* [Обзор юнитов systemd](./systemd_units_overview.md) — базовые типы и логика.
* [Управление службами (systemctl)](./service_management.md) — команды мониторинга.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами.
* [Изоляция контейнеров: Cgroups](../../../Docker/Concepts/linux_isolation.md) — механизмы ограничения ресурсов.
