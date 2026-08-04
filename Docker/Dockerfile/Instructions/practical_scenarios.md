# Инструкции Dockerfile: Практические сценарии переопределения

## Определения

**Переопределение инструкций (Instruction Overriding)** — процесс замещения параметров, определенных в `Dockerfile`, во время сборки образа или запуска контейнера. Это позволяет использовать один и тот же образ для разных окружений (dev, staging, prod), адаптируя его поведение без пересборки.

**Иерархия приоритетов (Precedence)** — строгий порядок применения настроек. Внешние параметры (флаги CLI) всегда имеют наивысший приоритет, перекрывая значения из конфигурационных файлов (Compose) и самого `Dockerfile`.

## Основные концепции

### Типы переопределения

1.  **Этап сборки (Build-time):** Замена значений **[ARG](./environment_variables.md)** через флаг `--build-arg`. Влияет на итоговый образ.
2.  **Этап выполнения (Runtime):** Замена параметров запуска (`CMD`, `ENTRYPOINT`, `ENV`, `USER`, `WORKDIR`, `VOLUME`, `HEALTHCHECK`, `STOPSIGNAL`). Влияет только на текущий запущенный контейнер.

### Сводная таблица Runtime-переопределений

| Инструкция | Флаг `docker run` | Директива Compose | Влияние на образ |
| :--- | :--- | :--- | :--- |
| **`CMD`** | `[аргументы]` в конце | `command:` | Полная замена |
| **`ENTRYPOINT`** | `--entrypoint` | `entrypoint:` | Сбрасывает оригинальный `CMD` |
| **`ENV`** | `-e`, `--env` | `environment:` | Добавление или замена |
| **`USER`** | `-u`, `--user` | `user:` | Переопределение UID/GID |
| **`WORKDIR`** | `-w`, `--workdir` | `working_dir:` | Смена текущей директории |
| **`HEALTHCHECK`** | `--no-healthcheck` | `healthcheck:` | Изменение или отключение |
| **`STOPSIGNAL`** | `--stop-signal` | `stop_signal:` | Смена сигнала завершения |

### Иерархия приоритетов переменных (от высшего к низшему)

1.  Флаги командной строки (`docker run -e VAR=val`).
2.  Секция `environment` в `compose.yaml`.
3.  Файлы переменных (`env_file`) в `compose.yaml`.
4.  Инструкция `ENV` в `Dockerfile`.
5.  Значения по умолчанию в приложении.

## Практические сценарии

### Сценарий 1: Взаимодействие ENTRYPOINT и CMD

Критически важно помнить: переопределение `ENTRYPOINT` через `--entrypoint` **автоматически удаляет** все аргументы, заданные в `CMD` в Dockerfile.

**Dockerfile:**
```dockerfile
ENTRYPOINT ["/usr/bin/python3"]
CMD ["app.py", "--log-level=info"]
```

**Переопределение для отладки:**
```bash
# Ошибка: app.py не будет запущен, так как CMD стерт
docker run --entrypoint /bin/bash my-image 

# Правильно: передаем новый CMD явно
docker run --entrypoint /bin/bash my-image -c "ls /app"
```

### Сценарий 2: Динамическое изменение USER (Numerical UID)

Переопределение пользователя полезно при монтировании томов (Volumes), чтобы UID внутри контейнера совпадал с UID владельца папки на хосте.

```bash
# Запуск от имени текущего пользователя хоста (Linux)
docker run -u $(id -u):$(id -g) -v /data:/data my-app
```
*Примечание: Если пользователь с таким UID не существует в /etc/passwd контейнера, многие утилиты могут работать некорректно (например, не резолвить домашнюю директорию).*

### Сценарий 3: Переопределение VOLUME на Bind Mount

Инструкция `VOLUME` в Dockerfile резервирует место, но не привязывает его к хосту. Runtime-переопределение через `-v` или `--mount` делает данные доступными вне контейнера.

```bash
# Переопределение анонимного тома на папку разработки с горячей перезагрузкой
docker run -v $(pwd)/src:/app/src my-node-app
```

### Сценарий 4: Глубокая настройка HEALTHCHECK

В Docker Compose можно не только отключить проверку, но и изменить её параметры без изменения образа.

```yaml
services:
  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
```

### Сценарий 5: Современные рантаймы (GPU, Wasm, CDI)

Современный Docker (2025+) позволяет переопределять среду выполнения для доступа к специфическому оборудованию.

```bash
# Использование CDI (Container Device Interface) для GPU (заменяет устаревший --gpus)
docker run --device nvidia.com/gpu=all my-ml-app

# Запуск WebAssembly модуля через специфический рантайм
docker run --runtime=io.containerd.wasmer.v1 my-wasm-app
```

### Сценарий 6: Использование Compose Overrides

Паттерн `compose.yaml` + `compose.override.yml` — это стандарт де-факто для локальной разработки.

**compose.yaml (базовый):**
```yaml
services:
  web:
    image: my-app:prod
    environment:
      NODE_ENV: production
```

**compose.override.yml (локальный):**
```yaml
services:
  web:
    build: . # Переопределяем образ на локальную сборку
    environment:
      NODE_ENV: development
    ports:
      - "3000:3000"
```

## Дополнительная информация

- **[Инструкции выполнения: CMD, ENTRYPOINT и USER](./runtime_execution.md)** — архитектурные детали запуска процессов.
- **[Директивы Docker Compose](../../Docker_compose/docker_compose_directives.md)** — полный справочник по YAML-синтаксису.
- **[Переменные: ENV и ARG](./environment_variables.md)** — детали работы с переменными на разных этапах.
- **[Безопасность в Dockerfile](../Docker_best_practices/security.md)** — почему переопределение USER важно для защиты.
