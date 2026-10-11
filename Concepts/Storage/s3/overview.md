# Amazon S3 — архитектура, протокол и эксплуатация

**Актуально для:** S3 API (S3 Protocol) и Ceph RGW (Squid 19.x / Tentacle 20.x / Umbrella 21.x)

---

## 1. Определения

**Amazon S3 (Simple Storage Service)** — сервис объектного хранилища, выпущенный Amazon в 2006 году. Со временем его REST API превратился в де-факто стандарт для объектных хранилищ. Под «S3» в инфраструктуре сегодня понимают не только сервис Amazon, но и **совместимый протокол и архитектуру**, реализованную множеством продуктов.

**Почему это важно для DevOps/SRE:** S3 — это backbone для большинства production-архитектур: артефакты CI/CD, бэкапы баз данных, логи, метрики, трейсы, state-файлы Terraform, конфигурации приложений. Понимание S3 = понимание того, как устроена инфраструктура данных в современных системах.

**Объектное хранилище** — модель хранения, в которой данные сохраняются как неделимые объекты (блобы) с уникальными ключами в плоском пространстве имён, сопровождаемые rich-метаданными и доступные через HTTP/HTTPS API.

**Почему объектное хранилище, а не файловое:** Файловые системы (NFS, POSIX) оптимизированы для low-latency random access к отдельным блокам, но плохо масштабируются горизонтально и имеют ограничения на объём. Объектные хранилища оптимизированы для throughput, горизонтального масштабирования до петабайт и долговечности данных (durability 11 девяток). Это делает их идеальными для бэкапов, архивов, артефактов — сценариев, где важнее объём и надёжность, чем latency.

**С3-совместимое хранилище** — любая реализация, поддерживающая S3 API (AWS Signature, REST операции). В контексте этих заметок — Ceph RGW.

**Bucket** — контейнер для объектов. Имя уникально в рамках кластера/региона. Это аналог корневого каталога, но без иерархии: `path/to/file.txt` — это просто строка-ключ.

**Зачем нужен bucket:** Bucket обеспечивает изоляцию данных (разные команды/проекты/окружения), контроль доступа на уровне контейнера и агрегацию метрик. Bucket — единица billing, quota и политик.

**Key** — уникальный идентификатор объекта внутри bucket. Может содержать `/`, но это лишь часть строки, а не вложенные директории.

**Почему flat namespace:** Это упрощает масштабирование. В иерархической файловой системе добавление новых серверов требует решения проблем с распределением директорий (какой сервер отвечает за `/var/log/app`?). В flat namespace любой сервер может обработать любой ключ, что позволяет горизонтально масштабировать кластер без изменения логики клиента.

**Object** — данные + системные метаданные (Content-Length, ETag, Last-Modified, Storage-Class) + пользовательские метаданные (x-amz-meta-*).

**Зачем метаданные:** Системные метаданные позволяют S3 управлять объектами без скачивания их содержимого (например, проверка ETag для целостности, Last-Modified для lifecycle policies). Versioning использует `VersionId` для управления версиями. Пользовательские метаданные позволяют приложениям хранить бизнес-контекст прямо в объекте (версия сборки, автор, дата деплоя), что упрощает аудит и поиск.

**Endpoint** — URL сервера обработки запросов, например `http://rgw:7480` или `storage.corp.local:9000`.

**Почему endpoint важен:** Endpoint определяет, куда идут запросы. В self-hosted реализациях endpoint указывает на ваш собственный кластер, что позволяет полностью изолировать трафик внутри дата-центра.

**Region** — логическая изоляция данных и эндпоинтов. Данные физически находятся в пределах региона. В self-hosted реализациях регион может соответствовать дата-центру или зоне доступности.

**Зачем регионы:** Регионы обеспечивают data residency (соответствие требованиям GDPR, локальным законам о хранении данных), disaster isolation (сбой в одном регионе не затрагивает другой) и latency optimisation (ближайший регион = меньшая задержка). Cross-region replication используется для disaster recovery.

