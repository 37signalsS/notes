# Traefik с Docker Compose: Практическое руководство

Это руководство основано на материалах вебинара и представляет собой пошаговую инструкцию по настройке Traefik в качестве reverse proxy для ваших сервисов с использованием Docker Compose.

## 1. Основные концепции Traefik

Traefik — это современный reverse proxy и балансировщик нагрузки, созданный для упрощения работы с микросервисами. Его главная особенность — автоматическое обнаружение сервисов.

Ключевые компоненты:
- **EntryPoints (Точки входа):** Сетевые порты, которые принимают входящий трафик (например, `:80` для HTTP и `:443` для HTTPS).
- **Providers (Провайдеры):** Инструменты для обнаружения сервисов (например, Docker, Kubernetes, File). Traefik "слушает" провайдеров, чтобы найти новые сервисы.
- **Routers (Маршрутизаторы):** Правила, которые определяют, как направить трафик от точек входа к сервисам. Правила могут основываться на домене, пути, заголовках и т.д.
- **Services (Сервисы):** Представляют собой конечные приложения, которые обрабатывают трафик.
- **Middlewares (Посредники):** Компоненты, которые могут изменять запрос перед тем, как он достигнет сервиса (например, для аутентификации, редиректов, добавления заголовков).

## 2. Базовая настройка Traefik

Мы будем использовать два основных конфигурационных файла:
1.  `traefik.yml`: Статическая конфигурация (точки входа, провайдеры).
2.  `dynamic.yml`: Динамическая конфигурация (посредники, TLS-опции).

### Шаг 2.1: Структура проекта

Создадим следующую структуру директорий:
```
/
├── traefik/
│   ├── traefik.yml
│   └── dynamic.yml
├── docker-compose.yml
└── acme.json
```

- `acme.json`: Файл для хранения SSL-сертификатов от Let's Encrypt. Его нужно создать вручную и установить права `600`.

### Шаг 2.2: Статическая конфигурация (`traefik.yml`)

Этот файл определяет основные параметры работы Traefik. Он не изменяется во время работы.

```yaml
# traefik/traefik.yml

# Включаем Dashboard и API (в небезопасном режиме для простоты)
api:
  dashboard: true
  insecure: true

# Определяем точки входа для HTTP и HTTPS
entryPoints:
  http:
    address: ":80"
    # Настраиваем глобальный редирект с HTTP на HTTPS
    http:
      redirections:
        entryPoint:
          to: "https"
          scheme: "https"
  https:
    address: ":443"

# Настраиваем провайдеров
providers:
  # Провайдер Docker для автоматического обнаружения контейнеров
  docker:
    endpoint: "unix:///var/run/docker.sock"
    # Не открывать все контейнеры по умолчанию
    exposedByDefault: false
    # Указываем, в какой сети Traefik будет искать сервисы
    network: "traefik_net"
  # Файловый провайдер для подключения динамической конфигурации
  file:
    filename: "/etc/traefik/dynamic.yml"
    watch: true

# Настраиваем логирование
log:
  level: DEBUG # Используйте INFO или WARN для продакшена

# Настраиваем получение сертификатов от Let's Encrypt
certificatesResolvers:
  letsencrypt:
    acme:
      email: "your-email@example.com" # Укажите ваш email
      storage: "/etc/traefik/acme.json"
      # Используем HTTP-Challenge для верификации домена.
      # Traefik создаст временный эндпоинт для подтверждения владения доменом.
      httpChallenge:
        entryPoint: "http"
      # Для отладки можно использовать staging-сервер Let's Encrypt
      # caServer: "https://acme-staging-v02.api.letsencrypt.org/directory"
```

### Шаг 2.3: Динамическая конфигурация (`dynamic.yml`)

Здесь мы можем определять общие для всех сервисов элементы, например, middleware.

```yaml
# traefik/dynamic.yml

http:
  middlewares:
    # Middleware для базовой аутентификации (пример)
    # Сгенерировать строку можно с помощью htpasswd
    # echo $(htpasswd -nb admin your_password) | sed -e s/\\$/\\$\\$/g
    basic-auth:
      basicAuth:
        users:
          - "admin:$$apr1$$...$$..." # Замените на вашу сгенерированную строку
```

### Шаг 2.4: `docker-compose.yml` для Traefik

Это основной файл, который запускает сам Traefik.

```yaml
# docker-compose.yml

version: '3.8'

services:
  traefik:
    image: traefik:v2.7 # Рекомендуется использовать конкретную версию
    container_name: traefik
    restart: always
    ports:
      - "80:80"
      - "443:443"
      # Порт для Dashboard (опционально, если insecure=true)
      # - "8080:8080"
    volumes:
      # Подключаем сокет Docker для обнаружения сервисов
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      # Подключаем статическую конфигурацию
      - "./traefik/traefik.yml:/etc/traefik/traefik.yml:ro"
      # Подключаем динамическую конфигурацию
      - "./traefik/dynamic.yml:/etc/traefik/dynamic.yml:ro"
      # Подключаем хранилище сертификатов
      - "./acme.json:/etc/traefik/acme.json"
    networks:
      - traefik_net

    labels:
      # Включаем Traefik для самого себя, чтобы открыть Dashboard
      - "traefik.enable=true"

      # --- Маршрутизатор для Dashboard (HTTPS) ---
      - "traefik.http.routers.dashboard.rule=Host(`traefik.your-domain.com`)"
      - "traefik.http.routers.dashboard.entrypoints=https"
      - "traefik.http.routers.dashboard.tls=true"
      - "traefik.http.routers.dashboard.tls.certresolver=letsencrypt"
      # Указываем, что этот роутер ведет на внутренний сервис API
      - "traefik.http.routers.dashboard.service=api@internal"
      # Применяем middleware для базовой аутентификации из файла
      - "traefik.http.routers.dashboard.middlewares=basic-auth@file"

networks:
  traefik_net:
    # Сеть должна быть создана заранее: docker network create traefik_net
    external: true
```

