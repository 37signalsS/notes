# Инструкция Dockerfile: EXPOSE

## Определения

**Инструкция `EXPOSE`** — декларативная директива Dockerfile, которая информирует Docker о том, что контейнер будет прослушивать определенные сетевые порты во время выполнения. Она фиксирует "сетевой контракт" образа, описывая порты и протоколы, которые приложение внутри контейнера ожидает для взаимодействия.

**Публикация портов (Port Publishing)** — механизм проброса портов контейнера на хост-машину через флаги `-p` (явное указание) или `-P` (автоматическое назначение) при запуске контейнера. Это единственное действие, делающее порт доступным снаружи.

## Предварительные требования

Для понимания инструкции `EXPOSE` необходимо:

- **Docker** версии 20.10 или новее.
- Понимание базовых концепций: **[CMD и ENTRYPOINT](./runtime_execution.md)** (как приложение слушает порт), **[ENV и ARG](./environment_variables.md)** (динамическая конфигурация портов).
- Понимание разницы между **shell-form** и **exec-form** в `CMD`/`ENTRYPOINT` — приложение должно быть запущено в exec-form, чтобы корректно слушать порт (shell-form добавляет обёртку, которая может перехватывать сигналы).
- Базовые знания Linux-сети: TCP/UDP, привилегированные порты (<1024), интерфейсы (0.0.0.0 vs 127.0.0.1).

## Основные концепции

### Декларативная природа и метаданные

Инструкция `EXPOSE` является исключительно **информационной**. Она:
- Служит документацией для пользователей и инструментов автоматизации.
- Добавляет метаданные в конфигурацию образа (секция `Config.ExposedPorts`).
- **Не открывает** порты на хост-машине и не создает правила фильтрации трафика.
- Не гарантирует, что приложение действительно слушает указанный порт (это ответственность разработчика).

**Что НЕ делает EXPOSE:**
- Не публикует порты на хосте (для этого нужен `-p` или `-P`).
- Не настраивает файрвол или правила iptables.
- Не является обязательным для сетевого взаимодействия контейнеров.
- Не влияет на доступность приложения снаружи.

**Синтаксис:**

```dockerfile
# Один порт (TCP по умолчанию)
EXPOSE 80

# Порт с указанием протокола (TCP, UDP или SCTP)
EXPOSE 53/udp
EXPOSE 53/tcp
EXPOSE 2905/sctp

# Диапазон портов
EXPOSE 8000-8010/tcp

# Несколько значений в одной строке
EXPOSE 80 443/tcp 161/udp
```

### Влияние на кэширование и дайджест

Инструкция `EXPOSE` обладает уникальным поведением при сборке:
- **Кэш сборки:** Изменение `EXPOSE` не инвалидирует кэш для последующих инструкций (например, `RUN`), так как она не меняет файловую систему.
- **Image Digest:** Несмотря на сохранение кэша, изменение портов меняет JSON-конфигурацию образа. Это приводит к изменению **Image Digest (SHA256)**, что важно учитывать при использовании деплоя по дайджестам.

### EXPOSE и реальное прослушивание порта

Инструкция `EXPOSE` — это **контракт**, а не **реализация**. Приложение должно фактически слушать указанный порт:

```dockerfile
# ПРАВИЛЬНО: приложение слушает порт 8080
FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
EXPOSE 8080
CMD ["node", "src/server.js"]  # server.js слушает порт 8080

# ПЛОХО: EXPOSE не совпадает с реальным портом
FROM node:22-alpine
EXPOSE 3000  # Объявлен порт 3000
CMD ["node", "src/server.js"]  # Но server.js слушает порт 8080!
```

**Проверка слушающих портов в запущенном контейнере:**

```bash
# Просмотр всех слушающих TCP-портов
docker exec mycontainer ss -tlnp

# Или через netstat
docker exec mycontainer netstat -tlnp

# Проверка конкретного порта
docker exec mycontainer curl -sf http://localhost:8080/health
```

### Взаимодействие с IPv6 и Rootless Docker

- **IPv6:** Инструкция работает на уровне L4 (порты/протоколы) и не зависит от версии IP. Маршрутизация IPv6 настраивается на уровне Docker-демона. Для публикации портов на IPv6 используйте `-p [::]:8080:80`.
- **Rootless Docker:** В Rootless-режиме Docker не может пробрасывать порты ниже 1024 (privileged ports) на хост-интерфейсы без дополнительных настроек ОС (например, `sysctl net.ipv4.ip_unprivileged_port_start=0`). Рекомендуется использовать порты >= 1024 или настраивать sysctl.

