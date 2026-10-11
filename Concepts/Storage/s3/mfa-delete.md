# S3: защита от случайного удаления в Ceph RGW

**Актуально для:** Ceph RGW (Squid 19.x / Tentacle 20.x)

---

## 1. Определения

**Случайное удаление** — удаление объектов или бакетов по ошибке, без злого умысла. Основная причина потери данных в S3-совместимых хранилищах.

**Версионирование** — механизм хранения всех версий объекта. При DELETE создаётся delete marker, предыдущие версии сохраняются.

**Object Lock (WORM)** — механизм защиты объектов от удаления или перезаписи в течение заданного срока. В Ceph RGW поддерживается в режимах Compliance и Governance.

**Retention period** — срок, в течение которого объект защищён от удаления. После истечения срока объект может быть удалён (в Governance mode) или остаётся защищённым (в Compliance mode).

**Legal Hold** — бессрочная защита объекта от удаления/изменения. Используется для litigation, investigations.

**MFA Delete** — механизм, требующий многофакторную аутентификацию через TOTP-токен для удаления версий объектов или изменения настроек версионирования бакета. В Ceph RGW реализован через `radosgw-admin mfa` с версии Mimic (13.x).

**Access Logging** — механизм записи всех запросов к бакету в отдельный целевой бакет. Позволяет отследить, кто, когда и что сделал с объектами.

**radosgw-admin audit** — встроенный механизм аудита операций RGW. Записывает события в логи Ceph или внешние системы (Loki, Elasticsearch).

---

## 2. Базовые концепции

### 2.1 Уровни защиты от удаления

| Уровень | Защита | Включение |
|---------|--------|-----------|
| **Prevention** | Object Lock, Versioning, Lifecycle, MFA Delete | Всегда для production |
| **Detection** | Access Logging, radosgw-admin audit | Всегда |
| **Recovery** | Version restore, multisite replication | Для критичных данных |

### 2.2 Ceph RGW и MFA Delete

Ceph RGW поддерживает MFA Delete, соответствующий спецификации AWS S3 MFA Delete. Механизм требует TOTP-токен для следующих операций:
- Постоянного удаления версии объекта (`delete-object` с `version-id`)
- Изменения состояния версионирования бакета (включение/отключение, удаление delete markers)

Токены управляются через `radosgw-admin mfa create/list/get/remove/check/resync`. Включение MFA Delete происходит через S3 API с заголовком `x-amz-mfa`. В Ceph Dashboard поддержка MFA Delete добавлена начиная с Squid.

### 2.3 Требования для MFA Delete

- Включённое версионирование на бакете
- TOTP-токен, присвоенный пользователю RGW
- Поддерживающее TOTP приложение (FreeOTP, Google Authenticator, hardware MFA device)
- Права `rgw-manager` или `admin` для управления MFA токенами

---

## 3. Практические сценарии

### 3.1 Предварительные требования

- Ceph кластер с RGW daemon (Squid 19.x / Tentacle 20.x)
- AWS CLI 2.x или совместимый S3 клиент
- Доступ к `radosgw-admin` на Ceph monitor/manager node
- Включённое версионирование на целевом бакете

### 3.2 Создание MFA TOTP токена

```bash
# Создание TOTP токена для пользователя RGW
radosgw-admin mfa create \
  --uid=app-user \
  --totp-serial=my-mfa-device \
  --totp-seed=492dedb20cf51d1405ef6a1316017e \
  --totp-seed-type=base32 \
  --totp-seconds=30 \
  --totp-window=2

# Проверка токена (сравнение текущего TOTP кода)
radosgw-admin mfa check \
  --uid=app-user \
  --totp-serial=my-mfa-device \
  --totp-pin=$(oathtool -d6 --totp 492dedb20cf51d1405ef6a1316017e)

# Список токенов пользователя
radosgw-admin mfa list --uid=app-user
```

**Почему это важно:** TOTP seed нужно сохранить в защищённом месте (vault, sealed secret). При потере seed доступ к MFA-защищённому бакету теряется безвозвратно — отключить MFA Delete без seed невозможно стандартными средствами.

