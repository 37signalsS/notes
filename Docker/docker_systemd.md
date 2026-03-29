# Systemd в Docker: анти-паттерн

## Определения

**Анти-паттерн "systemd в Docker"** — запуск `systemd` как PID 1 внутри контейнера. Нарушает принцип "один процесс на контейнер", требует привилегий `--privileged`, снижает изоляцию.

## Основные концепции

### Почему systemd не работает в Docker

`systemd` — полноценная init-система, требующая прямого доступа к ядру. Docker предоставляет виртуализированное окружение с ограничениями:

| Требование systemd | Ограничение Docker | Результат |
| :--- | :--- | :--- |
| **PID 1** | Контейнер запускает `CMD`/`ENTRYPOINT` | `systemd` не может управлять процессами |
| **Полный доступ к cgroups** | Виртуализированный `/sys/fs/cgroup` | Невозможно управлять ресурсами |
| **tmpfs для `/run`, `/tmp`** | Обычная файловая система | Ошибки монтирования |
| **Capabilities (`CAP_SYS_ADMIN`)** | Отобраны по умолчанию | Недостаточно прав для инициализации |

### Альтернативы systemd в контейнере

| Задача | Решение | Файл |
| :--- | :--- | :--- |
| Запуск нескольких процессов | Легковесные супервизоры (`supervisord`, `s6`, `runit`) | [Паттерн "Multi-Process"](./Docker_logs/docker_multi_process_logging.md) |
| Управление контейнерами на хосте | systemd на хосте (юниты для контейнеров) | [Интеграция Docker с systemd](../Linux/Core/systemd/docker_integration.md) |
| Полная изоляция как в VM | Kata Containers, gVisor | [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md) |

## Практические сценарии

### Сценарий 1: Multi-Process контейнер (рекомендуется)

Для запуска нескольких процессов используйте супервизоры вместо `systemd`:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y supervisor

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# supervisord становится PID 1
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

**Преимущества:**
- Не требует `--privileged`
- Агрегация логов через `docker logs`
- Корректная обработка сигналов (`SIGTERM`)
- Сбор zombi-процессов

### Сценарий 2: Принудительный запуск systemd (не рекомендуется)

**Внимание:** Используйте только для тестирования или миграции legacy. Контейнер имеет почти полный доступ к хосту.

```bash
docker run -d --name systemd-container \
  --privileged \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  my-systemd-image /sbin/init
```

**Флаги:**
- `--privileged`: Передает все capabilities контейнеру (угроза безопасности)
- `-v /sys/fs/cgroup:ro`: Монтирует cgroups хоста для управления ресурсами
- `/sbin/init`: Явно указывает `systemd` как PID 1

**Ограничения:**
- Контейнер может взаимодействовать с устройствами хоста
- Нарушается изоляция процессов
- Не рекомендуется для production

## Дополнительная информация

**Разграничение подходов:**
- **systemd внутри контейнера** — анти-паттерн (требует `--privileged`)
- **systemd на хосте для управления контейнерами** — рекомендуемая практика [Интеграция Docker с systemd](../Linux/Core/systemd/docker_integration.md)

**Связанные темы:**
- [Паттерн "Multi-Process" в Docker](./Docker_logs/docker_multi_process_logging.md)
- [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)
- [Проблема PID 1 и zombi-процессы](./Dockerfile/Docker_best_practices/container_execution.md)
