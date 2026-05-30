# Инструкции Dockerfile: Практические сценарии переопределения

## Определения

**Переопределение инструкций (Instruction Overriding)** — процесс замещения параметров, определенных в `Dockerfile` (таких как `CMD`, `ENTRYPOINT`, `USER`, `WORKDIR`, `ENV`), во время запуска контейнера с помощью аргументов командной строки или директив в файлах конфигурации.

**Приоритет выполнения** — иерархия источников конфигурации, где параметры запуска (Runtime) всегда имеют преимущество над параметрами сборки (Build time).

## Основные концепции

### Золотое правило приоритетов

Инструменты запуска всегда имеют приоритет над инструкциями образа:
1. Аргументы `docker run` или параметры в `docker-compose.yml`.
2. Инструкции в `Dockerfile`.

### Таблица взаимодействия ENTRYPOINT и CMD

При переопределении одной из инструкций итоговая команда формируется следующим образом:

| Ситуация | ENTRYPOINT (Dockerfile) | CMD (Dockerfile) | Переопределение (Runtime) | Итоговая команда |
| :--- | :--- | :--- | :--- | :--- |
| Без переопределения | `["entry"]` | `["cmd"]` | — | `entry cmd` |
| Переопределение CMD | `["entry"]` | `["cmd"]` | `command: ["new"]` | `entry new` |
| Переопределение ENTRYPOINT | `["entry"]` | `["cmd"]` | `entrypoint: ["new"]` | `new` |
| Переопределение обоих | `["entry"]` | `["cmd"]` | `EP: ["e"], CMD: ["c"]` | `e c` |

> **Важно:** Переопределение `ENTRYPOINT` через флаг `--entrypoint` или директиву `entrypoint:` приводит к полной потере параметров, указанных в оригинальной инструкции `CMD` образа.

## Практические сценарии

### Сценарий 1: Изменение цели выполнения (ping)

Если образ настроен на выполнение конкретной утилиты через `ENTRYPOINT`, аргументы запуска заменяют дефолтный `CMD`.

**Dockerfile:**
```dockerfile
FROM alpine:3.20
ENTRYPOINT ["ping", "-c", "3"]
CMD ["localhost"]
```

**Запуск с переопределением:**
```bash
# Вместо localhost будет пинговаться google.com
docker run my-ping google.com
```

### Сценарий 2: Отладка через смену ENTRYPOINT

Для входа в контейнер, где `ENTRYPOINT` настроен на запуск приложения, используется флаг `--entrypoint`.

**Команда CLI:**
```bash
docker run -it --entrypoint /bin/sh my-app-image
```

**Docker Compose:**
```yaml
services:
  app:
    image: my-app-image
    entrypoint: /bin/sh
    command: -c "ls -la /app && sleep 3600"
```

### Сценарий 3: Переопределение пользователя (USER)

Полезно для выполнения административных действий в контейнере, который по умолчанию запускается от непривилегированного пользователя.

```bash
# Запуск от root вместо пользователя, указанного в Dockerfile
docker run -u root my-secure-image id
```

### Сценарий 4: Изменение рабочей директории (WORKDIR)

Позволяет запустить команду в другом каталоге без изменения самого образа.

```bash
docker run -w /var/log my-app ls -lh
```

### Сценарий 5: Подмена переменных окружения (ENV)

Директивы запуска полностью заменяют значения переменных из `Dockerfile`.

**docker-compose.yml:**
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_PASSWORD=new_secret_password # Переопределяет значение из образа
```

### Сценарий 6: Комбинированное переопределение в CI/CD

Использование отдельного Compose-файла для запуска тестов в том же окружении, что и приложение.

**compose.test.yml:**
```yaml
services:
  sut: # System Under Test
    image: my-app:latest
    entrypoint: pytest
    command: tests/integration/
    environment:
      - DB_HOST=test-db
```

### Сценарий 7: Использование Override-файлов

В Docker Compose файлы `docker-compose.override.yml` автоматически объединяются с основным файлом, переопределяя его параметры для локальной разработки.

**docker-compose.override.yml:**
```yaml
services:
  web:
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app # Монтирование кода для hot-reload
```

## Дополнительная информация

- **[Инструкции выполнения: CMD, ENTRYPOINT и USER](./runtime_execution.md)** — детальное описание механики работы инструкций внутри образа.
- **[Директивы Docker Compose](../../Docker_compose/docker_compose_directives.md)** — справочник по переопределению параметров в YAML.
- **[Команды Docker CLI](../../docker_commands.md)** — подробнее о флагах `-u`, `-w`, `-e` и `--entrypoint`.
- **[Переменные окружения](./environment_variables.md)** — работа с `ENV` и `ARG`.