### 3.3 Включение MFA Delete на бакете

```bash
# Получение текущего TOTP кода
oathtool -d6 --totp 492dedb20cf51d1405ef6a1316017e
# → 293651

# Включение MFA Delete + версионирование
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration '{
    "Status": "Enabled",
    "MfaDelete": "Enabled"
  }' \
  --mfa "my-mfa-device 293651" \
  --endpoint-url http://rgw:7480

# Проверка статуса
aws s3api get-bucket-versioning \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480

# → {"Status": "Enabled", "MfaDelete": "Enabled"}
```

**Почему это важно:** MFA Delete требует TOTP код для любого изменения версионирования. Без MFA кода нельзя отключить версионирование или удалить delete markers, что предотвращает саботаж через compromised credentials.

### 3.4 MFA-защищённые операции

```bash
# Удаление конкретной версии объекта (требует MFA)
aws s3api delete-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --version-id 3lLf9... \
  --mfa "my-mfa-device 293651" \
  --endpoint-url http://rgw:7480

# Без MFA кода операция завершится ошибкой:
# → An error occurred (AccessDenied) when calling the DeleteObject operation
```

### 3.5 Включение версионирования

Версионирование — первая линия защиты. При случайном DELETE предыдущие версии сохраняются.

```bash
# Включение версионирования на бакете
aws s3api put-bucket-versioning \
  --bucket my-app-prod-assets \
  --versioning-configuration Status=Enabled \
  --endpoint-url http://rgw:7480

# Проверка статуса
aws s3api get-bucket-versioning \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480

# → {"Status": "Enabled"}
```

### 3.6 Настройка Object Lock

Object Lock защищает объекты от удаления или перезаписи в течение заданного срока.

```bash
# Включение Object Lock при создании бакета
aws s3api create-bucket \
  --bucket my-app-prod-assets-locked \
  --object-lock-enabled-for-bucket \
  --endpoint-url http://rgw:7480 \
  --region us-east-1

# Настройка retention по умолчанию (30 дней, Compliance mode)
aws s3api put-object-lock-configuration \
  --bucket my-app-prod-assets-locked \
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
```

### 3.7 Legal Hold

Legal Hold — бессрочная защита объекта от удаления/изменения.

```bash
# Установка Legal Hold через S3 API
aws s3api put-object-legal-hold \
  --bucket my-app-prod-assets-locked \
  --key backups/etcd-snapshot.db \
  --legal-hold Status=ON \
  --endpoint-url http://rgw:7480

# Проверка Legal Hold
aws s3api get-object-legal-hold \
  --bucket my-app-prod-assets-locked \
  --key backups/etcd-snapshot.db \
  --endpoint-url http://rgw:7480

# → {"LegalHold": {"Status": "ON"}, "ResponseMetadata": {...}}
```

### 3.8 Восстановление после случайного удаления

```bash
# Список версий объекта (включая delete markers)
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/app.tar.gz \
  --endpoint-url http://rgw:7480 \
  --query 'Versions[*].[Key, VersionId, LastModified, IsLatest]' \
  --output table

# Проверка delete markers
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/app.tar.gz \
  --endpoint-url http://rgw:7480 \
  --query 'DeleteMarkers[*].[Key, VersionId, LastModified]' \
  --output table

# Восстановление предыдущей версии
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --copy-source "my-app-prod-assets/releases/app.tar.gz?versionId=3lLf9..." \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480
```

### 3.9 Access Logging

```bash
# Включение access logging через Ceph Dashboard или REST API
# Логи записываются в целевой бакет
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

### 3.10 radosgw-admin audit

```bash
# Просмотр операций через radosgw-admin
radosgw-admin user stats --uid="app-user"

# Проверка бакета
radosgw-admin bucket stats --bucket="my-app-prod-assets"

# Список клиентских подключений
radosgw-admin client list
```

---

## 4. Сценарии инцидентов

### 4.1 Сценарий: Accidental deletion

**Симптомы:**
- Объекты исчезли из бакета
- Access logs показывают DELETE запросы

**Диагностика:**
```bash
# 1. Проверка версий
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/ \
  --endpoint-url http://rgw:7480 \
  --query 'Versions[*].[Key, VersionId, LastModified]' \
  --output table

