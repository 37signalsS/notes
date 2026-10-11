# Harbor: Генерация и управление SBOM

**Актуально для:** Harbor 2.15.x (2.15.2 — текущий релиз, 2.15.3-rc2 — кандидат)

## Определения

* **SBOM (Software Bill of Materials)**: Перечень всех компонентов ПО артефакта — пакет, версия, лицензия. Повышает прозрачность цепочки поставок: позволяет быстро найти образы с уязвимой библиотекой (например, log4j) во всей инфраструктуре.
* **SBOM в Harbor**: SBOM, сгенерированный встроенным сканером Trivy. Harbor оборачивает данные SBOM в OCI-артефакт и привязывает его к артефакту-субъекту как accessory (связанный объект).
* **SPDX**: Стандартный формат обмена SBOM; Harbor скачивает SBOM именно в этом формате.
* **Accessory**: Связанный артефакт (SBOM, подпись), привязанный к основному артефакту через OCI 1.1 Referrers API.
* **SBOM Details**: Страница артефакта в Harbor UI с таблицей «пакет / версия / лицензия» и кнопкой скачивания SBOM.

## Основные концепции

### Как работает генерация SBOM

1. Включается опция **SBOM generation** в конфигурации проекта (или запуск вручную).
2. При push артефакта (или по кнопке) Job Service запускает задачу генерации.
3. Trivy анализирует слои артефакта и формирует данные SBOM.
4. Harbor оборачивает данные в OCI-артефакт и привязывает к артефакту-субъекту (Referrers API).
5. В UI артефакта появляется ссылка **SBOM Details**.

### SBOM vs отчёт сканирования

| | SBOM | Отчёт сканирования |
| :--- | :--- | :--- |
| Содержимое | Состав артефакта (пакеты, версии, лицензии) | Уязвимости (CVE, severity, исправления) |
| Генератор | Trivy (SBOM-режим) | Trivy (vuln-режим) |
| Где смотреть | SBOM Details артефакта | Overview артефакта, Security Hub |
| Влияет на pull | Нет | Да (Deployment Security) |

SBOM не заменяет сканирование: SBOM отвечает «что внутри», отчёт сканирования — «что внутри уязвимо».

### Жизненный цикл SBOM

* **Репликация**: SBOM реплицируется вместе с артефактом — pull/push-based правила репликации копируют артефакт с привязанным SBOM.
* **Удаление**: удаление SBOM убирает accessory из UI; физическое удаление данных происходит при Garbage Collection. SBOM также удаляется вместе с артефактом-субъектом.
* **Квота**: SBOM как артефакт учитывается в квоте проекта.

## Практические сценарии

### Сценарий 1: Автоматическая генерация SBOM при push

1. Откройте проект: **Projects → myproject → Configuration**.
2. Включите опцию **SBOM generation** (Automatically generate SBOM on push).
3. **Save**.

После этого каждый `docker push` в проект автоматически запускает генерацию SBOM назначенным сканером (Trivy).

> При массовых конкурентных push в проект включите `core.quota_update_provider: redis` в `harbor.yml` (Docker Compose) или `core.quotaUpdateProvider: redis` в values.yaml (Helm) — снижает потребление ресурсов (БД, CPU, память).

### Сценарий 2: Ручная генерация SBOM

1. **Projects → myproject → репозиторий** — отметьте один или несколько артефактов.
2. Кнопка **GENERATE SBOM** станет доступна.
3. Прервать генерацию — **ACTIONS → Abort**.

### Сценарий 3: Просмотр и экспорт SBOM

1. Откройте артефакт → **SBOM Details**.
2. Таблица: **Package Name**, **Version**, **License**.
3. **DOWNLOAD SBOM** — скачивание полного SBOM в формате SPDX.

### Сценарий 4: SBOM через API и Referrers

SBOM хранится как OCI-артефакт, привязанный к субъекту — доступен через Referrers API (OCI 1.1, Harbor 2.11+):

```bash
# Referrers артефакта (подписи, SBOM, аттестации)
curl -sk -u "robot$production+ci-bot:$ROBOT_SECRET" \
  "https://harbor.corp.local/v2/production/my-app/manifests/sha256:abcd.../referrers"
# → 200 OK, список связанных артефактов с artifactType SBOM

# Артефакты с обзором сканирования и SBOM (with_sbom_overview — по умолчанию false)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?with_tag=true&with_scan_overview=true&with_sbom_overview=true" | \
  jq '.[] | {digest, tags: [.tags[].name], sbom: (.sbom_overview != null)}'
```

### Сценарий 5: Запуск генерации SBOM через API/CLI

Генерация SBOM — это разновидность сканирования; запускается тем же эндпоинтом, что и сканер:

```bash
# Через API: POST .../scan с scanType=sbom (вместо vulnerability)
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts/sha256:abcd.../scan" \
  -H "Content-Type: application/json" \
  -d '{"scan_type":"sbom"}'
# → 202 Accepted (задача поставлена в очередь Job Service)

# Остановка генерации: POST .../scan/stop с scanType=sbom
curl -sk -u "admin:$PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts/sha256:abcd.../scan/stop" \
  -H "Content-Type: application/json" \
  -d '{"scan_type":"sbom"}'

# Через CLI: запуск сканирования (scan start не различает тип — см. ниже)
harbor artifact scan start myproject/my-app/sha256:abcd...
```

