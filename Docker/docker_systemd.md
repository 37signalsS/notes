# Systemd в Docker — запуск и управление службами

## Определения

- **Systemd в Docker:** Запуск полнофункциональной системы инициализации `systemd` в качестве первого процесса (PID 1) внутри контейнера.
- **PID 1 (Init):** Первый процесс в пространстве имен (Namespace), ответственный за управление жизненным циклом служб, обработку сигналов и очистку «зомби-процессов».
- **Zombie Process:** Дочерний процесс, завершивший выполнение, но не удаленный из таблицы процессов, так как родитель (PID 1) не обработал его сигнал завершения.
- **Cgroup v2 (Unified Hierarchy):** Современная иерархия групп управления ресурсами в Linux, требующая делегирования прав контейнеру для корректной работы `systemd`.

## Основные концепции

### Почему запуск systemd в Docker считается анти-паттерном

1. **Нарушение атомарности:** Docker-контейнер предназначен для изоляции *одного* процесса. `systemd` превращает его в «микро-ВМ», что затрудняет сбор логов и мониторинг состояния конкретных приложений.
2. **Безопасность и привилегии:** Для работы `systemd` требуются расширенные полномочия (`CAP_SYS_ADMIN`), что увеличивает поверхность атаки.
3. **Механика сигналов:** `systemd` игнорирует стандартный `SIGTERM` для завершения работы, что часто приводит к принудительной остановке контейнера (`SIGKILL`) через 10 секунд ожидания.

### Сравнение систем инициализации

| Характеристика | systemd (внутри) | Tini / dumb-init | Supervisord / s6 |
| :--- | :--- | :--- | :--- |
| **Цель** | Эмуляция полной ОС | Только решение проблемы PID 1 | Групповой запуск служб |
| **Сложность** | Максимальная | Минимальная | Средняя |
| **Изоляция** | Требует `SYS_ADMIN` | Стандартная | Стандартная |
| **Сбор зомби** | Да | Да | Да |
| **Управление** | `systemctl` | Отсутствует | Собственные CLI/Web |

## Практические сценарии

### Сценарий 1: Решение проблемы PID 1 (Рекомендуется)

Если цель — корректная обработка сигналов и очистка зомби-процессов для одного приложения.

```dockerfile
# Использование встроенного в Docker механизма
# CLI: docker run --init my-image
# Compose: init: true

# Или через Dockerfile
FROM alpine:3.20
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/bin/my-app"]
```

### Сценарий 2: Правильная подготовка образа с systemd

Если запуск `systemd` необходим (Ansible-тесты, Legacy), используйте следующие настройки в `Dockerfile`.

```dockerfile
FROM ubuntu:24.04
ENV container docker
# Установка systemd и dbus (необходим для работы systemctl)
RUN apt-get update && apt-get install -y systemd dbus && apt-get clean
# Маскировка лишних служб для ускорения старта
RUN systemctl mask systemd-remount-fs.service dev-hugepages.mount sys-kernel-config.mount
# Настройка сигнала остановки (Критично!)
STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
```

### Сценарий 3: Запуск в режиме Cgroup v2 (2024-2026)

Для систем с Unified Hierarchy (ядра 5.15+) используйте «хирургические» флаги вместо `--privileged`.

```bash
docker run -d \
    --name systemd-node \
    --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    --cgroupns=private \
    --cap-add SYS_ADMIN \
    --security-opt seccomp=unconfined \
    my-systemd-image
```
- **`--tmpfs /run`**: Обязательно для хранения сокетов и PID-файлов `systemd`.
- **`--cgroupns=private`**: Изолирует иерархию cgroups внутри контейнера.
- **`-v /sys/fs/cgroup...:rw`**: На cgroup v2 `systemd` должен иметь права на запись в свою подгруппу.

### Сценарий 4: Использование специализированных рантаймов

Рантайм **Sysbox** позволяет запускать `systemd` без `SYS_ADMIN` и монтирования `/sys/fs/cgroup`, обеспечивая изоляцию через User Namespaces.

```bash
docker run --runtime=sysbox-runc -d my-systemd-image
```

## Дополнительная информация

### Диагностика и отладка (Troubleshooting)

- **Ошибка "Failed to connect to bus":** Обычно означает, что пакет `dbus` не установлен или служба `dbus.service` не запущена внутри контейнера.
- **Контейнер останавливается 10 секунд:** Docker отправляет `SIGTERM`, который `systemd` игнорирует. Убедитесь, что установлен `STOPSIGNAL SIGRTMIN+3`.
- **Логи не отображаются в `docker logs`:** По умолчанию `systemd` пишет в `journald`.
    - **Решение:** Настройте `Storage=volatile` в `/etc/systemd/journald.conf` и используйте `journalctl -f` внутри контейнера или пробросьте `/dev/console` в юнит-файлы.

### Особенности работы с DBus

Для управления службами через `systemctl` пользователю необходим доступ к сокету `/run/dbus/system_bus_socket`. Если вы запускаете команды через `docker exec`, убедитесь, что `dbus` активен.

### См. также
- **[Интеграция Docker с systemd на хосте](../Linux/Core/systemd/docker_integration.md)** — управление контейнерами как юнитами.
- **[Выполнение приложений в контейнере](./Dockerfile/Docker_best_practices/container_execution.md)** — глубокий разбор PID 1 и сигналов.
- **[Безопасность: Capabilities](./Docker_security/host_daemon_hardening.md)** — риски использования `SYS_ADMIN`.
- **[Паттерн Multi-Process](./Docker_logs/docker_multi_process_logging.md)** — альтернативы в виде Supervisord и s6-init.
