# Argo CD: Удаление, каскадное удаление и очистка ресурсов

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

---

## Определения

**Prune (Обрезка / удаление устаревших ресурсов)** — механизм контроллера Argo CD, удаляющий из целевого кластера Kubernetes те управляемые ресурсы, манифесты которых были удалены из Git-репозитория или перестали подпадать под условия рендеринга. Активируется опцией `syncPolicy.automated.prune: true` или CLI-флагом `--prune`.

**PruneLast (Отложенная обрезка)** — sync option (`PruneLast=true`), предписывающий контроллеру выполнять удаление устаревших объектов строго на финальной фазе синка — только после того, как все новые и обновленные ресурсы успешно применены и перешли в статус `Healthy`. Гарантирует zero-downtime при замене взаимоисключающих компонентов.

**Cascading Deletion (Каскадное удаление)** — процесс удаления сущности (например, объекта `Application` или родительского контроллера) вместе со всеми управляемыми или дочерними объектами в кластере Kubernetes. Управляется финализатором `resources-finalizer.argocd.argoproj.io` и стандартным механизмом Kubernetes Garbage Collector.

**Orphaning (Осиротение ресурсов)** — сохранение физических ресурсов в кластере при удалении управляющего объекта `Application` (выполняется флагом `--no-cascade` или при отсутствии финализатора). Ресурсы продолжают функционировать, но перестают отслеживаться контроллером Argo CD.

**Propagation Policy (Политика распространения удаления)** — параметр Kubernetes API (`foreground`, `background`, `orphan`), определяющий временной порядок и зависимость при удалении дочерних объектов (содержащих `metadata.ownerReferences` с полем `blockOwnerDeletion: true`):
- `foreground` — владелец переводится в статус удаления (`deletionTimestamp`), но физически не удаляется из etcd до тех пор, пока полностью не удалятся все дочерние зависимые ресурсы (по умолчанию в Argo CD).
- `background` — объект-владелец удаляется немедленно, а его дочерние объекты удаляются фоновым сборщиком мусора `kube-controller-manager` асинхронно.
- `orphan` — объект-владелец удаляется, а его дочерние объекты остаются в кластере, теряя ссылку на владельца.

**Finalizer (Финализатор)** — массив строк в `metadata.finalizers` ресурса Kubernetes, блокирующий физическое удаление объекта из etcd до тех пор, пока ответственный контроллер не завершит сервисные операции очистки и не удалит свою запись из массива.

**`resources-finalizer.argocd.argoproj.io`** — ключевой финализатор Argo CD, устанавливаемый на кастомные ресурсы `Application` и `AppProject`. При удалении `Application` гарантирует, что контроллер сначала каскадно удалит все связанные нагрузки в кластере, и лишь затем удалит сам CR `Application`. При установке на `AppProject` запрещает удаление проекта, пока в кластере существует хотя бы одно привязанное к нему приложение.

**PreDelete Hook** — (доступен с версии Argo CD v3.3+) хук жизненного цикла (`argocd.argoproj.io/hook: PreDelete`), запускаемый перед началом удаления управляемых ресурсов при деструкции всего приложения `Application`. Применяется для создания финальных снапшотов баз данных, дренажа трафика и graceful shutdown.

**PostDelete Hook** — (доступен с версии Argo CD v2.10+) хук жизненного цикла (`argocd.argoproj.io/hook: PostDelete`), выполняемый строго после успешного завершения удаления всех управляемых ресурсов приложения. Применяется для очистки внешних учетных записей, DNS-записей в локальных DNS-серверах (CoreDNS, BIND, PowerDNS) и снятия блокировок.

**Orphaned Resources Monitoring** — механизм инспекции пространства имен на уровне `AppProject` (`spec.orphanedResources`), выявляющий ресурсы, находящиеся в целевом namespace, но не принадлежащие ни одному зарегистрированному приложению Argo CD.

---

## Базовые концепции и архитектура

### Архитектура процесса удаления в Argo CD

Удаление ресурсов в инфраструктуре под управлением Argo CD разделяется на два принципиально разных уровня:
1. **Удаление отдельных ресурсов внутри активного приложения (Prune):** Git-репозиторий обновляется, файл удаляется, контроллер сравнивает желаемое состояние (desired state) с реальным состоянием кластера (live state) и посылает вызовы `DELETE` в Kubernetes API для лишних объектов.
2. **Удаление объекта `Application` целиком (Application Deletion):** пользователь или автоматизация удаляет сам кастомный ресурс приложения. Дальнейшая судьба развернутых в кластере подов, сервисов, секретов и томов зависит от наличия финализатора и флагов каскадности.

