# Обновление и миграция Grafana

**Актуально для:** Grafana 13.2.x (актуальная линия) / 12.4.x (LTS); 11.x — EOL (25 июня 2026). Облачные и ИИ-функции не рассматриваются.

## Определения

- **Release (стабильный выпуск)** — версия Grafana вида `MAJOR.MINOR.PATCH`; мажорные (MAJOR) содержат breaking changes, минорные (MINOR) — новые функции и возможные deprecations, патч (PATCH) — только исправления и security-фиксы.
- **Миграция схемы БД** — автоматическое преобразование структуры таблиц базы Grafana при каждом старте на более новой версии; выполняется только вперёд (forward-only) и необратима.
- **Plugin compatibility** — плагины версионируются независимо от ядра Grafana и объявляют в `plugin.json` совместимый диапазон (`grafanaDependency`); несовместимый плагин блокируется при старте.
- **LTS (Long Term Support)** — минорная ветка с расширенным сроком поддержки. Последний минор мажорной линии получает расширенную поддержку (15 месяцев против обычных 9): 12.4.x — последний минор линии 12, поэтому является LTS.
- **Rolling Update** — поочерёдное обновление реплик без простоя (для HA); классическая стратегия для Kubernetes/Helm.
- **Blue-Green** — параллельный запуск двух сред (старой и новой версии) с переключением трафика; альтернатива Rolling Update для одиночного узла.
- **Смена типа СУБД** — миграция хранилища состояния между SQLite/MySQL/PostgreSQL; штатным апгрейдом не выполняется и требует отдельного переноса данных.

## Базовые концепции

### Три независимые плоскости

Обновление затрагивает три независимые подсистемы, и сбой в любой из них ломает запуск:

1. **Бинарник/образ/пакет Grafana.** Собственно ядро; версия меняется через менеджер пакетов, тег образа или чарт.
2. **Схема БД.** Мигрирует автоматически при первом старте новой версии. Обратного хода нет — откат ядра без отката БД невозможен.
3. **Плагины.** Обновляются отдельно (каталог/образ/`grafana cli`); версия плагина часто несовпадает с версией ядра — это частая причина «Grafana не стартует» после апгрейда.

### Инкрементальный путь и поддержка версий

Grafana обновляется пошагово: рекомендуется идти по мажорным линиям последовательно (11 → 12 → 13), не перепрыгивая мажор. Официальная политика поддержки self-managed Grafana (OSS и Enterprise одинакова):

- каждый минорный выпуск поддерживается **9 месяцев** с даты релиза;
- **последний минор мажорной линии** получает расширенную поддержку **15 месяцев** (это и есть LTS-ветка);
- до окончания поддержки приходят security-патчи и исправления критичных дефектов; новые функции — только в текущей мажорной линии.

Ниже — состояние поддержки на конец 2026 года:

| Версия | Дата релиза | Конец поддержки | Уровень |
| :--- | :--- | :--- | :--- |
| 11.6.x (последний минор 11) | 25 марта 2025 | 25 июня 2026 | EOL (не поддерживается) |
| 12.4.x (последний минор 12, LTS) | 24 февраля 2026 | 24 мая 2027 | Patch Support |
| 13.0.x | 14 апреля 2026 | 9 января 2027 | Patch Support |
| 13.1.x | 23 июня 2026 | 20 марта 2027 | Patch Support |
| 13.2.x (актуальная) | 18 августа 2026 | 18 мая 2027 | Full/Patch Support |

**Стратегии обновления** (официальная рекомендация — минорная):

- **Минорная (bi-monthly, напр. 13.1 → 13.2)** — рекомендуется: маленький changelog, свежие security-фиксы, максимальная совместимость с активно развиваемыми плагинами.
- **По предыдущему мажору (раз в год, напр. 11.6 → 12.4)** — длинный срок поддержки, но большой объём изменений для ревью и худшая совместимость с новыми плагинами.
- **LTS-ориентированная** — держаться последнего минора мажора (12.4.x) и редко обновляться: минимальный риск нестабильности ценой отсутствия новых функций.

### Изменения между версиями, важные для апгрейда

Перед мажорным апгрейдом обязательно читайте release notes соответствующей версии. Ключевые breaking changes последних линий:

