# Compose extends, include и правила слияния

## Определения

**extends** — директива Compose для наследования конфигурации сервиса из другого сервиса в том же или в другом файле. Позволяет определить базовый сервис и расширять его, переопределяя только изменяющиеся параметры. Частично признана устаревшей в пользу `include`, так как работает только на уровне сервисов и не импортирует ресурсы верхнего уровня (сети, тома, секреты). Максимальная глубина наследования — 10 уровней.

**include** — директива Compose (v2.20+) для импорта целых файлов инфраструктуры (сервисы, сети, тома, секреты) в текущий проект. Является современной заменой `extends`. Поддерживает как локальные файлы, так и OCI-артефакты из реестров. Все ресурсы импортируемого файла автоматически изолированы — они не конфликтуют с ресурсами основного проекта.

**Merge Rules** — правила разрешения конфликтов при комбинировании нескольких файлов конфигурации (через флаг `-f` или директиву `include`). Массивы (порты, переменные окружения) объединяются, скаляры (image, restart) заменяются последним значением, а карты (labels, deploy.resources) выполняют глубокое слияние.

**Extension Fields (x-)** — ключи YAML с префиксом `x-`, которые игнорируются парсером Compose, но могут быть использованы как переиспользуемые шаблоны конфигурации через YAML-якоря (`&anchor` и `*alias`). Позволяют централизованно определять общие настройки (метки, переменные окружения, ресурсы) и применять их к нескольким сервисам.

**Override File** — файл `compose.override.yml`, который автоматически загружается Compose вместе с основным `compose.yml` без необходимости указывать его в командной строке. Используется для локальных переопределений (разработка), которые не должны попадать в контроль версий.

**Template Inheritance** — паттерн проектирования конфигурации, при котором определяется базовый набор настроек (шаблон), который наследуется или расширяется другими сервисами. Реализуется через `extends`, `x-` поля с YAML-якорями или комбинацию нескольких compose-файлов.

## Базовые концепции

### 1. extends: синтаксис и механика

Директива `extends` работает на уровне сервиса и позволяет наследовать его конфигурацию от другого сервиса.

- **Базовый синтаксис:**
  ```yaml
  services:
    base-service:
      image: myapp:latest
      environment:
        - APP_ENV=production

    child-service:
      extends:
        service: base-service
      environment:
        - APP_PORT=8080
  ```

- **Наследование из внешнего файла:**
  ```yaml
  services:
    child-service:
      extends:
        file: docker-compose.base.yml
        service: base-service
  ```

- **Ограничения `extends`:**
  - Не наследует `build`, `image`, `links` (в новых версиях — `depends_on` частично).
  - Не импортирует ресурсы верхнего уровня (сети, тома, секреты).
  - Ссылки на именованные ресурсы (сеть, том, секрет) должны быть доступны в контексте наследника.
  - Максимальная глубина вложенности — 10 уровней.

### 2. include: синтаксис и механика

Директива `include` работает на уровне всего файла и импортирует инфраструктуру целиком.

- **Базовый синтаксис:**
  ```yaml
  include:
    - path: ./infrastructure/database.yml
    - path: ./infrastructure/monitoring.yml
  ```

- **Пути и переменные:**
  ```yaml
  include:
    - path: ./${ENVIRONMENT:-dev}/compose.yml
  ```

- **OCI-реестры (v2.20+):**
  ```yaml
  include:
    - oci: my-registry.com/project/base-config:v1.0.0
  ```

- **Разрешение путей:** относительные пути разрешаются относительно основного `compose.yml`, а не относительно импортирующего файла.

- **Изоляция ресурсов:** файлы, импортированные через `include`, получают автоматический namespace для ресурсов верхнего уровня. Сеть `backend_net` в `base.yml` и `backend_net` в `override.yml` — это разные ресурсы.

### 3. Правила слияния (Merge Rules)

При использовании нескольких compose-файлов (через `-f` или `include`) Compose применяет следующие правила:

- **Скаляры (image, hostname, restart, command):** последнее значение заменяет предыдущее.
  ```yaml
  # compose.yml
  services:
    app:
      image: myapp:v1

  # compose.prod.yml
  services:
    app:
      image: myapp:v2
  # Результат: image = myapp:v2
  ```

- **Массивы (ports, environment, volumes, extra_hosts):** значения объединяются без дедупликации.
  ```yaml
  # compose.yml
  services:
    app:
      ports:
        - "80:80"

  # compose.prod.yml
  services:
    app:
      ports:
        - "443:443"
  # Результат: ports = ["80:80", "443:443"]
  ```

- **Карты (labels, deploy.resources, logging):** выполняется глубокое слияние (deep merge).
  ```yaml
  # compose.yml
  services:
    app:
      deploy:
        resources:
          limits:
            memory: 512M

  # compose.prod.yml
  services:
    app:
      deploy:
        resources:
          limits:
            cpus: "1.0"
          reservations:
            memory: 256M
  # Результат: limits.memory = 512M, limits.cpus = "1.0", reservations.memory = 256M
  ```

