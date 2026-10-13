# Crossplane: Резервное копирование и Disaster Recovery control plane

**Актуально для:** Crossplane 1.18+ / 2.x, Velero 1.15+

## Определения

| Термин | Описание |
| :--- | :--- |
| **Control Plane Crossplane** | Кластер Kubernetes с установленным Crossplane Core, набором провайдеров и функций, выступающий централизованным координатором жизненного цикла инфраструктуры (Bare-Metal серверы, СХД, базы данных, виртуализация, внутренние сервисы). |
| **SSoT (Single Source of Truth) в DR** | Разделение источников правды: **Git** хранит целевое декларативное состояние (XRD, Composition, Claims, Providers), **etcd/Velero** сохраняют динамическое runtime-состояние (`external-name`, status-поля, UID, connection secrets), а **внешняя система** хранит физические данные. |
| **RPO (Recovery Point Objective)** | Максимально допустимый интервал потери метаданных управления инфраструктурой между последним снимком etcd/Velero и моментом аварии. |
| **RTO (Recovery Time Objective)** | Время, необходимое для развертывания нового control plane, восстановления CRD, провайдеров, импорта runtime-состояния и возобновления реконсиляции. |
| **Split-Brain (в Crossplane DR)** | Аварийное состояние, при котором два независимых control plane одновременно выполняют реконсиляцию одних и тех же внешних инфраструктурных ресурсов, вызывая конфликты параметров, флаппинг и разрушение конфигурации. |
| **Fencing (изоляция)** | Процедура принудительного отключения или изоляции сетевого доступа старого control plane к внешним инфраструктурным API перед активацией резервного кластера. |
| **Re-adoption (повторный захват)** | Процесс связывания восстановленных объектов Managed Resource (MR) с уже существующими внешними сущностями без попытки их повторного создания или перезаписи. |
| **`crossplane.io/external-name`** | Аннотация, однозначно идентифицирующая ресурс во внешней инфраструктуре. Ключевой маркер для бесконфликтного восстановления и исключения дублирования. |
| **`crossplane.io/paused`** | Аннотация (`"true"`), полностью останавливающая цикл сверки (reconciliation) контроллерами Crossplane для конкретного ресурса или группы ресурсов. |

---

## Архитектура и базовые концепции

### Структура состояния: что бэкапить и где оно живет