**Storage Class** — класс хранения, определяющий цену за ГБ, стоимость операций и доступность. В Ceph RGW классы хранения определяются конфигурацией пулов (SSD, HDD, erasure coding).

**Зачем разные классы:** Не все данные одинаково часто используются. Горячие данные (активные артефакты, текущие бэкапы) требуют низкой latency и высокой доступности → hot pool (SSD). Тёплые данные (артефакты старше 30 дней) редко запрашиваются → warm pool (HDD). Холодные данные (архивы, compliance логи) могут ждать часы/дни для доступа → cold pool (archive). Lifecycle policies автоматически мигрируют объекты между классами, оптимизируя стоимость.

**Durability** — вероятность долговечности данных. В AWS S3 Standard — 99,999999999% (11 девяток) за год. В self-hosted реализациях durability определяется конфигурацией избыточности (репликация 3+ или erasure coding 8+3).

**Почему durability важно:** 11 девяток означает, что при хранении 10 000 000 объектов вы потеряете в среднем один объект раз в 10 000 лет. Для production-систем это критично: потеря бэкапа или артефакта может привести к простою или потере данных.

**Availability** — доступность сервиса в течение года. Для S3 Standard — 99,99% (~52 минуты простоя в год). В self-hosted реализациях availability зависит от количества узлов, зон и политики репликации.

**Почему availability отдельно от durability:** Durability гарантирует, что данные не потеряются. Availability гарантирует, что вы можете к ним обратиться. Объект может существовать (durability 100%), но быть временно недоступен (availability 99%). Для SLA приложений важно учитывать оба показателя.

---

## 2. Архитектура и принципы работы

### 2.1 Модель данных и S3 API

S3 предоставляет **упрощённый REST API** поверх HTTP/HTTPS. Основные операции:

| Операция | HTTP метод | Назначение |
|----------|-----------|-----------|
| PUT Object | `PUT /bucket/key` | Загрузка объекта |
| GET Object | `GET /bucket/key` | Скачивание объекта |
| DELETE Object | `DELETE /bucket/key` | Удаление объекта |
| HEAD Object | `HEAD /bucket/key` | Получение метаданных без тела |
| LIST Objects | `GET /bucket?list-type=2` | Перечисление объектов (flat list) |
| PUT Bucket | `PUT /bucket` | Создание bucket |
| DELETE Bucket | `DELETE /bucket` | Удаление bucket |

Все операции идемпотентны при использовании идентификаторов запросов (Request ID) и идемпотентных ключей где применимо.

**Почему REST API:** S3 спроектирован как web service с 2006 года, когда SOAP и сложные API доминировали. Простота HTTP-интерфейса позволила любому языку программирования работать с S3 без сложных SDK. Это же API сегодня поддерживается всеми S3-совместимыми хранилищами, что создаёт экосистему инструментов (aws-cli, s3cmd, SDK для Python/Go/Java/etc.).

**Зачем HEAD Object:** HEAD запрос возвращает только заголовки (метаданные) без тела объекта. Это позволяет проверить существование объекта, его размер, Storage Class, ETag, время модификации без скачивания всего файла. Критично для production-паттернов, где нужно проверять наличие или freshness артефакта.

**Зачем LIST Objects:** LIST операция перечисляет объекты в bucket. В production это может быть миллионы объектов. S3 возвращает результаты постранично (pagination) с указанием `IsTruncated` и `NextContinuationToken`. Важно понимать eventual consistency для LIST: только что загруженный объект может не появиться в LIST сразу.

### 2.2 Аутентификация и авторизация

**AWS Signature Version 4** — алгоритм аутентификации запросов, используемый по умолчанию в S3. Включает:
- Хеширование запроса с секретным ключом
- Подпись заголовков и тела запроса
- Временной штамп (timestamp) для защиты от replay-атак
- Регион и сервис в строке подписи

