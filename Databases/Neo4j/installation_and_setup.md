# Neo4j: Установка и настройка

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **DBMS** | Экземпляр Neo4j, управляющий одной или несколькими базами данных. |
| **Cypher Shell** | CLI для выполнения Cypher-запросов и административных задач по Bolt (порт 7687). |
| **neo4j-admin** | Утилита командной строки для административных операций: бэкап, восстановление, установка пароля, проверка store-файлов. |
| **Page cache** | Область RAM, в которой кэшируются store-файлы и Lucene-индексы для быстрого чтения. Не является частью JVM heap. |
| **Heap** | Память JVM для Java-объектов Neo4j: планы запросов, состояние транзакций, кэши. |
| **Store file** | Бинарный файл на диске, содержащий узлы, связи, свойства и индексы графа. |
| **WAL (transaction log)** | Журнал упреждающей записи всех изменений; используется для crash recovery и PITR. |
| **APOC** | Стандартная библиотека расширений Neo4j: импорт/экспорт, пакетная обработка, алгоритмы. |
| **Cypher 25** | Активная ветвь языка Cypher; новые базы создаются с ней по умолчанию начиная с 2026.02. |

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| **ОС** | Ubuntu 22.04/24.04 LTS, Debian 12+, RHEL/Rocky/Alma 9+, или Docker 24+ |
| **Java** | OpenJDK 21 (включён в пакет Neo4j; для tar.gz — отдельная установка) |
| **Память** | минимум 2 ГБ RAM, рекомендуется 8+ ГБ для production |
| **Диск** | минимум 10 ГБ свободного места; SSD для write-heavy нагрузок |
| **Сеть** | Bolt (7687), HTTP (7474), HTTPS (7473) — по умолчанию слушает только `localhost` |
| **Пользователь** | сервер работает от имени системного пользователя `neo4j` |
| **Swap** | должен быть отключён на выделенном сервере |

> **THP (Transparent Huge Pages).** На Linux THP фрагментирует память и вызывает паузы JVM. На выделенных серверах Neo4j его рекомендуется отключить через `echo never > /sys/kernel/mm/transparent_hugepage/enabled`. Подробнее — в [обслуживании](./operations.md).

## Вариант 1: Ubuntu/Debian (APT)

```bash
# Импорт GPG-ключа репозитория
curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key | \
  sudo gpg --dearmor -o /usr/share/keyrings/neo4j-archive-keyring.gpg

# Добавление репозитория
echo "deb [signed-by=/usr/share/keyrings/neo4j-archive-keyring.gpg] \
  https://debian.neo4j.com stable latest" | \
  sudo tee /etc/apt/sources.list.d/neo4j.list

# Установка Community Edition
sudo apt update
sudo apt install neo4j -y

# Установка Enterprise Edition (требуется лицензия)
# sudo apt install neo4j-enterprise -y

# Запуск и добавление в автозагрузку
sudo systemctl enable neo4j
sudo systemctl start neo4j
```

**Управление версией в APT.** Репозиторий `stable latest` следует за текущим релизом. Для production рекомендуется зафиксировать версию:

```bash
# Показать доступные версии
apt list -a neo4j

# Установить конкретную версию
sudo apt install neo4j=1:2026.09.0-1=...
```

## Вариант 2: RHEL/Rocky/Alma (DNF)

```bash
# Импорт GPG-ключа
sudo rpm --import https://debian.neo4j.com/neotechnology.gpg.key

# Добавление репозитория
curl -fsSL https://debian.neo4j.com/stable/neo4j-rpm.repo | \
  sudo tee /etc/yum.repos.d/neo4j.repo

# Установка Community Edition
sudo dnf install neo4j -y

# Установка Enterprise Edition
# sudo dnf install neo4j-enterprise -y

sudo systemctl enable neo4j
sudo systemctl start neo4j
```

## Вариант 3: tar.gz (ручная установка)

Для окружений, где пакетный менеджер не используется, или для контролируемого развёртывания:

```bash
# 1. Скачать дистрибутив
NEO4J_VERSION=2026.09.0
wget https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz
tar -xzf neo4j-community-${NEO4J_VERSION}-unix.tar.gz
mv neo4j-community-${NEO4J_VERSION} /opt/neo4j

# 2. Создать пользователя и группу
sudo groupadd -r neo4j
sudo useradd -r -g neo4j -d /opt/neo4j -s /usr/sbin/nologin neo4j

# 3. Назначить права
sudo chown -R neo4j:neo4j /opt/neo4j

# 4. Создать каталоги данных
sudo -u neo4j mkdir -p /opt/neo4j/data /opt/neo4j/logs /opt/neo4j/plugins

# 5. Запустить
sudo -u neo4j /opt/neo4j/bin/neo4j start
```

**Файловая структура tar.gz:**

| Каталог | Назначение |
| :--- | :--- |
| `/opt/neo4j/conf` | `neo4j.conf`, certificates |
| `/opt/neo4j/data` | Store-файлы, transaction logs |
| `/opt/neo4j/logs` | `neo4j.log`, `debug.log`, `query.log` |
| `/opt/neo4j/plugins` | APOC, GDS, пользовательские плагины |
| `/opt/neo4j/import` | `LOAD CSV` — только отсюда |

Полная таблица путей для пакетов Debian/RPM — в [архитектуре](./architecture.md).

## Вариант 4: Docker (разработка)

```bash
docker run -d \
  --name neo4j \
  --restart unless-stopped \
  -p 7474:7474 \
  -p 7687:7687 \
  -v neo4j_data:/data \
  -v neo4j_logs:/logs \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.09.0-community
```

