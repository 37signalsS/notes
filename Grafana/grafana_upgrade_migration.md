# Обновление и миграция Grafana

Практическое руководство по обновлению self-hosted Grafana и миграции между СУБД. Версии: 13.x — актуальная, 12.x — LTS, 11.x — EOL (июнь 2026). Облачные и ИИ-функции не рассматриваются.

## Определения

- **Release (стабильный выпуск)** — версия Grafana вида `X.Y.Z`; мажорные (X) содержат breaking changes, минорные (Y) — новые функции и возможные deprecations, патч (Z) — исправления.
- **Миграция схемы БД** — автоматическое преобразование структуры базы Grafana при каждом старте на более новой версии; выполняется только вперёд.
- **Plugin compatibility** — плагины имеют собственные версии и совместимость с мажорными версиями Grafana; несовместимый плагин блокируется при старте.
- **LTS (Long Term Support)** — ветка с расширенными исправлениями; 12.x — текущая LTS.
- **Rolling/Blue-Green** — стратегии обновления без/с минимальным простоем (для HA).

## Базовые концепции

Grafana обновляется инкрементально: рекомендуется идти по мажорным версиям по одной (11 → 12 → 13), не «перепрыгивать» через мажор. Схема БД мигрирует автоматически при первом старте новой версии; обратного хода нет, поэтому обязателен свежий бэкап ДО обновления.

Обновление затрагивает три независимые плоскости: (1) сам бинарник/образ Grafana, (2) схему БД (мигрирует сама), (3) плагины (обновляются отдельно, часто через провиженинг или `grafana-cli`). Несовпадение версии плагина с Grafana — частая причина «Grafana не стартует» после апгрейда.

Миграция типа СУБД (MySQL ↔ PostgreSQL) — отдельная задача, не выполняемая штатным апгрейдом; делается через экспорт состояния по API и пересоздание БД. Прямого конвертера БД Grafana нет.

## Практические сценарии

### Предварительные требования

- Свежий бэкап БД и `grafana.ini` (см. связанные темы) — обязательно до любого обновления.
- Фиксация текущей версии: `grafana-server -v` или `curl /api/health`.
- Окно обслуживания (для одиночного инстанса — простой; для HA — поочерёдно).
- Доступ к репозиторию пакетов или образу; для Helm — доступ к чарту.
- Проверка совместимости плагинов с целевой версией на странице релиза/в каталоге плагинов.

### Сценарий 1. Обновление на Debian/Ubuntu (deb)

```bash
# Текущая версия
grafana-server -v
# → Version 12.4.0

# Бэкап ДО обновления (см. grafana_backup_restore.md)
# Обновление пакета
sudo apt-get update
sudo apt-get install -y grafana=13.1.0

# Запуск — Grafana сама накатит миграции схемы
sudo systemctl restart grafana-server
```

Проверка:

```bash
curl -s http://localhost:3000/api/health
# → {"database":"ok","status":"ok","version":"13.1.0"}
journalctl -u grafana-server -n 50 --no-pager | grep -i "migrat\|error" 
# → "migrations completed" без ошибок
```

### Сценарий 2. Обновление через Docker Compose

```bash
# В docker-compose.yml поменять тег образа на целевой (не :latest в проде!)
sed -i 's/grafana:12.4.0/grafana:13.1.0/' docker-compose.yml

docker compose pull grafana
docker compose up -d grafana
# → контейнер пересоздаётся; миграции БД выполняются при старте
```

Проверка: `docker compose logs grafana --tail 50` — отсутствие `panic`/`migration failed`.

### Сценарий 3. Обновление через Helm

```bash
helm repo update
helm upgrade grafana grafana/grafana --version 13.1.0 -f values.yaml -n monitoring
# → новый ReplicaSet; миграции при старте пода
```

### Сценарий 4. Обновление плагинов

```bash
# Обновить все установленные плагины
grafana-cli plugins update-all

# Или конкретный
grafana-cli plugins update grafana-piechart-panel

# Установленные (для сверки версий)
grafana-cli plugins ls
```

Если плагин несовместим с новой Grafana, Grafana заблокирует его загрузку и запишет ошибку в лог; обновите плагин или временно удалите (`grafana-cli plugins remove <id>`).

### Сценарий 5. Откат (rollback)

Штатного отката схемы БД нет. Откат = восстановление из бэкапа:

```bash
systemctl stop grafana-server
# Восстановить БД из дампа нужной версии (grafana_backup_restore.md)
# Вернуть grafana.ini и пакет/образ предыдущей версии
sudo apt-get install -y grafana=12.4.0
systemctl start grafana-server
```

Для Docker/Helm — вернуть предыдущий тег образа/чарта и БД из бэкапа.

### Сценарий 6. Миграция MySQL → PostgreSQL (и обратно)

Прямого средства нет; переносим состояние через API:

```bash
# 1. Поднять Grafana на новой БД (пустой PostgreSQL), та же версия
# 2. Экспортировать дашборды/папки/источники со старой (MySQL) инстанции через API
GRAFANA_TOKEN=<sa-token>
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$OLD/api/search?type=dash-db&limit=5000" > export-list.json
# (см. grafana_backup_restore.md, Сценарий 3 — тот же механизм)

# 3. Импортировать на новую инстанцию
for f in dashboard-*.json; do
  curl -s -X POST -H "Authorization: Bearer $NEW_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"dashboard\":$(jq -c '.dashboard' "$f"),\"overwrite\":true}" \
    "$NEW/api/dashboards/db"
done
# → дашборды перенесены; пользователей/роли переносим отдельно (API users/org)
```

Пользователи и их пароли через API не переносятся (хеши привязаны к БД) — заведите их заново через SSO/RBAC или экспорт/импорт через провиженинг.

