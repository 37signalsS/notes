# Traefik Overview

Traefik — это современный обратный прокси и балансировщик нагрузки, который упрощает развертывание микросервисов. Его ключевая особенность — автоматическое и динамическое обнаружение сервисов (Service Discovery).

## Интеграция с Docker Swarm

Traefik идеально интегрируется с Docker Swarm, позволяя автоматически управлять маршрутизацией трафика к контейнерам.

### Основные принципы:

1.  **Service Discovery:** Traefik прослушивает Docker API, чтобы обнаруживать запущенные контейнеры.
2.  **Динамическая конфигурация:** Когда новый контейнер с определенными метками (labels) запускается, Traefik автоматически создает для него маршрут и, при необходимости, получает SSL-сертификат.
3.  **Маршрутизация на основе меток:** Конфигурация для каждого сервиса определяется с помощью меток в файле `docker-compose.yaml`.

### Пример конфигурации Traefik в `docker-compose.yaml`

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.5
    command:
      - "--api.insecure=true"
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedByDefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.myresolver.acme.httpchallenge=true"
      - "--certificatesresolvers.myresolver.acme.httpchallenge.entrypoint=web"
      - "--certificatesresolvers.myresolver.acme.email=${LETSENCRYPT_EMAIL}"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080" # Для дашборда
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./letsencrypt:/letsencrypt"
    networks:
      - internal

networks:
  internal:
    external: true
```

### Пример конфигурации сервиса для Traefik

Чтобы Traefik начал маршрутизировать трафик на ваш сервис, необходимо добавить специальные метки в `docker-compose.yaml` этого сервиса.

```yaml
services:
  my-app:
    image: my-app-image:latest
    networks:
      - internal
    deploy:
      replicas: 1
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.my-app.rule=Host(${APP_DOMAIN})
        - "traefik.http.routers.my-app.entrypoints=websecure"
        - "traefik.http.routers.my-app.tls.certresolver=myresolver"
        - "traefik.http.services.my-app.loadbalancer.server.port=80"
        - "traefik.http.routers.my-app-http.rule=Host(${APP_DOMAIN})
        - "traefik.http.routers.my-app-http.entrypoints=web"
        - "traefik.http.routers.my-app-http.middlewares=redirect-to-https"
        - "traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https"
```

**Описание меток:**

*   `traefik.enable=true`: Включает Traefik для этого сервиса.
*   `traefik.http.routers.my-app.rule=Host(${APP_DOMAIN})`: Определяет правило маршрутизации (по доменному имени).
*   `traefik.http.routers.my-app.entrypoints=websecure`: Указывает, что роутер работает на HTTPS (порт 443).
*   `traefik.http.routers.my-app.tls.certresolver=myresolver`: Указывает, какой resolver использовать для получения SSL-сертификатов (в данном случае, Let's Encrypt).
*   `traefik.http.services.my-app.loadbalancer.server.port=80`: Указывает порт, на котором работает приложение внутри контейнера.
*   `traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https`: Настраивает middleware для автоматического редиректа с HTTP на HTTPS.

## Автоматическое получение SSL-сертификатов с Let's Encrypt

Traefik может автоматически получать и обновлять SSL-сертификаты от Let's Encrypt. Для этого необходимо:

1.  Настроить `Certificate Resolver` в конфигурации Traefik.
2.  Указать email для уведомлений от Let's Encrypt.
3.  Подключить volume для хранения сертификатов (`acme.json`), чтобы они не терялись при перезапуске контейнера Traefik.
4.  В метках сервиса указать, что нужно использовать настроенный `certresolver`.

Эта функциональность избавляет от необходимости вручную управлять SSL-сертификатами, что значительно упрощает администрирование.

## Практические руководства

- **[Traefik с Docker Compose: Практическое руководство](./traefik_with_docker_compose.md)**: Пошаговая инструкция по настройке Traefik, сервисов, SSL и middleware с использованием Docker Compose.
