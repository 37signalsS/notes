# Traefik с Docker Compose: Практическое руководство

Это руководство представляет собой пошаговую инструкцию по настройке Traefik в качестве reverse proxy для ваших сервисов с использованием **[Docker Compose](../../Docker/Docker_compose/docker_compose_directives.md)**.

> Для понимания основных теоретических концепций Traefik (провайдеры, маршрутизаторы, сервисы) обратитесь к основной заметке: **[Traefik: Обзор](../traefik_overview.md)**.

---

## Определения

- **`traefik.yml` (Статическая конфигурация):** Основной конфигурационный файл Traefik, который определяет точки входа (entrypoints), провайдеров (providers) и другие параметры, не изменяющиеся во время работы.
- **`dynamic.yml` (Динамическая конфигурация):** Файл для определения динамических элементов, таких как middleware, которые могут быть применены к различным маршрутам. Traefik отслеживает изменения в этом файле без перезапуска.
- **`docker-compose.yml`:** Файл, описывающий и запускающий многоконтейнерные приложения. В данном контексте он используется для запуска самого Traefik и сервисов, которые будут за ним работать.
- **`acme.json`:** JSON-файл для хранения SSL-сертификатов, автоматически полученных от Let's Encrypt. Важно обеспечить ему правильные права доступа (`600`).

---

## Основные концепции

### Провайдер Docker и конфигурация через Labels

Traefik использует **провайдер Docker** для автоматического обнаружения контейнеров. Конфигурация маршрутизации, middleware и TLS для каждого сервиса задается с помощью **меток (labels)** прямо в `docker-compose.yml`.

- `traefik.enable=true`: "Включает" Traefik для данного контейнера.
- `traefik.http.routers.*`: Определяет правила маршрутизации.
- `traefik.http.services.*`: Настраивает, как Traefik должен подключаться к вашему сервису (например, указывает порт).
- `traefik.http.middlewares.*`: Применяет различные middleware (например, для аутентификации).

### `ports` vs `expose`

При работе с Traefik важно правильно определять порты в `docker-compose.yml`:

- **`expose`**: "Открывает" порт только для других контейнеров в той же Docker-сети, но не публикует его на хосте. **Это идеальный вариант** для сервисов, которые должны быть доступны *только* через Traefik.
- **`ports`**: Публикует порт контейнера на хост-машине, делая сервис доступным извне напрямую, в обход Traefik.

### HTTP-Challenge от Let's Encrypt

Для автоматического получения SSL-сертификатов используется `certificatesResolver` с методом **HTTP-Challenge**. Traefik автоматически создает временный маршрут и эндпоинт, чтобы Let's Encrypt мог проверить, что домен действительно указывает на ваш сервер. Этот процесс происходит без прерывания работы основных сервисов.

---

## Практический сценарий: Настройка Traefik и сервиса

Этот сценарий показывает, как запустить Traefik, защитить его Dashboard с помощью BasicAuth и опубликовать за ним веб-сервис (Nginx) с автоматическим получением SSL-сертификата.

### Шаг 1: Структура проекта и сеть

1. Создайте следующую структуру файлов и директорий:

    ```
    /
    ├── traefik/
    │   ├── traefik.yml
    │   └── dynamic.yml
    ├── docker-compose.yml
    └── acme.json
    ```

2. Создайте внешнюю Docker-сеть, через которую Traefik будет взаимодействовать с другими контейнерами:

    ```bash
    docker network create traefik_net
    ```

3. Создайте пустой файл `acme.json` и установите на него безопасные права доступа:

    ```bash
    touch acme.json
    chmod 600 acme.json
    ```

### Шаг 2: Статическая конфигурация (`traefik.yml`)

Этот файл настраивает точки входа, провайдеры и получение сертификатов.

```yaml
# traefik/traefik.yml

# Включаем Dashboard и API (в небезопасном режиме для демонстрации)
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
    exposedByDefault: false # Не открывать все контейнеры по умолчанию
    network: "traefik_net"  # Указываем, в какой сети искать сервисы
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

### Шаг 3: Динамическая конфигурация (`dynamic.yml`)

Здесь определим middleware для базовой аутентификации, который будем использовать для защиты Dashboard.

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

### Шаг 4: Основной `docker-compose.yml`

Этот файл запускает Traefik и пример сервиса `nginx`.

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
      - "traefik.http.routers.dashboard.service=api@internal" # Внутренний сервис API Traefik
      - "traefik.http.routers.dashboard.middlewares=basic-auth@file" # Middleware из файла dynamic.yml

  nginx:
    image: nginx:1.21
    container_name: nginx_app
    restart: always
    networks:
      - traefik_net
    expose: # Открываем порт только внутри Docker-сети
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
      # --- Сервис Traefik, указывающий на порт контейнера Nginx ---
      - "traefik.http.services.nginx-service.loadbalancer.server.port=80"

networks:
  traefik_net:
    external: true
```

### Шаг 5: Запуск

1. Убедитесь, что DNS-записи для `traefik.your-domain.com` и `app.your-domain.com` указывают на IP-адрес вашего сервера.
2. Запустите все сервисы:

    ```bash
    docker-compose up -d
    ```

    Подробнее о командах см. **[Основные команды docker compose](../../Docker/Docker_compose/docker_compose_cli_commands.md)**.

После запуска Traefik обнаружит сервис `nginx`, получит для него SSL-сертификат и начнет маршрутизировать трафик. Dashboard будет доступен по адресу `https://traefik.your-domain.com` после ввода логина и пароля.

---

## Дополнительная информация

### Сквозное шифрование (End-to-End Encryption)

По умолчанию, трафик между Traefik и вашим сервисом (`nginx`) идет по HTTP без шифрования. Это приемлемо, так как они находятся в одной изолированной **[сети Docker](../../Docker/Docker_network/docker_network.md)**. Однако для повышения безопасности можно настроить и шифрование на этом участке.

### Извлечение сертификатов из `acme.json`

Traefik хранит сертификаты в `acme.json`. Чтобы использовать их в других сервисах (например, для gRPC-сервера), их нужно извлечь в формате `.crt` и `.key`. Для этого существуют сторонние утилиты, например `traefik-certs-dumper`.

Пример добавления `certs-dumper` в `docker-compose.yml`:

```yaml
# ... (другие сервисы)

  certs-dumper:
    image: ldez/traefik-certs-dumper:v2.7.0
    container_name: certs_dumper
    restart: always
    volumes:
      - "./acme.json:/traefik/acme.json:ro" # Подключаем acme.json от Traefik
      - "./certs:/dump" # Директория, куда будут складываться сертификаты
    networks:
      - traefik_net
    command: >
      --source.file.path=/traefik/acme.json
      --dest.path=/dump
      --watch
```

Этот контейнер будет отслеживать `acme.json` и автоматически извлекать/обновлять сертификаты в папку `./certs`.