- **Исключения (замена целиком):** некоторые ключи не сливаются, а заменяются полностью: `build`, `image`, `network_mode`.

### 4. Extension Fields (x-) как механизм шаблонов

Поля `x-` игнорируются парсером Compose, но доступны для переиспользования через YAML-якоря.

- **Базовый пример:**
  ```yaml
  x-common-env: &common-env
    APP_ENV: production
    LOG_LEVEL: info

  services:
    web:
      image: nginx
      environment:
        <<: *common-env
        SERVER_PORT: "80"

    api:
      image: myapi
      environment:
        <<: *common-env
        API_PORT: "8080"
  ```

- **Шаблон сервиса:**
  ```yaml
  x-base-service: &base-service
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  services:
    web:
      <<: *base-service
      image: nginx:alpine
      ports:
        - "80:80"

    api:
      <<: *base-service
      image: myapi:latest
  ```

- **Вложенное слияние с `<<`:** оператор `<<` выполняет поверхностное слияние для карт. При переопределении значения внутри вложенной карты используйте полное указание ключа.

### 5. compose.override.yml: автоматическая загрузка

Compose автоматически загружает `compose.override.yml` (если он существует) рядом с основным `compose.yml`.

- **Порядок приоритета (от низкого к высокому):**
  1. `compose.yml` — базовая конфигурация.
  2. `compose.override.yml` — автоматические переопределения.
  3. Файлы, указанные через `-f` — ручные переопределения.

- **Отключение автозагрузки:**
  ```bash
  docker compose --no-auto-compose -f compose.yml -f compose.dev.yml up
  ```

### 6. Сравнение подходов

| Критерий | extends | include | -f override | x- поля |
| :--- | :--- | :--- | :--- | :--- |
| Уровень | Сервис | Файл | Файл | YAML-якоря |
| Импорт ресурсов верхнего уровня | Нет | Да | Да | Нет |
| Изоляция ресурсов | Нет | Да | Нет | Нет |
| OCI-реестры | Нет | Да | Нет | Нет |
| Рекомендация | Точечное переиспользование | Модульность инфраструктуры | Локальные переопределения | Шаблоны конфигурации |

## Практические сценарии

### 1. extends: базовое использование

Наследование сервиса из того же файла с переопределением переменных окружения.

```yaml
services:
  base-app:
    image: myapp:latest
    restart: unless-stopped
    environment:
      - NODE_ENV=production
    volumes:
      - app-data:/app/data

  worker:
    extends:
      service: base-app
    command: node worker.js
    environment:
      - WORKER_CONCURRENCY=4
```

**Результат для `worker`:** image, restart, volumes наследуются, environment объединяется, command задан новый.

### 2. extends: наследование из внешнего файла

Базовый сервис определен в `docker-compose.base.yml`, наследник — в `compose.yml`.

**docker-compose.base.yml:**
```yaml
services:
  common-worker:
    image: myapp:latest
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
    logging:
      driver: json-file
      options:
        max-size: "10m"
```

**compose.yml:**
```yaml
services:
  email-worker:
    extends:
      file: docker-compose.base.yml
      service: common-worker
    command: node email-worker.js

  report-worker:
    extends:
      file: docker-compose.base.yml
      service: common-worker
    command: node report-worker.js
```

### 3. include: импорт инфраструктуры

Импорт целых compose-файлов с сервисами, сетями и томами.

**infrastructure/database.yml:**
```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5

  redis:
    image: redis:7.4-alpine

volumes:
  pg_data:
```

**compose.yml (основной):**
```yaml
include:
  - path: ./infrastructure/database.yml

services:
  app:
    build: .
    depends_on:
      - postgres
      - redis
```

### 4. include: импорт из OCI-реестра

```yaml
include:
  - oci: ghcr.io/my-org/common-configs/monitoring-stack:v2.1.0
  - path: ./local-overrides.yml

services:
  app:
    image: myapp:latest
    networks:
      - monitoring  # сеть из OCI-пакета автоматически доступна
```

**Преимущества:** версионирование конфигураций, переиспользование между проектами, централизованное обновление инфраструктуры.

### 5. Extension fields (x-) как шаблоны

```yaml
x-logging: &default-logging
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"

x-deploy: &default-deploy
  deploy:
    resources:
      limits:
        memory: 512M

services:
  web:
    image: nginx:alpine
    <<: *default-logging
    ports:
      - "80:80"

  api:
    build: ./api
    <<: *default-logging
    <<: *default-deploy
    ports:
      - "8080:8080"
```

### 6. Правила слияния: демонстрация

Демонстрация поведения при слиянии двух compose-файлов.

