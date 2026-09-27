# Amazon S3 — архитектура, протокол и эксплуатация

## 1. Определения

**Amazon S3 (Simple Storage Service)** — сервис объектного хранилища, выпущенный Amazon в 2006 году. Со временем его REST API превратился в де-факто стандарт для объектных хранилищ. Под «S3» в инфраструктуре сегодня понимают не только сервис Amazon, но и **совместимый протокол и архитектуру**, реализованную множеством продуктов.

**Почему это важно для DevOps/SRE:** S3 — это backbone для большинства production-архитектур: артефакты CI/CD, бэкапы баз данных, логи, метрики, трейсы, state-файлы Terraform, конфигурации приложений. Понимание S3 = понимание того, как устроена инфраструктура данных в современных системах.

**Объектное хранилище** — модель хранения, в которой данные сохраняются как неделимые объекты (блобы) с уникальными ключами в плоском пространстве имён, сопровождаемые rich-метаданными и доступные через HTTP/HTTPS API.

**Почему объектное хранилище, а не файловое:** Файловые системы (NFS, POSIX) оптимизированы для low-latency random access к отдельным блокам, но плохо масштабируются горизонтально и имеют ограничения на объём. Объектные хранилища оптимизированы для throughput, горизонтального масштабирования до петабайт и долговечности данных (durability 11 девяток). Это делает их идеальными для бэкапов, архивов, артефактов — сценариев, где важнее объём и надёжность, чем latency.

**Bucket** — контейнер для объектов. Имя уникально в рамках кластера/региона. Это аналог корневого каталога, но без иерархии: `path/to/file.txt` — это просто строка-ключ.

**Зачем нужен bucket:** Bucket обеспечивает изоляцию данных (разные команды/проекты/окружения), контроль доступа на уровне контейнера и агрегацию метрик. Bucket — единица billing, quota и политик.

**Key** — уникальный идентификатор объекта внутри bucket. Может содержать `/`, но это лишь часть строки, а не вложенные директории.

**Почему flat namespace:** Это упрощает масштабирование. В иерархической файловой системе добавление новых серверов требует решения проблем с распределением директорий (какой сервер отвечает за `/var/log/app`?). В flat namespace любой сервер может обработать любой ключ, что позволяет горизонтально масштабировать кластер без изменения логики клиента.

**Object** — данные + системные метаданные (Content-Length, ETag, Last-Modified, Storage-Class) + пользовательские метаданные (x-amz-meta-*).

**Зачем метаданные:** Системные метаданные позволяют S3 управлять объектами без скачивания их содержимого (например, проверка ETag для целостности, Last-Modified для lifecycle policies). Versioning использует `VersionId` для управления версиями. Пользовательские метаданные позволяют приложениям хранить бизнес-контекст прямо в объекте (версия сборки, автор, дата деплоя), что упрощает аудит и поиск.

**Endpoint** — URL сервера обработки запросов, например `s3.amazonaws.com` или `storage.corp.local:9000`.

**Почему endpoint важен:** Endpoint определяет, куда идут запросы. В AWS у каждого региона свой endpoint, что влияет на latency и data residency. В self-hosted реализациях (Ceph RGW, Garage) endpoint указывает на ваш собственный кластер, что позволяет полностью изолировать трафик внутри дата-центра.

**Region** — логическая изоляция данных и эндпоинтов. Данные физически находятся в пределах региона.

**Зачем регионы:** Регионы обеспечивают data residency (соответствие требованиям GDPR, локальным законам о хранении данных), disaster isolation (сбой в одном регионе не затрагивает другой) и latency optimisation (ближайший регион = меньшая задержка). Cross-region replication используется для disaster recovery.

**Storage Class** — класс хранения, определяющий цену за ГБ, стоимость операций и доступность. В AWS: Standard, Intelligent-Tiering, Standard-IA, One Zone-IA, Glacier Instant Retrieval, Glacier Flexible Retrieval, Glacier Deep Archive.

**Зачем разные классы:** Не все данные одинаково часто используются. Горячие данные (активные артефакты, текущие бэкапы) требуют низкой latency и высокой доступности → Standard. Тёплые данные (артефакты старше 30 дней) редко запрашиваются → Standard-IA. Холодные данные (архивы, compliance логи) могут ждать часы/дни для доступа → Glacier. Lifecycle policies автоматически мигрируют объекты между классами, оптимизируя стоимость.

**Durability** — вероятность долговечности данных. В AWS S3 Standard — 99,999999999% (11 девяток) за год.

**Почему durability важно:** 11 девяток означает, что при хранении 10 000 000 объектов вы потеряете в среднем один объект раз в 10 000 лет. Для production-систем это критично: потеря бэкапа или артефакта может привести к простою или потере данных.

**Availability** — доступность сервиса в течение года. Для S3 Standard — 99,99% (~52 минуты простоя в год).

