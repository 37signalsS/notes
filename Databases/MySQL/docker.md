# MySQL в Docker

## Определения

**MySQL в Docker** — метод развертывания СУБД MySQL в изолированных контейнерах, обеспечивающий воспроизводимость окружения и упрощенное управление зависимостями.

Официальные образы (ранее базировавшиеся на Debian, теперь преимущественно на **Oracle Linux**) поддерживают две модели релизов:
- **LTS (Long Term Support):** Стабильные версии для Production (например, **8.4 LTS**). Поддержка до 8 лет, критические фиксы и минимальные изменения.
- **Innovation:** Версии с новыми функциями (например, **9.0 Innovation**). Короткий цикл поддержки (до следующего релиза), рекомендуются для тестирования новых возможностей (например, Vector types для AI).

## Базовые концепции

### Архитектура образа

Официальный образ MySQL спроектирован с учетом модульности:
- **Базовый слой:** Oracle Linux (Slim версия) для минимизации размера и поверхности атаки.
- **Слой СУБД:** Бинарные файлы MySQL, клиентские утилиты и библиотеки.
- **Entrypoint скрипт:** Умная логика инициализации, которая проверяет наличие данных в `/var/lib/mysql` и выполняет первичную настройку (создание root, пользователей, БД).

### Многоархитектурность (Multi-arch)

Официальные образы поддерживают `amd64` и `arm64`. Это критично для запуска на Apple Silicon (M1/M2/M3) или ARM-серверах в облаке (AWS Graviton). При сборке своих образов используйте `docker buildx` для поддержки обеих архитектур.

### Сборка кастомного образа (Dockerfile)

Иногда требуется предустановить плагины (например, `Clone Plugin`) или изменить часовой пояс.

```dockerfile
# Dockerfile
FROM mysql:8.4

# Установка часового пояса (пример для Oracle Linux)
RUN ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime

# Копирование кастомного конфига с правильными правами
COPY my-custom.cnf /etc/mysql/conf.d/
RUN chmod 644 /etc/mysql/conf.d/my-custom.cnf
```

### Персистентность данных: Volumes vs Bind Mounts

**Категорически запрещено** хранить данные внутри файловой системы контейнера (Writable Layer), так как они будут потеряны при удалении контейнера, а производительность I/O будет крайне низкой из-за Copy-on-Write.

| Тип монтирования | Применение | Особенности |
| :--- | :--- | :--- |
| **Named Volumes** | Production / General | Docker сам управляет местоположением. Оптимальная производительность. Рекомендуется: `mysql_data:/var/lib/mysql`. |
| **Bind Mounts** | Разработка / Отладка | Прямое монтирование папки хоста. Удобно для доступа к файлам, но требует ручного управления правами доступа (`UID/GID`). |

**Важно:** Для `Bind Mounts` на Linux необходимо убедиться, что пользователь хоста имеет UID `999`, иначе MySQL не сможет писать в директорию.

### Конфигурация

Настройки применяются тремя способами:
1. **Монтирование файлов:** Проброс кастомного `my.cnf` в `/etc/mysql/conf.d/`.
2. **Аргументы запуска:** Передача флагов после имени образа (например, `--character-set-server=utf8mb4`).
3. **Переменные окружения:** Базовая настройка через `MYSQL_*` переменные.
Подробности — в [конфигурации MySQL](./configuration.md).

### Инициализация (Seed Data)

При первом запуске на пустом томе MySQL выполняет скрипты из `/docker-entrypoint-initdb.d/`:
- **Форматы:** `.sh`, `.sql`, `.sql.gz`.
- **Порядок:** Алфавитный.
- **Особенность:** Если в `/var/lib/mysql` уже есть данные (даже системные таблицы), скрипты **не будут** выполнены. Для повторной инициализации том должен быть пуст.

### Проверка состояния (Healthcheck)

Используется для уведомления Docker и зависимых сервисов о готовности БД.
- **Команда:** `mysqladmin ping -h localhost -u root -p$MYSQL_ROOT_PASSWORD`
- **Параметры:**
  - `interval`: 10s
  - `timeout`: 5s
  - `retries`: 3
  - `start_period`: 30с–60с (время на инициализацию БД при первом запуске).

### Безопасность и аутентификация

- **Плагины аутентификации:** 
  - В MySQL 8.4 `mysql_native_password` отключен по умолчанию (но доступен).
  - В MySQL 9.0+ `mysql_native_password` **полностью удален**. 
  - Рекомендуется использовать `caching_sha2_password`.
- **Docker Secrets:** В Swarm или через Docker Compose (с версии 3.5+) рекомендуется передавать пароли через секреты, а не через переменные окружения напрямую.
- **Привилегии:** Используйте `MYSQL_USER` и `MYSQL_PASSWORD` для создания ограниченного пользователя вместо работы под `root`.

### Мониторинг в Docker

Наиболее распространенный способ мониторинга — использование `mysqld-exporter` в качестве sidecar-контейнера.

- **Экспортер:** `prom/mysqld-exporter`.
- **Права:** Требует отдельного пользователя в MySQL с правами `PROCESS`, `SELECT`, `REPLICATION CLIENT`.

### Журналирование (Logging)

По умолчанию MySQL в Docker направляет логи ошибок в `stderr`.
- **Доступ к логам:** `docker logs <container_id>`.
- **Бинарные логи:** Критичны для репликации и восстановления. В Docker важно настраивать их ротацию (`binlog_expire_logs_seconds`), чтобы не переполнить диск хоста.

### Производительность: Host vs Docker

