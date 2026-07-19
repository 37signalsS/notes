# Инструкции Dockerfile: Практические сценарии переопределения

## Определения

**Переопределение инструкций (Instruction Overriding)** — процесс замещения параметров, определенных в `Dockerfile`, во время сборки образа или запуска контейнера с помощью аргументов командной строки, переменных окружения или директив в файлах конфигурации (например, Docker Compose).

**Приоритет выполнения** — иерархия источников конфигурации, где внешние параметры (Runtime/Build-args) всегда имеют преимущество над значениями, жестко заданными в `Dockerfile`.

## Основные концепции

### Типы переопределения

Для эффективного управления образами важно различать, на каком этапе происходит замещение параметров:

1.  **Этап сборки (Build-time):** Относится к инструкции **[ARG](./environment_variables.md)**. Значение меняется через флаг `--build-arg`.
2.  **Этап выполнения (Runtime):** Относится к инструкциям `CMD`, `ENTRYPOINT`, `ENV`, `USER`, `WORKDIR`, `VOLUME`, `HEALTHCHECK`, `STOPSIGNAL`. Значения меняются через флаги `docker run` или секции в `docker-compose.yml`.

### Сводная таблица Runtime-переопределений

| Инструкция | Флаг `docker run` | Директива Compose |
| :--- | :--- | :--- |
| **`CMD`** | `[arguments]` (в конце команды) | `command:` |
| **`ENTRYPOINT`** | `--entrypoint` | `entrypoint:` |
| **`ENV`** | `-e`, `--env` | `environment:` |
| **`USER`** | `-u`, `--user` | `user:` |
| **`WORKDIR`** | `-w`, `--workdir` | `working_dir:` |
| **`HEALTHCHECK`** | `--no-healthcheck` | `healthcheck: disable: true` |
| **`STOPSIGNAL`** | `--stop-signal` | `stop_signal:` |

## Практические сценарии

### Сценарий 1: Взаимодействие ENTRYPOINT и CMD

При переопределении `ENTRYPOINT` через флаг `--entrypoint` оригинальный `CMD` из образа полностью игнорируется.

**Dockerfile:**
```dockerfile
ENTRYPOINT ["/usr/bin/python3"]
CMD ["app.py"]
```

**Переопределение:**
```bash
# Запустит интерактивный shell вместо Python-приложения
docker run -it --entrypoint /bin/bash my-image
```

### Сценарий 2: Подмена ENV для разных окружений

Инструкция `ENV` в образе задает значения по умолчанию, которые легко заменяются при запуске.

```bash
# Переопределение URL базы данных для стейджинга
docker run -e DB_HOST=staging-db.internal my-app
```

### Сценарий 3: Переопределение VOLUME (Bind Mounts)

Инструкция `VOLUME` в Dockerfile создает анонимный том. Переопределение на этапе запуска позволяет связать точку монтирования с конкретной папкой на хосте.

```bash
# Переопределение анонимного тома на bind mount для разработки
docker run -v $(pwd)/logs:/var/log/app my-app
```

### Сценарий 4: Отключение HEALTHCHECK

Если в базовом образе настроена проверка здоровья, которая не актуальна для вашего сценария (например, при запуске тестов), её можно отключить.

```bash
# Запуск без мониторинга здоровья
docker run --no-healthcheck my-db-image
```

### Сценарий 5: Смена STOPSIGNAL для корректной остановки

Если приложение требует специфического сигнала для завершения (например, `SIGINT` вместо стандартного `SIGTERM`), это можно указать при запуске.

```bash
docker run --stop-signal SIGINT my-legacy-app
```

### Сценарий 6: Переопределение рантайма (GPU и Wasm)

Современный Docker позволяет менять среду выполнения для поддержки ускорителей (CDI) или WebAssembly.

```bash
# Использование Wasm рантайма (Docker 25+)
docker run --runtime=io.containerd.wasmer.v1 my-wasm-module

# Использование GPU через CDI (заменяет устаревший флаг --gpus)
docker run --device nvidia.com/gpu=all my-ai-model
```

## Дополнительная информация

- **[Инструкции выполнения: CMD, ENTRYPOINT и USER](./runtime_execution.md)** — глубокий разбор механизмов запуска.
- **[Директивы Docker Compose](../../Docker_compose/docker_compose_directives.md)** — справочник по переопределению параметров в YAML.
- **[Переменные: ENV и ARG](./environment_variables.md)** — разница в области видимости и способах передачи.