- **11 → 12:** API Keys окончательно выведены из эксплуатации (все существующие ключи автоматически мигрированы в Service Accounts в январе 2025); удалены связанные permissions `apikeys:read/create/delete` и роли `fixed:apikeys:*`.
- **12 → 13:** удалены устаревшие команды `grafana-cli` и `grafana-server` (deprecated с v10) — используются `grafana cli` и `grafana server`; ядро переведено на React 19 (плагины, не готовые к нему, могут давать «Application Error»); введена схема дашборда `v2` и движок Dynamic Dashboards (дашборды `v1` мигрируют в `v2` автоматически при открытии).

### Миграция схемы БД

Схема БД мигрирует автоматически при старте Grafana. Особенности:

- Миграция идемпотентна внутри одной версии и необратима вперёд: запустив новую версию, вернуться на старую без восстановления БД нельзя.
- Для внешних СУБД миграция берёт блокировку (управляется `[database] migration_locking = true`); при нескольких репликах одновременно мигрирует одна, остальные ждут.
- Объём и длительность миграции зависят от размера БД, в первую очередь от истории версий дашбордов (`dashboard_version`). Раздутая история замедляет и апгрейд, и бэкап (см. `versions_to_keep` в [grafana_performance_tuning.md](grafana_performance_tuning.md)).

### Смена типа СУБД

Прямого конвертера между типами СУБД у Grafana нет. Возможны два направления:

- **SQLite → PostgreSQL** — возможен прямой перенос данных сторонней утилитой (см. Сценарий 7).
- **MySQL ↔ PostgreSQL** — перенос только через API/провиженинг: пересоздание дашбордов, источников, папок и заведение пользователей заново (см. Сценарий 6).

## Практические сценарии

### Предварительные требования

- Свежий бэкап БД и `grafana.ini` (см. [grafana_backup_restore.md](grafana_backup_restore.md)) — обязательно до любого обновления.
- Зафиксированная текущая версия и состояние: `grafana server -v` и `curl /api/health`.
- Окно обслуживания: для одиночного инстанса — простой, для HA — поочерёдное обновление реплик.
- Доступ к репозиторию пакетов/образу, а для Kubernetes — к чарту.
- Проверенные на совместимость с целевой версией плагины.

### Сценарий 0. Предобновленческая проверка

Выполняется до простоя и снижает риск неожиданных сбоев:

```bash
# 1. Текущая версия ядра и состояние БД
grafana server -v
curl -s http://localhost:3000/api/health
# → {"commit":"...","database":"ok","version":"13.1.x"}

# 2. Свободное место в каталоге данных (миграция и дампы занимают место)
df -h /var/lib/grafana

# 3. Установленные плагины и их версии (сверить с целевой версией ядра)
grafana cli plugins ls

# 4. Есть ли в текущих логах предупреждения об устаревших опциях
journalctl -u grafana-server --no-pager | grep -i deprecat
```

**Проверка на стенде:** восстановите копию рабочей БД в тестовом окружении, поднимите целевую версию, откройте ключевые дашборды, проверьте источники данных и правила алертинга. Это единственный надёжный способ выявить несовместимость плагинов и моделей алертов без риска для продакшена.

### Сценарий 1. Обновление на Debian/Ubuntu (deb)

```bash
# Текущая версия
grafana server -v
# → Version 12.4.0

# Бэкап ДО обновления (см. grafana_backup_restore.md)
# Обновление пакета
sudo apt-get update
sudo apt-get install -y grafana=13.2.3

# Запуск — Grafana сама накатит миграции схемы
sudo systemctl restart grafana-server
```

Проверка:

```bash
curl -s http://localhost:3000/api/health
# → {"database":"ok","version":"13.2.3"}
journalctl -u grafana-server -n 50 --no-pager | grep -i "migrat\|error"
# → "migrations completed" без ошибок
```

> Служба systemd по-прежнему называется `grafana-server`, но отдельный бинарник `grafana-server` удалён в Grafana 13 — команды версии и администрирования выполняются как `grafana server ...` и `grafana cli ...` (см. [grafana_plugins.md](grafana_plugins.md)).

### Сценарий 2. Обновление через Docker Compose

```bash
# В docker-compose.yml поменять тег образа на целевой (не :latest в проде!)
sed -i 's/grafana:12.4.0/grafana:13.2.3/' docker-compose.yml

docker compose pull grafana
docker compose up -d grafana
# → контейнер пересоздаётся; миграции БД выполняются при старте
```

Проверка: `docker compose logs grafana --tail 50` — отсутствие `panic`/`migration failed`.

