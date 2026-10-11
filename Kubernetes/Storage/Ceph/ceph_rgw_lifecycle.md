# RGW: жизненный цикл объектов и управление хранилищем

Руководство по управлению жизненным циклом объектов в RADOS Gateway (RGW): lifecycle policies, versioning, expiration, storage tiering и Object Lock. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** базовое описание RGW — в [RGW (S3-compatible)](./ceph_rgw_s3.md); RGW multisite — в [Сравнении CSI-драйверов](../CSI/csi_drivers_comparison.md) и [Бэкапе и DR](./ceph_backup_and_dr.md); интеграция с Kubernetes — в [PV/PVC Scenarios](../pv_and_pvc_scenarios.md).

## Определения

**Lifecycle Policy** — набор правил, автоматически управляющих жизненным циклом объектов в бакете: переход между классами хранения (tiers), удаление устаревших объектов, завершение multipart upload.

**Storage Tier** — уровень хранения с разной стоимостью и производительностью. В RGW реализуется через lifecycle transitions: Standard → Infrequent Access → Archive.

**Versioning** — механизм хранения всех версий объекта. При перезаписи объекта старая версия сохраняется как non-current.

**Object Lock (WORM)** — защита объектов от удаления или модификации на заданный период. Режимы: `COMPLIANCE` (нельзя удалить даже администратором) и `GOVERNANCE` (удаление только с governance permission).

**Expiration** — автоматическое удаление объектов по сроку жизни (days since creation/modification).

**Abort Incomplete Multipart Upload** — автоматическая очистка незавершенных multipart upload после заданного периода.

## Базовые концепции

### Жизненный цикл объекта RGW

```
┌──────────┐    PUT    ┌──────────┐    Transition    ┌──────────┐
│  Client  │ ────────► │  Standard │ ◄─────────────── │  Archive │
│  (S3 SDK)│           │  (Hot)    │                  │  (Cold)  │
└──────────┘           └────┬─────┘                  └──────────┘
                            │
                     ┌──────┴──────┐
                     │  Lifecycle  │
                     │   Policy    │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Expire   │ │  Delete  │ │   Abort  │
        │ (days)   │ │  Marker  │ │ Multipart│
        └──────────┘ └──────────┘ └──────────┘
```

### Компоненты lifecycle

| Компонент | Назначение |
|-----------|-----------|
| **Filter** — Prefix, Tag, Size | Ограничение правил на подмножество объектов |
| **Transition** — Days, StorageClass | Переход между классами хранения |
| **Expiration** — Days, DeleteMarker | Удаление устаревших объектов |
| **AbortIncompleteMultipartUpload** — Days | Очистка незавершенных загрузок |
| **NoncurrentVersionExpiration** | Удаление старых версий (при versioning) |
| **NoncurrentVersionTransition** | Переход старых версий в Archive |

### Storage tiers в RGW

| Tier | Описание | Сценарий |
|------|----------|----------|
| **STANDARD** | Быстрый доступ, высокая стоимость | Активные данные, частое чтение |
| **INFREQUENT_ACCESS** | Редкий доступ, низкая стоимость | Резервные копии, логи |
| **ARCHIVE** | Минимальная стоимость, долгий доступ | Compliance, долгосрочное хранение |

## Практические сценарии

### 1. Создание lifecycle policies

#### 1.1 Через radosgw-admin (CLI)

```bash
# Создание JSON с policy
cat > lifecycle.json <<EOF
{
  "Rules": [
    {
      "ID": "expire-old-objects",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "logs/"
      },
      "Expiration": {
        "Days": 30
      }
    },
    {
      "ID": "transition-to-archive",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "backups/"
      },
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "INFREQUENT_ACCESS"
        },
        {
          "Days": 365,
          "StorageClass": "ARCHIVE"
        }
      ]
    },
    {
      "ID": "abort-incomplete-uploads",
      "Status": "Enabled",
      "Filter": {},
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 7
      }
    }
  ]
}
EOF

# Применение к бакету
radosgw-admin bucket lifecycle set --bucket my-bucket --lifecycle-file lifecycle.json

# Проверка
radosgw-admin bucket lifecycle get --bucket my-bucket
```

#### 1.2 Через S3 API (AWS CLI)

```bash
# Создание policy
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-bucket \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "expire-old-objects",
        "Status": "Enabled",
        "Filter": {"Prefix": "logs/"},
        "Expiration": {"Days": 30}
      }
    ]
  }' \
  --endpoint-url http://rgw.example.com
```

### 2. Versioning + Lifecycle

