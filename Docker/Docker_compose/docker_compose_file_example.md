# Примеры конфигурации compose.yml

## Определения

**Файл `compose.yml`** — центральный файл декларативного описания ресурсов в Docker Compose. В нем определяются сервисы, сети, тома, секреты, конфигурации и AI-модели, составляющие единый стек приложения.

Этот документ содержит эталонные примеры конфигураций для различных сценариев разработки и эксплуатации. Техническое описание каждой директивы представлено в [Справочнике по директивам](./docker_compose_directives.md).

## Базовые концепции

### Современный стандарт (Compose v5+)

В современных конфигурациях (начиная с 2025 года) приняты следующие стандарты:
- **Отсутствие версии:** поле `version: "3.x"` удалено.
- **Модульность:** активное использование `include` для разделения ответственности.
- **Инструменты разработки:** интеграция секции `develop` для автоматизации синхронизации кода.
- **Безопасность по умолчанию:** использование `secrets` и `configs` вместо переменных окружения для чувствительных данных.
- **Ресурсные ограничения:** обязательное использование `deploy.resources` для предотвращения деградации хоста.

## Практические сценарии

### Сценарий 1: Веб-приложение с базой данных и кэшем (Best Practice)

Классический стек с настроенным режимом разработки, проверками готовности и ротацией логов.

```yaml
name: production-ready-stack

services:
  database:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
      - POSTGRES_USER=app_user
      - POSTGRES_DB=app_db
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - backend_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d app_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    user: "1001:1001"
    depends_on:
      database:
        condition: service_healthy
    develop:
      watch:
        - action: sync
          path: ./backend/src
          target: /app/src
          initial_sync: true
    environment:
      - DB_HOST=database
      - REDIS_URL=redis://cache:6379
    networks:
      - backend_net
      - frontend_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M

  cache:
    image: redis:7.4-alpine
    networks:
      - backend_net

volumes:
  postgres_data:

networks:
  frontend_net:
  backend_net:
    internal: true

secrets:
  db_password:
    file: ./secrets/db_pass.txt
```

### Сценарий 2: AI-сервис с использованием секции models

Интеграция LLM-модели с поддержкой GPU.

```yaml
name: ai-assistant-project

services:
  inference-api:
    image: llama-cpp-python:latest
    ports:
      - "8080:8000"
    models:
      - path: ./models/llama-3-8b-q4.gguf
        target: /models/model.gguf
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - ai_net

networks:
  ai_net:
```

### Сценарий 3: Масштабируемый стек с Nginx (Load Balancing)

Балансировка нагрузки между несколькими экземплярами приложения.

```yaml
name: scalable-web-app

services:
  web:
    build: ./app
    restart: always
    deploy:
      replicas: 3
    networks:
      - web_net

  proxy:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - web
    networks:
      - web_net

networks:
  web_net:
```

### Сценарий 4: Корпоративный стек с профилями и модулями

Использование профилей для выборочного запуска инструментов мониторинга и отладки.

```yaml
name: enterprise-app

include:
  - path: ./infrastructure/monitoring.yml # Импорт сторонней конфигурации

services:
  app:
    image: my-corp-app:latest
    networks:
      - app_net

  debug-tools:
    image: nicolaka/netshoot
    profiles:
      - debug
    network_mode: "service:app"

networks:
  app_net:
```

### Сценарий 5: Стек для CI/CD тестирования

Конфигурация, оптимизированная для быстрого завершения после тестов.

```yaml
services:
  test-runner:
    build: .
    command: npm test
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:17-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
```
*Запуск:* `docker compose up --build --abort-on-container-exit --exit-code-from test-runner`

## Дополнительная информация

### Рекомендации по эксплуатации

- **Безопасность:** Файлы секретов (`secrets`) никогда не должны попадать в систему контроля версий (Git). Добавляйте их в `.gitignore`.
- **Права доступа:** Всегда стремитесь запускать контейнеры от имени не-root пользователя (`user: "1001:1001"`).
- **Сетевая изоляция:** Используйте `internal: true` для баз данных и внутренних сервисов, которым не нужен доступ в интернет.

### См. также

- **[Справочник по директивам](./docker_compose_directives.md)** — детальное описание ключей YAML.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — модульность, `include` и профили.
- **[Режим watch](./docker_compose_watch_mode.md)** — настройка горячей перезагрузки кода.