# 2. Проверка delete markers
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix releases/ \
  --endpoint-url http://rgw:7480 \
  --query 'DeleteMarkers[*].[Key, VersionId, LastModified]' \
  --output table

# 3. Проверка access logs
grep "DELETE.*my-app-prod-assets" /var/log/ceph/radosgw.*.log | tail -50
```

**Восстановление:**
```bash
# Восстановление через copy-object с versionId
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key releases/app.tar.gz \
  --copy-source "my-app-prod-assets/releases/app.tar.gz?versionId=3lLf9..." \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480
```

### 4.2 Сценарий: Compromised credentials

**Симптомы:**
- Access logs показывают необычные GET/PUT запросы
- Резкий рост размера бакета

**Немедленные действия:**
```bash
# 1. Отозвать compromised credentials
radosgw-admin user rm --uid="compromised-user" --purge-data

# 2. Проверить последние операции
grep "compromised-user\|suspicious-ip" /var/log/ceph/radosgw.*.log | awk '{print $1, $4}' | sort | uniq -c | sort -rn | head -20

# 3. Создать новые credentials
radosgw-admin user create --uid="app-user" --display-name="Application User"
```

### 4.3 Сценарий: Mass overwrite

**Симптомы:**
- Объекты имеют неожиданный размер или содержимое
- Access logs показывают массовые PUT запросы

**Диагностика:**
```bash
# Проверка версий для определения момента overwrite
aws s3api list-object-versions \
  --bucket my-app-prod-assets \
  --prefix data/ \
  --endpoint-url http://rgw:7480 \
  --query 'Versions[?IsLatest==`false`].[Key, VersionId, LastModified]' \
  --output table | head -20
```

**Восстановление:**
```bash
# Rollback через versioning
aws s3api copy-object \
  --bucket my-app-prod-assets \
  --key data/file.json \
  --copy-source "my-app-prod-assets/data/file.json?versionId=<good-version-id>" \
  --metadata-directive COPY \
  --endpoint-url http://rgw:7480
```

### 4.4 Сценарий: Lost MFA token

**Симптомы:**
- Нельзя отключить MFA Delete или изменить версионирование бакета
- Нельзя удалить старые delete markers для cleanup

**Диагностика:**
```bash
# Проверка токенов пользователя
radosgw-admin mfa list --uid=app-user

# Проверка статуса MFA Delete на бакете
aws s3api get-bucket-versioning \
  --bucket my-app-prod-assets \
  --endpoint-url http://rgw:7480
```

**Решение:**
- Если seed сохранён: перегенерируйте TOTP код и используйте для отключения MFA Delete
- Если seed утерян: требуется вмешательство Ceph admin для сброса MFA состояния бакета через cluster operations

---

## 5. Best Practices

1. **Включите версионирование** на всех production бакетах. Это базовая защита.
2. **Используйте Object Lock в Compliance mode** для критичных данных (бэкапы, compliance логи).
3. **Настройте MFA Delete** для бакетов с критичными данными, где требуется дополнительная защита от злоумышленного удаления.
4. **Сохраняйте TOTP seed** в защищённом месте (vault, sealed secret). Без seed MFA-защищённый бакет становится недоступным для управления.
5. **Настройте retention period** через `radosgw-admin` или S3 API.
6. **Включите access logging** на всех бакетах для audit.
7. **Настройте radosgw-admin audit** и экспортируйте логи в Loki/Elasticsearch.
8. **Используйте multisite репликацию** для DR. RPO = время синхронизации между зонами.
9. **Документируйте runbook'и** для каждого сценария восстановления.
10. **Регулярно тестируйте восстановление** из versioned объектов.
11. **Combine Object Lock + Versioning + MFA Delete + Multisite** для максимальной защиты.
12. **Для cross-tenant изоляции** используйте отдельных пользователей RGW с минимальными привилегиями.

---

## 6. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