## 3. Добавление сервисов за Traefik

Теперь добавим в `docker-compose.yml` другой сервис (например, Nginx) и настроим для него маршрутизацию через Traefik.

> **`ports` vs `expose`**
> - **`ports`**: Публикует порт контейнера на хост-машине. Это делает сервис доступным извне напрямую, в обход Traefik.
> - **`expose`**: "Открывает" порт только для других контейнеров в той же Docker-сети, но не публикует его на хосте. Это идеальный вариант для сервисов, которые должны быть доступны только через Traefik.

```yaml
# docker-compose.yml (продолжение)

  # ... сервис traefik ...

  nginx:
    image: nginx:1.21
    container_name: nginx_app
    restart: always
    networks:
      - traefik_net
    # Открываем порт 80 только внутри сети Docker
    expose:
      - "80"
    labels:
      - "traefik.enable=true"
      # Указываем, что Traefik должен использовать эту сеть для данного сервиса
      - "traefik.docker.network=traefik_net"

      # --- Маршрутизатор для сервиса (HTTPS) ---
      # Имя роутера (nginx-https) может быть любым
      - "traefik.http.routers.nginx-https.rule=Host(`app.your-domain.com`)"
      - "traefik.http.routers.nginx-https.entrypoints=https"
      - "traefik.http.routers.nginx-https.tls=true"
      - "traefik.http.routers.nginx-https.tls.certresolver=letsencrypt"
      
      # Привязка к сервису и указание порта
      - "traefik.http.services.nginx-service.loadbalancer.server.port=80"
```

### Разбор лейблов для сервиса `nginx`:

- `traefik.enable=true`: "Включает" этот контейнер для Traefik.
- `traefik.docker.network=traefik_net`: Явно указывает Traefik, по какой сети обращаться к этому контейнеру. Это полезно, если контейнер подключен к нескольким сетям.
- `traefik.http.routers.nginx-https.rule=Host(...)`: Создает роутер `nginx-https` для домена `app.your-domain.com`.
- `traefik.http.routers.nginx-https.entrypoints=https`: Указывает, что роутер работает на точке входа `https`.
- `traefik.http.routers.nginx-https.tls.certresolver=letsencrypt`: Включает SSL и указывает использовать резолвер `letsencrypt` для получения сертификата.
- `traefik.http.services.nginx-service.loadbalancer.server.port=80`: Traefik будет направлять трафик на порт `80` внутри этого контейнера. Имя `nginx-service` здесь произвольное.
- `...@file`: Суффикс `@file` (как в `basic-auth@file`) указывает, что `middleware` определен в файловом провайдере (`dynamic.yml`). Если бы он был определен через лейблы, использовался бы суффикс `@docker`.

## 4. Запуск

1.  Убедитесь, что DNS-записи для `traefik.your-domain.com` и `app.your-domain.com` указывают на IP-адрес вашего сервера.
2.  Создайте сеть: `docker network create traefik_net`
3.  Создайте файл `acme.json` и установите права:
    ```bash
    touch acme.json
    chmod 600 acme.json
    ```
4.  Запустите все сервисы:
    ```bash
    docker-compose up -d
    ```

После запуска Traefik автоматически обнаружит сервис `nginx`, получит для него SSL-сертификат и начнет маршрутизировать трафик. Dashboard будет доступен по адресу `https://traefik.your-domain.com`.

## 5. Продвинутые темы

### Сквозное шифрование (End-to-End Encryption)

По умолчанию, трафик между Traefik и вашим сервисом (например, `nginx`) идет по HTTP без шифрования. Это приемлемо, так как они находятся в одной изолированной Docker-сети. Однако для повышения безопасности можно настроить сквозное шифрование (HTTPS от клиента до Traefik и от Traefik до сервиса).

Для этого необходимо:
1.  Настроить ваш сервис (Nginx, Apache) на работу по HTTPS с самоподписанным или полноценным сертификатом.
2.  Извлечь сертификаты, полученные Traefik от Let's Encrypt, и использовать их в ваших сервисах.

### Извлечение сертификатов из `acme.json`

Traefik хранит сертификаты в файле `acme.json`. Чтобы использовать их в других сервисах, их нужно извлечь в стандартном формате (`.crt`, `.key`). Для этого существуют сторонние утилиты, например, `traefik-certs-dumper`.

Пример добавления `certs-dumper` в `docker-compose.yml`:

```yaml
  certs-dumper:
    image: ldez/traefik-certs-dumper:v2.7.0
    container_name: certs_dumper
    restart: always
    volumes:
      # Подключаем acme.json от Traefik
      - "./acme.json:/traefik/acme.json:ro"
      # Директория, куда будут складываться извлеченные сертификаты
      - "./certs:/dump"
    networks:
      - traefik_net
    command: >
      --source.file.path=/traefik/acme.json
      --dest.path=/dump
      --watch
```

После запуска этот контейнер будет отслеживать изменения в `acme.json` и автоматически извлекать/обновлять сертификаты в папку `./certs`, откуда их уже могут подхватить ваши бэкенд-сервисы.