**Signature Version 2** — устаревший алгоритм, поддерживаемый для обратной совместимости. Используется только старыми клиентами.

**Path-style vs Virtual-hosted-style запросы:**
- **Virtual-hosted-style:** `https://bucket-name.s3.region.amazonaws.com/key` — bucket в поддомене. Стандарт для AWS S3.
- **Path-style:** `https://s3.region.amazonaws.com/bucket-name/key` — bucket в пути. Используется для self-hosted реализаций и бэкворд-совместимости. Ceph RGW по умолчанию использует path-style.

**Почему это важно:** Неправильный стиль адресации — частая причина 403 Forbidden при работе с self-hosted S3. Ceph RGW по умолчанию использует path-style. При работе с aws-cli или SDK явно указывайте `addressing_style=path` для внутренних хранилищ.

### 2.3 Система метаданных

Каждый объект имеет два набора метаданных:

**Системные (System-defined):**
- `Content-Length` — размер объекта в байтах
- `Content-Type` — MIME-тип
- `ETag` — MD5-хеш (для объектов ≤ 4 МБ), для multipart — агрегированный ETag
- `Last-Modified` — время последней модификации
- `Storage-Class` — текущий класс хранения
- `VersionId` — идентификатор версии (если включено версионирование)

**Пользовательские (User-defined):**
- `x-amz-meta-*` — произвольные ключево-значительные пары (до 2 КБ на объект)
- `x-amz-server-side-encryption` — тип серверного шифрования
- `x-amz-website-redirect-location` — редирект для статических сайтов

**Почему системные метаданные критичны:** S3 использует их для внутренней логики без доступа к данным объекта. Например, lifecycle policies проверяют `Last-Modified` для определения, нужно ли перемещать объект в другой Storage Class. Versioning использует `VersionId` для управления версиями. ETag используется для проверки целостности при multipart upload. Понять системные метаданные — значит понять, как S3 управляет объектами "под капотом".

**Почему пользовательские метаданные:** Это механизм для enrichment объектов бизнес-контекстом без необходимости хранить отдельную базу данных. Примеры: `x-amz-meta-build-id`, `x-amz-meta-deployed-by`, `x-amz-meta-commit-hash`. Позволяют фильтровать объекты через S3 Inventory или S3 Select по бизнес-атрибутам.

### 2.4 Консистентность

**Ceph RGW:**
- **Strong consistency** для новых объектов: после успешной записи объект сразу доступен для чтения.
- **Eventual consistency** для LIST и overwrite: только что загруженный объект может не появиться в LIST сразу; overwrite может временно возвращать старую версию.

**Почему консистентность важна:** В distributed системах консистентность определяет, когда изменения становятся видимыми для всех клиентов. Strong consistency упрощает разработку приложений (можно читать сразу после записи). Eventual consistency требует дополнительной логики (retry, version check), но позволяет достичь higher throughput и availability. Для Ceph RGW strong consistency для новых объектов означает, что большинство приложений могут считать RGW source of truth без дополнительных механизмов согласованности. Для LIST и overwrite добавьте retry.

### 2.5 Классы хранения (Storage Classes) в Ceph RGW

В Ceph RGW классы хранения определяются конфигурацией пулов:

| Класс | Пул RGW | Сценарий | Стоимость хранения | Retrieval время |
|-------|---------|----------|-------------------|-----------------|
| **Hot (SSD)** | `<zone>.rgw.data` (SSD) | Частый доступ, горячие данные | Высокая | Немедленный |
| **Warm (HDD)** | `<zone>.rgw.data` (HDD) | Тёплые данные, редко читаемые | Низкая | Немедленный |
| **Cold (Archive)** | `<zone>.rgw.data` (Archive pool) | Холодные данные, compliance логи | Минимальная | Минуты/часы |