```text
                                  +---------------------------------------+
                                  | Пользователь / CI/CD Pipeline         |
                                  +---------------------------------------+
                                       |                             |
                       git rm resource.yaml             argocd app delete my-app
                                       |                             |
                                       v                             v
                        +----------------------------+   +----------------------------+
                        |  GitOps Sync Reconciliation|   | Проверка Finalizers на CR  |
                        +----------------------------+   +----------------------------+
                                       |                               |
                         Опция `automated.prune`?                      |
                        /                      \                       |
                     ДА                         НЕТ                    |
                     /                            \                    |
        +-----------------------+     +--------------------+           |
        | Проверка аннотации    |     | Ресурс остается    |           |
        | `Prune=false`?        |     | в OutOfSync        |           |
        +-----------------------+     +--------------------+           |
         /                     \                                       |
       НЕТ                     ДА                                      |
       /                         \                                     |
+--------------------+   +--------------------+                        |
| DELETE через K8s   |   | Ресурс не удаляется|                        |
| API (Prune/Last)   |   | (Сохраняется)      |                        |
+--------------------+   +--------------------+                        |
                                                                       |
                 +-----------------------------------------------------+
                 |
                 v
   +------------------------------------------+
   | Наличие resources-finalizer на Application|
   +------------------------------------------+
          /                                \
       ПРИСУТСТВУЕТ                     ОТСУТСТВУЕТ (или флаг --no-cascade)
       /                                    \
+------------------------------------+   +------------------------------------+
| 1. Запуск PreDelete хуков (v3.3+)  |   | 1. Контроллер снимает финализатор  |
| 2. Удаление управляемых ресурсов   |   |    (если был)                      |
|    согласно PropagationPolicy      |   | 2. CR Application удаляется        |
| 3. Запуск PostDelete хуков (v2.10+)|   | 3. Нагрузки в кластере ОСТАЮТСЯ    |
| 4. Снятие финализатора с Application|   |    (Orphaned / потеря контроля)    |
| 5. CR Application удаляется из K8s |   +------------------------------------+
+------------------------------------+
```

---

### Механика Prune при GitOps-синхронизации

Когда манифест удаляется из Git, Argo CD в ходе очередного цикла reconciler обнаруживает, что в кластере присутствует ресурс, помеченный tracking-идентификатором приложения (через annotation `argocd.argoproj.io/tracking-id` или label `app.kubernetes.io/instance`), но отсутствующий в целевом дереве манифестов.

1. Если `prune: false` (по умолчанию в ручном режиме): ресурс помечается статусом `OutOfSync` с пометкой `RequiresPruning`. Физическое удаление не происходит.
2. Если `prune: true`: контроллер формирует операцию удаления.
3. Порядок выполнения Prune:
   - **Обычный Prune (без PruneLast):** устаревшие ресурсы удаляются параллельно с применением новых манифестов (Wave 0). Если новый сервис зависит от ресурсов старого, возможен кратковременный отказ обслуживания.
   - **PruneLast (`PruneLast=true`):** контроллер откладывает удаление устаревших объектов до тех пор, пока все обновленные объекты не достигнут статуса `Healthy`. Это предотвращает ситуацию, когда старый `Deployment` уже удален, а новый не может запуститься из-за `ImagePullBackOff`.

---

### Каскадное удаление (Cascading Deletion) и Propagation Policy

При удалении сущностей в Kubernetes задействуются два механизма каскадности:
1. **Уровень Argo CD:** контроллер Argo CD считывает инвентарь ресурсов, привязанных к `Application`, и отправляет вызовы `DELETE` для каждого из них.
2. **Уровень Kubernetes API Server & Kube-Controller-Manager:** когда удаляется родительский ресурс (например, `Deployment` или `StatefulSet`), Kubernetes Garbage Collector обрабатывает дочерние объекты (`ReplicaSet`, `Pod`, `PVC`) на основе поля `metadata.ownerReferences`.

#### Режимы Propagation Policy

| Режим | Поведение контроллера Argo CD | Поведение Kubernetes Garbage Collector | Сценарий применения в Production |
| :--- | :--- | :--- | :--- |
| **`foreground`** *(по умолчанию)* | Ожидает полного подтверждения удаления каждого зависимого ресурса перед снятием финализатора приложения. | Устанавливает финализатор `foregroundDeletion` на родительский объект; удаляет дочерние ресурсы (`Pods`, `ReplicaSets`) **до** удаления родителя. | Стандарт для production. Гарантирует упорядоченный graceful shutdown и отсутствие брошенных подов. |
| **`background`** | Отправляет запросы на удаление родительских объектов и не блокирует процесс ожидания их дочерних элементов. | Родительский объект удаляется немедленно; сборщик мусора очищает дочерние объекты в фоновом режиме. | Быстрое удаление некритичных dev-окружений, когда не требуется строгая последовательность. |
| **`orphan`** | Удаляет только конфигурацию родителя или управляющего объекта, оставляя дочерние ресурсы нетронутыми. | Снимает `ownerReferences` с дочерних объектов; поды и диски продолжают функционировать в кластере без родителя. | Экстренная миграция, сохранение хранилищ (`PersistentVolumeClaim`) при пересоздании чартов. |

---

### Жизненный цикл финализатора `resources-finalizer`

Финализатор `resources-finalizer.argocd.argoproj.io` гарантирует целостность жизненного цикла:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-api
  namespace: argocd
  finalizers:
    # Защищает кластер от сиротских ресурсов при удалении CR
    - resources-finalizer.argocd.argoproj.io