**Почему availability отдельно от durability:** Durability гарантирует, что данные не потеряются. Availability гарантирует, что вы можете к ним обратиться. Объект может существовать (durability 100%), но быть временно недоступен (availability 99%). Для SLA приложений важно учитывать оба показателя.

---

## 2. Базовые концепции

### 2.1 Модель данных и API

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

### 2.2 Система метаданных

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

### 2.3 Консистентность

**AWS S3 (с 2020 года):**
- **Strong consistency** для PUT, DELETE, LIST: после успешной записи объект сразу доступен для чтения и отображается в LIST.
- **Strong read-after-write** для новых объектов.
- **Eventual consistency** для операций перезаписи (overwrite) и DELETE в редких сценариях edge cases.

**Self-hosted реализации (Ceph RGW, Garage):**
- Гарантии зависят от конкретного продукта и конфигурации.
- Ceph RGW: strong для новых объектов, eventual для LIST и overwrite.
- Garage: strong для новых объектов, eventual для LIST.
- **В production всегда проверяйте матрицу консистентности конкретной версии** перед проектированием.

**Почему консистентность важна:** В distributed системах консистентность определяет, когда изменения становятся видимыми для всех клиентов. Strong consistency упрощает разработку приложений (можно читать сразу после записи). Eventual consistency требует дополнительной логики (retry, version check), но позволяет достичь higher throughput и availability. Для S3 strong consistency с 2020 года означает, что большинство приложений могут считать S3 source of truth без дополнительных механизмов согласованности.

### 2.4 Классы хранения (Storage Classes)

| Класс | Сценарий | Стоимость хранения | Стоимость запроса | Retrieval время |
|-------|----------|-------------------|------------------|-----------------|
| Standard | Частый доступ, горячие данные | Высокая | Низкая | Немедленный |
| Intelligent-Tiering | Непредсказуемый паттерн доступа | Средняя | Средняя | Немедленный |
| Standard-IA | Инфраструктурные бэкапы, редко читаемые | Низкая | Выше Standard | Немедленный |
| One Zone-IA | Тёплые данные без cross-AZ избыточности | Очень низкая | Выше Standard | Немедленный |
| Glacier Instant Retrieval | Архив с немедленным доступом | Очень низкая | Высокая | Миллисекунды |
| Glacier Flexible Retrieval | Архив, доступ 1 мин–12 часов | Минимальная | Средняя | 1 мин–12 ч |
| Glacier Deep Archive | Долгосрочный архив, доступ 12–48 часов | Минимальная | Низкая | 12–48 ч |

**Lifecycle policies** автоматически мигрируют объекты между классами по истечении TTL или удаляют их.

**Почему экономия на Storage Class может быть огромной:** Цена за ГБ в Standard ≈ $0.023, в Deep Archive ≈ $0.00099. Для 100 ТБ данных разница составляет ~$2 300/месяц vs ~$100/месяц. Lifecycle policies позволяют автоматически оптимизировать стоимость без ручного вмешательства. **Важно:** стоимость запросов в IA/Glacier выше, поэтому для часто читаемых данных Standard может быть выгоднее.

### 2.5 Версионирование (Versioning)

Версионирование хранит **все версии** одного и того же ключа:
- При overwrite создаётся новая версия, старая остаётся доступной.
- При DELETE объект помечается как deleted (delete marker), предыдущие версии сохраняются.
- Позволяет откатываться (rollback) и защищает от случайного удаления или перезаписи.
- **Важно:** версионирование нельзя отключить, только приостановить. При возобновлении создаётся новая версия для каждого уникального ключа.

**Зачем versioning в production:** Versioning — это первая линия защиты от случайного удаления. Если `rm -rf` случайно удалил объекты в bucket, или CI/CD pipeline загрузила битый артефакт, versioning позволяет быстро восстановить предыдущую версию. В сочетании с lifecycle policy (удаление старых версий через 90 дней) это даёт баланс защиты и стоимости.

### 2.6 Шифрование

**Server-Side Encryption (SSE):**
- **SSE-S3** — ключи управляются сервисом. Объекты шифруются ключом данных (AES-256), который шифруется мастер-ключом.
- **SSE-KMS** — ключи управляются через KMS. Поддерживает rotation ключей, аудит через CloudTrail, granular permissions.
- **SSE-C** — клиент предоставляет ключ для каждого запроса. Сервис не хранит ключ.

**Client-Side Encryption:**
- Шифрование происходит на стороне клиента до загрузки.
- Используется для compliance требований, когда провайдер не должен иметь ключи.

**Почему шифрование обязательно:** Даже если данные "не чувствительные", шифрование at rest защищает от:
- Фической кражи дисков (в дата-центре).
- Неавторизованного доступа к S3 bucket через compromised credentials.
- Compliance требований (PCI DSS, HIPAA, GDPR).