**Lifecycle policies** автоматически мигрируют объекты между пулами по истечении TTL или удаляют их.

**Почему экономия на Storage Class может быть огромной:** Цена за ГБ в SSD ≈ $0.023, в HDD ≈ $0.012, в архивном пуле ≈ $0.001. Для 100 ТБ данных разница составляет ~$2 300/месяц vs ~$100/месяц. Lifecycle policies позволяют автоматически оптимизировать стоимость без ручного вмешательства. **Важно:** стоимость запросов в HDD/Archive выше, поэтому для часто читаемых данных SSD может быть выгоднее.

### 2.6 Версионирование (Versioning)

Версионирование хранит **все версии** одного и того же ключа:
- При overwrite создаётся новая версия, старая остаётся доступной.
- При DELETE объект помечается как deleted (delete marker), предыдущие версии сохраняются.
- Позволяет откатываться (rollback) и защищает от случайного удаления или перезаписи.
- **Важно:** версионирование нельзя отключить, только приостановить. При возобновлении создаётся новая версия для каждого уникального ключа.

**Зачем versioning в production:** Versioning — это первая линия защиты от случайного удаления. Если `rm -rf` случайно удалил объекты в bucket, или CI/CD pipeline загрузила битый артефакт, versioning позволяет быстро восстановить предыдущую версию. В сочетании с lifecycle policy (удаление старых версий через 90 дней) это даёт баланс защиты и стоимости.

### 2.7 Шифрование

**Server-Side Encryption (SSE):**
- **SSE-S3** — ключи управляются самой RGW-совместимой реализацией. AES-256.
- **SSE-C** — клиент предоставляет ключ для каждого запроса. Сервис не хранит ключ.

**Client-Side Encryption:**
- Шифрование происходит на стороне клиента до загрузки.
- Используется для compliance требований, когда провайдер не должен иметь ключи.

**Ceph RGW KMS integration:**
- Встроенный KMS через `rgw crypto` или интеграция с HashiCorp Vault.
- Настройка через `radosgw-admin` или Ceph Dashboard.

**Почему шифрование обязательно:** Даже если данные "не чувствительные", шифрование at rest защищает от:
- Фической кражи дисков (в дата-центре).
- Неавторизованного доступа к S3 bucket через compromised credentials.
- Compliance требований (PCI DSS, HIPAA, GDPR).

---

## 3. Self-hosted реализация: Ceph RGW

### 3.1 Архитектура Ceph RGW

Ceph RGW — это часть кластера Ceph, предоставляющая S3-compatible и Swift-compatible API поверх RADOS.

```
Клиент (S3 SDK / aws-cli / s3cmd)
        │ HTTPS (порт 7480/443)
        ▼
   RGW (RADOS Gateway)
        │ librados
        ▼
   RADOS (объектное хранилище)
        │
        ▼
   OSD (физические диски)
```

**Компоненты:**
- **RGW Daemon** — HTTP/HTTPS сервер, обрабатывающий запросы S3/Swift API
- **RGW Zone** — логическая единица в multisite-конфигурации (сайт)
- **RGW Zone Group** — группа зон в пределах одного региона
- **RGW Region** — географический регион, объединяющий несколько zone groups

### 3.2 Пулы RGW

RGW автоматически создаёт несколько пулов для хранения данных:

| Пул | Назначение | Тип |
|-----|-----------|-----|
| `rgw.root` | Корневые метаданные | Replicated |
| `<zone>.rgw.meta` | Метаданные пользователей и бакетов | Replicated |
| `<zone>.rgw.log` | Журнал операций | Replicated |
| `<zone>.rgw.data` | Данные объектов | Replicated или EC |

### 3.3 S3 API Compatibility

RGW поддерживает большинство API S3:

| API | Поддержка | Примечание |
|-----|-----------|------------|
| Object CRUD (GET/PUT/DELETE) | Полная | Включая multipart upload |
| Bucket operations | Полная | Create, Delete, List, Head |
| Versioning | Полная | Все версии объектов |
| Lifecycle | Полная | Автоматическая очистка и переходы между пулами |
| CORS | Полная | Настройка правил |
| Notification | Базовая | MQTT, AMQP, HTTP webhooks |
| Replication | Полная | Синхронная/асинхронная (multisite) |
| Encryption (SSE-S3, SSE-C) | Полная | Шифрование на стороне сервера |
| Object Lock (WORM) | Полная | Compliance и Governance modes |
| Select (S3 Select) | Базовая | SQL-запросы к объектам |

### 3.4 Порт RGW

| Режим | Порт по умолчанию | Примечание |
|-------|-------------------|------------|
| HTTP | 7480 | Для development |
| HTTPS | 443 (или 7443) | Для production |
| Ingress (HA) | 80/443 | Keepalived + HAProxy |

### 3.5 Когда выбирать Ceph RGW

- Уже есть кластер Ceph для блочного/файлового хранения.
- Нужно единое хранилище для блоков, файлов и объектов.
- Требуется распределённое, высоконадёжное решение на собственных дисках.
- Нужна in-cluster репликация и multisite для DR.

---

## 4. Terraform S3 Backend

Terraform может использовать S3-совместимое хранилище (Ceph RGW) для хранения state-файлов. Это критичный production-паттерн для distributed teams.

### 4.1 Backend configuration

```hcl
# main.tf
terraform {
  backend "s3" {
    bucket         = "terraform-state-prod"
    key            = "infra/terraform.tfstate"
    region         = "us-east-1"
    endpoint       = "http://rgw:7480"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    # Для OpenTofu / Terraform 1.10+:
    use_lockfile   = true
  }
}
```

**Параметры:**
- `bucket` — имя бакета для хранения state
- `key` — путь к state-файлу внутри бакета
- `endpoint` — URL RGW-эндпоинта
- `skip_credentials_validation` — отключает проверку AWS credentials (для self-hosted)
- `use_lockfile` — включает S3-native locking (OpenTofu / Terraform 1.10+)

### 4.2 Environment variables

```bash
export AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
export AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
export AWS_REGION="us-east-1"
```

### 4.3 State locking

Для Terraform < 1.10 используйте DynamoDB для locking. Для Terraform 1.10+ / OpenTofu используйте `use_lockfile = true` (S3-native locking).

### 4.4 Best Practices

- **Обязательно включите versioning** на бакете с state-файлами.
- **Используйте Object Lock** (Compliance mode) для защиты state от удаления.
- **Ограничьте доступ** к бакету через bucket policy — только CI/CD service account.
- **Никогда не храните state локально** — только в RGW.

---

## 5. Практические сценарии

### 5.1 Создание bucket и базовая работа через aws-cli

```bash
# Создание bucket (имя должно быть globally unique в рамках кластера)
aws s3 mb s3://my-app-prod-assets \
  --region us-east-1 \
  --endpoint-url http://rgw:7480

# → make_bucket: my-app-prod-assets
```

**Зачем каждый параметр:**
- `--region` — определяет, в каком регионе создаётся bucket. В Ceph RGW регион часто соответствует дата-центру.
- `--endpoint-url` — явное указание endpoint RGW.

```bash
# Включение версионирования
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled \
  --endpoint-url http://rgw:7480

# Включение шифрования по умолчанию (SSE-S3)
aws s3api put-bucket-encryption \
  --bucket my-app-prod-assets \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }' \
  --endpoint-url http://rgw:7480

# Загрузка объекта с metadata
aws s3 cp ./build/app.tar.gz s3://my-app-prod-assets/releases/v1.2.3/ \
  --storage-class STANDARD_IA \
  --metadata "build-id=abc123,commit=def456" \
  --server-side-encryption AES256 \
  --endpoint-url http://rgw:7480

# Синхронизация директории
aws s3 sync ./dist/ s3://my-app-prod-assets/static/ \
  --delete \
  --exclude "*.tmp" \
  --exclude ".git/*" \
  --endpoint-url http://rgw:7480
```