### Влияние на кэширование слоёв

`EXPOSE` **не инвалидирует** кэш последующих инструкций, так как не модифицирует файловую систему. Однако изменение `EXPOSE` меняет конфигурацию образа и, следовательно, **Image Digest**:

```dockerfile
# Изменение EXPOSE не пересоздаёт кэш для后续 RUN
EXPOSE 80      # Слой 1: метаданные
RUN apt-get update  # Кэш не сброшен
EXPOSE 443     # Слой 2: метаданные (Digest изменился)
RUN apt-get install -y curl  # Кэш не сброшен
```

Это полезно знать при рефакторинге Dockerfile — изменение `EXPOSE` не требует пересборки зависимых слоёв.

### Сравнение: EXPOSE, -p и -P

| Метод | Где задается | Действие | Доступность |
| :--- | :--- | :--- | :--- |
| **`EXPOSE`** | `Dockerfile` | Документирует порты в образе | Внутри Docker-сетей |
| **`-p`** | `docker run` | Явно связывает порт хоста с портом контейнера | Внешний мир |
| **`-P`** | `docker run` | Пробрасывает все порты из `EXPOSE` на случайные порты хоста | Внешний мир |

**Подробный синтаксис `-p`:**

```bash
# Базовый формат: -p [host_ip:]host_port:container_port[/protocol]

# Привязка к конкретному интерфейсу (рекомендуется для безопасности)
docker run -p 127.0.0.1:8080:80 nginx   # Только localhost
docker run -p 0.0.0.0:8080:80 nginx     # Все интерфейсы (по умолчанию)

# Привязка к порту хоста с указанием протокола
docker run -p 8080:80/tcp nginx
docker run -p 53:53/udp dns-server
docker run -p 53:53/tcp -p 53:53/udp dns-server  # Оба протокола

# Случайный порт хоста (аналог -P для одного порта)
docker run -p 80 nginx
docker port <container>  # Узнать назначенный порт
```

> **Важно для Kubernetes:** K8s игнорирует `EXPOSE`. Вместо нее используется `containerPort` в манифестах Pod/Deployment. Тем не менее, `EXPOSE` рекомендуется для интеграции с инструментами анализа образов и Service Discovery в средах без Kubernetes.
## Практические сценарии

### Сценарий 1: Подготовка к автоматической публикации (-P)

Если вы не хотите вручную назначать порты хоста для каждой копии приложения, используйте флаг `-P` (uppercase):

```dockerfile
FROM nginx:alpine
EXPOSE 80
# Запуск: docker run -d -P nginx
# Docker сам найдет свободный порт на хосте и свяжет его с 80 портом внутри
```

**Просмотр назначенных портов:**

```bash
docker port <container_id>
# 80/tcp -> 0.0.0.0:32768
```

### Сценарий 2: Динамические порты через переменные

Для гибкости можно использовать `ARG` и `ENV` для задания портов:

```dockerfile
ARG DEFAULT_PORT=8080
ENV APP_PORT=${DEFAULT_PORT}
EXPOSE ${APP_PORT}
```

**Сборка с изменением порта:**

```bash
# Использование порта по умолчанию (8080)
docker build -t myapp .

# Переопределение порта при сборке
docker build --build-arg DEFAULT_PORT=9090 -t myapp .

# Переопределение при запуске
docker run -p 8080:9090 myapp
```

### Сценарий 3: Изоляция через Docker Compose expose

В Docker Compose секция `expose` делает порты доступными только для других сервисов в той же сети, предотвращая их публикацию на внешних интерфейсах хоста:

```yaml
services:
  api:
    build: .
    expose:
      - "9000"  # Доступно для 'proxy', но закрыто для интернета
  proxy:
    image: nginx
    ports:
      - "80:80"
```

**Разница между `expose` и `ports` в Compose:**

```yaml
services:
  db:
    image: postgres
    expose:
      - "5432"   # Только внутри сети Docker (для других сервисов)
    # ports: НЕ определён — порт НЕ доступен с хоста

  web:
    image: nginx
    ports:
      - "8080:80"  # Доступен и с хоста, и внутри сети
```

### Сценарий 4: Multi-stage сборка с EXPOSE

В multi-stage сборке `EXPOSE` определяется в финальной стадии (runtime):

```dockerfile
# Stage 1: сборка (EXPOSE не нужен)
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY . .
RUN go build -o app

# Stage 2: runtime (EXPOSE определяет порт приложения)
FROM alpine:3.21
WORKDIR /app
COPY --from=builder /build/app .
EXPOSE 8080
CMD ["./app"]
```