В отличие от классических приложений в Kubernetes, потеря control plane Crossplane не приводит к мгновенной остановке управляемой инфраструктуры (базы данных на Bare-Metal и виртуальные машины продолжают работать). Однако теряется способность управлять этой инфраструктурой, а некорректное восстановление может привести к удалению работающих систем.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Источники состояния                             │
├──────────────────────────┬─────────────────────────┬───────────────────┤
│    Git (Декларации)      │      etcd / Velero      │ Внешние системы   │
│  (Холодное/Желаемое)     │   (Runtime-состояние)   │ (Фактическое)     │
├──────────────────────────┼─────────────────────────┼───────────────────┤
│ • XRD и Composition      │ • UID и ResourceVersion │ • Базы данных     │
│ • Provider / Function    │ • crossplane.io/        │ • Сетевые фабрики │
│ • Claims и спецификации  │   external-name         │ • Дисковые LUN    │
│ • GitOps-конфигурация    │ • status.atProvider     │ • Гипервизоры     │
│ • ProviderConfig (шаблон)│ • Connection Secrets    │ • K8s-воркеры     │
└──────────────────────────┴─────────────────────────┴───────────────────┘
```

1. **Декларативный слой (Git):** Содержит манифесты определений типов и композиций. При «холодном старте» без сохранения etcd применение манифестов из Git приведет к генерации новых имен ресурсов, если `external-name` не был явно зафиксирован.
2. **Runtime-слой (etcd / Velero):** Содержит связки между ресурсами Kubernetes и внешними идентификаторами, сгенерированные учетные записи (connection secrets), токены и системные финалайзеры (`finalizers: [finalizer.managedresource.crossplane.io]`).
3. **Физический слой (Инфраструктура):** Сами целевые объекты. Crossplane не хранит данные внутри себя, он управляет состоянием конфигураций через внешние API.

### Риски и механизмы защиты при катастрофах

#### 1. Каскадное удаление (Cascading Deletion)
По умолчанию во многих ресурсах Crossplane параметр `spec.deletionPolicy` равен `Delete`. Если при аварии или миграции администратор удалит namespace или манифест MR из кластера, контроллер отправит вызов на удаление физического ресурса во внешней системе.
* **Защита:** Для всей критической инфраструктуры обязательна политика `spec.deletionPolicy: Orphan`. При удалении объекта из Kubernetes внешняя сущность остается нетронутой.

#### 2. Рассинхронизация при восстановлении (Reconciliation Race)
Если при восстановлении из резервной копии контроллеры Crossplane стартуют раньше, чем развернуты секреты `ProviderConfig` или зарегистрированы все CRD провайдеров, контроллеры перейдут в состояние ошибки (`Synced=False`), а зависимые ресурсы могут начать перезапрашивать создание сущностей.
* **Защита:** Заморозка цикла сверки аннотацией `crossplane.io/paused: "true"` на время импорта метаданных.

#### 3. Split-Brain и необходимость Fencing
Если исходный кластер потерял сетевую связность, но физически продолжает работать, подъем резервного кластера приведет к тому, что два контроллера будут слать противоречивые команды в одни и те же внешние API (например, менять сетевые маршруты или конфигурации СУБД).
* **Защита:** Обязательный административный барьер (Fencing): отзыв токенов доступа, изоляция сетевого периметра старого кластера перед снятием паузы на новом.

---

## Практические сценарии и конфигурация

### Сценарий 1: Резервное копирование через Velero в локальное S3-хранилище (MinIO/Ceph RGW)

Для резервного копирования control plane используется Velero с S3-совместимым хранилищем в закрытом контуре. 

#### Конфигурация локального BackupStorageLocation
```yaml
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: onprem-minio-bsp
  namespace: velero
spec:
  provider: aws
  objectStorage:
    bucket: k8s-crossplane-backups
    prefix: control-plane-main
  config:
    region: minio
    s3ForcePathStyle: "true"
    s3Url: http://minio.storage.internal:9000
    publicUrl: http://minio.storage.internal:9000
  credential:
    name: minio-credentials
    key: cloud
```

#### Манифест регулярного бэкапа по расписанию (Schedule)
Бэкап разделяется на инфраструктурные CRD, системный namespace Crossplane и прикладные пространства имен с клеймами:

```yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: crossplane-daily-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    ttl: 720h0m0s # 30 дней
    includedNamespaces:
      - crossplane-system
      - infrastructure-claims
      - tenant-prod
    includedClusterScopedResources:
      - customresourcedefinitions.apiextensions.k8s.io
      - providers.pkg.crossplane.io
      - configurations.pkg.crossplane.io
      - functions.pkg.crossplane.io
      - compositeresourcedefinitions.apiextensions.crossplane.io
      - compositions.apiextensions.crossplane.io
      - clusterproviderconfigs.kubernetes.m.crossplane.io
    excludedResources:
      - events
      - events.events.k8s.io
      - leases.coordination.k8s.io
    snapshotVolumes: false
```

---

### Сценарий 2: Низкоуровневый snapshot etcd (Bare-Metal инсталляция)

В self-hosted кластерах Kubernetes на физических серверах создание снимка etcd гарантирует сохранение всех транзакций и связей объектов без искажений.

```bash
# Создание консистентного снимка на мастере etcd
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  snapshot save /var/backups/etcd/crossplane-etcd-$(date +%Y%m%d_%H%M%S).db

# Проверка целостности созданного файла снимка
ETCDCTL_API=3 etcdctl --write-out=table snapshot status /var/backups/etcd/crossplane-etcd-$(date +%Y%m%d_%H%M%S).db
```

При аварийном восстановлении снимка на новом узле:

```bash
# Остановка kube-apiserver перед восстановлением etcd
systemctl stop kubelet
docker stop $(docker ps -q --filter name=k8s_kube-apiserver) 2>/dev/null || true