### 5.2 Lifecycle policies

```json
// lifecycle.json
{
  "Rules": [
    {
      "ID": "archive-old-logs",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Transitions": [
        {"Days": 7, "StorageClass": "WARM"},
        {"Days": 90, "StorageClass": "COLD"}
      ],
      "Expiration": {"Days": 365},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    },
    {
      "ID": "delete-old-logs",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Expiration": {"Days": 30},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}
    }
  ]
}
```

```bash
# Применение политики
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-prod-assets \
  --lifecycle-configuration file://lifecycle.json \
  --endpoint-url http://rgw:7480

# Просмотр политики
aws s3api get-bucket-lifecycle-configuration \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480
```

### 5.3 S3 Object Lock (WORM)

```bash
# Включение Object Lock при создании bucket
aws s3api create-bucket \
  --bucket my-app-prod-assets \
  --object-lock-enabled-for-bucket \
  --endpoint-url http://rgw:7480 \
  --region us-east-1

# Настройка retention по умолчанию (30 дней, Compliance mode)
aws s3api put-object-lock-configuration \
  --bucket my-app-prod-assets \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 30
      }
    }
  }' \
  --endpoint-url http://rgw:7480

# Проверка retention для конкретного объекта
aws s3api get-object-retention \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz \
  --endpoint-url http://rgw:7480
```

### 5.4 Multipart Upload

Для объектов > 5 ГБ (или для надёжности при нестабильном канале) используется multipart upload:

```bash
# Автоматический multipart upload через aws-cli (файл > 8 ГБ)
aws s3 cp large-backup.tar.gz s3://my-app-prod-assets/backups/ \
  --storage-class COLD \
  --endpoint-url http://rgw:7480

# Проверка незавершённых multipart uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480

# Массовая отмена старых незавершённых загрузок
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --query 'Uploads[*].[Key,UploadId]' --output text \
  --endpoint-url http://rgw:7480 | while read key upload_id; do
    echo "Aborting: $key ($upload_id)"
    aws s3api abort-multipart-upload \
      --bucket my-app-prod-assets \
      --key "$key" \
      --upload-id "$upload_id" \
      --endpoint-url http://rgw:7480
  done
```

### 5.5 Event Notifications

RGW поддерживает MQTT, AMQP и HTTP webhooks для событий:

```bash
# Настройка уведомлений на HTTP webhook
aws s3api put-bucket-notification-configuration \
  --bucket my-app-prod-assets \
  --notification-configuration '{
    "TopicConfigurations": [
      {
        "Topic": "http://webhook.example.com/notifications",
        "Events": ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
      }
    ]
  }' \
  --endpoint-url http://rgw:7480
```

**События RGW:**
- `s3:ObjectCreated:*` — загрузка, multipart completion, copy
- `s3:ObjectRemoved:*` — удаление, lifecycle expiration
- `s3:ObjectRestore:*` — initiate, complete, expire (для lifecycle transitions)

**Цели:** MQTT, AMQP, HTTP webhooks. В Ceph RGW нет Lambda/SNS/SQS.

### 5.6 Presigned URLs

```python
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client('s3',
    endpoint_url='http://rgw:7480',
    region_name='us-east-1'
)

# GET presigned URL (действителен 1 час)
url = s3_client.generate_presigned_url(
    'get_object',
    Params={'Bucket': 'my-app-prod-assets', 'Key': 'releases/app.tar.gz'},
    ExpiresIn=3600
)

# PUT presigned URL для загрузки от имени сервиса
upload_url = s3_client.generate_presigned_url(
    'put_object',
    Params={
        'Bucket': 'my-app-prod-assets',
        'Key': 'uploads/${filename}',
        'ContentType': 'application/gzip',
        'ServerSideEncryption': 'AES256'
    },
    ExpiresIn=3600
)
```