### Сценарий 5: Несколько портов (приложение + дебаг)

Приложения часто используют несколько портов — основной для трафика и дополнительный для отладки:

```dockerfile
FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY src/ ./src/

# Основной порт приложения
EXPOSE 3000

# Порт отладки Node.js (только для разработки)
EXPOSE 9229

CMD ["node", "--inspect=0.0.0.0:9229", "src/server.js"]
```

```bash
# Запуск с публикацией обоих портов
docker run -p 3000:3000 -p 9229:9229 myapp

# Подключение отладчика к localhost:9229
```

### Сценарий 6: Микросервисная архитектура с internal-only портами

В микросервисной архитектуре некоторые порты должны быть доступны только внутри кластера:

```yaml
services:
  # Бэкенд: порт доступен только для фронтенда
  api:
    build: .
    expose:
      - "8080"  # Внутренний API
    # Нет ports — не доступен снаружи

  # Фронтенд: публикуется наружу
  frontend:
    build: ./frontend
    ports:
      - "80:80"

  # База данных: доступна только для API
  db:
    image: postgres:16
    expose:
      - "5432"
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
```

### Сценарий 7: Порт 80/443 и привилегированные порты

В Linux порты ниже 1024 требуют привилегий root. Если приложение запускается от непривилегированного пользователя, используйте порты >= 1024:

```dockerfile
FROM node:22-alpine
RUN addgroup -g 10001 appgroup && adduser -u 10001 -G appgroup -s /bin/sh -D appuser

WORKDIR /app
COPY --chown=appuser:appgroup . .
RUN npm install --production

# Порт 8080 (не требует привилегий)
EXPOSE 8080

USER appuser
CMD ["node", "src/server.js"]
```

```bash
# Проксирование 80 -> 8080 через nginx или iptables
# Или используйте capabilities для привязки к порту 80
docker run --cap-add=NET_BIND_SERVICE -p 80:80 myapp
```

### Сценарий 8: EXPOSE и UFW (конфликт и решение)

UFW и Docker конфликтуют — Docker обходит UFW через iptables. Порт, опубликованный через `-p`, будет доступен несмотря на UFW:

```bash
# Порт 8080 доступен даже если UFW блокирует его!
docker run -p 8080:80 nginx

# Решение 1: Привязка к localhost
docker run -p 127.0.0.1:8080:80 nginx

# Решение 2: Настройка Docker daemon (Docker 20.10+)
# В /etc/docker/daemon.json:
# { "iptables": false }
# ВНИМАНИЕ: это отключает проброс портов для ВСЕХ контейнеров!
```

### Сценарий 9: EXPOSE с -P в CI/CD (динамические порты для тестов)

В CI/CD удобно использовать динамические порты для параллельного тестирования:

```bash
# Запуск нескольких контейнеров с динамическими портами
for i in 1 2 3 4 5; do
  docker run -d --name "test-$i" -P myapp
done

# Получение портов для каждого контейнера
for i in 1 2 3 4 5; do
  PORT=$(docker port "test-$i" 8080 | head -1 | awk -F: '{print $NF}')
  echo "test-$i -> http://localhost:$PORT"
done
```

### Сценарий 10: Docker Desktop и проброс портов

В Docker Desktop (macOS/Windows) проброс портов работает через виртуальную машину. При публикации порта Docker Desktop создает прокси от хоста до VM:

```bash
# Публикация порта
docker run -p 8080:80 nginx

# Доступ из хоста
curl http://localhost:8080  # Работает

# Просмотр всех опубликованных портов в Docker Desktop
# GUI: Dashboard -> Containers -> Ports
# CLI: docker ps --format "table {{.Names}}\t{{.Ports}}"
```
## Типичные ошибки и их решение

### Ошибка 1: Connection Refused после добавления EXPOSE

**Причина:** `EXPOSE` — это только документация. Порт не опубликован на хосте.

```bash
# Проверка: порт опубликован?
docker ps
# PORTS колонка пуста -> порт не опубликован

# Решение: добавить -p при запуске
docker run -d -p 8080:80 myapp
```

### Ошибка 2: Приложение слушает 127.0.0.1 вместо 0.0.0.0

**Причина:** Приложение привязано к localhost внутри контейнера. Docker не может пробросить порт на хост.

```bash
# Диагностика: проверка адреса прослушивания
docker exec mycontainer ss -tlnp | grep 8080
# 127.0.0.1:8080  -> приложение слушает только localhost!
# 0.0.0.0:8080    -> приложение слушает все интерфейсы (правильно)
```