- **Дисковый I/O:** Накладные расходы минимальны при использовании Volumes. Рекомендуется использовать файловые системы `Ext4` или `XFS` на хосте.
- **Сеть:** 
  - `bridge` (default): Накладные расходы на NAT и проксирование (до 10-20% падения пропускной способности).
  - `host`: Контейнер использует сеть хоста. Максимальная производительность, рекомендуется для высоконагруженных Production-баз. См. [драйвер host](../../Docker/Docker_network/drivers/host.md).

## Практические сценарии

### 1. Базовый запуск (LTS 8.4)

```bash
# Создание тома
docker volume create mysql_data

# Запуск с ограничением ресурсов и init-процессом (для корректной обработки сигналов)
docker run -d --name mysql-db \
  --init \
  -p 3306:3306 \
  --memory="2g" \
  --cpus="1.5" \
  -e MYSQL_ROOT_PASSWORD=secret_pass \
  -v mysql_data:/var/lib/mysql \
  mysql:8.4
# -> <container_id>
```

### 2. Запуск с Docker Secrets и Мониторингом (Compose)

Безопасный способ развертывания с готовым мониторингом.

```yaml
# docker-compose.yml
services:
  db:
    image: mysql:8.4
    secrets:
      - mysql_root_password
    environment:
      MYSQL_ROOT_PASSWORD_FILE: /run/secrets/mysql_root_password
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost -u root -p$$(cat /run/secrets/mysql_root_password)"]
      interval: 10s
      start_period: 30s

  exporter:
    image: prom/mysqld-exporter:latest
    environment:
      DATA_SOURCE_NAME: "exporter:password@(db:3306)/"
    ports:
      - "9104:9104"
    depends_on:
      db:
        condition: service_healthy

volumes:
  mysql_data:

secrets:
  mysql_root_password:
    file: ./root_password.txt
```

### 3. Настройка бинарных логов и GTID

Для подготовки к репликации или инкрементальному бэкапу.

```bash
docker run -d --name mysql-binlog \
  -e MYSQL_ROOT_PASSWORD=pass \
  -v mysql_data:/var/lib/mysql \
  mysql:8.4 \
  --server-id=1 \
  --log-bin=mysql-bin \
  --gtid-mode=ON \
  --enforce-gtid-consistency=ON \
  --binlog_expire_logs_seconds=604800
```

### 4. Репликация (Source-Replica) через Docker Compose

Современный стек с использованием терминологии Source/Replica и GTID.

```yaml
# docker-compose.yml
services:
  mysql-source:
    image: mysql:8.4
    environment:
      MYSQL_ROOT_PASSWORD: root_pass
    command:
      - --server-id=1
      - --log-bin=mysql-bin
      - --gtid-mode=ON
      - --enforce-gtid-consistency=ON
    networks:
      - mysql-net

  mysql-replica:
    image: mysql:8.4
    environment:
      MYSQL_ROOT_PASSWORD: root_pass
    command:
      - --server-id=2
      - --gtid-mode=ON
      - --enforce-gtid-consistency=ON
      - --read-only=1
    depends_on:
      - mysql-source
    networks:
      - mysql-net

networks:
  mysql-net:
    driver: bridge
```

### 5. Создание бэкапа и восстановление

Для контейнеризированной MySQL рекомендуется использовать те же инструменты, что и для классической установки. Детальные инструкции и примеры (XtraBackup, MySQL Shell, mysqldump) находятся в **[Резервное копирование и восстановление в MySQL](./backup_and_recovery/overview.md)**.

Пример выполнения логического дампа через `docker exec`:
```bash
# Создание логического дампа (все базы)
docker exec mysql-db mysqldump -u root -p"pass" --all-databases > full_backup.sql
```

### 6. Процедура обновления (например, 8.0 -> 8.4)

1. **Бэкап:** Создать полный дамп данных.
2. **Проверка аутентификации:** Убедиться, что пользователи не используют `mysql_native_password` (если планируется переход на 9.0).
3. **Остановка:** `docker stop mysql-db`.
4. **Запуск новой версии:** Запустить контейнер с новым тегом образа, примонтировав старый том. MySQL автоматически выполнит `upgrade` словаря данных при старте.
5. **Проверка:** Изучить логи `docker logs mysql-db` на предмет ошибок миграции.

## Устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Access denied (root)** | Неверный пароль или плагин | Проверить `MYSQL_ROOT_PASSWORD`. Для 9.0 использовать `caching_sha2_password` в клиенте. |
| **Permission denied (volume)** | Права доступа на хосте | Выполнить `chown -R 999:999` на директорию тома (999 — стандартный UID mysql в Docker). |
| **Container keeps restarting** | Ошибка в `my.cnf` или init-скрипте | Проверить логи: `docker logs <id>`. Проверить синтаксис конфига. |
| **Authentication plugin '...' not loaded** | Использование удаленного плагина | Обновить клиентские библиотеки или включить плагин в настройках (только для 8.4). |
| **OOM Killer / Exit code 137** | Недостаточно памяти для InnoDB | Увеличить лимит `--memory` или уменьшить `innodb_buffer_pool_size`. |

## Дополнительная информация

- [Конфигурация MySQL (my.cnf)](./configuration.md)
- [Мониторинг MySQL](./monitoring.md)
- [Репликация MySQL: Обзор](./replication/overview.md)
- [Docker: Тома и персистентное хранение](../../Docker/Docker_fs/docker_volumes.md)
- [Docker: Справочник по сетям](../../Docker/Docker_network/docker_network.md)
- [Официальная документация MySQL Docker (Hub)](https://hub.docker.com/_/mysql)