```

1. **Инициализация:** финализатор добавляется автоматически при создании приложения через CLI (`argocd app create`) или веб-интерфейс. Если манифест подается через raw `kubectl apply`, финализатор должен быть явно объявлен в секции `metadata.finalizers`.
2. **Инициация удаления:** при выполнении `kubectl delete app billing-api -n argocd` API-сервер проставляет полю `metadata.deletionTimestamp` текущее время.
3. **Обработка контроллером:**
   - Reconciler видит непустой `deletionTimestamp` и наличие финализатора.
   - Запускаются `PreDelete` хуки (если объявлены). Контроллер ожидает их завершения в статусе `Healthy`.
   - Контроллер выполняет итеративное удаление всех managed ресурсов в кластере с учетом заданной политики `PrunePropagationPolicy`.
   - Запускаются `PostDelete` хуки (если объявлены). Контроллер ожидает их успешного завершения.
   - Контроллер очищает массив `metadata.finalizers`, удаляя запись `resources-finalizer.argocd.argoproj.io`.
4. **Физическое удаление:** Kubernetes API-сервер удаляет запись об `Application` из etcd.

---

### Хуки удаления: PreDelete (v3.3+) и PostDelete (v2.10+)

Хуки удаления выполняются **только** при полном удалении кастомного ресурса `Application` (через `argocd app delete` или `kubectl delete app`). При обычной GitOps-синхронизации (даже если срабатывает Prune отдельных объектов) хуки `PreDelete` и `PostDelete` **не вызываются**.

```text
Запрос на удаление Application
               │
               ▼
   [Фаза PreDelete Hooks] ──(сбой)──> Application зависает с DeletionError
               │ (успех)
               ▼
[Удаление Managed Ресурсов] ──(блок)──> Ожидание завершения Terminating (PDB/Graceful)
               │ (успех)
               ▼
  [Фаза PostDelete Hooks] ──(сбой)──> Application зависает с DeletionError
               │ (успех)
               ▼
  Снятие resources-finalizer
               │
               ▼
  Удаление Application из etcd
```

Особенности поведения хуков:
- **Политика удаления хуков:** управляется аннотацией `argocd.argoproj.io/hook-delete-policy`. Рекомендуется задавать комбинацию `BeforeHookCreation,HookSucceeded`, чтобы хук удалялся при повторных попытках или после успешного выполнения.
- **Отказоустойчивость:** если хук `PreDelete` или `PostDelete` завершается с ошибкой (`Failed`) или зависает по таймауту, контроллер переводит `Application` в состояние ошибки удаления (`DeletionError`) и **не снимает финализатор**. Это предотвращает потерю данных при сбое скрипта резервного копирования.

---

### Аннотации точечного управления Pruning на уровне ресурсов

Помимо глобальных настроек приложения, Argo CD предоставляет аннотации для тонкой настройки удаления индивидуальных манифестов:

| Аннотация / Опция | Допустимые значения | Поведение |
| :--- | :--- | :--- |
| `argocd.argoproj.io/sync-options` | `Prune=false` | Запрещает удаление данного ресурса при Git-синхронизации (Prune), даже если файл удален из репозитория. |
| `argocd.argoproj.io/sync-options` | `Prune=confirm` | Требует явного подтверждения оператором (через UI/CLI или простановку аннотации одобрения) перед удалением ресурса при Prune. |
| `argocd.argoproj.io/sync-options` | `Delete=false` | Запрещает удаление данного ресурса при полном удалении всего объекта `Application`. Ресурс остается в кластере. |
| `argocd.argoproj.io/sync-options` | `Delete=confirm` | Запрещает удаление ресурса при деструкции приложения без ручного подтверждения. |
| `argocd.argoproj.io/sync-options` | `PrunePropagationPolicy=orphan` | Локально переопределяет политику каскадности для конкретного манифеста (например, для сохранения PVC при удалении StatefulSet). |

---

## Практические сценарии и конфигурация

### Сценарий 1: Production GitOps Prune с защитой от простоев

**Контекст:** Продакшн-сервис `order-backend` развернут на On-Premise кластере. Необходимо настроить автоматическое удаление устаревших манифестов из кластера при их удалении из ветки `main`, но гарантировать, что старые реплики и сервисы не удалятся раньше, чем новые поды пройдут readiness-пробы.

#### Манифест Application с безопасным Pruning

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: order-backend
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: git@gitlab.internal.corp:ecommerce/manifests.git
    targetRevision: main
    path: environments/production/order-backend
  destination:
    server: https://kubernetes.default.svc
    namespace: ecommerce-prod
  syncPolicy:
    automated:
      prune: true        # Удалять ресурсы, отсутствующие в Git
      selfHeal: true     # Восстанавливать изменения, сделанные мимо Git
      allowEmpty: false  # ЗАЩИТА: запрещает удалять всё приложение при пустом репозитории
    syncOptions:
      - CreateNamespace=false
      - PruneLast=true                   # Удалять устаревшие ресурсы строго ПОСЛЕ старта новых
      - PrunePropagationPolicy=foreground # Каскадное ожидание зависимостей
      - ServerSideApply=true
```

#### Проверка работы в GitOps-пайплайне

```bash
# 1. Удаление устаревшего виртуального сервиса или конфигмапа из Git
git rm environments/production/order-backend/configmap-deprecated.yaml
git commit -m "refactor(order): remove legacy configmap"
git push origin main

# 2. Проверка статуса синхронизации через CLI
argocd app get order-backend --refresh
# → GROUP  KIND       NAMESPACE       NAME                  STATUS     HEALTH   HOOK  MESSAGE
# →        ConfigMap  ecommerce-prod  configmap-deprecated  OutOfSync  Healthy        requires pruning

# 3. Контроллер автоматически применяет изменения:
# - Применяются обновленные манифесты (Wave 0)
# - Ожидается статус Healthy для новых подов
# - На финальном шаге удаляется configmap-deprecated
```