SSE-KMS предпочтительнее SSE-S3, потому что даёт контроль над ключами, аудит и возможность rotation без повторного шифрования всех объектов.

---

## 3. Практические сценарии

### 3.1 Создание bucket и базовая работа через aws-cli

```bash
# Создание bucket (имя должно быть globally unique в рамках региона)
aws s3 mb s3://my-app-prod-assets \
  --region eu-central-1 \
  --endpoint-url https://s3.eu-central-1.amazonaws.com
```

**Зачем каждый параметр:**
- `--region` — определяет, в каком регионе создаётся bucket. Влияет на latency, стоимость и data residency.
- `--endpoint-url` — явное указание endpoint. Полезно при работе с S3-compatible хранилищами (Ceph RGW, Yandex).

```bash
# Включение версионирования
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled
```

**Зачем versioning сразу при создании:** Versioning нельзя отключить, только приостановить. Если вы планируете использовать versioning в production, включите его на старте. Приостановка versioning не удаляет существующие версии, но новые overwrite не создают версий.

```bash
# Включение шифрования по умолчанию
aws s3api put-bucket-encryption \
  --bucket my-app-prod-assets \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:eu-central-1:123456789012:alias/my-key"
      },
      "BucketKeyEnabled": true
    }]
  }'
```

**Зачем encryption по умолчанию:** Это защищает от человеческой ошибки. Если разработчик случайно загрузит объект без явного указания шифрования, bucket default encryption автоматически зашифрует его. Без default encryption объект остаётся незашифрованным, что является compliance нарушением.

```bash
# Загрузка объекта с metadata
aws s3 cp ./build/app.tar.gz s3://my-app-prod-assets/releases/v1.2.3/ \
  --storage-class STANDARD_IA \
  --metadata "build-id=abc123,commit=def456" \
  --server-side-encryption aws:kms
```

**Зачем metadata и storage class явно:**
- `--storage-class` позволяет контролировать, в какой класс помещается объект. По умолчанию — Standard, но для бэкапов и артефактов IA/Glacier выгоднее.
- `--metadata` добавляет бизнес-контекст к объекту. Это позволяет фильтровать объекты через S3 Inventory или S3 Select без скачивания.

```bash
# Синхронизация директории
aws s3 sync ./dist/ s3://my-app-prod-assets/static/ \
  --delete \
  --exclude "*.tmp" \
  --exclude ".git/*"
```

**Зачем sync вместо cp:** `sync` сравнивает локальные и удалённые файлы по размеру и времени модификации, загружает только изменившиеся. Это значительно ускоряет повторные деплои. `--delete` удаляет объекты в S3, которых нет локально (аналог `rsync --delete`). `--exclude` позволяет фильтровать временные файлы.

### 3.2 Lifecycle policies

```json
{
  "Rules": [
    {
      "ID": "TransitionToIA",
      "Status": "Enabled",
      "Filter": {"Prefix": "releases/"},
      "Transitions": [
        {"Days": 30, "StorageClass": "STANDARD_IA"},
        {"Days": 90, "StorageClass": "GLACIER_IR"},
        {"Days": 365, "StorageClass": "DEEP_ARCHIVE"}
      ],
      "NoncurrentVersionTransitions": [
        {"Days": 7, "StorageClass": "STANDARD_IA"},
        {"Days": 30, "StorageClass": "GLACIER_IR"}
      ],
      "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    },
    {
      "ID": "DeleteOldLogs",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Expiration": {"Days": 30},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}
    }
  ]
}
```

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-prod-assets \
  --lifecycle-configuration file://lifecycle.json
```

**Зачем lifecycle policies критичны для cost optimization:**
- Без lifecycle policies все объекты остаются в Standard (самый дорогой класс). Для 100 ТБ это ~$2 300/месяц.
- Lifecycle policies автоматически мигрируют объекты в дешёвые классы по истечении TTL.
- `AbortIncompleteMultipartUpload` удаляет зависшие multipart uploads, которые могут стоить dearly.

**Важно:** lifecycle policies работают асинхронно. Не рассчитывайте на немедленное удаление или переход.

### 3.3 S3 Object Lock (WORM)

Object Lock защищает объекты от удаления или перезаписи в течение заданного срока. Используется для compliance (SEC Rule 17a-4, FINRA) и защиты от ransomware.

**Режимы:**
- **Governance** — администратор может снять блокировку при наличии специальных permissions (`s3:BypassGovernanceRetention`).
- **Compliance** — никто, включая root account, не может удалить или изменить объект до истечения срока.

```bash
# Включение Object Lock на bucket (только при создании)
aws s3api create-bucket \
  --bucket my-app-prod-assets \
  --object-lock-enabled-for-bucket \
  --region eu-central-1

# Настройка retention по умолчанию (30 дней, Compliance режим)
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
  }'

# Проверка retention для конкретного объекта
aws s3api get-object-retention \
  --bucket my-app-prod-assets \
  --key releases/v1.2.3/app.tar.gz
