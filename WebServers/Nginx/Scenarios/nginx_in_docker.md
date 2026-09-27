# Nginx в Docker: эксплуатация контейнерного веб-сервера

## Определения

**Официальный образ Nginx** — `nginx` из Docker Hub, поддерживаемый Nginx Inc. Образ основан на Debian/Ubuntu (для сборок `mainline`/`stable`) и Alpine, запускает Nginx как процесс **PID 1** в контейнере.

Запуск даемонного Nginx в контейнере отличается от bare metal: **нельзя** запускать master-воркеры через `systemd`, логи и сигналы привязаны к жизненному циклу контейнера, конфигурация подключается через volumes, а управление ведётся сигналами `docker stop`/`docker exec`.

## Основные концепции

### Процессная модель и PID 1

- Официальный образ запускает команду `nginx -g 'daemon off;'` — Nginx работает в **foreground**, потому что контейнер живёт, пока жив PID 1.
- `daemon on (default)` приведёт к тому, что master-процесс уйдёт в фон, PID 1 завершится, и Docker остановит контейнер (нет процессов — контейнер «мёртв»).
- Signals: `docker stop` посылает `SIGTERM` процессу PID 1. Для корректного graceful shutdown Nginx в `entrypoint` официального образа обрабатывает `SIGQUIT`, `SIGTERM` и `SIGWINCH` через `trap`. В итоге `docker stop` выполняет плавное завершение (как `nginx -s quit`).

### Логи

- Официальный образ пишет `access.log` и `error.log` в **stdout/stderr** (symlink на `/dev/stdout`), поэтому логи доступны через `docker logs` без настройки.
- Для централизованного сбора использовать `docker logs` напрямую или JSON-лог в stdout — без файлов внутри контейнера.

### Конфигурация

- Конфиг подключается volumes (`/etc/nginx/`), либо через `docker config`/секреты (Swarm/K8s).
- Предпочтителен подход **immutable**: образ собирается с готовым конфигом, а не меняется на лету `docker exec`.
- При изменении конфига применить его можно `docker exec nginx nginx -t && docker exec nginx nginx -s reload` (без пересоздания контейнера).

### Непрерывная работа и healthcheck

- Для мониторинга добавляют `HEALTHCHECK` с curl к `/healthz` (требует поставить `curl` или использовать `wget`).
- Nginx как reverse proxy внутри Compose/Swarm обычно не перезапускается при падении бэкенда — это делает приложение; Nginx перезапускается только по политике `restart`.

## Практические сценарии

### Сценарий 1: Минимальный reverse proxy на официальном образе

```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    restart: unless-stopped
```

Проверка:

```bash
docker compose up -d
curl -I http://localhost:8080
# → HTTP/1.1 200 OK
```

### Сценарий 2: Конфигурация с worker_processes auto и не-root пользователем

```nginx
# nginx.conf
worker_processes auto;

events { worker_connections 1024; }

http {
    include /etc/nginx/mime.types;

    server {
        listen 80;
        server_name _;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
}
```

Запуск от непривилегированного пользователя (без прав на `:80` — используйте порт `>=1024` или `user` + `listen 8080`):

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    user: "101:101"          # non-root (nginx uid/gid в образе)
    ports:
      - "8080:8080"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

### Сценарий 3: Dockerfile с предустановленным конфигом (immutable)

```dockerfile
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY ssl /etc/nginx/ssl
COPY html /usr/share/nginx/html
EXPOSE 80 443
STOPSIGNAL SIGQUIT   # гарантировать graceful shutdown
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -q --spider http://127.0.0.1/ || exit 1
```

> `STOPSIGNAL SIGQUIT` — к официальному entrypoint'у, который транслирует `SIGQUIT` в `nginx -s quit`, даёт плавное завершение соединений вместо немедленного `SIGTERM`.

### Сценарий 4: Reload конфига без пересоздания контейнера

```bash
docker cp nginx.conf.example nginx:/etc/nginx/nginx.conf
docker exec nginx nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
docker exec nginx nginx -s reload
# → signal reload started (старые воркеры завершаются плавно)
```