### Сценарий 3. Обновление через Helm

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
helm upgrade grafana grafana-community/grafana --version 13.5.0 -f values.yaml -n monitoring
# → новый ReplicaSet; миграции при старте пода
```

Для production рекомендуется `--atomic --wait --timeout 10m`: при непрохождении `readinessProbe` Helm автоматически откатит релиз. Пошаговое обновление реплик в кластере (Rolling Update, анти-аффинность, проверки готовности) — в [high_availability.md](high_availability.md).

### Сценарий 4. Обновление плагинов

Обновляйте плагины **сразу после** обновления ядра (в новой версии Grafana часть старых плагинов может перестать работать):

```bash
# Обновить все установленные плагины
grafana cli plugins update-all

# Обновить один плагин
grafana cli plugins update <plugin-id>

# Список установленных плагинов
grafana cli plugins ls
```

При несовместимом плагине Grafana пишет в лог `plugin is unsigned`/`plugin X incompatible` и не загружает его. Обновите плагин или удалите: `grafana cli plugins remove <plugin-id>`. Полный порядок обновления (ядро → патч → плагины → мажор) и особенности React 19 — в [grafana_plugins.md](grafana_plugins.md).

### Сценарий 5. Откат (rollback)

Схему БД откатить нельзя, поэтому откат версии возможен только вместе с БД:

```bash
# 1. Остановить Grafana
sudo systemctl stop grafana-server

# 2. Вернуть прежнюю версию пакета/образа/чарта
sudo apt-get install -y grafana=<previous-version>

# 3. Восстановить БД из бэкапа, снятого ДО обновления
#    (см. grafana_backup_restore.md, сценарии восстановления)

# 4. Запустить сервис
sudo systemctl start grafana-server
```

Для Docker/Helm — вернуть предыдущий тег образа/чарта и восстановить БД из дампа. Если рабочая БД уже мигрирована новой версией, запуск старого ядра на ней завершится ошибкой `database migration failed` — восстановление дампа обязательно.

### Сценарий 6. Миграция MySQL → PostgreSQL (и обратно)

Прямого средства нет; состояние переносится через API:

```bash
# 1. Поднять Grafana на новой БД (пустой PostgreSQL), та же версия
# 2. Экспортировать дашборды/папки/источники со старой (MySQL) инстанции через API
GRAFANA_TOKEN=<sa-token>
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$OLD/api/search?type=dash-db&limit=5000" > export-list.json
# (см. grafana_backup_restore.md, Сценарий 5 — тот же механизм)

# 3. Импортировать на новую инстанцию
for f in dashboard-*.json; do
  curl -s -X POST -H "Authorization: Bearer $NEW_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"dashboard\":$(jq -c '.dashboard' "$f"),\"overwrite\":true}" \
    "$NEW/api/dashboards/db"
done
# → дашборды перенесены; пользователей/роли переносим отдельно (API users/org)
```

Пользователи и их пароли через API не переносятся (хеши привязаны к БД) — заведите их заново через SSO/RBAC или провиженинг.

> В Grafana 13 маршруты `/api` считаются устаревшими в пользу `/apis`, но продолжают работать без изменений; в примерах выше используются стабильные legacy-эндпоинты.

### Сценарий 7. Миграция SQLite → PostgreSQL (Docker Compose)

При интенсивной нагрузке на систему оповещений (Unified Alerting, начиная с Grafana 8.0/9.0) встроенная SQLite может блокироваться из-за ограничений на конкурентную запись. Симптом — в логах `error="database is locked"`. Временное облегчение — настройки SQLite, постоянное решение — переход на PostgreSQL.

#### Подготовка: смягчение блокировок SQLite

До миграции (или если переход пока невозможен) включите Write-Ahead Logging и повторы запросов в `[database]`:

```ini
[database]
type = sqlite3
wal = true
query_retries = 3
```

`wal = true` переводит БД в журнальный режим WAL (по умолчанию `false`); `query_retries` задаёт число повторов запроса при блокировке (по умолчанию `0`). Это снижает частоту ошибок, но не устраняет принципиальное ограничение SQLite на конкурентную запись — для production нужна серверная СУБД.

> WAL хранит индекс страниц в разделяемой памяти (`-shm`-файл), поэтому он пригоден только для локальных файловых систем и небезопасен на сетевых (NFS/EFS и т. п.) и при доступе нескольких хостов к одному файлу БД.

#### Временное решение (аварийный бэкап)

При внезапной блокировке (падение контейнера/хоста) помогает клонирование файла БД:

```bash
sqlite3 grafana.db '.clone grafana-new.db'
mv grafana.db grafana-old.db
mv grafana-new.db grafana.db
```

Это работает как аварийная мера, но не решает проблему при росте числа алертов и частых обновлений.

#### Постоянное решение: миграция в PostgreSQL

##### 1. Развёртывание PostgreSQL

Добавляем сервис в `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    restart: always
    container_name: postgres-grafana
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=<strong-password>
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
```

Запускаем и создаём БД:

```bash
docker compose up -d postgres
docker exec -ti postgres-grafana psql -U postgres -c "CREATE DATABASE grafana;"
```

##### 2. Подготовка Grafana

Временно добавляем сервис Grafana с подключением к пустой PostgreSQL, чтобы накатить миграции схемы:

```yaml
  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    user: "472:472"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      GF_DATABASE_TYPE: postgres
      GF_DATABASE_HOST: postgres:5432
      GF_DATABASE_NAME: grafana
      GF_DATABASE_USER: postgres
      GF_DATABASE_PASSWORD: <strong-password>
      GF_DATABASE_SSL_MODE: disable
    ports:
      - "3000:3000"