```

**Зачем Object Lock в production:**
- **Ransomware protection:** Даже если злоумышленник получит доступ к S3 credentials, он не сможет удалить или зашифровать объекты с Object Lock.
- **Compliance:** SEC Rule 17a-4 требует, чтобы broker-dealer records были immutable в течение минимум 3 лет. Object Lock в режиме Compliance удовлетворяет это требование.
- **Audit integrity:** Логи и метрики, загруженные с Object Lock, не могут быть удалены или изменены для сокрытия следов.

### 3.4 Multipart Upload

Для объектов > 5 ГБ (или для надёжности при нестабильном канале) используется multipart upload:

1. Инициализация: `POST /bucket/key?uploads` → получаем `UploadId`.
2. Загрузка частей: `PUT /bucket/key?uploadId=...&partNumber=N` (каждая часть ≥ 5 МБ, кроме последней).
3. Завершение: `POST /bucket/key?uploadId=...` с XML, содержащим ETag каждой части.
4. Отмена: `DELETE /bucket/key?uploadId=...` (части удаляются через lifecycle policy).

```bash
# Ручной multipart upload через aws-cli (файл > 8 ГБ)
aws s3 cp large-backup.tar.gz s3://my-app-prod-assets/backups/ \
  --storage-class DEEP_ARCHIVE

# Проверка незавершённых multipart uploads
aws s3api list-multipart-uploads --bucket my-app-prod-assets

# Отмена старых незавершённых загрузок
aws s3api list-multipart-uploads --bucket my-app-prod-assets \
  --query 'Uploads[*].[Key,UploadId]' --output text | while read key upload_id; do
    aws s3api abort-multipart-upload --bucket my-app-prod-assets --key "$key" --upload-id "$upload_id"
  done
```

**Зачем multipart upload:**
- **Надёжность:** Если часть загрузки прервалась, можно повторить только эту часть, а не весь файл.
- **Производительность:** Загрузка частей параллельно увеличивает throughput в разы.
- **Гибкость:** Можно начать загрузку, прерваться на неопределённое время, затем продолжить.

**Production best practice:** всегда настраивайте lifecycle rule `AbortIncompleteMultipartUpload` для автоматической очистки зависших загрузок. Незавершённые multipart uploads хранятся до отмены или expiration и могут стоить dearly.

### 3.5 Replication (CRR / SRR)

**Cross-Region Replication (CRR)** — асинхронное реплицирование объектов между bucket в разных регионах. Используется для disaster recovery и compliance.

**Same-Region Replication (SRR)** — реплицирование внутри региона для separation of duties.

**Ограничения:**
- Не реплицирует объекты, существовавшие до включения replication (требуется batch replication).
- Не реплицирует объекты, загруженные с `ServerSideEncryption: AES256` если в destination bucket нет permissions на KMS key.
- Delete markers реплицируются только при наличии `DeleteMarkerReplication` в rule.
- Стоимость: плата за межрегиональный трафик + операции в destination bucket.

### 3.6 Event Notifications

S3 может генерировать события для интеграции с другими системами:

**Триггеры:**
- `s3:ObjectCreated:*` — загрузка, multipart completion, copy
- `s3:ObjectRemoved:*` — удаление, lifecycle expiration
- `s3:ObjectRestore:*` — initiate, complete, expire
- `s3:Replication:*` — успешное/неуспешное реплицирование

**Цели:**
- **SQS** — очередь для асинхронной обработки (рекомендуется для production).
- **SNS** — pub/sub, несколько подписчиков.
- **Lambda** — serverless обработка (обработка загруженных файлов, трансформации).
- **EventBridge** — сложная маршрутизация и фильтрация.

```bash
# Настройка уведомлений на SQS
aws s3api put-bucket-notification-configuration \
  --bucket my-app-prod-assets \
  --notification-configuration '{
    "QueueConfigurations": [{
      "QueueArn": "arn:aws:sqs:eu-central-1:123456789012:my-queue",
      "Events": ["s3:ObjectCreated:Put"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {"Name": "prefix", "Value": "uploads/"},
            {"Name": "suffix", "Value": ".csv"}
          ]
        }
      }
    }]
  }'
```

**Зачем event notifications в production:**
- **Event-driven architecture:** Вместо polling S3 на новые объекты (что неэффективно и медленно), S3 push'ет события в SQS/Lambda. Это стандартный паттерн для serverless и event-driven систем.
- **Decoupling:** Загрузчик не знает о потребителе. Можно добавить новых потребителей (новый Lambda) без изменения кода загрузчика.
- **Reliability:** SQS буферизует события, обеспечивая at-least-once delivery. Если consumer упал, сообщения не потеряются.

### 3.7 Static Website Hosting

S3 может выступать статическим веб-сервером с поддержкой index document, error document и custom domain через CloudFront.

```bash
# Включение static website hosting
aws s3 website s3://my-app-prod-assets/ \
  --index-document index.html \
  --error-document error.html
