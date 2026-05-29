# MySQL в Docker

## Определения

**MySQL в Docker** — подход, при котором сервер БД MySQL запускается в изолированном контейнере Docker. Обеспечивает переносимость, консистентность окружения, упрощает развертывание и масштабирование.

## Базовые концепции

### Персистентность данных: Volumes

**Категорически запрещено** хранить данные базы данных внутри файловой системы контейнера — при удалении контейнера данные будут утеряны. Для сохранения данных используются **именованные тома (named volumes)**.

- **Принцип:** Том (`mysql-data`) монтируется в директорию `/var/lib/mysql`. Данные физически сохраняются в управляемой Docker области на хосте.
- **Преимущество:** Тома существуют независимо от контейнеров. Можно удалить и запустить новый контейнер с тем же томом — данные сохранятся.

### Конфигурация

Для применения кастомных настроек используется монтирование файла `my.cnf` из хоста в контейнер. Подробности — в [конфигурации MySQL](./configuration.md).

### Инициализация

Официальные образы MySQL поддерживают автоматическую инициализацию при первом запуске на пустом томе. Скрипты (`.sh`, `.sql`, `.sql.gz`) из директории `/docker-entrypoint-initdb.d/` выполняются в алфавитном порядке.

### Производительность: Host vs Docker

Производительность зависит от **дискового I/O** и **сетевого режима**.

- **Дисковый I/O:** При использовании `docker volume` накладные расходы минимальны — операции транслируются напрямую в ФС хоста.
- **Сетевой режим:**
  - **`bridge` (по умолчанию):** Трафик проходит через `docker-proxy`, что создает накладные расходы на CPU. Падение производительности на read-only нагрузках — до **50%**.
  - **`host` (`--network host`):** Контейнер использует сетевой стек хоста напрямую. Максимальная производительность, **рекомендовано для production**. Недостатки — снижение изоляции и риск конфликта портов.

См. также: [сети Docker](../../Docker/Docker_network/docker_network.md), [драйвер host](../../Docker/Docker_network/drivers/host.md).

## Практические сценарии

### 1. Базовый запуск с именованным томом

```bash
# 1. Создаем именованный том для данных
docker volume create mysql-data
# -> mysql-data

# 2. Запускаем контейнер MySQL, монтируя том
docker run -d --name mysql-db \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=my-secret-pw \
  -v mysql-data:/var/lib/mysql \
  mysql:8.4
# -> <container_id>
```

### 2. Запуск с кастомной конфигурацией

```bash
# Пробрасываем свой my.cnf в контейнер
docker run -d --name mysql-db-custom-config \
  -p 3307:3306 \
  -e MYSQL_ROOT_PASSWORD=my-secret-pw \
  -v mysql-data:/var/lib/mysql \
  -v ./my.cnf:/etc/mysql/conf.d/custom.cnf \
  mysql:8.4
# -> <container_id>
```

### 3. Запуск со скриптами инициализации

```bash
# Монтируем директорию со скриптами для первоначальной настройки
docker run -d --name mysql-db-initialized \
  -p 3308:3306 \
  -e MYSQL_ROOT_PASSWORD=my-secret-pw \
  -v mysql-data:/var/lib/mysql \
  -v ./init-scripts:/docker-entrypoint-initdb.d \
  mysql:8.4
# -> <container_id>
```

### 4. Запуск для максимальной производительности

```bash
# Используем сетевой режим 'host' для минимизации задержек
docker run -d --name mysql-db-high-perf \
  --network host \
  -e MYSQL_ROOT_PASSWORD=my-secret-pw \
  -v mysql-data:/var/lib/mysql \
  mysql:8.4
# -> <container_id>
```

> **Примечание:** В режиме `--network host` проброс портов (`-p`) не работает. MySQL доступен напрямую по порту 3306 на IP-адресе хоста.

### 5. Запуск через Docker Compose

Для управления многоконтейнерными приложениями предпочтительнее использовать `docker-compose.yml`. Данный пример также настроен на использование именованных томов.

```yaml
# docker-compose.yml
services:
  db:
    image: mysql:8.4
    container_name: mysql-compose-db
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: my-secret-pw
      MYSQL_DATABASE: my_database
    ports:
      - "3306:3306"
    volumes:
      - mysql-data:/var/lib/mysql

volumes:
  mysql-data:
```

Запуск сервисов:

```bash
docker compose up -d
# -> [+] Running 2/2
# ->  ✔ Network my_network        Created
# ->  ✔ Container mysql-compose-db Started
```

## Дополнительная информация

- [Docker: Тома и персистентное хранение](../../Docker/Docker_fs/docker_volumes.md)
- [Docker: Справочник по сетям](../../Docker/Docker_network/docker_network.md)