# Восстановление базы etcd в новый рабочий каталог
ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd/crossplane-etcd-latest.db \
  --data-dir=/var/lib/etcd-restored \
  --name=master-01 \
  --initial-cluster=master-01=https://192.168.10.11:2380 \
  --initial-cluster-token=etcd-dr-token \
  --initial-advertise-peer-urls=https://192.168.10.11:2380

# Переключение пути etcd и запуск kubelet
mv /var/lib/etcd /var/lib/etcd-broken
mv /var/lib/etcd-restored /var/lib/etcd
systemctl start kubelet
```

---

### Сценарий 3: Пошаговый Disaster Recovery Runbook (Восстановление кластера)

При полной потере основного кластера развертывание резервного control plane выполняется по строгой схеме.

```text
[Фаза 0: Fencing] ──▶ Отзыв токенов / изоляция старого кластера
         │
[Фаза 1: Bootstrap] ─▶ Подъем K8s, GitOps-оператора и Secret Management (Vault/ESO)
         │
[Фаза 2: Providers] ─▶ Установка Provider-пакетов и ожидание готовности CRD
         │
[Фаза 3: Restore] ───▶ Импорт MR с аннотацией crossplane.io/paused="true"
         │
[Фаза 4: Verify] ────▶ Аудит external-name и ProviderConfig
         │
[Фаза 5: Unpause] ───▶ Поэтапное снятие паузы и запуск реконсиляции
```

#### Пошаговые действия администратора:

1. **Fencing (Изоляция аварийного кластера):**
   * Отозвать API-ключи и сервисные учетные записи, которые использовались на старом кластере, либо изолировать сеть старого кластера.
   * Сгенерировать новые учетные данные с идентичными правами для нового control plane.

2. **Базовый Bootstrap:**
   * Развернуть чистый кластер Kubernetes.
   * Установить оператор управления секретами (External Secrets Operator или HashiCorp Vault Agent) и доставить `ProviderConfig`-секреты.
   * Установить базовый Crossplane Core через Helm или GitOps (Argo CD / Flux).

3. **Установка пакетов (CRD & Providers):**
   * Применить определения `Provider`, `Configuration`, `Function` из Git.
   * Дождаться перехода провайдеров в состояние `HEALTHY=True`:
     ```bash
     kubectl wait --for=condition=Healthy provider.pkg.crossplane.io --all --timeout=300s
     ```

4. **Восстановление состояния через Velero с паузой реконсиляции:**
   * Перед разблокировкой контроллеров восстановить ресурсы из бэкапа:
     ```bash
     velero restore create restore-cp-dr \
       --from-backup crossplane-daily-backup-20261013 \
       --include-namespaces infrastructure-claims,tenant-prod \
       --wait
     ```
   * Сразу заморозить сверку всех Managed Resources, чтобы избежать лавинообразных запросов:
     ```bash
     kubectl annotate managed --all crossplane.io/paused="true" --overwrite
     ```

5. **Проверка привязки (Adoption Check):**
   * Убедиться, что аннотация `crossplane.io/external-name` присутствует на всех объектах и указывает на существующие физические серверы/БД.
   * Проверить валидность `spec.providerConfigRef`.

6. **Поэтапное снятие паузы (Controlled Unpause):**
   * Снять паузу сначала с одиночного тестового ресурса:
     ```bash
     kubectl annotate managed <test-resource-name> crossplane.io/paused-
     ```
   * Проверить логи провайдера: убедиться, что контроллер выполнил только `Observe` и перевел ресурс в `Synced=True, Ready=True` без пересоздания.
   * Снять паузу со всех оставшихся ресурсов:
     ```bash
     kubectl annotate managed --all crossplane.io/paused-
     ```

---

### Сценарий 4: Безопасный захват (Adopt) инфраструктуры через Management Policies

В ситуациях, когда runtime-состояние etcd утеряно полностью, а восстановление ведется исключительно из Git, Crossplane попытается создать ресурсы заново. Для предотвращения сбоя используется механизм `managementPolicies` (Crossplane 1.15+ / 2.x).

#### Манифест безопасного импорта существующего ресурса
```yaml
apiVersion: postgresql.sql.m.crossplane.io/v1alpha1
kind: Database
metadata:
  name: internal-billing-db
  annotations:
    # Явное указание существующего имени сущности в СУБД
    crossplane.io/external-name: "billing_prod"