### Сценарий 7. Миграция SQLite → PostgreSQL (Docker Compose)

При интенсивной нагрузке на систему оповещений (начиная с Grafana 8.0.0 Unified Alerting) встроенная SQLite может блокироваться из-за ограничений на конкурентную запись. Симптом — в логах `error="database is locked"`. Временное решение — аварийное клонирование файла БД, постоянное — переход на PostgreSQL.

#### Временное решение (аварийный бэкап)

```bash
sqlite3 grafana.db '.clone grafana-new.db'
mv grafana.db grafana-old.db
mv grafana-new.db grafana.db
```

Работает при внезапной блокировке (падение контейнера/хоста), но не решает проблему при росте числа алертов и частых обновлений.

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
    image: grafana/grafana:13.1.3
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
      GF_DATABASE_PASSWORD=<strong-password>
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

**Вариант A: pgloader** (не рекомендуется для продакшена). Утилита пытается импортировать hex-значения напрямую, что ломает авторизацию. На PostgreSQL 14+ по умолчанию используется `scram-sha-256`, с которым pgloader не работает без ручной настройки аутентификации.

**Вариант B: grafana-migrate** (рекомендуется). Утилита сообщества корректно обрабатывает hex-поля:

```bash
wget https://github.com/wbh1/grafana-sqlite-to-postgres/releases/download/v2.2.3/grafana-migrate_linux_amd64-v2.2.3
chmod +x grafana-migrate_linux_amd64-v2.2.3

./grafana-migrate_linux_amd64-v2.2.3 /var/lib/grafana/grafana.db \
  'postgres://postgres:<strong-password>@127.0.0.1:5432/grafana?sslmode=disable'
```

Если до этого использовался pgloader, удалите БД и создайте заново.

Проверка: в PostgreSQL появились таблицы с данными дашбордов, пользователей и алертов.

##### 4. Финальная конфигурация

Убираем временный сервис, оставляем постоянный:

```yaml
  grafana:
    image: grafana/grafana:13.1.3
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
      GF_DATABASE_PASSWORD=<strong-password>
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
# → {"database":"ok","status":"ok","version":"13.1.3"}
```

Проверьте авторизацию и отображение дашбордов.

##### Производительность миграции

Время зависит от типа диска:
- HDD: >12 часов для БД ~150 МБ
- SSD: несколько часов
- NVMe: ~30 минут для БД ~150 МБ

Если миграция занимает слишком долго на production-хосте, выполните её на временном сервере с быстрым диском, затем перенесите том PostgreSQL.

#### Ограничения и особые случаи

- Пароли пользователей не мигрируют автоматически (хеши привязаны к `secret_key` и механизму хранения). Перенастройте аутентификацию через SSO/RBAC.
- `secret_key` должен быть сохранён; иначе зашифрованные секреты источников данных не расшифруются.
- Миграция схемы БД при старте Grafana выполняется автоматически, но только вперёд.

## Дополнительная информация

### Рекомендации по эксплуатации

- Не используйте `:latest` в проде — фиксируйте мажорную/минорную версию.
- Обновляйтесь по одному мажору за раз; читайте release notes на breaking changes (особенно 11→12: API Keys → Service Accounts Legacy, Alertmanager встроен).
- Бэкап БД — обязателен перед каждым мажорным обновлением.
- Плагины обновляйте синхронно с Grafana и проверяйте совместимость.
- Для HA обновляйте реплики поочерёдно (drain → обновить → вернуть в балансировку).

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| `database migration failed` при старте | Дамп от более новой версии или повреждённая БД | Восстановить БД из бэкапа нужной версии |
| Grafana не стартует, `plugin X incompatible` | Плагин несовместим с новой версией | `grafana-cli plugins update <id>` или `remove` |
| Дашборды сломались после 11→12 | API Keys помечены Legacy, изменения в Alerting | Перевести API Keys в Service Accounts, перепроверить правила алертов |
| `secret_key` mismatch после переезда | Секреты источников не расшифровываются | Перенести тот же `secret_key` |
| Откат не работает (БД новее) | Схема мигрировала вперёд | Только восстановление из бэкапа нужной версии |
| Helm: под в CrashLoopBackOff | Миграция БД не прошла из-за прав доступа | Проверить доступ к БД, логи init-контейнера |

### Ограничения и особые случаи

- Миграция схемы необратима; не запускайте новую версию без бэкапа.
- Переход MySQL ↔ PostgreSQL требует переноса через API (см. Сценарий 6); миграция SQLite → PostgreSQL возможна напрямую через grafana-migrate (см. Сценарий 7). В обоих случаях пароли пользователей не мигрируют автоматически.
- При обновлении в HA все реплики должны в итоге иметь одинаковую версию; допускается кратковременное сосуществование разных патч-версий, но не мажоров.
- Некоторые фичи (например, dashboard query caching) появились в 11.x — их настройка имеет смысл только на актуальных версиях.

### Очистка и откат изменений

- После успешного обновления оставьте бэкап ДО обновления минимум на один цикл, затем удалите.
- Удалите временные экспорт-файлы (`export-list.json`, `dashboard-*.json`) после подтверждения работоспособности.
- При неудаче — верните предыдущий образ/пакет и БД из бэкапа (Сценарий 5).

### Актуальность и статус

Актуально для 11.x/12.x/13.x. 11.x уходит в EOL (июнь 2026) — планируйте переход на 12.x LTS/13.x. Breaking changes 11→12→13 документированы в официальных release notes; сверяйтесь перед мажорным апгрейдом.

### Связанные темы

- [Резервное копирование и восстановление](grafana_backup_restore.md)
- [Высокая доступность и отказоустойчивость](high_availability.md)
- [Провиженинг дашбордов и источников данных](grafana_provisioning.md)
