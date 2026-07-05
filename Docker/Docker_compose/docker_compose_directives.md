# Справочник по директивам Docker Compose

## Определения

**Директивы Docker Compose** — это ключевые инструкции в файле `compose.yml`, которые определяют, как Docker должен управлять запуском, конфигурацией и взаимодействием многоконтейнерных приложений. Они делятся на директивы верхнего уровня (определяющие проект) и директивы уровня сервиса.

## Базовые концепции

### Директивы верхнего уровня

Эти директивы находятся в корне `compose.yml` и определяют глобальные настройки проекта.

- **`name`**: Задает имя проекта, которое используется как префикс для контейнеров, сетей и томов. Если не указано, используется имя директории.
- **`networks`**: Определяет именованные сети для всего проекта.
- **`volumes`**: Определяет именованные тома. Подробнее в [**Docker Volumes**](../../Docker/Docker_fs/docker_volumes.md).
- **`secrets`**: Определяет внешние файлы секретов для использования в сервисах.
- **`configs`**: Аналогично `secrets`, но для неконфиденциальных конфигурационных файлов.

### Директивы уровня сервиса (`services`)

Ключевые директивы, используемые внутри секции `services`:

- **`image` vs. `build`**:
  - `image`: Указывает готовый образ из registry (например, `postgres:16`). Подробнее о развертывании БД через Compose — **[Развертывание PostgreSQL в Docker](../../Databases/PostgreSQL/Operations/docker_deployment.md)**.
  - `build`: Указывает параметры сборки образа локально.
    - **Короткая форма**: `build: .` (сборка из `Dockerfile` в текущей директории).
    - **Расширенная форма**:
      - `context`: Путь к директории, содержащей Dockerfile (относительный или абсолютный).
      - `dockerfile`: Имя альтернативного Dockerfile (если отличается от стандартного `Dockerfile`).
    ```yaml
    services:
      webapp:
        build:
          context: ./dir
          dockerfile: Dockerfile-alternate
    ```

- **`ports`**: Пробрасывает порты в формате `IP:ХОСТ_ПОРТ:КОНТЕЙНЕР_ПОРТ`.

- **`environment` и `env_file`**:
  - `environment`: Задает переменные окружения прямо в YAML (`environment: [ "POSTGRES_USER=user" ]`). **Не используйте для секретов.**
  - `env_file`: Загружает переменные из файла.

- **`secrets`**: Позволяет безопасно передавать в сервис секреты, определенные на верхнем уровне. Секреты монтируются как файлы в `/run/secrets/`.
  - > **Подробнее:** [**Безопасное управление секретами в Docker**](../Docker_security/secrets_management.md)

- **`volumes`**: Монтирует тома или bind-mount'ы в контейнер. `[ИМЯ_ТОМА_ИЛИ_ПУТЬ_НА_ХОСТЕ]:[ПУТЬ_В_КОНТЕЙНЕРЕ]`.

- **`networks`**: Подключает сервис к одной или нескольким сетям, определенным на верхнем уровне.

- **`depends_on`**: Определяет зависимости между сервисами. **Современный подход** — использование `condition`.
  - `condition: service_started`: Запустить после старта зависимого сервиса (поведение по умолчанию).
  - `condition: service_healthy`: **(Рекомендуется)** Запустить только после того, как зависимый сервис пройдет проверку `healthcheck`.
  - `condition: service_completed_successfully`: Ожидать успешного завершения (код 0) зависимого сервиса (для миграций, тестовых задач).
  - > **Исторический контекст:** В ранних версиях формата v3 поддержка `condition` временно отсутствовала, что привело к появлению практик с `wait-for-it.sh`. Сейчас они не рекомендуются. Подробнее в [**сравнении версий**](docker_compose_versions_comparison.md).

- **`command` и `entrypoint`**: Переопределяют `CMD` и `ENTRYPOINT` из `Dockerfile` образа.
  - Подробнее: [Инструкции Dockerfile: ENTRYPOINT vs CMD](../Dockerfile/Instructions/practical_scenarios.md).

- **`restart`**: Определяет политику перезапуска контейнера.
  - `no` — не перезапускать (по умолчанию).
  - `on-failure` — перезапуск только при ненулевом коде выхода (для одноразовых задач).
  - `always` — всегда, включая ручную остановку.
  - `unless-stopped` — перезапуск при любом падении, кроме ручной остановки. **Рекомендуется для production.**

- **`healthcheck`**: Позволяет Docker проверять работоспособность приложения. Крайне важен для `depends_on.condition: service_healthy`.
  - `start_period` — время после старта, в течение которого неудачные проверки не считаются ошибкой (приложению нужно время на инициализацию).
  - Если в образе нет `curl` (Alpine), используйте `wget`:
    ```yaml
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:8080/health || exit 1"]
    ```

- **`deploy.resources`**: Ограничения ресурсов контейнера (память, CPU).
  - `limits` — жёсткий потолок (при превышении памяти — OOMKilled).
  - `reservations` — гарантированный минимум.
  ```yaml
  deploy:
    resources:
      limits:
        memory: 512M
        cpus: "1.0"
      reservations:
        memory: 256M
  ```

- **`logging`**: Настройка драйвера и ротации логов. Без ротации JSON-файлы растут бесконтрольно.
  ```yaml
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"
  ```

- **`user`**: Запускает процесс от имени указанного пользователя (`user:group`).

## Практические сценарии

### Пример: Веб-приложение с PostgreSQL (Современный подход)

Пример файла `compose.yml`, демонстрирующий правильное использование директив, включая `depends_on` с `condition`. См. также расширенный [пример compose.yml](./docker_compose_file_example.md).

```yaml
name: my-web-app

services:
  database:
    image: postgres:16
    restart: unless-stopped
    env_file: ./.env
    secrets:
      - db_password
    environment:
      # Образ postgres умеет читать пароль из файла
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    volumes:
      - db_data:/var/lib/postgresql/data
    networks:
      - app_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 5

  web_app:
    build: .
    restart: on-failure:3
    ports:
      - "8000:8000"
    env_file: ./.env
    networks:
      - app_net
    # Гарантирует запуск ТОЛЬКО после полной готовности БД.
    # Скрипты wait-for-it.sh больше не нужны.
    depends_on:
      database:
        condition: service_healthy
    command: "python manage.py runserver 0.0.0.0:8000"

volumes:
  db_data:

networks:
  app_net:

secrets:
  db_password:
    file: ./db_password.txt
```

**Пояснение:** Сервис `web_app` не запустит свою `command` до тех пор, пока `healthcheck` сервиса `database` не завершится успешно. Это надежный и декларативный способ управления зависимостями.

## Дополнительная информация

### Связанные документы

- **[Сравнение версий Docker Compose](./docker_compose_versions_comparison.md)** — эволюция формата от v2/v3 к Compose Spec
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — интерполяция переменных, профили и масштабирование
- **[Пример compose.yml](./docker_compose_file_example.md)** — практические примеры конфигураций стеков