```

**Production limitations:**
- Только GET/HEAD запросы (нет HTTPS на endpoint напрямую, нужен CloudFront).
- Нет server-side логики (используйте Lambda@Edge или CloudFront Functions).
- Нет gzip/br автоматического сжатия для всех типов контента (CloudFront добавляет это).

**Когда использовать:** Для статических сайтов, single-page applications, документации. Не для динамических приложений.

### 3.8 Presigned URLs

Генерация временных URL для доступа к объектам без раскрытия credentials:

```python
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client('s3', region_name='eu-central-1')

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
        'ServerSideEncryption': 'aws:kms'
    },
    ExpiresIn=3600
)
```

**Зачем presigned URLs:**
- **Security:** Не нужно раскрывать permanent credentials клиентам/сервисам. Presigned URL действителен только ограниченное время.
- **Audit:** Все операции через presigned URL логируются в CloudTrail с идентификацией принципала.
- **Flexibility:** Можно генерировать presigned URLs на лету в API gateway, Lambda, не храня credentials в клиентском коде.

---

## 4. Безопасность

### 4.1 IAM Policies

IAM policies управляют доступом на уровне bucket, prefix, объекта:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowListBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-app-prod-assets",
      "Condition": {"StringLike": {"s3:prefix": "releases/*"}}
    },
    {
      "Sid": "AllowReadWriteReleases",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::my-app-prod-assets/releases/*"
    },
    {
      "Sid": "DenyUnencryptedUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::my-app-prod-assets/*",
      "Condition": {
        "StringNotEquals": {"s3:x-amz-server-side-encryption": "aws:kms"}
      }
    }
  ]
}
```

**Зачем Condition в IAM:** Condition позволяет ограничить действия по дополнительным атрибутам: IP-адресу, времени суток, наличию MFA, протоколу (TLS). Например, можно разрешить доступ к S3 только из corporate IP диапазона или только через HTTPS.

**Production best practices:**
- Используйте **IAM roles** вместо статических ключей.
- Включите **Block Public Access** на уровне account и bucket.
- Ограничивайте действия через **Condition** (IP, MFA, TLS).
- Включите **s3:PutObject** с `s3:x-amz-server-side-encryption` condition для принудительного шифрования.

### 4.2 Bucket Policies vs ACL

**Bucket Policy** — JSON-документ на уровне bucket, более гибкий, поддерживает Condition.
**ACL** — устаревший механизм (2006), ограниченный (разрешения: READ, WRITE, READ_ACP, WRITE_ACP, FULL_CONTROL). Используется только для обратной совместимости.

**Рекомендация:** отключайте ACL (`BucketOwnerEnforced`), используйте только Bucket Policies и IAM.

**Почему ACL устарели:** ACL — это механизм 2006 года, до появления IAM. Они не поддерживают Condition, не интегрируются с CloudTrail, не позволяют задавать сложные правила. В 2023+ AWS рекомендует отключить ACL полностью (`BucketOwnerEnforced`), полагаясь только на Bucket Policies и IAM.

### 4.3 Access Logging и Audit

```bash
# Включение access logging (логи записываются в целевой bucket)
aws s3api put-bucket-logging \
  --bucket my-app-prod-assets \
  --bucket-logging-status '{
    "LoggingEnabled": {
      "TargetBucket": "my-app-audit-logs",
      "TargetPrefix": "s3-logs/my-app-prod-assets/"
    }
  }'
```

**CloudTrail data events** — детальный аудит всех операций S3 (GET, PUT, DELETE) с integration в CloudWatch Logs / Athena.

**Зачем аудит в production:**
- **Incident investigation:** Если данные утекли, access logs и CloudTrail events позволяют отследить, кто, когда и что сделал.
- **Compliance:** PCI DSS, HIPAA, SOC 2 требуют аудит всех операций с чувствительными данными.
- **Cost attribution:** Access logs показывают, какие сервисы/пользователи генерируют больше всего запросов, что помогает оптимизировать затраты.

### 4.4 Block Public Access

На уровне account и bucket:

```bash
aws s3api put-public-access-block \
  --bucket my-app-prod-assets \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'
```

**Почему Block Public Access критичен:** Публичный S3 bucket — одна из самых частых причин утечек данных. Даже если вы не намеревались делать bucket публичным, ошибка в bucket policy или ACL может сделать его публичным. Block Public Access на уровне account блокирует все попытки сделать bucket публичным, даже если bucket policy разрешает это.

---

## 5. Мониторинг и эксплуатация

### 5.1 CloudWatch Metrics

**Основные метрики:**
- `BucketSizeBytes` — размер bucket по Storage Class (отчёт раз в сутки).
- `NumberOfObjects` — количество объектов (отчёт раз в сутки).
- `AllRequests` — общее количество запросов.
- `GetRequests`, `PutRequests`, `DeleteRequests` — распределение по типам.
- `4xxErrors`, `5xxErrors` — ошибки клиента/сервиса.
- `FirstByteLatency`, `TotalRequestLatency` — задержки.