```bash
# Включение versioning на бакете
radosgw-admin bucket versioning enable --bucket my-bucket

# Lifecycle для non-current версий
cat > lifecycle-versioned.json <<EOF
{
  "Rules": [
    {
      "ID": "expire-noncurrent-versions",
      "Status": "Enabled",
      "Filter": {},
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 30
      },
      "NoncurrentVersionTransition": {
        "NoncurrentDays": 7,
        "StorageClass": "INFREQUENT_ACCESS"
      }
    }
  ]
}
EOF

radosgw-admin bucket lifecycle set --bucket my-bucket --lifecycle-file lifecycle-versioned.json
```

### 3. Object Lock (WORM)

```bash
# Включение Object Lock на бакете
radosgw-admin bucket create --bucket my-lock-bucket --lock-enabled

# Настройка default retention (COMPLIANCE mode, 7 лет)
radosgw-admin bucket create --bucket my-lock-bucket \
  --lock-mode COMPLIANCE \
  --lock-days 2555

# Или GOVERNANCE mode (удаление только с permission)
radosgw-admin bucket create --bucket my-lock-bucket \
  --lock-mode GOVERNANCE \
  --lock-days 365
```

**Режимы:**
- `COMPLIANCE` — объект нельзя удалить/изменить даже администратором в течение периода retention.
- `GOVERNANCE` — удаление возможно только с `s3:BypassGovernanceRetention` permission.

### 4. Storage Tiers и cost optimization

```bash
# Сценарий: hot data → warm → cold

# 1. STANDARD (0-30 дней)
# 2. INFREQUENT_ACCESS (30-90 дней)
# 3. ARCHIVE (90+ дней)

# Lifecycle policy
cat > lifecycle-tiering.json <<EOF
{
  "Rules": [
    {
      "ID": "tiering-policy",
      "Status": "Enabled",
      "Filter": {"Prefix": "data/"},
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "INFREQUENT_ACCESS"
        },
        {
          "Days": 90,
          "StorageClass": "ARCHIVE"
        }
      ],
      "Expiration": {
        "Days": 2555
      }
    }
  ]
}
EOF

radosgw-admin bucket lifecycle set --bucket data-bucket --lifecycle-file lifecycle-tiering.json
```

### 5. Monitoring lifecycle operations

```bash
# Проверка статуса lifecycle
radosgw-admin bucket lifecycle get --bucket my-bucket

# Просмотр версий объектов
radosgw-admin object stat --bucket my-bucket --object my-object

# Проверка lock статуса
radosgw-admin object lock get --bucket my-bucket --object my-object

# Мониторинг в Prometheus
# Метрики: rgw_lc_*, rgw_bucket_*
```

## Лучшие практики

### Lifecycle design

1. **Используйте lifecycle для автоматизации** — не полагайтесь на ручную очистку.
2. **Начинайте с generous retention** — лучше хранить лишнее, чем потерять нужное.
3. **Тестируйте policies на dev-бакете** перед применением в production.
4. **Мониторьте transition costs** — переходы между tiers могут быть платными в некоторых реализациях.

### Versioning

1. **Включайте versioning** для всех production бакетов — это защита от случайного удаления.
2. **Настройте NoncurrentVersionExpiration** — иначе бакет бесконечно растет.
3. **Используйте MFA Delete** для критичных бакетов — требует MFA token для удаления версий.

### Object Lock

1. **COMPLIANCE mode** — для regulatory requirements (finance, healthcare).
2. **GOVERNANCE mode** — для internal policies с возможностью override.
3. **Не переусердствуйте** — длинный retention = сложность управления.

### Cost optimization

1. **Шаблон:** 30 дней Standard → 90 дней IA → 7 лет Archive.
2. **Для логов:** 7 дней Standard → 30 дней IA → удаление.
3. **Для бэкапов:** 1 день Standard → 1 год Archive → удаление.

## Дополнительная информация

### См. также

- [RGW (S3-compatible)](./ceph_rgw_s3.md) — базовое руководство по RGW
- [Резервное копирование и DR](./ceph_backup_and_dr.md) — бэкап данных и конфигурации
- [Безопасность Ceph](./ceph_security_hardening.md) — CephX, аудит, шифрование

### Официальные ресурсы

- [RGW Lifecycle](https://docs.ceph.com/en/latest/radosgw/bucket-lifecycle/) — официальное руководство
- [RGW Object Lock](https://docs.ceph.com/en/latest/radosgw/object-lock/) — WORM конфигурация
- [RGW Versioning](https://docs.ceph.com/en/latest/radosgw/versioning/) — версионирование объектов