> **Ограничение.** `NEO4J_PLUGINS` в development-средах скачивает плагин при старте контейнера из сети. Для production используйте смонтированный JAR — см. [APOC](./apoc.md#docker-production).

## Вариант 5: Docker Compose (production)

```yaml
services:
  neo4j:
    image: neo4j:2026.09.0-enterprise
    container_name: neo4j-prod
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      NEO4J_AUTH: neo4j/CHANGE_ME_STRONG_PASSWORD
      NEO4J_ACCEPT_LICENSE_AGREEMENT: "yes"
      # JVM heap: фиксированный initial=max, 50% от RAM на примере 8G heap + 8G pagecache на сервере 16G
      NEO4J_server_memory_heap_initial__size: "4G"
      NEO4J_server_memory_heap_max__size: "4G"
      # Page cache: остаток RAM после heap и ОС
      NEO4J_server_memory_pagecache_size: "8G"
      NEO4J_PLUGINS: '["apoc"]'
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 20G
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -a bolt://localhost:7687 -u neo4j -p $${NEO4J_AUTH#neo4j/} 'RETURN 1'"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

volumes:
  neo4j_data:
  neo4j_logs:
```

> **Важно:** `mem_limit` должен превышать сумму heap + page cache с запасом на ОС. Для примера выше: heap 4G + pagecache 8G = 12G, `mem_limit=20G` оставляет 8G на ОС и заголовки контейнера. Урезанный лимит не вызывает ошибки конфигурации: Neo4j стартует, а упирается в OOM Kill под нагрузкой, где диагностика hardest всего. Подробнее — в [обслуживании](./operations.md#docker-память-в-контейнере).

## Начальная конфигурация

### Установка начального пароля

```bash
# APT/RPM/tar.gz: только до первого запуска
sudo neo4j-admin dbms set-initial-password YourStrongPassword2026 --require-password-change
```

`--require-password-change` обязывает администратора сменить пароль при первом входе — это покрытие правила «начальный пароль не должен быть постоянным».

### Подключение через cypher-shell

```bash
# Подключение к localhost
cypher-shell -u neo4j -p YourStrongPassword2026

# Явный адрес Bolt
cypher-shell -a bolt://localhost:7687 -u neo4j -p YourStrongPassword2026
```

`cypher-shell` устанавливается вместе с пакетом `neo4j`. Для Docker:

```bash
docker exec -it neo4j cypher-shell -u neo4j -p YourStrongPassword2026
```

## Проверка работоспособности

```bash
# Статус сервиса
sudo systemctl status neo4j

# Проверка через HTTP
curl http://localhost:7474
# → {"bolt_routing":"neo4j://localhost:7687","transaction":"http://localhost:7474/db/{databaseName}/tx",...}

# Проверка через cypher-shell
echo "RETURN 1 AS test;" | cypher-shell -u neo4j -p YourStrongPassword2026
# → +------+
#    | test |
#    +------+
#    | 1    |
#    +------+
```

## Усиление установки (hardening)

### Права на файлы и каталоги

Пакеты Debian/RPM создают пользователя `neo4j` и назначают права автоматически. Для tar.gz:

```bash
# Каталоги: 750, конфигурация: 640, владелец neo4j:neo4j
sudo chown -R neo4j:neo4j /opt/neo4j
sudo chmod 750 /opt/neo4j/{data,logs,plugins,import}
sudo chmod 640 /opt/neo4j/conf/neo4j.conf
```

> `neo4j.conf` содержит секреты (пароли OIDC, LDAP, passphrase приватного ключа) и потому не должен быть world-readable. Проверка:

```bash
ls -ld /var/lib/neo4j/{data,logs,plugins,conf}
# → drwxr-x---  neo4j neo4j     (750)
ls -l /etc/neo4j/neo4j.conf
# → -rw-r-----  neo4j neo4j     (640)
```

Полный чек-лист прав — в [безопасности](./security.md#защита-данных-при-хранении).

### systemd: переопределение юнита

Для выделенного сервера рекомендуемые параметры в `/etc/systemd/system/neo4j.service.d/hardening.conf`:

```ini
[Service]
LimitNOFILE=65536
```

Применение:

```bash
sudo systemctl daemon-reload
sudo systemctl restart neo4j
```

Полный набор hardening-флагов (`ProtectSystem`, `LockMemory`, `RestrictNamespaces` и др.) — в [обслуживании](./operations.md#жёсткая-изоляция-службы-systemd-hardening).

### Swap

```bash
# Отключить swap немедленно
sudo swapoff -a

# Убрать из /etc/fstab для постоянства
sudo sed -i '/ swap / s/^\(.*\)$/#\1/' /etc/fstab
```

Отключение swap предотвращает своппинг heap'а JVM, который вызывает паузы в десятки секунд.

### Журналирование в systemd

Для пакетов Debian/RPM `neo4j.log` пишется в journald:

```bash
# Просмотр в реальном времени
journalctl --unit=neo4j -f

# Постоянное хранение
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald
```

### Docker: переменные окружения

В Docker параметры `neo4j.conf` передаются переменными по схеме `NEO4J_<параметр>`, где **каждое подчёркивание в имени параметра удваивается**:

```bash
# Пример: server.bolt.tls_level=REQUIRED
-e NEO4J_server_bolt_tls__level=REQUIRED
```

Одинарное подчёркивание (`NEO4J_server_bolt_tls_level`) — самая частая опечатка; при неверном имени настройка молча не применяется.

## Обновление

### APT

```bash
# Проверка доступной версии
apt list -a neo4j

# Обновление
sudo apt update
sudo apt upgrade neo4j -y
sudo systemctl restart neo4j
```

**Вариант 2: обновление остановленной базы.** Если обновление требует миграции store-формата:

```bash
sudo systemctl stop neo4j
sudo apt upgrade neo4j -y
sudo systemctl start neo4j
```

### RHEL/Rocky/Alma

```bash
sudo dnf upgrade neo4j -y
sudo systemctl restart neo4j
```

### tar.gz

```bash
# 1. Остановить сервер
sudo -u neo4j /opt/neo4j/bin/neo4j stop

# 2. Распаковать новую версию рядом
tar -xzf neo4j-community-2026.09.0-unix.tar.gz

# 3. Скопировать конфигурацию и данные (если пути изменились)
cp /opt/neo4j/conf/neo4j.conf /opt/neo4j-2026.09.0/conf/
sudo chown -R neo4j:neo4j /opt/neo4j-2026.09.0

# 4. Переключить симлинк или обновить путь
sudo mv /opt/neo4j /opt/neo4j-OLD
sudo mv /opt/neo4j-2026.09.0 /opt/neo4j

# 5. Запустить
sudo -u neo4j /opt/neo4j/bin/neo4j start
```

### Миграция формата хранилища

При обновлении с 5.26 LTS на 2026.x базы Enterprise Edition должны быть переведены в формат `block`. Проверка:

```cypher
SHOW DATABASES YIELD name, store;
```

Миграция — операция офлайн, I/O-интенсивна. Подробности — в [бэкапе и восстановлении](./backup_and_restore.md#миграция-формата-хранилища).

## Устранение неполадок

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Сервис не стартует** | `systemctl status neo4j` показывает failed | Неверный `neo4j.conf`, порт занят, не хватает памяти | Проверить `neo4j.log` и `debug.log`; `ss -tlnp \| grep 7687` |
| **Порт 7687 занят** | `Address already in use` при старте | Другой процесс или предыдущий экземпляр | `sudo systemctl stop neo4j` или найти процесс через `ss` |
| **`Connection refused` на Bolt** | Драйвер не подключается | Сервис остановлен, firewall, `advertised_address` | `systemctl status neo4j`, `ss -tlnp`, проверить `server.bolt.listen_address` |
| **`OutOfMemoryError` при старте** | Сервер падает сразу | `mem_limit` контейнера или RAM меньше heap + page cache | Увеличить память; проверить `memory-recommendation` |
| **Ошибка GPG при apt update** | `NO_PUBKEY` | Устаревший ключ или смена ключа репозитория | Переимпортировать ключ; проверить URL репозитория |
| **Дифференциальный бэкап не восстанавливается** | `not found` при restore | Полный и дифференциальный бэкапы в разных директориях | Положить всю цепочку в одну папку — см. [бэкап и восстановление](./backup_and_restore.md) |
| **APOC не найден** | `Procedure not found` после обновления | Несовместимая версия APOC JAR | Убедиться, что версия APOC совпадает с версией Neo4j по году и месяцу; см. [APOC](./apoc.md) |
| **Запросы зависают после обновления** | Высокий `planning` в `query.log` | План не пересобран после изменения индексов | `CALL db.clearQueryCaches()` — см. [оптимизацию запросов](./query_optimization.md) |

## Лучшие практики

- **Фиксируйте `neo4j.conf` в репозитории.** Конфигурация — часть состояния системы; воспроизводимость важнее удобства редактирования на месте.
- **Задавайте память явно.** Без явных `server.memory.*` Neo4j вычисляет значения сам, и результат меняется от версии к версии. Используйте `neo4j-admin server memory-recommendation` дляbaseline.
- **Не меняйте `initial_size` и `max_size` по отдельности.** Расхождение вызывает Full GC на каждом расширении кучи.
- **Отключайте VERBOSE на production.** `db.logs.query.enabled=INFO` с осмысленным порогом вместо `VERBOSE` снижает объём логов.
- **Используйте `--require-password-change`** при установке начального пароля.
- **Не выставляйте порты наружу без необходимости.** Bolt (7687) только на внутренней сети; HTTP (7474) выключен; HTTPS (7473) только через reverse proxy с TLS.
- **Для production используйте Enterprise Edition**, если нужны: кластеризация, онлайн-бэкап, несколько баз, fine-grained RBAC, `block` формат, `parallel` runtime, Bloom, GDS Enterprise.
- **Планируйте миграцию формата как операцию с окном простоя.** 100 ГБ — от 10 минут до более часа; тестируйте на копии.
- **Восстанавливайте в новую базу, а не поверх существующей** — так проверка не зависит от боевого окружения.
- **Используйте именованные тома Docker** для данных и логов, а не bind mounts — это упрощает миграцию и бэкап.

## См. также

- **[Обзор Neo4j](./overview.md)** — редакции и лицензии, версии и поддержка, модель данных, форматы хранения, порты и коннекторы, версии Cypher и рантаймы.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, store files, файловая структура, WAL, page cache.
- **[Обслуживание и эксплуатация](./operations.md)** — systemd hardening, память, checkpoint, диагностика, метрики, journald.
- **[Мониторинг и логи](./monitoring.md)** — расположение логов, Log4j 2, query.log, Prometheus, диагностика.
- **[Безопасность](./security.md)** — RBAC, TLS, file permissions, auth recovery, production hardening чек-лист.
- **[APOC: библиотека расширений](./apoc.md)** — установка, конфигурация, allowlist, Docker production, безопасность.
- **[Бэкап и восстановление](./backup_and_restore.md)** — офлайн- и онлайн-бэкап, restore, PITR, проверка, миграция формата.
- **[Драйверы](./drivers.md)** — пулы соединений, ретраи, causal consistency, TLS, health check.
- **[Кластеризация и HA](./clustering.md)** — primary/secondary, топология, маршрутизация, rolling upgrade, DR.
- **[Kubernetes](./kubernetes_deployment.md)** — развёртывание в Kubernetes, типы томов, лимиты памяти.
- **[Массовый импорт и начальная загрузка](./bulk_import.md)** — начальная загрузка данных через `neo4j-admin`.

