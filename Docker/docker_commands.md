# Команды Docker CLI

## Определения

**Docker CLI** — интерфейс командной строки для управления контейнерами, образами, сетями и томами. Работает через REST API демона `dockerd`.

## Основные концепции

### Жизненный цикл контейнера

| Команда | Описание |
| :--- | :--- |
| `docker run <образ>` | Создает и запускает контейнер. Флаги: `-d` (фон), `--rm` (удалить после) |
| `docker start <контейнер>` | Запускает остановленный контейнер |
| `docker stop <контейнер>` | Останавливает (`SIGTERM`, затем `SIGKILL` через 10с) |
| `docker restart <контейнер>` | Перезапускает контейнер |
| `docker pause / unpause` | Замораживает/размораживает процессы |
| `docker rm <контейнер>` | Удаляет остановленный контейнер |
| `docker exec -it <контейнер> <команда>` | Выполняет команду внутри контейнера |
| `docker attach <контейнер>` | Подключается к PID 1 (отсоединение: `Ctrl+P`, `Ctrl+Q`) |
| `docker update <контейнер>` | Обновляет ресурсы (CPU, память) без перезапуска |
| `docker cp <откуда> <куда>` | Копирует файлы между хостом и контейнером |

**Политики перезапуска (`--restart`):**

| Политика | Поведение |
| :--- | :--- |
| `no` (по умолчанию) | Никогда не перезапускать |
| `on-failure[:max-retries]` | Только при ошибке (exit code ≠ 0) |
| `always` | Всегда перезапускать, даже после `docker stop` |
| `unless-stopped` | Всегда, кроме случаев явной остановки (**рекомендуется для production**) |

### Управление образами

| Команда | Описание |
| :--- | :--- |
| `docker images` | Список локальных образов |
| `docker build -t <имя>:<тег> .` | Сборка образа из `Dockerfile` |
| `docker pull <образ>:<тег>` | Скачивание из реестра |
| `docker push <образ>:<тег>` | Загрузка в реестр |
| `docker rmi <образ>` | Удаление образа |
| `docker tag <source> <target>` | Добавление тега |
| `docker history <образ>` | Показывает слои образа |

### Инспекция и мониторинг

| Команда | Описание |
| :--- | :--- |
| `docker ps` | Запущенные контейнеры (`-a` — все) |
| `docker inspect <объект>` | Детальная информация в JSON |
| `docker stats <контейнер>` | Метрики ресурсов в реальном времени |
| `docker top <контейнер>` | Процессы внутри контейнера |
| `docker port <контейнер>` | Маппинг портов |
| `docker logs <контейнер>` | Вывод логов (`-f` — follow, `--tail N`, `--since 10m`) |

### Очистка системы (Prune)

| Команда | Описание |
| :--- | :--- |
| `docker system prune` | Удаление остановленных контейнеров, dangling образов, сетей |
| `docker container prune` | Удаление остановленных контейнеров |
| `docker image prune` | Удаление dangling образов (`-a` — все неиспользуемые) |
| `docker volume prune` | Удаление неиспользуемых томов |
| `docker system prune -a --volumes` | **Опасно:** удаляет всё, включая тома |

**Dangling images** — образы без тега (`<none>`), появляются при пересборке с тем же тегом.

## Практические сценарии

### Быстрое изменение конфигурации

```bash
# Вход в контейнер
docker exec -it my_container /bin/sh

# Внести правки в конфиг

# Перезапуск
docker restart my_container
```

Изменения сохраняются в writable layer, приложение перечитывает конфиг при старте.

### Динамическое обновление ресурсов

```bash
# Ограничение памяти без остановки
docker update --memory 1G my-container

# Ограничение CPU
docker update --cpus 1.5 my-container
```

### Получение IP-адреса контейнера

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' my-container
```

### Логирование Nginx в STDOUT/STDERR

Приложения должны писать логи в стандартные потоки для сбора через `docker logs`:

```dockerfile
RUN ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log
```

### Поиск и удаление dangling образов

```bash
# Найти
docker images -f "dangling=true"

# Удалить
docker image prune
```

## Дополнительная информация

**Различия `stop` vs `pause`:**
- `pause` — замораживает процессы (сохраняет RAM, не потребляет CPU)
- `stop` — корректная остановка (`SIGTERM` → `SIGKILL`), память и CPU освобождаются

**Связанные темы:**
- [Управление сетями (CLI)](./Docker_network/cli.md)
- [Тома и хранение данных](./Docker_fs/docker_volumes.md)
- [Анализ слоев образа (dive)](./Dockerfile/dockerfile_optimization_tools.md)
- [Политики перезапуска в Docker Swarm](../Docker_swarm/swarm_stack_deployment.md)
