# Пример файла compose.yml

## Определения

Файл `compose.yml` (или `docker-compose.yml`) является центральным файлом конфигурации для приложений, управляемых с помощью Docker Compose. В нем описывается набор сервисов, сетей и томов, которые составляют приложение. Этот декларативный подход позволяет определять и запускать сложные многоконтейнерные приложения одной командой.

## Практические сценарии

### Пример: Веб-приложение с базой данных

Рассмотрим типичный пример `compose.yml` для веб-приложения (`web`) и базы данных PostgreSQL (`database`).

-   **Изолированная сеть:** Сервисы работают в общей сети `app-network`, что позволяет им общаться друг с другом по именам (`web`, `database`).
-   **Персистентность данных:** Данные базы хранятся в именованном томе `db-data`, что защищает их от удаления при пересоздании контейнера.
-   **Управление зависимостями:** Сервис `web` стартует только после того, как `database` пройдет проверку работоспособности (`healthcheck`).
-   **Конфигурация через `.env`:** Чувствительные данные (пароли, ключи API) вынесены в отдельный файл `.env`.

```yaml
# Имя проекта, которое будет использоваться как префикс для контейнеров, сетей и томов.
name: taxi-app

services:
  web:
    # Собирает образ локально из Dockerfile в текущей директории.
    build: .
    # Присваивает имя локально собранному образу.
    image: my-taxi-app
    # Политика перезапуска: всегда перезапускать контейнер, если он остановился.
    restart: always
    # Загружает переменные окружения из файла .env.
    env_file:
      - .env
    # Проброс портов: IP:ХОСТ_ПОРТ:КОНТЕЙНЕР_ПОРТ.
    ports:
      - "100.64.0.13:3845:3000"
    networks:
      - app-network
    # Указывает, что этот сервис зависит от сервиса 'database'.
    depends_on:
      database:
        # Условие: запустить 'web' только после того, как 'database' станет 'healthy'.
        condition: service_healthy
    # Проверка работоспособности приложения внутри контейнера.
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://127.0.0.1:3000/api/health || exit 1"]
      interval: 10s
      start_period: 30s

  database:
    # Использует готовый образ PostgreSQL с расширениями ParadeDB.
    image: paradedb/paradedb:0.20.0-pg17
    restart: always
    env_file:
      - .env
    ports:
      - "100.64.0.13:3856:5432"
    networks:
      - app-network
    # Монтирует именованный том 'db-data' для хранения данных PostgreSQL.
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 30s
      retries: 3
      start_period: 80s

# Определение сетей, используемых в проекте.
networks:
  app-network:
    driver: bridge

# Определение томов для персистентного хранения данных.
volumes:
  db-data:
    driver: local
```

### Файл `.env` для конфигурации

> **ВАЖНО:** Никогда не храните пароли, токены и другие секреты прямо в `compose.yml`. Используйте для этого `.env` файл и добавьте его в `.gitignore`, чтобы избежать случайной компрометации.

```ini
# .env

# Учетные данные для PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_strong_password_here
POSTGRES_DB=taxi

# Секретный ключ для веб-приложения
API_KEY=some_secret_key
```

## Дополнительная информация

Этот пример использует множество директив Docker Compose. Для получения подробной информации о каждой из них (`build`, `restart`, `healthcheck`, `depends_on` и т.д.) обратитесь к основному справочнику:
-   **[Директивы Docker Compose](./docker_compose_directives.md)**

Для более глубокого понимания механизма работы томов (volumes) и их жизненного цикла:
-   **[Docker Volumes](../../Docker/Docker_fs/docker_volumes.md)**