### 5.7 CORS

```bash
# Применение CORS через aws-cli
aws s3api put-bucket-cors \
  --bucket my-app-prod-assets \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedOrigins": ["https://app.example.com"],
      "AllowedMethods": ["GET", "PUT"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }]
  }' \
  --endpoint-url http://rgw:7480
```

---

## 6. Безопасность

### 6.1 Модель безопасности

Ceph RGW использует **multi-layered security model**:

1. **Network layer:** TLS 1.2+ для всех операций, изоляция трафика через firewall / network policies.
2. **Identity layer:** Access keys, пользователи RGW, bucket policies, ACL.
3. **Encryption layer:** SSE-S3, SSE-C, Client-Side Encryption, rgw crypto / Vault integration.
4. **Data layer:** Object Lock, Versioning, Replication, Lifecycle.
5. **Audit layer:** Access Logging, application-level audit, metrics.

### 6.2 Bucket Policies vs ACL

**Bucket Policy** — JSON-документ на уровне bucket, более гибкий, поддерживает Condition.

**ACL** — устаревший механизм (2006), ограниченный. В Ceph RGW рекомендуется отключать ACL, используя только Bucket Policies.

### 6.3 Access Logging и Audit

```bash
# Включение access logging
aws s3api put-bucket-logging \
  --bucket my-app-prod-assets \
  --bucket-logging-status '{
    "LoggingEnabled": {
      "TargetBucket": "my-app-audit-logs",
      "TargetPrefix": "s3-logs/my-app-prod-assets/"
    }
  }' \
  --endpoint-url http://rgw:7480

# Просмотр логов RGW через radosgw-admin
radosgw-admin log list
```

### 6.4 Block Public Access

```bash
# Включение Block Public Access через bucket policy
aws s3api put-bucket-policy \
  --bucket my-app-prod-assets \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::my-app-prod-assets", "arn:aws:s3:::my-app-prod-assets/*"],
      "Condition": {"Bool": {"aws:SecureTransport": false}}
    }]
  }' \
  --endpoint-url http://rgw:7480
```

---

## 7. Мониторинг и эксплуатация

### 7.1 Метрики и алерты

**Основные метрики Ceph RGW:**
- `rgw_requests_total` — общее количество запросов
- `rgw_requests_bytes_sent` / `rgw_requests_bytes_received` — трафик
- `rgw_5xx_errors` / `rgw_4xx_errors` — ошибки
- `rgw_bucket_size_bytes` — размер bucket'а
- `rgw_bucket_objects` — количество объектов

### 7.2 Access Logging

RGW access logging позволяет отследить все операции с bucket'ами. Логи экспортируются в Loki/Elasticsearch для анализа.

### 7.3 Cost tracking

Для отслеживания затрат используйте:
- **Prometheus + Grafana** для метрик RGW
- **Кастомные скрипты** для анализа размера bucket'ов и количества запросов
- **Python/pandas** для анализа CSV inventory отчётов

---

## 8. Производственные паттерны

### 8.1 Идемпотентные загрузки

Используйте `x-amz-content-sha256` и client-side idempotency tokens для предотвращения дублирования при повторных загрузках.

### 8.2 Server-side copy (Upload Part Copy)

Для копирования объектов внутри RGW без скачивания используйте Upload Part Copy.

### 8.3 Cross-account access (Ceph RGW tenants)

В Ceph RGW cross-account access реализуется через изоляцию tenants и пользователей:

```bash
# Создание изолированного тенанта
radosgw-admin tenant create --tenant="team-a"

# Создание пользователя в тенанте
radosgw-admin user create \
  --uid="team-a-user" \
  --display-name="Team A User" \
  --tenant="team-a"
```

---

## 9. См. также

- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
- [S3: защита от случайного удаления в Ceph RGW](./mfa-delete.md)
