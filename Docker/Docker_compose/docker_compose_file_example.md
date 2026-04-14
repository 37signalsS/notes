# Пример файла compose.yml: Веб-приложение + База данных

## Определения

Файл `compose.yml` является центральным файлом конфигурации для приложений Docker Compose. Этот документ демонстрирует практическое применение директив на классическом примере стека "веб-приложение + база данных".

Все объяснения синтаксиса вынесены в документы, на которые даются ссылки.

## Базовые концепции

### Структура файла compose.yml

Файл `compose.yml` состоит из следующих основных секций:

- **`version`** — версия спецификации Compose (в современных версиях Docker Compose v2 не обязательна)
- **`name`** — имя проекта, используемое как префикс для ресурсов
- **`services`** — определение контейнеров приложения
- **`networks`** — настройка сетей для связи между сервисами
- **`volumes`** — определение именованных томов для персистентного хранения
- **`secrets`** — управление секретами (пароли, ключи, токены)
- **`configs`** — передача конфигурационных файлов в контейнеры

### Ключевые практики

- **Healthcheck:** проверка готовности сервиса перед запуском зависимых сервисов
- **Secrets:** безопасная передача чувствительных данных без хранения в открытом виде
- **Volumes:** персистентное хранение данных, независимое от жизненного цикла контейнера
- **Networks:** изоляция сервисов в отдельных сетях для безопасности

## Практические сценарии

### Пример 1: Веб-приложение + PostgreSQL {#пример-1}

```yaml
version: '3.8'
name: my-app

services:
  web:
    build:
      context: .
    image: my-app-web:latest
    ports:
      - "127.0.0.1:8000:8000"
    networks:
      - app-net
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    networks:
      - app-net
    volumes:
      - db-data:/var/lib/postgresql/data
    secrets:
      - db_password
    env_file:
      - .env
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  db-data:

networks:
  app-net:
    driver: bridge

secrets:
  db_password:
    file: ./db_password.txt
```

### Разбор Примера 1

Этот `compose.yml` демонстрирует ключевые практики:

- **Управление зависимостями:** Сервис `web` стартует только после того, как `db` пройдет проверку `healthcheck`. Это реализовано через `depends_on` с условием `service_healthy`. Подробнее: [Справочник по директивам](./docker_compose_directives.md)

- **Управление секретами:** Пароль от базы данных не хранится в открытом виде, а передается через Docker Secrets. Подробнее: [Безопасное управление секретами в Docker](../Docker_security/secrets_management.md)

- **Персистентность данных:** Данные PostgreSQL хранятся в именованном томе `db-data`, что защищает их от потери при пересоздании контейнера. Подробнее: [Docker Volumes](../../Docker/Docker_fs/docker_volumes.md)

- **Сетевая изоляция:** Сервисы `web` и `db` общаются друг с другом по именам в изолированной сети `app-net`.

### Пример 2: Балансировка нагрузки — Nginx + Node.js + Redis

Сценарий: веб-приложение на Node.js, которое подсчитывает визиты через Redis. Nginx выступает как reverse proxy и балансировщик нагрузки между двумя экземплярами бэкенда.

**Структура проекта:**

```
nginx-nodejs-redis/
├── compose.yml
├── nginx/
│   ├── Dockerfile
│   └── nginx.conf
└── web/
    ├── Dockerfile
    ├── package.json
    └── server.js
```

**Файл `compose.yml`:**

```yaml
version: '3.8'
name: nginx-nodejs-redis

services:
  redis:
    image: redis:7-alpine
    networks:
      - app-network

  web1:
    build: ./web
    hostname: web1
    restart: unless-stopped
    networks:
      - app-network
    depends_on:
      redis:
        condition: service_started

  web2:
    build: ./web
    hostname: web2
    restart: unless-stopped
    networks:
      - app-network
    depends_on:
      redis:
        condition: service_started

  nginx:
    build: ./nginx
    ports:
      - "80:8080"
    networks:
      - app-network
    depends_on:
      - web1
      - web2

networks:
  app-network:
    driver: bridge
```

**Файл `nginx/nginx.conf`:**

```nginx
upstream backend {
    server web1:5000;
    server web2:5000;
}

server {
    listen 8080;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Файл `nginx/Dockerfile`:**

```dockerfile
FROM nginx:1.25-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/
```

**Файл `web/server.js`:**

```javascript
const http = require('http');
const redis = require('redis');

const client = redis.createClient({
  host: 'redis',
  port: 6379
});

const hostname = process.env.HOSTNAME || 'unknown';

const server = http.createServer(async (req, res) => {
  const count = await client.incr('visits');
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end(`Hostname: ${hostname}\nVisits: ${count}\n`);
});

server.listen(5000, () => {
  console.log(`Server running at http://${hostname}:5000/`);
});
```

**Файл `web/Dockerfile`:**

```dockerfile
FROM node:21-alpine
WORKDIR /usr/src/app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5000
CMD ["npm", "start"]
```

**Ключевые особенности данного примера:**

- **Балансировка нагрузки:** Nginx распределяет запросы между `web1` и `web2` через директиву `upstream`. Каждый запрос может попасть на любой из бэкендов (round-robin)
- **DNS-разрешение:** сервисы обращаются друг к другу по именам (`redis`, `web1`, `web2`), которые автоматически резолвятся внутри сети `app-network`
- **Счётчик визитов:** Redis хранит общий счётчик, увеличивающийся при каждом запросе к любому из бэкендов
- **Автоматическое масштабирование:** для добавления третьего экземпляра достаточно продублировать секцию `web3` и добавить его в `upstream` nginx-конфига

**Запуск:**

```bash
docker compose up -d --build
# → Собираются образы из ./web и ./nginx
# → Создаётся сеть app-network
# → Запускаются 4 контейнера
```

**Проверка работы:**

```bash
curl http://localhost
# → Hostname: web1
# → Visits: 1

curl http://localhost
# → Hostname: web2  (или web1, зависит от балансировки)
# → Visits: 2
```

**Остановка и очистка:**

```bash
docker compose down
# → Остановка и удаление всех контейнеров
# → Удаление сети app-network
```

> **Примечание:** данный пример упрощён для демонстрации концепции балансировки. Production-конфигурация с healthcheck, volumes, секретами и ограничением ресурсов представлена в [Примере 1](#пример-1) выше. Подробнее о проксировании в Nginx: [Nginx L4 Proxy](../../WebServers/Nginx/Proxy/nginx_l4_proxying.md).

## Дополнительная информация

### Вспомогательные файлы

#### Файл `.env` (неконфиденциальные данные)

```ini
# .env
# Используется для переменных, которые можно безопасно коммитить в Git
POSTGRES_USER=app_user
POSTGRES_DB=app_db
```

#### Файл `db_password.txt` (секрет)

```
# db_password.txt
<your_secret_password_here>
```

> **ВАЖНО:** Обязательно добавьте файл с секретом (в данном случае `db_password.txt`) в ваш `.gitignore`, чтобы он никогда не попал в систему контроля версий.

### См. также

- [Справочник по директивам compose.yml](./docker_compose_directives.md)
- [Безопасное управление секретами в Docker](../Docker_security/secrets_management.md)
- [Docker Volumes](../../Docker/Docker_fs/docker_volumes.md)