---

### Сценарий 2: Защита критических ресурсов от случайного Prune

**Контекст:** В составе приложения деплоятся `Secret` со статическими сертификатами и `CustomResourceDefinition` внутреннего оператора. Требуется защитить их от удаления, даже если разработчик случайно удалит файл из Git-репозитория или ошибется в ветке.

#### Аннотирование манифестов для блокировки удаления

```yaml
# config/pki-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: internal-ca-certs
  namespace: ecommerce-prod
  annotations:
    # Запрещает удаление ресурса как при sync prune, так и при удалении всего Application
    argocd.argoproj.io/sync-options: Prune=false,Delete=false
type: Opaque
data:
  ca.crt: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0t...
---
# crds/queue-crd.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: messagequeues.infra.internal.corp
  annotations:
    # Запрещает удаление CRD через Prune — удаление CRD привело бы к сносу всех экземпляров очередей в кластере!
    argocd.argoproj.io/sync-options: Prune=false
spec:
  group: infra.internal.corp
  names:
    kind: MessageQueue
    plural: messagequeues
  scope: Namespaced
  versions:
    - name: v1
      served: true
      storage: true
```

#### Валидация защиты

```bash
# Тест: удаление файла из Git и запуск sync
git rm config/pki-secret.yaml && git commit -m "accidental delete" && git push
argocd app sync order-backend --prune

# Результат: ресурс остается в кластере, синк завершается успехом
kubectl get secret internal-ca-certs -n ecommerce-prod
# → NAME                TYPE     DATA   AGE
# → internal-ca-certs   Opaque   1      45d
```

---

### Сценарий 3: Защита хранилищ Ceph/Local-PV при удалении StatefulSet

**Контекст:** В on-premise кластере развернут `StatefulSet` PostgreSQL с локальными томами (Local Persistent Volumes) или блочными устройствами Ceph RBD (`StorageClass: ceph-block-replicated`). При пересоздании приложения или изменении топологии базы данных данные в `PersistentVolumeClaim` должны сохраниться в обязательном порядке.

#### Конфигурация Application с Orphaning для томов

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-ha
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: databases
  source:
    repoURL: git@gitlab.internal.corp:infra/db-charts.git
    targetRevision: v1.4.2
    path: charts/postgresql
  destination:
    server: https://kubernetes.default.svc
    namespace: database-prod
  syncPolicy:
    automated:
      prune: true
    syncOptions:
      # Запрещает каскадное удаление зависимых дисков при удалении StatefulSet
      - PrunePropagationPolicy=orphan
```

#### Защита PVC на уровне аннотаций в StatefullSet VolumeClaimTemplate

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg-cluster
  namespace: database-prod
spec:
  serviceName: pg-cluster-headless
  replicas: 3
  template:
    metadata:
      labels:
        app: pg-cluster
    spec:
      containers:
        - name: postgres
          image: postgres:16.4-alpine
  volumeClaimTemplates:
    - metadata:
        name: pgdata
        annotations:
          # Запрещает удаление PVC при любом типе очистки Argo CD
          argocd.argoproj.io/sync-options: Delete=false,Prune=false
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: ceph-block-replicated
        resources:
          requests:
            storage: 200Gi
```

#### Проверка сохранения дисков при сносе приложения

```bash
# Удаление приложения с флагом каскада
argocd app delete postgres-ha --cascade --yes
# → Application 'postgres-ha' deleted

# Проверка физического наличия PVC и связанных PV в кластере
kubectl get pvc -n database-prod
# → NAME               STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS            AGE
# → pgdata-pg-cluster-0 Bound    pvc-11e2f89c-4f81-42ab-9d0a-9bc501e52b21   200Gi      RWO            ceph-block-replicated   62d
# → pgdata-pg-cluster-1 Bound    pvc-22e3f89d-5f82-43bc-8e1b-0cd602e63c32   200Gi      RWO            ceph-block-replicated   62d
```

---

### Сценарий 4: PreDelete и PostDelete хуки в On-Premise окружении

**Контекст:** При выводе сервиса из эксплуатации необходимо гарантировать выполнение регламентных процедур:
1. `PreDelete`: снять нагрузку в балансировщике BGP/Keepalived, сделать дамп схемы базы данных и сохранить в локальное хранилище бэкапов MinIO.
2. Контроллер удаляет все поды и службы.
3. `PostDelete`: отозвать внутренние TLS-сертификаты в HashiCorp Vault, удалить DNS-запись в локальном PowerDNS и отправить алерт в инженерный канал Mattermost.

#### Манифест PreDelete Hook (Дамп БД перед удалением)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: pre-delete-backup-job
  namespace: billing-prod
  annotations:
    argocd.argoproj.io/hook: PreDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: db-dumper
          image: internal-registry.corp/infra/pg-backup-tool:v2.1
          command:
            - /bin/sh
            - -c
            - |
              set -e
              echo "Создание аварийного снапшота перед удалением сервиса..."
              pg_dump -h pg-host.internal.corp -U billing_admin -d billing_db > /tmp/final_snapshot.sql
              s3cmd put /tmp/final_snapshot.sql s3://infra-backups/billing-predelete-$(date +%s).sql
              echo "Резервное копирование завершено успешно."
