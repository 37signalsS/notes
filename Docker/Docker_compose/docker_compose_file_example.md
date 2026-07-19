# Примеры конфигурации compose.yml

## Определения

**Файл `compose.yml`** — центральный файл декларативного описания ресурсов в Docker Compose. В нем определяются сервисы, сети, тома, секреты, конфигурации и AI-модели, составляющие единый стек приложения.

Этот документ содержит эталонные примеры конфигураций для различных сценариев разработки и эксплуатации. Техническое описание каждой директивы представлено в [справочнике по директивам](./docker_compose_directives.md).

## Базовые концепции

### Современный стандарт (Compose v5+)

В современных конфигурациях (начиная с 2025 года) приняты следующие стандарты:
- **Отсутствие версии:** поле `version: "3.x"` удалено и официально признано устаревшим.
- **Модульность:** активное использование `include` для разделения ответственности.
- **Инструменты разработки:** интеграция секции `develop` для автоматизации синхронизации кода.
- **Безопасность по умолчанию:** использование `secrets` и `configs` вместо переменных окружения для чувствительных данных.

## Практические сценарии

### Сценарий 1: Веб-приложение с базой данных и кэшем

Классический стек (Python/Node.js + PostgreSQL + Redis) с настроенным режимом разработки и проверками готовности.

```yaml
name: production-ready-stack

include:
  - path: ./infrastructure/networks.yml
  - path: ./infrastructure/volumes.yml

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

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile.dev
    depends_on:
      database:
        condition: service_healthy
      cache:
        condition: service_started
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

  cache:
    image: redis:7.4-alpine
    networks:
      - backend_net

secrets:
  db_password:
    file: ./secrets/db_prowd.txt
```

**Результат запуска:**
```bash
docker compose up -d
# → [OK] Network production-ready-stack_backend_net created
# → [OK] Volume production-ready-stack_postgres_data created
# → [OK] Service database: healthy
# → [OK] Service backend: started
```

### Сценарий 2: AI-сервис с использованием секции models

Пример интеграции LLM-модели в локальную среду разработки.

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
    driver: bridge
```

### Сценарий 3: Масштабируемый стек с Nginx (Load Balancing)

Балансировка нагрузки между несколькими экземплярами бэкенда.

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

**Конфигурация Nginx (`nginx.conf`):**
```nginx
upstream myapp {
    server web:5000; # Docker DNS автоматически распределит запросы между репликами
}

server {
    listen 80;
    location / {
        proxy_pass http://myapp;
    }
}
```

## Дополнительная информация

### Рекомендации по безопасности

1.  **Файлы секретов:** Никогда не фиксируйте файлы из секции `secrets` в Git. Добавьте их в `.gitignore`.
2.  **Пользователи:** Всегда указывайте директиву `user: "1000:1000"` в сервисах, если образ поддерживает запуск не от root.
3.  **Лимиты ресурсов:** В производственных конфигурациях всегда описывайте секцию `deploy.resources.limits` для предотвращения OOM (Out Of Memory) на хосте.

### См. также

- **[Справочник по директивам](./docker_compose_directives.md)** — описание всех ключей YAML.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — интерполяция переменных и YAML-якоря.
- **[Режим watch](./docker_compose_watch_mode.md)** — детали настройки горячей перезагрузки кода.
- **[Сравнение версий](./docker_compose_versions_comparison.md)** — почему мы больше не используем поле `version`.