> `scan_type` принимает значения `vulnerability` и `sbom` (из `#/definitions/ScanType` в swagger). Ответ `202` — задача поставлена, результат появляется в Job Service Dashboard.

### Сценарий 5: Удаление SBOM

1. На артефакте — **ACTIONS → Delete SBOM** (или удаление через интерфейс accessory).
2. SBOM исчезает из UI немедленно; физическое удаление — при следующем GC.
3. Удаление артефакта-субъекта удаляет и привязанный SBOM.

## Валидация

```bash
# 1. SBOM сгенерирован: в UI артефакта есть ссылка SBOM Details

# 2. Referrers API возвращает связанные артефакты (в т.ч. SBOM)
curl -sk -u "robot$production+ci-bot:$ROBOT_SECRET" \
  "https://harbor.corp.local/v2/production/my-app/manifests/sha256:abcd.../referrers" | jq '.manifests | length'
# → число связанных артефактов (>=1 при наличии SBOM/подписи)

# 3. Задача генерации выполнена: Job Service Dashboard (Administration → Job Service)
#    или метрика harbor_task_queue_size не растёт
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Нет кнопки GENERATE SBOM / нет SBOM Details | Сканер не установлен | Установите Harbor с `--with-trivy` или `trivy.enabled: true` в Helm |
| SBOM не генерируется при push | Опция SBOM generation выключена в конфиге проекта | Включите в Projects → Configuration → SBOM generation |
| Генерация «зависла» | Перегрузка Job Service | Проверьте `harbor_task_queue_size`, `max_job_workers`; при массовых push — `core.quota_update_provider: redis` |
| SBOM не появился в целевом реестре после репликации | Правило репликации без SBOM | Harbor реплицирует SBOM вместе с артефактом — проверьте, что артефакт реплицирован целиком (по digest) |
| Покрытие SBOM неполное | Air-gapped: `offline_scan: true` не разрешает транзитивные зависимости Java | Ожидаемое ограничение offline-режима; см. [offline_trivy_update.md](./offline_trivy_update.md) |

## Граничные случаи

* **SBOM не влияет на Deployment Security** — блокировку pull определяет только отчёт сканирования; SBOM — это состав, а не уязвимости.
* **Java-артефакты**: состав Java-библиотек определяется неполностью, если в конфигурации Trivy не загружена Java DB (`skip_java_db_update: false` и отсутствует `--skip-java-db-update`). Уязвимости по Java-пакетам при этом также не определяются.
* **Helm-чарты**: Trivy не сканирует Helm-чарты (выбор артефактов сканером по `consumes_mime_types`) — SBOM для чартов не генерируется.
* **Квота**: SBOM — артефакт, учитывается в `harbor_project_quota_usage_byte`; при включённой авто-генерации объём хранилища растёт быстрее.
* **Генерация SBOM не отменяет сканирование**: SBOM и отчёт уязвимостей — разные задачи (`scan_type: sbom` vs `scan_type: vulnerability`); для блокировки pull нужен vuln-отчёт.

## Лучшие практики

* **Включайте SBOM generation на проектах, где образы публикуются downstream** — SBOM — основа для SCA-инструментов и аудита цепочки поставок.
* **Генерируйте SBOM при сборке (buildx/syft)**, а не только в Harbor — так SBOM есть у образа до push, и не нужно ждать задачу Job Service.
* **`with_sbom_overview` включайте только по необходимости** — по умолчанию `false`, так как лишние поля увеличивают ответ в десятки раз.
* **Ограничьте репликацию SBOM**: pull/push-правила реплицируют SBOM вместе с артефактом; если SBOM не нужен в десте, репликуйте по digest и фильтруйте на стороне потребителя.
* **GC для очистки старых SBOM**: настройте расписание GC (`POST /system/gc/schedule`), так как SBOM — это дополнительные OCI-артефакты.
* **Не генерируйте SBOM для чартов и образов, которые не будут анализироваться** — это лишняя нагрузка на Job Service и рост квоты.
* **Безопасность**: SBOM содержит состав ПО, включая критические библиотеки — храните его доступно тем, кому нужен аудит, но не публикуйте без проверки.

## Дополнительная информация

* Официальная документация: [SBOM Generation Capabilities](https://goharbor.io/docs/2.15.0/administration/sbom-integration/).
* **SBOM при сборке (buildx/syft)** — [Docker SBOM](../../Docker_security/docker_sbom.md) — генерация SBOM на этапе сборки, до попадания в Harbor.
* **Referrers API** — [Registry HTTP API v2](../registry_api_v2.md).
* **Репликация артефактов с SBOM** — [replication.md](./replication.md).
* **Аттестации и подписи** — [image_signature_and_verification.md](../../Docker_security/image_signature_and_verification.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — модель безопасности и OCI 1.1.
* **[Работа с Harbor](./usage.md)** — артефакты, подписи.
* **[Политики безопасности](./security_policies.md)** — сканирование и Deployment Security.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — актуальность баз в air-gapped.
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor.