**Алерты:**
- `5xxErrors > 0` в течение 5 минут — инцидент.
- `4xxErrors > 100` в течение 5 минут — возможно, misconfiguration или атака.
- Рост `BucketSizeBytes` без соответствующего роста `NumberOfObjects` — возможно, утечка больших объектов.

### 5.2 S3 Inventory

AWS S3 Inventory генерирует ежедневные/еженедельные отчёты о всех объектах в bucket (ключ, размер, Storage Class, статус шифрования, версия). Используется для:
- Аудита compliance.
- Обнаружения неожиданных Storage Class.
- Lifecycle policy validation.

### 5.3 Request Payers

Для кросс-account сценариев (один аккаунт загружает, другой платит):
- **Requester Pays** — загрузчик платит за GET/LIST запросы.
- Включается на bucket уровне.

---

## 6. Производственные паттерны

### 6.1 Идемпотентные загрузки

Используйте `x-amz-content-sha256` и client-side idempotency tokens для предотвращения дублирования при повторных загрузках.

### 6.2 Transfer Acceleration

Ускорение загрузки/скачивания через edge-сеть CloudFront для клиентов в других регионах. Используется для больших файлов (> 100 МБ).

### 6.3 Select и Glacier Select

Позволяют выполнять SQL-подобные запросы (SELECT, WHERE, LIMIT) напрямую в объектах (CSV, JSON, Parquet) без скачивания всего файла. Критично для аналитических пайплайнов.

### 6.4 Batch Operations

Массовые операции над миллионами объектов:
- Копирование между buckets.
- Изменение Storage Class.
- Установка tags/metadata.
- Восстановление из Glacier.
- Invoke Lambda для каждого объекта.

### 6.5 Storage Lens

Centralized observability для organisation-wide S3 usage. Предоставляет:
- Объём данных по bucket, account, region.
- Прогнозы стоимости.
- Рекомендации по оптимизации (неиспользуемые buckets, устаревшие versioning, недостаточное шифрование).
- Detector для public buckets, unencrypted objects, отсутствия versioning.

---

## 7. Self-hosted совместимые реализации

В приватных инфраструктурах (on-prem, air-gapped) для совместимости с S3 API используются:

### 7.1 Ceph RADOS Gateway (RGW)

**Архитектура:**
- Часть кластера Ceph, предоставляет S3-compatible и Swift-compatible API поверх RADOS.
- Данные распределяются по OSDs с erasure coding или репликацией.
- Поддерживает большинство S3 API: Object CRUD, Bucket operations, Versioning, Lifecycle (частично), ACL, Bucket Policies.

**Производственные особенности:**
- **Масштабируемость:** горизонтальная, до PB.
- **Durability:** регулируемая через EC pool (например, 8+3).
- **Производительность:** зависит от сети (RDMA/ RoCE для high-performance).
- **Совместимость:** полная для базовых операций; некоторые расширения AWS (S3 Access Points, S3 Batch Operations) не поддерживаются.

**When to choose Ceph RGW:**
- Уже есть кластер Ceph для блочного/файлового хранения.
- Нужно единое хранилище для блоков, файлов и объектов.
- Требуется распределённое, высоконадёжное решение на собственных дисках.

### 7.2 Garage

**Архитектура:**
- Распределённое объектное хранилище на Rust.
- Гео-распределённые кластеры (multisite) из коробки.
- S3-compatible API.

**Производственные особенности:**
- **Масштабируемость:** горизонтальная, multisite.
- **Durability:** erasure coding, регулируемая избыточность.
- **Производительность:** оптимизировано для edge и распределённых сценариев.
- **Совместимость:** базовая S3 API; advanced features (Object Lock, Lifecycle) могут отсутствовать в Open Source версии.

### 7.3 Сравнение совместимых реализаций

| Критерий | Ceph RGW | Garage | Cloud-native S3 |
|----------|----------|--------|-----------------|
| **Хранение** | RADOS (распределённое) | Собственный distributed | Облачное |
| **S3 API** | Полная (основные операции) | Базовая | Полная |
| **Object Lock** | Да (с 2023) | Частично | Да |
| **Lifecycle** | Частично | Нет | Да |
| **Versioning** | Да | Да | Да |
| **Масштабирование** | Горизонтальное (PB+) | Горизонтальное | Неограниченное |
| **Производительность** | Высокая (с RDMA) | Средняя/высокая | Высокая |
| **Use case** | Unified storage, enterprise | Edge, geo-distributed | Любой |

---

## 8. Типичные ошибки и troubleshooting

### 8.1 403 Forbidden