**compose.yml:**
```yaml
services:
  app:
    image: myapp:v1
    restart: no
    ports:
      - "80:80"
    environment:
      - APP_ENV=dev
    deploy:
      resources:
        limits:
          memory: 256M
```

**compose.prod.yml:**
```yaml
services:
  app:
    image: myapp:v2
    restart: unless-stopped
    ports:
      - "443:443"
    environment:
      - APP_PORT=8080
    deploy:
      resources:
        limits:
          cpus: "1.0"
```

**Запуск:** `docker compose -f compose.yml -f compose.prod.yml config`

**Итог:** image=v2 (скаляр), restart=unless-stopped (скаляр), ports=["80:80","443:443"] (массив), environment=["APP_ENV=dev","APP_PORT=8080"] (массив), limits={memory:256M, cpus:1.0} (deep merge).

### 7. Мульти-файловый состав с -f

Создание стека из нескольких compose-файлов для разных окружений.

**Структура проекта:**
```
project/
  compose.yml              # базовая конфигурация
  compose.override.yml     # локальная разработка (автозагрузка)
  compose.prod.yml         # продакшн
  compose.test.yml         # тестирование
```

**compose.yml:**
```yaml
services:
  app:
    build: .
    networks:
      - app_net

  db:
    image: postgres:16-alpine
    networks:
      - app_net

networks:
  app_net:
```

**compose.override.yml (автозагрузка):**
```yaml
services:
  app:
    volumes:
      - ./src:/app/src
    environment:
      - NODE_ENV=development
    develop:
      watch:
        - action: sync
          path: ./src
          target: /app/src
```

**compose.prod.yml:**
```yaml
services:
  app:
    image: registry.example.com/myapp:${TAG:-latest}
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 1G
```

**Запуск dev:** `docker compose up -d`
**Запуск prod:** `docker compose -f compose.yml -f compose.prod.yml up -d`

### 8. Продакшн-паттерн: base + dev + prod compose файлы

Полноценная схема организации конфигурации для проекта с разделением ответственности.

**compose.yml (общая):**
```yaml
include:
  - path: ./compose.monitoring.yml

services:
  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
    networks:
      - backend_net

  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5
    volumes:
      - pg_data:/var/lib/postgresql/data
    networks:
      - backend_net

volumes:
  pg_data:

networks:
  backend_net:
```

**compose.override.yml (dev):**
```yaml
services:
  app:
    volumes:
      - ./src:/app/src
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=development

  db:
    ports:
      - "5432:5432"
```

**compose.prod.yml (prod):**
```yaml
services:
  app:
    image: registry.example.com/myapp:${TAG:-latest}
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 1G
          cpus: "2.0"
    environment:
      - NODE_ENV=production

  db:
    deploy:
      resources:
        limits:
          memory: 2G
```

## Дополнительная информация

### Связанные документы

- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — интерполяция переменных, профили, расширенные поля.
- **[Справочник по директивам](./docker_compose_directives.md)** — детальное описание всех ключей YAML.
- **[Пример compose.yml](./docker_compose_file_example.md)** — готовые шаблоны конфигураций стеков.

### Миграция с extends на include

1. **Разделите файл:** вынесите базовый сервис в отдельный compose-файл.
2. **Добавьте `include`:** импортируйте этот файл через директиву `include`.
3. **Добавьте ресурсы верхнего уровня:** если базовый сервис использовал сети или тома, добавьте их в импортируемый файл.
4. **Удалите `extends`:** замените наследование на прямое использование импортированных сервисов.

```yaml
# Было (extends)
services:
  child:
    extends:
      file: base.yml
      service: worker

# Стало (include)
include:
  - path: ./base.yml

services:
  child:
    image: myapp:latest
    command: node child.js
```

### Частые ошибки и ограничения

- **`extends` + `networks`:** если базовый сервис ссылается на сеть, определенную в другом файле, она не импортируется автоматически. Используйте `include` вместо `extends`.
- **`include` + переопределение ресурсов:** ресурсы, импортированные через `include`, можно переопределять в основном файле, но нельзя удалять — только переопределять.
- **`x-` + `<<` оператор:** при использовании нескольких `<<` в одном сервисе выполняется последовательное слияние слева направо.
- **Глубина наследования `extends`:** Compose допускает максимальную глубину 10 уровней. При превышении — ошибка валидации.
- **OCI-реестры в `include`:** требуют Docker Compose v2.20+. Старые версии не поддерживают формат `oci:`.
- **`compose.override.yml` + CI/CD:** в CI-среде файл `compose.override.yml` может нежелательно переопределять настройки. Используйте `--no-auto-compose` или явно указывайте файлы через `-f`.
- **Массивы с одинаковыми значениями:** при слиянии массивов дедупликация не выполняется. Если `ports: ["80:80"]` есть в обоих файлах, в итоге будет два одинаковых порта.