**Решение:** Настроить приложение на прослушивание `0.0.0.0`:

```bash
# Пример для Node.js
node server.js --host 0.0.0.0

# Пример для Python Flask
flask run --host=0.0.0.0

# Пример для Go
go run main.go -addr 0.0.0.0:8080
```

### Ошибка 3: EXPOSE не совпадает с реальным портом приложения

**Причина:** В Dockerfile объявлен один порт, но приложение слушает другой.

```bash
# Проверка: какой порт реально слушает приложение?
docker exec mycontainer ss -tlnp
# Вывод: *:3000 -> приложение слушает 3000, а не 8080!

# Решение: исправить EXPOSE или порт приложения
EXPOSE 3000  # Было 8080
```

### Ошибка 4: Порт уже занят на хосте

**Причина:** Другой процесс или контейнер уже использует указанный порт хоста.

```bash
# Диагностика: кто использует порт?
sudo ss -tlnp | grep 8080
# LISTEN  0  128  0.0.0.0:8080  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))

# Решение 1: остановить конфликтующий процесс
sudo systemctl stop nginx

# Решение 2: использовать другой порт хоста
docker run -d -p 9090:80 myapp

# Решение 3: найти свободный порт автоматически
docker run -d -p 80 myapp  # Docker назначит случайный порт
docker port <container>     # Узнать какой
```

### Ошибка 5: UFW блокирует порт, но Docker публикует его

**Причина:** Docker обходит UFW через прямую модификацию iptables.

```bash
# Проверка: порт доступен despite UFW?
curl http://localhost:8080  # Работает, хотя UFW блокирует 8080!

# Решение: привязка к localhost
docker run -p 127.0.0.1:8080:80 myapp
# Теперь порт доступен ТОЛЬКО с localhost
```

### Ошибка 6: EXPOSE в multi-stage сборке не влияет на runtime

**Причина:** `EXPOSE` в builder-стадии не действует в runtime-стадии.

```dockerfile
# Stage 1: EXPOSE здесь бесполезен
FROM golang:1.22 AS builder
EXPOSE 8080  # Не действует в runtime!
RUN go build -o app

# Stage 2: EXPOSE должен быть здесь
FROM alpine
EXPOSE 8080  # Это имеет效力
COPY --from=builder /app .
CMD ["./app"]
```

### Ошибка 7: Несовпадение протокола (TCP vs UDP)

**Причина:** Приложение использует UDP, а порт опубликован только для TCP.

```bash
# Проверка: какой протокол использует приложение?
docker exec mycontainer ss -ulnp | grep 53
# UDP  *:53  -> приложение использует UDP

# Публикация для UDP
docker run -p 53:53/udp dns-server

# Или оба протокола
docker run -p 53:53/tcp -p 53:53/udp dns-server
```

## Лучшие практики

### Безопасность

1. **Привязка к интерфейсу:** Всегда указывайте интерфейс при публикации портов:

```bash
# ПРАВИЛЬНО: только localhost
docker run -p 127.0.0.1:8080:80 myapp

# ПЛОХО: все интерфейсы (включая публичные)
docker run -p 8080:80 myapp
```

2. **Минимализм:** Указывайте только те порты, которые действительно необходимы:

```dockerfile
# ПРАВИЛЬНО: только необходимые порты
EXPOSE 8080

# ПЛОХО: избыточные порты
EXPOSE 80 443 8080 8443 9090 3000 3001
```

3. **Дебаг-порты только в dev:** Отладочные порты (JMX, Debugger, Prometheus metrics) не должны быть в production-образах:

```dockerfile
# Development stage
FROM node:22-alpine AS dev
EXPOSE 3000
EXPOSE 9229  # Debug port - ТОЛЬКО для разработки
CMD ["node", "--inspect=0.0.0.0:9229", "src/server.js"]

# Production stage
FROM node:22-alpine AS production
EXPOSE 3000
# Debug port НЕ объявлен
CMD ["node", "src/server.js"]
```

4. **Не используйте EXPOSE для безопасности:** `EXPOSE` не защищает порты. Используйте файрволы, Docker network policies или iptables.

### Кэширование и оптимизация

1. **EXPOSE в конце Dockerfile:** Размещайте `EXPOSE` перед `CMD`/`ENTRYPOINT` для оптимального кэширования:

```dockerfile
FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
# EXPOSE перед CMD — не влияет на кэш, но документирует контракт
EXPOSE 3000
CMD ["node", "src/server.js"]
```