**Причины:**
- Bucket Policy denies доступ.
- IAM policy не授予 permissions на bucket/object.
- Block Public Access блокирует запрос.
- KMS key policy denies `kms:Decrypt` для SSE-KMS объектов.
- Bucket в другом аккаунте, нет bucket owner permissions.

**Диагностика:**
```bash
# Проверка bucket policy
aws s3api get-bucket-policy --bucket my-app-prod-assets

# Проверка public access block
aws s3api get-public-access-block --bucket my-app-prod-assets

# Проверка encryption
aws s3api head-object --bucket my-app-prod-assets --key path/to/object
```

### 8.2 404 NoSuchKey / NoSuchBucket

**Причины:**
- Объект удалён или never существовал.
- Bucket в другом регионе, используется неправильный endpoint.
- Eventual consistency: LIST показал объект, но он ещё не реплицирован в целевой регион.
- Ключ содержит непечатаемые символы или неправильно закодирован.

### 8.3 Slow uploads/downloads

**Причины:**
- Не используется multipart upload для больших файлов.
- Нет Transfer Acceleration для cross-region доступа.
- S3 Select не используется для больших файлов с партициями.
- Пропускная способность сети ограничена.
- Для self-hosted: не настроен parallelism на клиенте (aws-cli использует 10 потоков по умолчанию).

### 8.4 Unexpected costs

**Причины:**
- LIST запросы на bucket с миллионами объектов (paginated requests).
- Cross-region replication traffic.
- Glacier retrieval requests без правильного Storage Class transition.
- Незавершённые multipart uploads (хранятся до отмены или lifecycle expiration).
- Versioned bucket без lifecycle policy для удаления старых версий.

**Мониторинг:** включите S3 Storage Lens и Cost Explorer tags для attribution по bucket/team.

---

## 9. Сравнение S3 с другими хранилищами

| Критерий | S3 (object) | NFS (file) | Block (iSCSI) | HDFS |
|----------|-------------|------------|---------------|------|
| **Модель** | Объекты + ключи | Иерархия файлов | Блочные устройства | Файлы, HDFS FS |
| **Метаданные** | Rich (ключи, tags, ACL) | POSIX (inode) | Минимальные | HDFS-specific |
| **API** | REST/HTTP | NFS/SMB | iSCSI/ NVMe-oF | Proprietary |
| **Масштабирование** | Горизонтальное (PB+) | Вертикальное/cluster | Вертикальное | Горизонтальное |
| **Производительность** | Высокая (throughput), высокая latency | Низкая latency | Очень низкая latency | Высокая throughput |
| **Сценарии** | Бэкапы, статика, артефакты, логи | Shared storage, home dirs | СУБД, ВМ | Big Data, Spark |
| **Совместимость** | S3 API universal | POSIX | block device | Hadoop ecosystem |

---

## 10. Interview-вопросы и ответы

**Q: В чём разница между S3 и обычным файловым хранилищем?**

S3 — объектное хранилище с плоским пространством ключей, доступом через REST API и автоматическим горизонтальным масштабированием. Файловое хранилище (NFS, SMB) — иерархия каталогов, POSIX-семантика, низкая latency, ограниченное масштабирование.

**Q: Что такое Eventual Consistency в S3 и когда она применяется?**

В AWS S3 eventual consistency была до 2020 года для overwrite и DELETE. Сейчас S3 обеспечивает strong consistency для всех операций. Self-hosted реализации (Ceph RGW, Garage) могут иметь eventual consistency для LIST и overwrite — проверяйте документацию конкретной версии.

**Q: Как обеспечить долговечность данных 99,999999999%?**

S3 Standard автоматически реплицирует данные ≥ 3 Availability Zones в регионе. Для self-hosted: используйте erasure coding с избыточностью ≥ 8+3 или репликацию ≥ 3 копий на разных узлах/стойках.

**Q: Что такое S3 Versioning и зачем он нужен?**

Версионирование хранит все версии одного ключа. Защищает от случайного удаления/перезаписи, позволяет откатываться. В production включайте versioning для критичных bucket (артефакты, бэкапы) и комбинируйте с lifecycle policy для удаления старых версий.

**Q: Объясните S3 Lifecycle policies.**

Lifecycle — правила автоматической миграции объектов между Storage Class или удаления по истечении TTL. Используется для оптимизации стоимости: горячие данные → Standard, тёплые → IA, холодные → Glacier, устаревшие → удаление.

**Q: Что такое S3 Object Lock и в чём разница между Governance и Compliance режимами?**

Object Lock — WORM-механизм, защищающий объекты от удаления/изменения. Governance: администратор может снять блокировку с специальными permissions. Compliance: никто, включая root, не может удалить объект до истечения retention period.

**Q: Как работает SSE-KMS?**

SSE-KMS — серверное шифрование с ключами из AWS KMS. Данные шифруются ключом данных (AES-256), который шифруется KMS master key. Преимущества: rotation ключей, аудит через CloudTrail, granular permissions (kms:GenerateDataKey, kms:Decrypt). В production используйте SSE-KMS вместо SSE-S3 для контроля над ключами.

