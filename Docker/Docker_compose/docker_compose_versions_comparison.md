# Сравнение версий файла Docker Compose (v2 vs v3)

### Определения

Формат файла Docker Compose развивался, что привело к появлению нескольких версий, наиболее значимыми из которых являются v2 и v3. Основная причина этой эволюции — расширение функциональности Docker от инструмента для локальной разработки (`docker-compose`) до системы оркестрации контейнеров (`docker swarm`). Версия v3 была введена для лучшей интеграции с Docker Swarm, что привело к изменению синтаксиса для некоторых директив.

### Основные концепции

Ключевые различия между версиями v2.x и v3.x влияют на управление зависимостями и ресурсами.

#### 1. Управление зависимостями: `depends_on`

Это главное функциональное различие для локальной разработки (`docker compose up`).

-   **Версия 2.x:** Поддерживала опцию `condition: service_healthy`, которая заставляла сервис ожидать, пока его зависимость не только запустится, но и пройдет проверку `healthcheck`.
-   **Версия 3.x:** **Убрана поддержка** `condition`. Директива `depends_on` теперь гарантирует только **порядок запуска** сервисов, но не их фактическую готовность.

#### 2. Ограничение ресурсов: `cpu_shares`, `mem_limit` vs. `deploy`

-   **Версия 2.x:** Лимиты ресурсов задавались напрямую в сервисе через директивы `cpu_shares`, `mem_limit` и другие.
-   **Версия 3.x:** Эти директивы были **удалены**. Вместо них появилась секция `deploy`, предназначенная для `docker swarm`. **Важно:** `docker compose up` **игнорирует** секцию `deploy`. Она используется только командой `docker stack deploy` в Swarm-кластере.

### Практические сценарии

#### Миграция с v2 на v3

Рассмотрим, как адаптировать файл `docker-compose.yml` с v2 на v3.

**Пример `docker-compose.yml` (синтаксис v2):**

```yaml
# V2 SYNTAX
version: '2.4'
services:
  database:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
  
  web:
    image: my-app
    build: .
    mem_limit: 1g
    cpu_shares: 73
    depends_on:
      database:
        condition: service_healthy
```

**Тот же файл, адаптированный для v3:**
```yaml
# V3 SYNTAX
version: '3.8'
services:
  database:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    image: my-app
    build: .
    depends_on:
      - database
    command: >
      sh -c "./wait-for-it.sh database:5432 -- yarn start"
    deploy:
      resources:
        limits:
          cpus: '0.75' # Эквивалент cpu_shares
          memory: 1G
```

**Ключевые изменения при миграции:**

1.  **Ожидание сервиса:** Вместо `condition: service_healthy` в `command` сервиса `web` добавлен вызов скрипта `wait-for-it.sh`, который решает ту же задачу.
2.  **Лимиты ресурсов:** `mem_limit` и `cpu_shares` перенесены в секцию `deploy.resources`. Необходимо помнить, что эти настройки будут применены только при развертывании в Docker Swarm.

### Дополнительная информация

- **Рекомендация:** Для всех новых проектов используйте последнюю версию формата v3. Это стандарт индустрии.
- **Секция `deploy`:** Для более глубокого понимания всех возможностей секции `deploy` (например, `replicas`, `update_config`) обратитесь к [официальной документации Docker](https://docs.docker.com/compose/compose-file/deploy/).