```

Запускаем и ждём завершения миграций:

```bash
docker compose up -d grafana
docker logs -f grafana
# → "migrations completed"
```

Останавливаем Grafana перед переносом данных:

```bash
docker compose stop grafana
```

##### 3. Перенос данных

**Вариант A: pgloader** (не рекомендуется для продакшена). Утилита пытается импортировать hex-значения напрямую, что ломает авторизацию. На PostgreSQL 14+ по умолчанию используется аутентификация `scram-sha-256`, с которой pgloader не работает без ручной перенастройки.

**Вариант B: сторонняя утилита переноса SQLite → PostgreSQL** (рекомендуется). Утилиты семейства `grafana-sqlite-to-postgres` корректно обрабатывают hex-поля:

```bash
# Скачать бинарник со страницы релизов:
# https://github.com/wbh1/grafana-sqlite-to-postgres/releases (например, v2.2.4)
chmod +x grafana-migrate

./grafana-migrate /var/lib/grafana/grafana.db \
  'postgres://postgres:<strong-password>@127.0.0.1:5432/grafana?sslmode=disable'
```

> **Важно:** оригинальный инструмент `wbh1/grafana-sqlite-to-postgres` переведён в режим best-effort (фактически не развивается) и не всегда успевает за изменениями схемы Grafana. Начиная с Grafana 11.4 возможны расхождения типов и порядка колонок (`is_prunable`, `is_provisioned`, таблица `playlist`); при ошибках импорта (`pq: column ... is of type ...`) таблицы-цели приходится временно приводить вручную, а после импорта — возвращать типы. Для больших и новых БД предпочтительнее поддерживаемые форки: [percona/grafana-db-migrator](https://github.com/percona/grafana-db-migrator) и `rl0nergan/grafana-db-migrator`. Всегда проверяйте перенос алертов (contact points, templates, notification policies) — известны случаи их неполного переноса.

Если ранее запускался pgloader, удалите БД и создайте заново.

Проверка: в PostgreSQL появились таблицы с данными дашбордов, пользователей и алертов.

##### 3.1. Утилита pgloader (справочно)

`pgloader` переносит данные SQLite → PostgreSQL, но не годится для production: он импортирует hex-значения полей `data_source`/`user` напрямую, что ломает расшифровку секретов и авторизацию, а на PostgreSQL 14+ требует ручной настройки под `scram-sha-256`. Используйте его только для чернового переноса тестовых данных.

##### 4. Финальная конфигурация

Убираем временный сервис, оставляем постоянный:

```yaml
  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    user: "472:472"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      GF_DATABASE_TYPE: postgres
      GF_DATABASE_HOST: postgres:5432
      GF_DATABASE_NAME: grafana
      GF_DATABASE_USER: postgres
      GF_DATABASE_PASSWORD: <strong-password>
      GF_DATABASE_SSL_MODE: disable
    ports:
      - "3000:3000"