```

#### Манифест PostDelete Hook (Очистка внешних систем)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: post-delete-cleanup-job
  namespace: billing-prod
  annotations:
    argocd.argoproj.io/hook: PostDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: deprovisioner
          image: internal-registry.corp/infra/dns-cleanup-tool:v1.0
          command:
            - /bin/sh
            - -c
            - |
              echo "Удаление записей из PowerDNS API..."
              curl -X DELETE -H "X-API-Key: ${PDNS_API_KEY}" \
                http://ns1.internal.corp:8081/api/v1/servers/localhost/zones/internal.corp./records/billing.internal.corp.
              echo "Отправка уведомления об успешной деинициализации..."
              curl -X POST -H 'Content-Type: application/json' \
                -d '{"text":"[SRE Alert] Сервис billing-prod полностью демонтирован из кластера k8s-prod-01."}' \
                http://mattermost.internal.corp/hooks/webhook-token
```

---

### Сценарий 5: Каскадное удаление ApplicationSet и разрыв каскада

**Контекст:** В кластере используется `ApplicationSet`, генерирующий десятки микросервисов по каталогам в Git. По умолчанию при удалении объекта `ApplicationSet` контроллер каскадно удаляет все созданные им объекты `Application`, а те, имея `resources-finalizer`, физически удаляют всю полезную нагрузку в кластере. Необходимо пересоздать `ApplicationSet` с новой структурой генераторов, категорически исключив простой работающих приложений.

#### Настройка разрыва каскада в ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: microservices-appset
  namespace: argocd