spec:
  # Режим наблюдения: Crossplane проверяет ресурс, но не может изменить или удалить его
  managementPolicies: ["Observe"]
  deletionPolicy: Orphan
  forProvider:
    encoding: "UTF8"
  providerConfigRef:
    name: onprem-postgres-infra
```

После того как ресурс перейдет в статус `Synced=True`, политика меняется на полную `["*"]` или `["Create", "Update", "Observe"]`.

---

## Операции и команды

### Инспекция и верификация состояния

Команда проверки статуса Managed Resources с отображением внешних идентификаторов:

```bash
kubectl get managed -o custom-columns=\
NAME:.metadata.name,\
KIND:.kind,\
EXTERNAL-NAME:.metadata.annotations['crossplane\.io/external-name'],\
PAUSED:.metadata.annotations['crossplane\.io/paused'],\
SYNCED:.status.conditions[?(@.type=="Synced")].status,\
READY:.status.conditions[?(@.type=="Ready")].status
```
```text
# → result
NAME                    KIND       EXTERNAL-NAME      PAUSED   SYNCED   READY
prod-storage-bucket     Bucket     corp-storage-01    <none>   True     True
internal-pg-cluster     Database   pg-cluster-prod    <none>   True     True
edge-network-vlan       Vlan       vlan-104           true     True     True
```

### Экстренная заморозка и разморозка реконсиляции

```bash
# Массовая установка паузы на все Managed Resources в кластере
kubectl annotate managed --all crossplane.io/paused=true --overwrite
# → result: managed.pkg.crossplane.io annotated

# Массовая установка паузы на все Composite Resources (XR)
kubectl annotate composite --all crossplane.io/paused=true --overwrite
# → result: composite.apiextensions.crossplane.io annotated

# Снятие паузы после завершения аварийных работ
kubectl annotate managed --all crossplane.io/paused-
# → result: managed.pkg.crossplane.io/prod-storage-bucket annotation "crossplane.io/paused" removed
```

### Операции Velero для Crossplane

```bash
# Создание внеочередного бэкапа перед плановыми работами
velero backup create pre-maintenance-cp \
  --include-namespaces crossplane-system,infrastructure-claims \
  --include-cluster-resources=true
# → result: Backup request "pre-maintenance-cp" submitted successfully.

# Проверка прогресса и статуса завершения
velero backup describe pre-maintenance-cp --details
# → result: Phase: Completed | Errors: 0 | Warnings: 0

