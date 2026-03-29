# Инструкции Dockerfile: Данные и Хранилища

## Определения

**Инструкция `VOLUME`** — директива в Dockerfile, объявляющая точку монтирования для внешнего тома. Создаёт анонимный том при запуске контейнера.

**Том (Volume)** — механизм для персистентного хранения данных, управляемый Docker. Подробнее см. **[Docker Volumes](../../Docker_fs/docker_volumes.md)**.

## Основные концепции

### Синтаксис

```dockerfile
VOLUME ["/path/to/directory"]
```

Или в виде строки с несколькими путями:

```dockerfile
VOLUME /var/log
VOLUME /var/log /var/db
VOLUME ["/app/data", "/app/cache"]
```

> **Важно:** При использовании JSON-массива применяйте двойные кавычки (`"`), а не одинарные (`'`).

### Поведение инструкции

| Аспект | Описание |
| :--- | :--- |
| **Назначение** | Создаёт точку монтирования и маркирует её как содержащую externally mounted volume |
| **Инициализация** | `docker run` инициализирует том любыми данными, существующими в указанной локации базового образа |
| **Тип тома** | Создаёт **анонимные тома** (управляются Docker, имя генерируется автоматически) |

### Пример инициализации тома данными

```dockerfile
FROM ubuntu
RUN mkdir -p /myvol
RUN echo "hello world" > /myvol/greeting
VOLUME /myvol
```

При запуске `docker run` создаст новую точку монтирования в `/myvol` и скопирует файл `greeting` в созданный том.

### Ограничения и предостережения

| Правило | Описание |
| :--- | :--- |
| **Нельзя указать путь хоста** | `VOLUME` в Dockerfile не принимает host-пути — это нарушает портативность образа |
| **Windows-контейнеры** | Путь назначения должен быть: несуществующей/пустой директорией ИЛИ диском, отличным от `C:` |
| **Изменения после `VOLUME`** | Legacy builder: изменения данных в томе после объявления отбрасываются. BuildKit: изменения сохраняются |
| **Монтирование** | Выполняется при запуске контейнера через `-v` или `--mount` флаг |

### Отличие от bind mount

| Характеристика | `VOLUME` (в Dockerfile) | Bind mount (`-v` / `--mount`) |
| :--- | :--- | :--- |
| Управление | Docker управляет автоматически | Пользователь управляет |
| Расположение | В директории Docker (`/var/lib/docker/volumes/`) | Любая директория хоста |
| Переносимость | Переносится между хостами | Привязан к хосту |
| Объявление | В `Dockerfile` | При запуске (`docker run` / `docker-compose.yml`) |

## Практические сценарии

### Сценарий 1: Логи веб-сервера

```dockerfile
FROM nginx:alpine
VOLUME /var/log/nginx
```

Docker создаст анонимный том и автоматически примонтирует его к `/var/log/nginx`. Данные в таком томе переживут удаление и пересоздание контейнера.

### Сценарий 2: Пользовательские файлы и кэш

```dockerfile
FROM node:20-alpine
WORKDIR /app
VOLUME ["/app/uploads", "/app/cache"]
```

### Сценарий 3: Переопределение в Docker Compose

В Docker Compose директива `VOLUME` из Dockerfile работает как значение по умолчанию и может быть переопределена:

```yaml
services:
  app:
    build: .
    volumes:
      - my_named_volume:/app/data  # Переопределяет VOLUME из Dockerfile
volumes:
  my_named_volume:
```

### Сценарий 4: BuildKit — сохранение изменений после VOLUME

```dockerfile
# syntax=docker/dockerfile:1
FROM ubuntu
VOLUME /data
# В BuildKit эти изменения сохранятся в образе
RUN echo "config" > /data/config.txt
```

В legacy builder изменения в `/data` после `VOLUME` были бы отброшены.

## Дополнительная информация

Данные в томах не являются частью записываемого слоя контейнера и не включаются в `docker export`. Для управления томами используйте команды `docker volume create/ls/inspect/rm` (подробнее **[Docker Volumes](../../Docker_fs/docker_volumes.md)**). Конфигурацию в Docker Compose см. в **[Docker Compose file example](../../Docker_compose/docker_compose_file_example.md)**. Для копирования данных в образ используйте **[COPY и ADD](./copying_files.md)**.