### Сценарий 5: Логи в stdout + ротация на хосте

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
```

Логи агрегируются логирующим драйвером Docker; если нужен централизованный анализ — используйте JSON-формат `log_format ... escape=json` и Filebeat/Loki.

### Сценарий 6: Автоподхват сертификатов Let's Encrypt (цикл reload)

В контейнере нельзя повесить reload на systemd-таймер — используется фоновый цикл в entrypoint:

```bash
#!/bin/sh
trap 'nginx -s quit; exit 0' TERM QUIT INT
nginx -g 'daemon off;' &
while :; do
  sleep 6h
  nginx -t && nginx -s reload
done &
wait
```

Более простой вариант — mount уже обновлённого `fullchain.pem` и `nginx -s reload` по событию из certbot на хосте.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker compose up -d` | Запуск стека |
| `docker compose logs -f nginx` | Просмотр логов |
| `docker exec nginx nginx -t` / `-s reload` | Проверка и перезагрузка конфига |
| `docker stop nginx` / `docker compose stop` | Graceful shutdown |
| `docker cp nginx.conf nginx:/etc/nginx/nginx.conf` | Подмена конфига на лету |
| `docker inspect nginx --format '{{.Config.Cmd}}'` | Проверка стартовой команды |
| `SS -tanp` на хосте | Проверка проброшенных портов |

## Устранение неполадок

### Контейнер мгновенно «умирает» или не стартует access

**Причина:** `daemon off;` не задан, или процесс перешёл в фон и PID 1 завершился.

**Решение:** используйте официальный entrypoint (он уже задаёт `daemon off;`) — не переопределяйте `command` на `nginx` без `-g 'daemon off;'`. Проверьте: `docker inspect --format '{{.Config.Cmd}}'`.

### `nginx: [emerg] bind() to 0.0.0.0:80 failed (13: Permission denied)`

**Причина:** запуск от non-root пользователя, а `listen 80` требует CAP_NET_BIND_SERVICE.

**Решение:** используйте порт `>=1024` (например `8080`), либо дайте capability `NET_BIND_SERVICE` (`cap_add`), либо оставьте root-процесс (менее безопасно).

### Healthcheck всегда fail

**Причина:** в образе нет `curl` (Alpine-варианты), либо `/healthz` не существует.

**Решение:** используйте `wget -q --spider` (доступен в образе) или команду через `bash -c` с установленным `curl`; убедитесь что `/healthz` возвращает 200.

### Логи не появляются в `docker logs`

**Причина:** в образе логи переопределены на файлы (`access_log /var/log/nginx/... access;`), а не stdout.

**Решение:** удалите переопределение `access_log`/`error_log` или явно укажите `access_log /dev/stdout`.

## Лучшие практики

- **Immutable конфиг:** собирайте образ с конфигом; не редактируйте файлы в живом контейнере.
- **`restart: unless-stopped`** для визуализации бизнес-значимых сервисов в Compose.
- **Non-root:** запускайте на портах >=1024 или с `cap_add: NET_BIND_SERVICE`, никогда не давайте контейнеру лишних capabilities.
- **Graceful shutdown** через `STOPSIGNAL SIGQUIT` и корректные `trap` в entrypoint.
- **Тестируйте конфиг перед reload:** `nginx -t` обязателен перед `docker exec nginx -s reload`.
- **Логируйте в stdout** и настраивайте ротацию на уровне Docker logging driver, а не внутри контейнера.
- Для production держите Nginx как отдельный сервис перед приложением (не в одном контейнере с приложением).

## Дополнительная информация

### Связанные темы

- **[Nginx как reverse proxy для Grafana](../Scenarios/nginx_as_reverse_proxy_for_grafana.md)** — пример рабочего прокси-стека.
- **[Настройка Let's Encrypt с Nginx](../Scenarios/nginx_with_letsencrypt.md)** — Docker Compose-сценарий с обновлением сертификатов.
- **[Диагностика Nginx](../Operations/nginx_troubleshooting.md)** — общие методы диагностики состояния сервиса.