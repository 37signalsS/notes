# MySQL в Docker

## Определения

**MySQL в Docker** — метод развертывания СУБД MySQL в изолированных контейнерах. Официальные образы поддерживают две модели релизов:
- **LTS (Long Term Support):** Стабильные версии для Production (например, **8.4 LTS**). Поддержка до 8 лет.
- **Innovation:** Версии с новыми функциями (например, **9.0 Innovation**). Короткий цикл поддержки, рекомендуются для тестирования новых возможностей (например, Vector types).

## Базовые концепции

### Персистентность данных: Volumes

**Категорически запрещено** хранить данные внутри файловой системы контейнера. Для сохранения данных используются **именованные тома (named volumes)**.

- **Принцип:** Директория `/var/lib/mysql` монтируется на том.
- **Преимущество:** Данные сохраняются при удалении, обновлении или перезапуске контейнера.

### Конфигурация

Настройки применяются путем монтирования кастомного `my.cnf` (или файлов в `/etc/mysql/conf.d/`) либо через аргументы команды запуска (`command`).
Подробности — в [конфигурации MySQL](./configuration.md).

### Инициализация

При первом запуске на пустом томе MySQL выполняет скрипты из `/docker-entrypoint-initdb.d/` (форматы `.sh`, `.sql`, `.sql.gz`) в алфавитном порядке. Это удобно для создания схем, пользователей и начального наполнения данными.

### Проверка состояния (Healthcheck)

Используется для уведомления Docker и зависимых сервисов о готовности БД.
- **Команда:** `mysqladmin ping -h localhost -u root -p$MYSQL_ROOT_PASSWORD`
- **Параметры:** Рекомендуется устанавливать `start_period` (около 30с), так как инициализация БД требует времени.

### Безопасность и аутентификация

- **Плагины аутентификации:** 
  - В MySQL 8.4 `mysql_native_password` отключен по умолчанию (но доступен).
  - В MySQL 9.0+ `mysql_native_password` **полностью удален**. 
  - Рекомендуется использовать `caching_sha2_password`.
- **Docker Secrets:** В Swarm или через Docker Compose (с версии 3.5+) рекомендуется передавать пароли через секреты, а не через переменные окружения напрямую.
- **Привилегии:** Используйте `MYSQL_USER` и `MYSQL_PASSWORD` для создания ограниченного пользователя вместо работы под `root`.

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

# Запуск с ограничением ресурсов
docker run -d --name mysql-db \
  -p 3306:3306 \
  --memory="2g" \
  --cpus="1.5" \
  -e MYSQL_ROOT_PASSWORD=secret_pass \
  -v mysql_data:/var/lib/mysql \
  mysql:8.4
# -> <container_id>
```

### 2. Запуск с Docker Secrets (Compose)

Безопасный способ передачи паролей без отображения в `docker inspect` или истории команд.

```yaml
# docker-compose.yml
services:
  db:
    image: mysql:8.4
    secrets:
      - mysql_root_password
    environment:
      MYSQL_ROOT_PASSWORD_FILE: /run/secrets/mysql_root_password

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

```bash
# Создание логического дампа (все базы)
docker exec mysql-db mysqldump -u root -p"pass" --all-databases > full_backup.sql

# Восстановление из дампа
docker exec -i mysql-db mysql -u root -p"pass" < full_backup.sql
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

## Дополнительная информация

- [Конфигурация MySQL (my.cnf)](./configuration.md)
- [Мониторинг MySQL](./monitoring.md)
- [Репликация MySQL: Обзор](./replication/overview.md)
- [Docker: Тома и персистентное хранение](../../Docker/Docker_fs/docker_volumes.md)
- [Docker: Справочник по сетям](../../Docker/Docker_network/docker_network.md)
- [Официальная документация MySQL Docker (Hub)](https://hub.docker.com/_/mysql)