```

Запускаем:

```bash
docker compose up -d grafana
docker logs -f grafana
# → "migrations completed"
```

##### 5. Проверка

```bash
curl -s http://localhost:3000/api/health
# → {"database":"ok","version":"13.2.3"}
```

Проверьте авторизацию и отображение дашбордов.

##### Производительность миграции

Время зависит от типа диска (ориентировочные значения для БД ~150 МБ):

- HDD: >12 часов;
- SSD: несколько часов;
- NVMe: ~30 минут.

Если миграция занимает слишком долго на production-хосте, выполните её на временном сервере с быстрым диском, затем перенесите том PostgreSQL.

## Дополнительная информация

### Рекомендации по эксплуатации

- Не используйте `:latest` в проде — фиксируйте точную версию (пакет/тег/чарт).
- Обновляйтесь по одному мажору за раз; читайте release notes на breaking changes (особенно 11 → 12: API Keys → Service Accounts; 12 → 13: удаление `grafana-cli`/`grafana-server`, React 19, схема дашборда v2).
- Бэкап БД — обязателен перед каждым мажорным обновлением; бэкап без проверки восстановления бэкапом не считается.
- Обновляйте плагины сразу после ядра и проверяйте совместимость с целевой версией.
- Для HA обновляйте реплики поочерёдно (drain → обновить → вернуть в балансировку), не обновляйте все узлы одновременно (см. [high_availability.md](high_availability.md)).
- Проверяйте актуальность `grafana.ini`: новые версии добавляют ключи в `defaults.ini`, а ваш `grafana.ini` не сливается автоматически; удалённые/устаревшие опции игнорируются. Переопределения через `GF_*`, Helm values или аргументы запуска учитывайте наравне с файлом.
- Для больших инсталляций держите объём истории версий дашбордов под контролем (`[dashboards] versions_to_keep`) — это ускоряет и миграции, и бэкапы.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | :--- | :--- |
| `database migration failed` при старте | Дамп от более новой версии или повреждённая БД | Восстановить БД из бэкапа нужной версии |
| Grafana не стартует, `plugin X incompatible` | Плагин несовместим с новой версией | `grafana cli plugins update <id>` или `remove` |
| `command not found: grafana-server`/`grafana-cli` после обновления до 13 | Команды удалены в v13 | Использовать `grafana server` и `grafana cli` |
| «Application Error» в UI после обновления до 13 | Плагин несовместим с React 19 | Обновить плагин до версии с поддержкой Grafana 13 |
| Источники данных недоступны после переезда | Другой `secret_key` — секреты не расшифровываются | Перенести прежний `secret_key` |
| Дашборды сломались после 11 → 12 | API Keys упразднены (перенесены в Service Accounts), изменения в Alerting | Проверить, что интеграции используют SA-токены, перепроверить правила алертов |
| `database is locked` (SQLite) | Конкурентная запись в SQLite | `wal = true`, `query_retries > 0`; постоянное решение — PostgreSQL (Сценарий 7) |
| Откат не работает (`database migration failed`) | Схема мигрировала вперёд | Только восстановление БД из бэкапа нужной версии |
| Helm: под в CrashLoopBackOff | Миграция БД не прошла из-за прав доступа | Проверить доступ к БД и логи init-контейнера/пода |
| Миграция SQLite → PG падает на `is_prunable`/`playlist` | Инструмент отстаёт от схемы Grafana | Использовать актуальный форк или ручные `ALTER TABLE` (см. Сценарий 7) |

### Ограничения и особые случаи

- Миграция схемы необратима; не запускайте новую версию без бэкапа.
- Переход MySQL ↔ PostgreSQL требует переноса через API (Сценарий 6); SQLite → PostgreSQL возможен прямым переносом данных (Сценарий 7). В обоих случаях пароли пользователей автоматически не переносятся.
- `secret_key` должен быть сохранён; иначе зашифрованные секреты источников данных не расшифруются.
- При обновлении в HA все реплики должны в итоге иметь одинаковую версию; кратковременно допускается различие патчей, но не мажоров.
- Плагины версионируются независимо от ядра, и старые версии при обновлении через CLI не удаляются автоматически — проверяйте `grafana cli plugins ls`.
- Утилита `grafana-migrate` (SQLite → PostgreSQL) поддерживается на уровне «best-effort» и может не успевать за изменениями схемы Grafana; для крупных и новых БД предпочтительны поддерживаемые форки.
- Диагностика сбоев миграции (доступ к БД, ход миграции в логах, права) — в [grafana_troubleshooting.md](grafana_troubleshooting.md).

### Связанные темы

- [Резервное копирование и восстановление](grafana_backup_restore.md)
- [Высокая доступность и отказоустойчивость](high_availability.md)
- [Провиженинг дашбордов и источников данных](grafana_provisioning.md)
- [Плагины Grafana](grafana_plugins.md)
- [Диагностика и устранение неполадок](grafana_troubleshooting.md)
- [Производительность и тюнинг](grafana_performance_tuning.md)
