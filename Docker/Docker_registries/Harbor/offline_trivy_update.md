# Harbor: Оффлайн-обновление баз Trivy

**Актуально для:** Harbor 2.15.x. Версии Trivy: 2.15.0 — v0.69.3 / adapter v0.35.1; 2.15.1 — v0.70.0 / adapter v0.36.0; 2.15.2 — v0.72.0 / adapter v0.38.0. Для точной матрицы см. [harbor-scanner-trivy](https://github.com/goharbor/harbor-scanner-trivy).

## Определения

* **Trivy**: Сканер уязвимостей, встроенный в Harbor. Использует базы данных уязвимостей (Trivy DB и Trivy Java DB) для идентификации CVE в образах.
* **Trivy DB (схема v2)**: Основная база данных уязвимостей (пакеты ОС и зависимости приложений). Публикуется как OCI-артефакт `ghcr.io/aquasecurity/trivy-db:2`.
* **Trivy Java DB (схема v1)**: База для анализа уязвимостей в Java-библиотеках. OCI-артефакт `ghcr.io/aquasecurity/trivy-java-db:1`.
* **ORAS (OCI Registry As Storage)**: CLI-инструмент для работы с OCI-артефактами; позволяет скачать базы напрямую, без Docker-демона.
* **Air-gapped (закрытый контур)**: Среда без доступа к интернету. Обновления баз доставляются вручную.
* **trivy-offline.tar.gz**: Архив с файлами `trivy.db` и `metadata.json` — так именует бандл баз документация Harbor.

## Основные концепции

Сканер Trivy проверяет актуальность баз через файл `metadata.json` (содержит временную метку и интервал обновления) и при возможности скачивает новую версию из интернета. В закрытых контурах автоматическое обновление отключается (`skip_update`, `skip_java_db_update`), а базы доставляются вручную.

### Жизненный цикл обновления

1. **Загрузка**: На хосте с интернетом скачиваются актуальные базы из GitHub Container Registry (ORAS или Trivy CLI).
2. **Извлечение**: Распаковка OCI-артефактов в файлы (`trivy.db`, `metadata.json`, `trivy-java.db`).
3. **Транспортировка**: Перенос архивов во внутренний контур (rsync/ssh, съёмный носитель).
4. **Развёртывание**: Распаковка в кэш адаптера с правами пользователя `scanner` (UID/GID 10000).
5. **Валидация**: Проверка метки времени базы и работоспособности сканирования.

**Периодичность:** Trivy DB пересобирается несколько раз в сутки (каждые 6 часов согласно aquasecurity/trivy-db; Harbor документирует интервал в 12 часов), интервал обновления в `metadata.json` по умолчанию — 24 часа. Рекомендуется синхронизировать базы не реже одного раза в неделю.

## Требования

* Harbor 2.15.x с включённым Trivy (`install.sh --with-trivy` или `trivy.enabled: true` в Helm).
* На хосте с интернетом: `oras` ≥ v0.13.0 **или** Trivy CLI.
* Сетевой доступ к `ghcr.io` / `pkg-containers.githubusercontent.com` на онлайн-машине.
* Права sudo на сервере Harbor.

## Практические сценарии

### Сценарий 1: Подготовка баз с использованием ORAS (рекомендуется)

Использование `oras` — наиболее быстрый способ, не требующий запуска контейнеров.

```bash
# On a machine with internet access
oras pull ghcr.io/aquasecurity/trivy-db:2       # → db.tar.gz
oras pull ghcr.io/aquasecurity/trivy-java-db:1   # → javadb.tar.gz

# Bundle for transfer
tar -czf trivy-update-bundle.tgz db.tar.gz javadb.tar.gz
```

> Для ORAS < v0.13.0 добавьте флаг `-a` (artifact): `oras pull -a ghcr.io/aquasecurity/trivy-db:2`.

### Сценарий 2: Подготовка баз через Trivy CLI

Альтернатива ORAS — штатная команда Trivy (документированный способ заполнения кэша).

```bash
TRIVY_TEMP_DIR=$(mktemp -d)

# Vulnerability DB
trivy --cache-dir "$TRIVY_TEMP_DIR" image --download-db-only
tar -cf ./db.tar.gz -C "$TRIVY_TEMP_DIR/db" metadata.json trivy.db

# Java DB
trivy --cache-dir "$TRIVY_TEMP_DIR" image --download-java-db-only
tar -cf ./javadb.tar.gz -C "$TRIVY_TEMP_DIR/java-db" metadata.json trivy-java.db

rm -rf "$TRIVY_TEMP_DIR"
```

### Сценарий 3: Развёртывание баз на сервере Harbor (Docker Compose)

1. Перенесите архивы на сервер Harbor (например, `rsync -av -e ssh trivy-update-bundle.tgz user@harbor-host:/tmp/`).
2. Распакуйте файлы в кэш адаптера. Пути зависят от `data_volume` в `harbor.yml` (по умолчанию `/data`); контейнерный путь — `/home/scanner/.cache/trivy`:

```bash
DB_DIR="/data/trivy-adapter/trivy/db"
JAVA_DB_DIR="/data/trivy-adapter/trivy/java-db"

sudo mkdir -p "$DB_DIR" "$JAVA_DB_DIR"

sudo tar -xzf db.tar.gz -C "$DB_DIR"           # → trivy.db, metadata.json
sudo tar -xzf javadb.tar.gz -C "$JAVA_DB_DIR"  # → trivy-java.db, metadata.json

# The adapter container runs as user scanner (UID/GID 10000)
sudo chown -R 10000:10000 /data/trivy-adapter/trivy
```

3. Примените конфигурацию (если меняли `harbor.yml`) и перезапустите адаптер:

```bash
sudo ./prepare
sudo docker compose up -d

# Или только адаптер после ручной замены баз:
sudo docker restart trivy-adapter
```

> Отчёты сканирования кэшируются отдельно: `/data/trivy-adapter/reports` → `/home/scanner/.cache/reports`.

### Сценарий 4: Kubernetes (Helm)

В Helm-чарте адаптер — StatefulSet `<fullname>-trivy` (при релизе `harbor` — `harbor-trivy`; при другом имени релиза — `<release>-harbor-trivy`). Кэш расположен на PVC, смонтированном в `/home/scanner/.cache`.

```bash
# Найти под адаптера (лейбл component=trivy)
kubectl get pods -l component=trivy -n harbor
# → harbor-trivy-0   1/1     Running

# Скопировать распакованные файлы в кэш пода
kubectl cp trivy.db      harbor-trivy-0:/home/scanner/.cache/trivy/db/trivy.db      -n harbor
kubectl cp metadata.json harbor-trivy-0:/home/scanner/.cache/trivy/db/metadata.json  -n harbor
kubectl cp trivy-java.db      harbor-trivy-0:/home/scanner/.cache/trivy/java-db/trivy-java.db      -n harbor
kubectl cp metadata.json      harbor-trivy-0:/home/scanner/.cache/trivy/java-db/metadata.json      -n harbor
```

Отключение автоматических загрузок в values:

```yaml
trivy:
  skipUpdate: true
  skipJavaDBUpdate: true
  offlineScan: true
```

### Сценарий 5: Внутренний mirror баз (self-hosting)

Для полностью изолированных контуров базы можно зеркалировать во внутренний OCI-реестр и указать его в `harbor.yml`.

```bash
# На хосте с доступом к внутреннему реестру
oras cp ghcr.io/aquasecurity/trivy-db:2      registry.internal.local/trivy-db:2
oras cp ghcr.io/aquasecurity/trivy-java-db:1 registry.internal.local/trivy-java-db:1
```

```yaml
# harbor.yml
trivy:
  db_repository: registry.internal.local/trivy-db
  java_db_repository: registry.internal.local/trivy-java-db
```

> Mirror необходимо обновлять регулярно — иначе результаты сканирования устаревают. OCI-слой базы имеет нестандартный media type (`application/vnd.aquasec.trivy.db.layer.v1.tar+gzip`): это не обычный образ контейнера, для копирования используйте oras/crane/regclient.

## Конфигурация harbor.yml

Полный список параметров секции `trivy` (шаблон `make/harbor.yml.tmpl` Harbor 2.15.x):

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `ignore_unfixed` | `false` | Показывать только исправленные уязвимости |
| `skip_update` | `false` | Не скачивать Trivy DB из интернета. При `true` файлы `trivy.db` и `metadata.json` размещаются вручную в `/home/scanner/.cache/trivy/db` контейнера |
| `skip_java_db_update` | `false` | Не скачивать Java DB. При `true` файл `trivy-java.db` размещается вручную в `/home/scanner/.cache/trivy/java-db/` |
| `db_repository` | `ghcr.io/aquasecurity/trivy-db` | OCI-реестр для Trivy DB (можно указать внутренний mirror, см. сценарий 5) |
| `java_db_repository` | `ghcr.io/aquasecurity/trivy-java-db` | OCI-реестр для Java DB |
| `offline_scan` | `false` | Запретить API-запросы для идентификации зависимостей (JAR, pom.xml). Не влияет на скачивание баз; в air-gapped требуется вместе с `skip_update`. Число обнаруженных уязвимостей в Java-артефактах может уменьшиться. Примечание: для `security_check: config`/`misconfig` Trivy пытается скачать checks bundle даже в air-gapped; embedded checks используются как fallback при недоступности внешнего bundle |
| `security_check` | `vuln` | Что анализировать: `vuln`, `config`, `secret` (через запятую) |
| `insecure` | `false` | Пропускать проверку сертификата реестра (только dev/test) |
| `timeout` | `5m0s` | Таймаут ожидания сканирования; верхняя граница в job — 30 минут |
| `github_token` | — | GitHub-токен для скачивания баз (анонимно: 60 запросов/час; с токеном: 5000/час) |

Значения передаются адаптеру как переменные `SCANNER_TRIVY_*` (шаблон `make/photon/prepare/templates/trivy-adapter/env.jinja`): `SCANNER_TRIVY_SKIP_UPDATE`, `SCANNER_TRIVY_SKIP_JAVA_DB_UPDATE`, `SCANNER_TRIVY_OFFLINE_SCAN`, `SCANNER_TRIVY_DB_REPOSITORY`, `SCANNER_TRIVY_JAVA_DB_REPOSITORY`, `SCANNER_TRIVY_CACHE_DIR=/home/scanner/.cache/trivy`. Проверка применённых значений:

```bash
docker exec trivy-adapter env | grep SCANNER_TRIVY
# → SCANNER_TRIVY_SKIP_UPDATE=true
# → SCANNER_TRIVY_OFFLINE_SCAN=true
```

Минимальная конфигурация для закрытого контура:

```yaml
trivy:
  skip_update: true
  skip_java_db_update: true
  offline_scan: true
```

После редактирования `harbor.yml` выполните `sudo ./prepare && sudo docker compose up -d` — переменные окружения внедряются при создании контейнера, поэтому без пересоздания изменения не применяются.

## Валидация

1. Метка времени базы: `sudo cat /data/trivy-adapter/trivy/db/metadata.json` — поле обновления должно соответствовать дате синхронизации.
2. Конфигурация адаптера: `docker exec trivy-adapter env | grep SCANNER_TRIVY_SKIP_UPDATE` → `SCANNER_TRIVY_SKIP_UPDATE=true`.
3. Сканирование: запустите сканирование образа с известными CVE через UI или API — в отчёте должны появиться уязвимости.
4. Логи адаптера: `docker logs trivy-adapter` — отсутствие ошибок скачивания баз.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `database error: schema mismatch` | Версия базы не совпадает с версией Trivy | Используйте базы, соответствующие встроенному Trivy (v0.69.3 в Harbor 2.15.x); при апгрейде Harbor синхронизируйте базы заново |
| `permission denied` | Неверный владелец файлов на хосте | `sudo chown -R 10000:10000 /data/trivy-adapter/trivy` |
| Сканирование не находит уязвимости, `metadata.json missing` | Не перенесён файл метаданных | `metadata.json` обязателен в обеих директориях: `db/` и `java-db/` |
| Адаптер пытается выйти в интернет | `skip_update` не применён | Проверьте `docker exec trivy-adapter env \| grep SCANNER_TRIVY_SKIP_UPDATE`; после правки `harbor.yml` выполните `sudo ./prepare && sudo docker compose up -d` |
| Ошибки rate limit GitHub | Анонимные загрузки (60 запросов/час) | Укажите `github_token` в `harbor.yml` или перейдите на ручную синхронизацию баз |
| Базы не скачиваются через прокси | Прокси блокирует GHCR | Разрешите `ghcr.io`, `pkg-containers.githubusercontent.com`, `mirror.gcr.io`; в настройках прокси Harbor — `github.com`, `github-releases.githubusercontent.com`, `*.s3.amazonaws.com` |
| `Falling back to embedded checks` / `context deadline exceeded` при `security_check: config` | Checks bundle не доступен в air-gapped, таймаут меньше времени fallback | Используйте embedded checks (встроены в бинарник Trivy) или зеркалите checks bundle; увеличьте `trivy.timeout` или ограничьте `security_check: vuln` в air-gapped |

## Best Practices

### Планирование и гигиена

* **Синхронизируйте базы не реже раза в неделю** — интервал обновления Trivy DB в `metadata.json` по умолчанию 24 часа; устаревшая база даёт false negatives (пропуск CVE) и `schema mismatch` при несовпадении версий.
* **Перед апгрейдом Harbor синхронизируйте базы Trivy заново** — изменение версии Trivy/адаптера приводит к несовместимости схемы DB. При `schema mismatch` после обновления — повторная синхронизация из исправленного бандла.
* **Резервируйте место на адаптере** — объём Trivy DB ~400–700 МБ, Java DB ~50–150 МБ. На PVC/volume адаптера резервируйте ≥2× от объёма бандла.
* **Верифицируйте бандл после транспортировки** — контрольная сумма (sha256) и антивирусная проверка на «шлюзовом» узле перед распаковкой во внутренний контур. Общий air-gapped гайд — в [air_gapped_environments.md](../../../CI-CD/Core_Concepts/air_gapped_environments.md).

### Мониторинг и оповещения

* **Алерт на застрявшее сканирование** — метрика `harbor_task_queue_size` для операций `scan`/`scan_all` в сочетании с `harbor_up{component="trivy-adapter"}`. Если адаптер up, но очередь растёт — вероятно, устаревшая DB даёт пустые отчёты. Детали — в [operations.md](./operations.md).
* **Журнал синхронизации** — ведите учёт дат обновления баз (DB + Java DB). Просроченная запись на 14+ дней — инцидент SRE.
* **Логи адаптера** — `docker logs trivy-adapter` (Compose) или `kubectl logs` (K8s). Ищите `downloaded`, `skip_update`, `schema mismatch`, `Falling back to embedded checks`.

### Управление изменениями и откат

* **Имейте backup предыдущей версии DB** — перед заменой скопируйте `trivy.db` и `trivy-java.db` в архив. При проблемах с новой базой восстановите предыдущую версию.
* **Очистка после неудачного развёртывания** — если `metadata.json` повреждён или база несовместима, удалите файлы в `db/` и `java-db/` и разверните заново из проверенного бандла.
* **Change management** — фиксируйте версию Trivy DB и дату синхронизации в CMDB/change-логе. Это облегчает расследование инцидентов, когда «внезапно» пропали CVE из отчётов.

### Специфика air-gapped контуров

* **Checks bundle (misconfig)** — в air-gapped `offline_scan: true` не предотвращает загрузку checks bundle для `security_check: config`/`misconfig`. Trivy падает с `Falling back to embedded checks` или `context deadline exceeded`, если не может скачать bundle и таймаут меньше времени fallback. Используйте embedded checks (встроенные в бинарник Trivy) или зеркалите bundle через внутренний реестр.
* **Java DB — не опциональна** — даже без Java-приложений в образах могут быть JAR-файлы; без Java DB уязвимости в них не обнаруживаются.
* **Внутренний mirror OCI-артефактов** — используйте `oras`/`crane`/`regclient` для копирования баз (не `docker pull`): media type нестандартный (`application/vnd.aquasec.trivy.db.layer.v1.tar+gzip`).
* **Обновление Harbor 2.15.2+** — автоматический апгрейд embedded PostgreSQL 15→18 через `pg_upgrade` не затрагивает Trivy DB, но после перезапуска адаптера проверяйте работоспособность сканирования. При проблемах с UI/пустыми списками — `reindexdb --all-databases -U postgres` (см. [installation.md](./installation.md)).

### CI/CD интеграция

* **Упаковывайте DB как артефакт пайплайна** — после скачивания баз на онлайн-машине создайте артефакт (Nexus, Artifactory, GitLab Package Registry) и разворачивайте через тот же пайплайн, что и приложения.
* **Верификация в CI** — добавьте stage, который проверяет `metadata.json` на актуальность (`date` поля) и сканирует контрольный образ с известными CVE. Паттерны кэширования Trivy DB в CI — в [vulnerability_scanning.md](../../Docker_security/vulnerability_scanning.md).

## Граничные случаи

* **Java DB нужен даже без Java**: образы могут содержать JAR-файлы; без Java DB уязвимости в них не обнаруживаются.
* **`offline_scan` снижает покрытие**: для `pom.xml` не разрешаются транзитивные зависимости — число найденных уязвимостей может быть меньше, чем при онлайн-сканировании.
* **ORAS < v0.13.0**: используйте флаг `-a` (`oras pull -a ghcr.io/aquasecurity/trivy-db:2`).
* **Helm: `persistence.enabled: false`** — кэш адаптера размещается в `emptyDir`, ручные базы теряются при перезапуске пода.
* **Helm: `trivy.replicas > 1`** — у каждого пода свой PVC (`volumeClaimTemplates`); обновлять базы нужно на каждом поде (`harbor-trivy-0`, `harbor-trivy-1`, …).
* **Обновление Harbor**: данные в `data_volume` (включая `/data/trivy-adapter/trivy`) сохраняются при пересоздании контейнеров; после апгрейда Harbor проверьте совместимость схемы базы.
* **Прокси в Harbor**: секция `proxy.components` по умолчанию включает `trivy` — при использовании прокси убедитесь, что хосты Trivy доступны.
* **Checks bundle в air-gapped**: при `security_check: config`/`misconfig` Trivy пытается скачать checks bundle из интернета. В air-gapped используйте embedded checks (fallback) или зеркалите bundle. Ошибка — `Falling back to embedded checks` или `context deadline exceeded` при коротком `trivy.timeout`.
* **Harbor 2.15.2 и PostgreSQL 18**: после автоматического апгрейда PostgreSQL 15→18 возможна коррупция B-Tree индексов, влияющая на UI списки и работу адаптера. Исправление — `reindexdb --all-databases -U postgres` в окне обслуживания (см. [installation.md](./installation.md)).
* **False negatives от устаревшей DB**: даже при `skip_update: true` и наличии `trivy.db`, устаревшая база пропускает новые CVE. Мониторьте дату в `metadata.json` и отслеживайте `harbor_task_queue_size` (см. [operations.md](./operations.md)).

## Дополнительная информация

* Документация Trivy: [Air-Gapped Environment](https://trivy.dev/docs/v0.69/guide/advanced/air-gap), [Self-Hosting Trivy's Databases](https://trivy.dev/docs/v0.69/guide/advanced/self-hosting/), [aquasecurity/trivy-db](https://github.com/aquasecurity/trivy-db).
* Источники параметров Harbor: [`make/harbor.yml.tmpl`](https://github.com/goharbor/harbor/blob/v2.15.2/make/harbor.yml.tmpl), шаблон compose-файла и `env.jinja` в репозитории goharbor/harbor.

### Связанные документы

* **[Установка Harbor](./installation.md)** — развертывание в закрытых контурах.
* **[Обзор Harbor](./overview.md)** — архитектура Trivy-адаптера.
* **[Сертификаты](./certificates.md)** — параметр `trivy.insecure` и TLS для адаптера.
* **[Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md)** — методология анализа CVE.