**Q: Когда использовать multipart upload?**

Для объектов > 5 ГБ или при нестабильном канале. Multipart позволяет параллельно загружать части, возобновлять прерванные загрузки и повышает throughput. Части ≥ 5 МБ (кроме последней). Незавершённые загрузки автоматически удаляются через lifecycle policy.

**Q: Что такое Presigned URL?**

Временный URL для доступа к объекту без раскрытия credentials. Генерируется на основе secret access key с ограничением по времени (ExpiresIn) и действию (get_object, put_object). Используется для безопасной передачи файлов между сервисами без хранения credentials.

**Q: Как отладить 403 Forbidden в S3?**

1. Проверить Block Public Access на bucket и account.
2. Проверить Bucket Policy и IAM policy.
3. Проверить ACL (если используется legacy ACL).
4. Для SSE-KMS: проверить KMS key policy и `kms:Decrypt` permission.
5. Проверить, нет ли explicit Deny в любой из policies.

**Q: Что такое S3 Select и когда его использовать?**

S3 Select позволяет выполнять SQL-запросы (SELECT, WHERE, LIMIT) напрямую в объектах CSV, JSON, Parquet без скачивания всего файла. Уменьшает количество передаваемых данных и ускоряет аналитические пайплайны. Используется для больших файлов (> 1 ГБ), когда нужен только подмножество данных.

**Q: В чём разница между S3 и Ceph RGW?**

S3 — managed сервис Amazon с полной совместимостью API, SLA 11 девяток durability, глобальной сетью edge. Ceph RGW — self-hosted реализация S3 API поверх RADOS, распределённое хранение на собственных дисках, горизонтальное масштабирование до PB. RGW подходит для on-prem/air-gapped сценариев, S3 — для облачных и гибридных архитектур.

---

## 11. Best Practices (Production Checklist)

### Security
- [ ] Включён **Block Public Access** на уровне account и bucket.
- [ ] Используются **IAM roles** вместо статических ключей.
- [ ] Включено **Server-Side Encryption** (SSE-KMS для production).
- [ ] Настроен **Bucket Policy** с explicit Deny для нешифрованных загрузок.
- [ ] Включён **Access Logging** и **CloudTrail data events**.
- [ ] Настроены **S3 Inventory** для compliance аудита.
- [ ] Versioning включён для критичных bucket с lifecycle policy для старых версий.

### Reliability
- [ ] Настроены **Lifecycle policies** для автоматического управления Storage Class и удаления.
- [ ] Для объектов > 5 ГБ используется **multipart upload**.
- [ ] Незавершённые multipart uploads очищаются через `AbortIncompleteMultipartUpload`.
- [ ] Для critical data включён **Object Lock** (Compliance или Governance).
- [ ] Настроено **Cross-Region Replication** для disaster recovery (RPO/RTO определён).
- [ ] Используются **Presigned URLs** с коротким TTL вместо долгоживущих ключей.

### Cost Optimization
- [ ] Lifecycle policies для миграции в IA/Glacier по истечении TTL.
- [ ] **Intelligent-Tiering** для данных с непредсказуемым паттерном доступа.
- [ ] **Storage Lens** включён для организации-wide visibility.
- [ ] **Request Payers** для кросс-account сценариев (если применимо).
- [ ] **S3 Inventory** используется для обнаружения устаревших данных.
- [ ] **Transfer Acceleration** включён только для cross-region больших файлов.

### Performance
- [ ] Для больших файлов (> 100 МБ) используется **multipart upload** с оптимальным part size (≥ 5 МБ, рекомендуется 8–128 МБ).
- [ ] **Transfer Acceleration** или **CloudFront** для клиентов в других регионах.
- [ ] **S3 Select** для аналитических запросов к большим файлам.
- [ ] **Prefix naming** оптимизирован для параллелизма (хеширование в начале ключа для равномерного распределения).
- [ ] Для high-throughput сценариев используется **S3 Batch Operations** вместо последовательных CLI вызовов.

---

## 12. См. также

- [Ansible и S3: интеграция, автоматизация и эксплуатация](./ansible-integration.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [Ceph RGW: S3-совместимое хранилище на базе Ceph](../../../Kubernetes/Storage/Ceph/ceph_rgw_s3.md)
- [Обзор систем хранения данных (СХД)](../data_storage_overview.md)
- [Thanos: долгосрочное хранение метрик Prometheus](../../../Prometheus/scaling/thanos_overview.md)
- [Grafana Tempo: архитектура и операции](../../../Tempo/architecture_operations.md)
- [Vector: сбор и маршрутизация логов](../../../Vector/vector_overview.md)
- [HashiCorp Consul: service discovery и конфигурация](../../../Consul/consul_overview.md)
