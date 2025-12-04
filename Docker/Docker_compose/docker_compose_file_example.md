# Пример файла `compose.yml`

Рассмотрим пример для веб-приложения (`web`) и базы данных (`database`), которые работают в общей изолированной сети(могу в ней общаться между собой по именнам сервисов присвоенных им, при помощи dns имени, например, db) и используют именованный том для хранения данных.

```yaml
# Имя проекта, которое будет использоваться как префикс
name: taxi-app

services:
  web:
    build: .
    image: my-taxi-app # Имя для локально собранного образа
    restart: always
    env_file:
      - .env
    ports:
      # Проброс портов: IP:ХОСТ_ПОРТ:КОНТЕЙНЕР_ПОРТ
      - "100.64.0.13:3845:3000"
    networks:
      - app-network
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://127.0.0.1:3000/api/health || exit 1"]
      interval: 10s
      start_period: 30s

  database:
    image: paradedb/paradedb:0.20.0-pg17
    restart: always
    # Переменные окружения загружаются из .env файла
    env_file:
      - .env
    ports:
      - "100.64.0.13:3856:5432"
    networks:
      - app-network
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 30s
      retries: 3
      start_period: 80s

networks:
  app-network:
    driver: bridge

volumes:
  db-data:
    driver: local
```

### Файл `.env` для секретов и конфигураций

> **ВАЖНО:** Никогда не храните пароли, токены и другие секреты прямо в `compose.yml`. Используйте для этого `.env` файл.

```ini
# .env

POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_strong_password_here
POSTGRES_DB=taxi

API_KEY=some_secret_key
```