spec:
  syncPolicy:
    # КРИТИЧЕСКИ ВАЖНО: сохраняет дочерние Application при удалении ApplicationSet
    preserveResourcesOnDeletion: true
  generators:
    - git:
        repoURL: git@gitlab.internal.corp:platform/services.git
        revision: main
        directories:
          - path: apps/*
  template:
    metadata:
      name: "{{path.basename}}"
      finalizers:
        # Даже если у приложений есть финализатор, сохранение ApplicationSet предотвращает снос
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: default
      source:
        repoURL: git@gitlab.internal.corp:platform/services.git
        targetRevision: main
        path: "{{path}}"
      destination:
        server: https://kubernetes.default.svc
        namespace: "{{path.basename}}"
```

#### Безопасная процедура пересоздания ApplicationSet

```bash
# 1. Проверка флага preserveResourcesOnDeletion
kubectl get applicationset microservices-appset -n argocd -o jsonpath='{.spec.syncPolicy.preserveResourcesOnDeletion}'
# → true

# 2. Удаление ApplicationSet
kubectl delete applicationset microservices-appset -n argocd
# → applicationset.argoproj.io "microservices-appset" deleted

# 3. Проверка: все дочерние Application и их поды продолжают работать!
argocd app list
# → NAME         CLUSTER                         NAMESPACE   STATUS  HEALTH   SYNCPOLICY
# → auth-api     https://kubernetes.default.svc  auth-api    Synced  Healthy  Auto-Prune
# → cart-api     https://kubernetes.default.svc  cart-api    Synced  Healthy  Auto-Prune

# 4. Применение обновленного манифеста ApplicationSet
kubectl apply -f appset-v2.yaml
# Контроллер переподключает существующие Application без рестарта подов
```

---

### Сценарий 6: Обнаружение, аудит и очистка бесхозных (Orphaned) ресурсов

**Контекст:** Разработчики периодически выполняли ручные `kubectl apply` или удаляли приложения с флагом `--no-cascade`. В namespace `ecommerce-prod` накопились «мертвые» ресурсы (ConfigMap, Secret, Deployment), потребляющие квоты etcd и памяти. Необходимо настроить автоматический мониторинг через `AppProject` и провести регламентную очистку.

#### Конфигурация AppProject с отслеживанием бесхозных ресурсов

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: ecommerce-project
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "Проект сервисов электронной коммерции"
  sourceRepos:
    - "git@gitlab.internal.corp:ecommerce/*"
  destinations:
    - server: https://kubernetes.default.svc
      namespace: ecommerce-prod
  orphanedResources:
    warn: true  # Формирует предупреждения в UI и генерирует метрики Prometheus
    ignore:
      # Исключение системных объектов Kubernetes
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt
      - group: ""
        kind: ServiceAccount
        name: default
      - group: "discovery.k8s.io"
        kind: EndpointSlice
      - group: ""
        kind: Endpoints
      - group: "apps"
        kind: ReplicaSet
```

#### Инспекция и скрипт безопасной очистки

```bash
# 1. Запрос списка бесхозных ресурсов через CLI/JSON
kubectl get appproject ecommerce-project -n argocd -o jsonpath='{.status.orphanedResources}' | jq .
# → [
# →   {
# →     "group": "apps",
# →     "kind": "Deployment",
# →     "name": "legacy-test-worker",
# →     "namespace": "ecommerce-prod"
# →   },
# →   {
# →     "group": "",
# →     "kind": "ConfigMap",
# →     "name": "test-env-vars",
# →     "namespace": "ecommerce-prod"
# →   }
# → ]

# 2. Аудит перед удалением: проверка даты создания и наличия трафика
kubectl get deployment legacy-test-worker -n ecommerce-prod -o yaml | grep creationTimestamp
# → creationTimestamp: "2026-02-14T08:12:00Z"

# 3. Безопасное удаление осиротевшего ресурса
kubectl delete deployment legacy-test-worker -n ecommerce-prod
# → deployment.apps "legacy-test-worker" deleted
```

---

### Сценарий 7: Удаление Namespace и обработка блокировок

**Контекст:** Приложение создавало собственный Namespace (`CreateNamespace=true`). При выводе сервиса из эксплуатации namespace зависает в статусе `Terminating` из-за неудаляемых CustomResources сторонних операторов или зависших финализаторов локального хранилища.

#### Порядок правильного удаления Namespace через Argo CD

1. Если `Namespace` описан как ресурс внутри Git-репозитория приложения:
   - В манифесте `Application` должна стоять опция `PrunePropagationPolicy=foreground`.
   - При удалении манифеста Namespace из Git Argo CD каскадно удалит сначала все объекты внутри namespace, дождется завершения работы всех подов (`terminationGracePeriodSeconds`) и только затем отправит запрос на удаление самого Namespace.
2. Если `Namespace` удаляется при сносе `Application`:
   - Убедитесь, что в манифесте не прописана аннотация `argocd.argoproj.io/sync-options: Delete=false` на ресурсе Namespace.

#### Устранение зависания Namespace в статусе `Terminating`

Если namespace застрял при каскадном удалении:

```bash
# 1. Поиск ресурсов, оставшихся в зависшем namespace
kubectl api-resources --verbs=list --namespaced -o name | \
  xargs -P8 -I {} sh -c 'kubectl get {} -n ecommerce-prod --ignore-not-found 2>/dev/null' | grep -v "No resources"

# 2. Выявление неработающих APIService (частая причина вечного Terminating в on-premise)
kubectl get apiservice | grep False
# → v1beta1.custom.metrics.k8s.io   monitoring/prometheus-adapter   False (ServiceNotFound)

# 3. Если блокировка вызвана неработающим APIService, исправьте или удалите сломанный APIService:
kubectl delete apiservice v1beta1.custom.metrics.k8s.io
# После этого kube-controller-manager успешно завершит удаление namespace.
```

---

### Сценарий 8: Безопасное массовое удаление приложений без деградации etcd

**Контекст:** Требуется расформировать тестовый стенд из 200+ микросервисов. Одновременный запуск `argocd app delete` для всех приложений способен перегрузить кластер etcd миллионами операций записи и чтения событий, вызвав всплеск задержек (`etcd_disk_wal_fsync_duration_seconds`) и флаппинг лидерства etcd.

#### Скрипт пакетного удаления с контролем нагрузки

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_PROJECT="qa-experiments"
BATCH_SIZE=5
SLEEP_INTERVAL=10

echo "Получение списка приложений проекта ${TARGET_PROJECT}..."
APPS=$(argocd app list -p "${TARGET_PROJECT}" -o name)

COUNT=0
for APP in ${APPS}; do
  echo "[$(date +'%T')] Удаление приложения ${APP} (foreground cascade)..."
  argocd app delete "${APP}" --cascade --yes
  
  COUNT=$((COUNT + 1))
  if (( COUNT % BATCH_SIZE == 0 )); then
    echo "Батч из ${BATCH_SIZE} приложений отправлен. Пауза ${SLEEP_INTERVAL} сек для разгрузки etcd и GC..."
    sleep "${SLEEP_INTERVAL}"
    
    # Контроль здоровья API сервера
    kubectl get --raw='/readyz' > /dev/null
  fi
done

echo "Все приложения проекта ${TARGET_PROJECT} успешно удалены."
```

---

## Операции и команды

Сводная таблица основных операций управления удалением, очисткой и финализаторами:

| Действие | Команда | Описание / Параметры | Ожидаемый результат (`# → result`) |
| :--- | :--- | :--- | :--- |
| **Каскадное удаление (CLI)** | `argocd app delete <app> --cascade --yes` | Удаляет CR Application и все физические ресурсы в кластере. | `# → application '<app>' deleted` |
| **Некаскадное удаление (Orphan)** | `argocd app delete <app> --no-cascade --yes` | Удаляет только CR Application. Нагрузки остаются в кластере. | `# → application '<app>' deleted (resources preserved)` |
| **Удаление с фоновым GC** | `argocd app delete <app> --propagation-policy background --yes` | Удаляет объект-владелец сразу, дочерние ресурсы удаляет K8s GC в фоне. | `# → application '<app>' deleted` |
| **Ручной Prune при синке** | `argocd app sync <app> --prune` | Выполняет синхронизацию с физическим удалением лишних манифестов. | `# → Phase: Succeeded, Status: Synced` |
| **Синк без Prune** | `argocd app sync <app> --prune=false` | Применяет изменения, но оставляет ресурсы, удаленные из Git. | `# → Phase: Succeeded, Status: OutOfSync` |
| **Удаление через kubectl (Каскад)** | `kubectl delete app <app> -n argocd` | При наличии финализатора `resources-finalizer` инициирует каскадный снос. | `# → application.argoproj.io "<app>" deleted` |
| **Экстренное снятие финализатора** | `kubectl patch app <app> -n argocd -p '{"metadata":{"finalizers":null}}' --type=merge` | Принудительно разрывает финализатор на зависшем приложении. Нагрузки в кластере не удаляются. | `# → application.argoproj.io/<app> patched` |
| **Проверка финализаторов на CR** | `kubectl get app <app> -n argocd -o jsonpath='{.metadata.finalizers}'` | Проверяет, защищено ли приложение каскадным финализатором. | `# → ["resources-finalizer.argocd.argoproj.io"]` |
| **Проверка статуса удаления** | `kubectl get app <app> -n argocd -o jsonpath='{.status.conditions}'` | Инспекция ошибок удаления (`DeletionError`). | `# → [{"type":"DeletionError","message":"Hook failed"}]` |
| **Поиск бесхозных ресурсов** | `kubectl get appproject <proj> -n argocd -o jsonpath='{.status.orphanedResources}'` | Выводит список неконтролируемых ресурсов в namespace проекта. | `# → [{"kind":"Deployment","name":"orphan-worker"}]` |
| **Запрет Prune на объекте** | `kubectl annotate deployment <name> -n <ns> argocd.argoproj.io/sync-options=Prune=false --overwrite` | Защищает объект от удаления при Prune. | `# → deployment.apps/<name> annotated` |

---

## Диагностика и устранение неполадок

### Матрица типовых проблем при удалении и очистке

| Проблема / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **CR Application завис в статусе `Terminating`** | Финализатор `resources-finalizer` не может завершить удаление из-за зависшего дочернего ресурса или ошибки хука. | `kubectl get app <app> -n argocd -o yaml` (секции `conditions` и `operationState`). | Найти блокирующий ресурс; устранить блокировку в кластере или сбросить финализатор вручную. |
| **Ошибка `DeletionError` в статусе Application** | Сбой выполнения `PreDelete` или `PostDelete` Job (Exit code != 0, ошибка таймаута). | `kubectl get jobs -n <ns>`, `kubectl logs job/<hook-job-name> -n <ns>`. | Исправить причину сбоя Job (сеть, учетные данные), удалить упавший Job; синк повторит удаление. |
| **Pod / StatefulSet завис в `Terminating`** | Процесс в контейнере игнорирует `SIGTERM`; не может отмонтироваться Ceph/NFS диск; нарушен `PodDisruptionBudget`. | `kubectl describe pod <pod-name> -n <ns>`, проверка dmesg на нодах хранения. | Проверить PDB (`kubectl get pdb -n <ns>`); проверить доступность Ceph CSI; при необходимости `kubectl delete pod <name> --force --grace-period=0`. |
| **PVC не удаляется после сноса StatefulSet** | На PVC установлен финализатор защиты `kubernetes.io/pvc-protection`, и под все еще удерживает том. | `kubectl describe pvc <pvc-name> -n <ns>`. | Дождаться остановки пода; если под уже удален, проверить статус CSI driver. |
| **Катастрофический снос ресурсов при пустом коммите** | Случайный мерж пустой ветки или ошибка рендеринга Helm привел к полному Prune всех объектов. | Просмотр событий `kubectl get events -n <ns>` и логов `argocd-application-controller`. | Всегда выставлять `allowEmpty: false` в `syncPolicy.automated`; оперативный `git revert` коммита в Git. |
| **Ресурс удален из Git, но остается в кластере** | На манифесте установлена аннотация `Prune=false`, либо в приложении выключен `prune: true`. | `kubectl get <kind> <name> -o yaml \| grep -i prune`. | Удалить аннотацию `Prune=false` или выполнить ручной `argocd app sync --prune`. |

---

### Алгоритм устранения зависшего удаления Application (Emergency Runbook)

Когда приложение находится в статусе `Terminating` длительное время, выполните пошаговую диагностику:

```text
                  Application завис в Terminating
                                │
                                ▼
         Шаг 1: Проверка условий DeletionError
         $ kubectl get app <name> -n argocd -o jsonpath='{.status.conditions}'
                                │
               ┌────────────────┴────────────────┐
          Есть ошибка                       Ошибок нет
               │                                 │
               ▼                                 ▼
   Хук Pre/PostDelete упал             Шаг 2: Проверка managed ресурсов
   Логи: $ kubectl logs job/<hook>     $ kubectl get all -n <target-ns>
   Устранить ошибку / перезапустить              │
                                       ┌─────────┴─────────┐
                                  Ресурсы есть        Все ресурсы удалены
                                       │                       │
                                       ▼                       ▼
                         Ресурс завис в Terminating   Контроллер Argo CD не
                         - PDB блокирует удаление?    может обновить etcd.
                         - CSI диск не отмонтирован?  Рестарт controller:
                         - Webhook не отвечает?       $ kubectl rollout restart
                                       │              deploy argocd-app-controller
                                       ▼                       │
                         Устранить причину на ноде             ▼
                                       │              Финализатор снимется
                                       v              автоматически
                         Финализатор снимется сам
```

#### Пошаговые команды ликвидации аварии

```bash
# 1. Поиск зависших подов и проверка PDB в целевом пространстве имен
kubectl get pdb -n ecommerce-prod
# Если PDB блокирует удаление (Allowed disruptions = 0):
kubectl delete pdb order-pdb -n ecommerce-prod

# 2. Проверка зависших финализаторов на пользовательских объектах внутри namespace
kubectl get pods,pvc,statefulsets -n ecommerce-prod -o json | \
  jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.kind)/\(.metadata.name): \(.metadata.finalizers)"'
# → Pod/order-worker-0: ["kubernetes.io/pod-cleanup"]

# 3. Крайняя мера: если ресурсы физически очищены, но Application CR заблокирован контроллером
# Снятие финализатора вручную с объекта Application:
kubectl patch application order-backend -n argocd \
  --type='json' \
  -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
# → application.argoproj.io/order-backend patched
# CR мгновенно удаляется из Kubernetes API
```

---

## Лучшие практики

1. **Защита от опустошения репозитория (`allowEmpty: false`):**
   Всегда указывайте `spec.syncPolicy.automated.allowEmpty: false`. Если Git-ветка окажется повреждена, скрипт шаблонизации упадет или репозиторий вернет пустой список манифестов, контроллер откажется выполнять синк и сохранит текущую инфраструктуру в кластере от тотального Prune.

2. **Обязательное использование `PruneLast=true` для Production:**
   Никогда не используйте обычный `Prune` на боевых контурах без `PruneLast=true`. Обычный Prune сначала удаляет старый объект (например, `Service` или `ConfigMap`), что гарантирует даунтайм до момента готовности нового пода.

3. **Защита хранилищ от случайного уничтожения:**
   - На уровне `StorageClass` устанавливайте `reclaimPolicy: Retain` для продуктивных томов Ceph/Local-Storage.
   - В `StatefulSet` и манифестах `PersistentVolumeClaim` жестко прописывайте аннотацию `argocd.argoproj.io/sync-options: Delete=false,Prune=false`.

4. **Изоляция и контроль `ApplicationSet`:**
   В манифестах `ApplicationSet` всегда объявляйте `spec.syncPolicy.preserveResourcesOnDeletion: true`. Это защитит десятки порожденных сервисов от мгновенного уничтожения при случайном удалении самого `ApplicationSet`.

5. **Мониторинг Orphaned Resources:**
   Включайте `orphanedResources.warn: true` в `AppProject` для изолированных тенантских пространств имен. Настройте Prometheus Alerting по метрике `argocd_app_info{orphaned_resources_count!="0"}` для превентивного обнаружения неконтролируемых нагрузок.

6. **Управление окнами синхронизации (`Sync Windows`):**
   Блокируйте Prune во время пиковых нагрузок бизнеса с помощью Sync Windows. Запрет ручного и автоматического синка в рабочие часы снижает вероятность случайного удаления инфраструктуры оператором.

---

## Ограничения и граничные случаи

- **Манифесты CRD и каскадный риск:** Если манифест `CustomResourceDefinition` находится в репозитории под управлением Prune, удаление файла CRD приведет к тому, что Kubernetes API Server каскадно удалит **все** экземпляры кастомных ресурсов этого типа во всем кластере. Манифесты CRD должны обязательно защищаться аннотацией `Prune=false` или исключаться в `AppProject` (`namespaceResourceBlacklist`).
- **Собственные контроллеры и OwnerReferences:** Если оператор внутри кластера порождает дочерние ресурсы без привязки tracking-аннотаций Argo CD, Argo CD Prune не сможет удалить их напрямую при удалении родительского манифеста из Git. Их удаление ложится исключительно на стандартный Kubernetes Garbage Collector.
- **Откат удаленных ресурсов (Rollback Limitation):** Argo CD не хранит копии манифестов удаленных ресурсов в кластере. Откат операции Prune невозможен через команду `argocd app rollback`. Восстановление удаленного ресурса осуществляется исключительно через `git revert` в Git-репозитории.
- **Влияние массового удаления на etcd:** Удаление сотен приложений с тысячами объектов единовременно создает взрывную нагрузку на etcd (интенсивные записи DeletionTimestamp, генерация тысяч событий Events, работа GC). В on-premise кластерах массовое удаление должно производиться батчами с обязательным мониторингом метрик `etcd_server_has_leader` и `etcd_disk_wal_fsync_duration_seconds`.

---

## Дополнительная информация

### Внутренние ссылки

- [Методы отслеживания ресурсов (Resource Tracking)](./argocd_resource_tracking.md) — аннотации, метки и механизм идентификации объектов.
- [Синхронизация и Sync Options](./synchronization.md) — полный обзор опций автоматической и ручной синхронизации.
- [Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md) — детальная архитектура волн, PreDelete и PostDelete хуков.
- [AppProject — глубокое погружение](./argocd_appproject_deep.md) — ограничения проектов, списки разрешений и мониторинг orphaned resources.
- [ApplicationSets в Argo CD](./argocd_applicationsets.md) — генераторы приложений, каскады и параметр `preserveResourcesOnDeletion`.
- [Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — метрики контроллера, Prometheus-алерты и журналы событий.
- [Аварийное восстановление (Disaster Recovery)](./argocd_disaster_recovery.md) — резервное копирование etcd, экспорт манифестов и восстановление кластера.

### Официальная документация

- [Argo CD: Deleting Applications](https://argo-cd.readthedocs.io/en/stable/user-guide/app_deletion/)
- [Argo CD: Sync Options Reference](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Argo CD: Orphaned Resources Monitoring](https://argo-cd.readthedocs.io/en/stable/user-guide/orphaned-resources/)
- [Kubernetes: Garbage Collection and Propagation Policy](https://kubernetes.io/docs/concepts/architecture/garbage-collection/)