2. **EXPOSE не инвалидирует кэш:** Изменение `EXPOSE` безопасно для кэширования — последующие `RUN` не пересоздаются.

### Документация

1. **Комментарии к портам:** Документируйте назначение каждого порта:

```dockerfile
# HTTP API
EXPOSE 8080

# Metrics endpoint (Prometheus)
EXPOSE 9090

# Debug port (Node.js Inspector)
EXPOSE 9229
```

2. **Соглашение на именование:** Используйте единый стиль для портов в проекте:

```dockerfile
# Соглашение: основной порт - 8080, альтернативный - 8443
EXPOSE 8080
EXPOSE 8443
```

### Порядок инструкций в Dockerfile

```dockerfile
# 1. FROM
FROM node:22-alpine

# 2. WORKDIR
WORKDIR /app

# 3. Кэширование зависимостей
COPY package.json package-lock.json ./
RUN npm ci --production

# 4. Копирование кода
COPY src/ ./src/

# 5. USER (безопасность)
USER node

# 6. EXPOSE (документация портов)
EXPOSE 3000

# 7. CMD/ENTRYPOINT
CMD ["node", "src/server.js"]
```

## Граничные случаи и ограничения

### EXPOSE не создаёт сеть

`EXPOSE` не создаёт сетевой интерфейс и не настраивает маршрутизацию. Контейнеры могут общаться через Docker-сети независимо от `EXPOSE`:

```bash
# Контейнеры в одной сети общаются без EXPOSE
docker network create mynet
docker run -d --name web --network mynet nginx
docker run -d --name api --network mynet myapp

# api может обращаться к web:80 без EXPOSE в Dockerfile nginx
```

### EXPOSE и docker inspect

Метаданные `EXPOSE` доступны через `docker inspect`:

```bash
# Просмотр EXPOSE через JSON
docker inspect --format '{{json .Config.ExposedPorts}}' myimage
# -> {"80/tcp":{},"443/tcp":{}}

# Просмотр опубликованных портов (с -p)
docker inspect --format '{{json .NetworkSettings.Ports}}' mycontainer
# -> {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
```

### EXPOSE и docker commit

При создании контейнера через `docker commit` инструкция `EXPOSE` **сохраняется**:

```bash
docker commit mycontainer newimage
docker inspect --format '{{json .Config.ExposedPorts}}' newimage
# -> {"80/tcp":{}} — EXPOSE сохранён
```

### EXPOSE и docker export

При экспорте контейнера через `docker export` инструкция `EXPOSE` **теряется**:

```bash
docker export mycontainer > container.tar
# EXPOSE не экспортируется — это файловая система без метаданных
```

### EXPOSE в Swarm mode

В Docker Swarm `EXPOSE` используется для Service Discovery. Порты публикуются через `--publish` в `docker service create`:

```bash
# EXPOSE в Dockerfile Swarm не публикует порты автоматически
docker service create --name web --publish published=8080,target=80 nginx
```

### Несколько инструкций EXPOSE

Можно указать несколько инструкций `EXPOSE` — они не конфликтуют:

```dockerfile
EXPOSE 80
EXPOSE 443
EXPOSE 8080-8090/tcp
```

## Дополнительная информация

### Инспекция метаданных

Увидеть список "экспонированных" портов образа можно без его запуска:

```bash
# Просмотр EXPOSE из образа
docker image inspect --format '{{json .Config.ExposedPorts}}' <image_name>
# -> {"80/tcp":{},"443/tcp":{}}

# Просмотр портов из запущенного контейнера
docker ps --format "table {{.Names}}\t{{.Ports}}"
# NAMES    PORTS
# mynginx  0.0.0.0:8080->80/tcp
```

### Резюме по использованию

1. **`EXPOSE` — документация, не публикация.** Для доступа снаружи используйте `-p` или `-P`.
2. **Указывайте только необходимые порты.** Минимизация поверхности атаки.
3. **Привязывайтесь к интерфейсу.** Используйте `-p 127.0.0.1:8080:80` для локальных сервисов.
4. **Проверяйте реальное прослушивание.** Используйте `ss -tlnp` для диагностики.
5. **Документируйте порты.** Комментарии к `EXPOSE` упрощают сопровождение.

**См. также:**
- **[Docker Network: Обзор](../../Docker_network/docker_network.md)** — архитектура сетей в Docker.
- **[Инструкции Dockerfile: Обзор](./overview_definitions.md)** — сводная таблица всех инструкций.
- **[Traefik и Docker Compose](../../../WebServers/Traefik/traefik_with_docker_compose.md)** — использование `expose` для динамической маршрутизации.