# Запуск восстановления из резервной копии
velero restore create --from-backup pre-maintenance-cp --wait
# → result: Restore completed: 48 objects restored, 0 errors, 0 warnings
```

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `cannot create external resource: already exists` | Ресурс восстанавливается из Git без аннотации `crossplane.io/external-name`. Провайдер генерирует случайный ID и пытается создать объект заново. | `kubectl describe <kind> <name>` (раздел `Events`) | Добавить аннотацию `crossplane.io/external-name` с реальным именем сущности и установить `managementPolicies: ["Observe"]`. |
| `Resource is paused` в статусе, сверка не происходит | Установлена защитная аннотация `crossplane.io/paused: "true"`. | `kubectl get <kind> <name> -o yaml \| grep paused` | Удалить аннотацию: `kubectl annotate <kind> <name> crossplane.io/paused-`. |
| `cannot resolve ProviderConfig: Secret not found` | Секреты с креденшелами провайдера не были восстановлены до запуска контроллеров. | `kubectl get providerconfig -o wide`, логи пода в `crossplane-system` | Восстановить Secret через менеджер секретов (Vault/ESO) или применить из защищенной копии; проверить имя в `spec.credentials.secretRef`. |
| Зависание удаления объекта в `Terminating` | На объекте висит финалайзер `finalizer.managedresource.crossplane.io`, а провайдер недоступен или учетные данные невалидны. | `kubectl get <kind> <name> -o jsonpath='{.metadata.finalizers}'` | Проверить сетевой доступ к целевой системе. В крайнем случае аварийного удаления: `kubectl patch <kind> <name> -p '{"metadata":{"finalizers":[]}}' --type=merge`. |
| Flapping конфигурации между двумя кластерами | Split-Brain: оба кластера (аварийный и новый) одновременно ведут реконсиляцию одного ресурса с разными параметрами. | Логи провайдеров в обоих кластерах; аудит изменений в целевой системе. | Провести немедленный Fencing старого кластера (погасить контроллеры: `kubectl scale deploy -n crossplane-system --replicas=0 --all`). |
| `CRD not established` при импорте через Velero | Гонка компонентов: Velero пытается восстановить инстансы MR до того, как API-сервер зарегистрировал CRD от провайдеров. | `kubectl get crd \| grep crossplane` | Восстанавливать пакеты провайдеров отдельным этапом; дождаться `Healthy=True` у объектов `Provider` перед накатом MR. |

---

## Лучшие практики (SRE и Platform Ops)

1. **`deletionPolicy: Orphan` по умолчанию:**
   В шаблонах Composition для всех критических физических ресурсов всегда фиксируйте `deletionPolicy: Orphan`. Политика `Delete` допустима только для временных и эфемерных сред (dev, preview).
2. **Фиксация детерминированных имен:**
   Избегайте случайной генерации имен физических сущностей (`generateName`). Задавайте `crossplane.io/external-name` явно через функции композиции (например, на основе имени Claim и Namespace). Это позволяет восстановить связь с инфраструктурой даже при «чистом» старте из Git.
3. **Хранение секретов вне etcd:**
   Учетные записи подключения к инфраструктуре не должны жить исключительно в etcd. Используйте External Secrets Operator в связке с внешним отказоустойчивым хранилищем (HashiCorp Vault). Это устраняет зависимость восстановления Crossplane от бэкапа секретов K8s.
4. **Регулярные учения Disaster Recovery (GameDays):**
   Не реже одного раза в квартал тестируйте восстановление control plane на изолированном кластере без сетевого доступа к продуктовой инфраструктуре (с замороженной реконсиляцией `paused=true`), проверяя корректность считывания метаданных и отсутствие попыток деструктивных действий.
5. **Мониторинг метрик паузы и рассинхронизации:**
   Настройте алертинг в Prometheus на метрику `crossplane_managed_resource_exists` и наличие ресурсов со статусом `Synced=False` дольше 15 минут, а также на наличие забытых ресурсов с `crossplane.io/paused=true`.

---

## Дополнительная информация

* [Disaster Recovery: концепции и паттерны](../../Concepts/disaster_recovery.md) — уровни RPO/RTO, стратегии холодного и горячего резервирования.
* [etcd: кластеризация и восстановление](../../etcd/clustering_and_recovery.md) — регламенты работы с кворумом Raft и восстановление снимков etcd.
* [Резервное копирование и восстановление в Linux](../../Linux/SystemAdministration/backup_and_recovery.md) — системные принципы консистентности и ротации копий.
* [Velero: обзор и архитектура](../../Kubernetes/ToolsUtilities/velero-overview.md) — детальная настройка плагинов, BSL и механизмов Data Mover.
* [Crossplane: обзор архитектуры](./overview.md) — базовые сущности (XRD, Composition, MR).
* [Crossplane: интеграция с GitOps](./gitops_integration.md) — двухконтурная модель сверки Git и runtime.
* [Crossplane: защита зависимостей (Usage)](./usage_protection.md) — блокировка случайного удаления связанных ресурсов.
* [Crossplane: обновление и миграция](./upgrade_migration.md) — версионирование пакетов и откат ревизий.
* [Crossplane: управление ресурсами Kubernetes](./provider_kubernetes_setup.md) — управление нативными объектами кластера через `provider-kubernetes`.
