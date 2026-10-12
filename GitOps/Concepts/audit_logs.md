# GitOps: Журналы аудита и трассируемость

**Актуально для:** Argo CD v3.4–v3.6+ / v2.12+, Flux v2.4–v2.9+, Kubernetes 1.30–1.32+ (bare-metal / on-premise)

В парадигме GitOps, где Git выступает единым источником истины (SSoT), журналы аудита и механизмы трассируемости обеспечивают возможность отследить полный жизненный цикл любого изменения конфигурации и инфраструктуры: от первичного коммита разработчика до работающего ресурса в кластере. В контексте работы системных администраторов, DevOps- и SRE-инженеров аудит — это не просто формальное требование безопасности, а главный инструмент расследования инцидентов (forensics), выявления несанкционированного дрейфа (drift detection) и обеспечения непрерывного комплаенса в локальных (on-premise) и bare-metal инфраструктурах.

## Определения

- **Журнал аудита (Audit Log)**: Неизменяемая, хронологически упорядоченная последовательность записей о событиях в системе. Фиксирует контекст «кто, что, когда, где и через какой интерфейс изменил» в Git-репозитории, GitOps-контроллере, API-сервере Kubernetes и на уровне операционной системы узлов.
- **Трассируемость (Traceability)**: Способность восстановить непрерывную причинно-следственную цепочку изменений: `Личность автора (SSO/OIDC) → Подписанный коммит (GPG/SSH) → Merge Request (ревью) → Сборка и OCI Digest (CI/Harbor) → GitOps Sync ID (Argo CD / Flux) → Runtime Resource UID (Kubernetes)`.
- **Происхождение артефакта (Provenance)**: Верифицируемые метаданные о процессе сборки артефакта (исходный репозиторий, коммит, параметры окружения сборщика, используемые зависимости), удостоверенные криптографической подписью.
- **Kubernetes Audit Logs**: Структурированные записи запросов к `kube-apiserver` (схема `audit.k8s.io/v1`). Являются единственным авторитетным источником, фиксирующим все вызовы Control Plane — как от GitOps-контроллеров, так и от операторов (`kubectl`).
- **Kubernetes Events**: Ресурсы API-сервера (`kind: Event`), генерируемые системными компонентами и контроллерами (Argo CD, Flux) для описания изменений состояния. Хранятся в `etcd` с временем жизни по умолчанию 1 час (`--event-ttl=1h0m0s`), из-за чего требуют немедленного экспорта во внешнее хранилище.
- **Дрейф конфигурации (Configuration Drift)**: Расхождение между эталонным состоянием, описанным в Git (Desired State), и фактическим состоянием объектов в кластере (Actual State). Аудит дрейфа фиксирует факт ручного вмешательства в обход Git.
- **WORM (Write Once, Read Many)**: Модель неизменяемого хранения данных, при которой записанный лог не может быть перезаписан, усечен или удален до истечения заданного срока (реализуется через Object Lock с режимом `COMPLIANCE` в локальных S3-хранилищах MinIO и Ceph RGW).
- **SLSA (Supply-chain Levels for Software Artifacts)**: Стандарт безопасности цепочки поставки ПО (актуальная версия — v1.2, трек `Build L0–L3`). В GitOps реализуется через обязательную валидацию аттестаций и подписей артефактов до их развертывания.
- **SBOM (Software Bill of Materials)**: Полный машиночитаемый перечень компонентов и библиотек приложения (в форматах SPDX или CycloneDX), хранящийся в реестре артефактов и сопоставляемый с журналом аудита релиза.
- **VSA (Verification Summary Attestation)**: Сводный криптографический документ, удостоверяющий факт успешного прохождения проверок политик (SLSA, сканирование уязвимостей) admission-контроллером перед применением манифеста.
- **Неотказуемость (Non-repudiation)**: Свойство криптографической системы, гарантирующее, что автор действия (коммита, тега, одобрения) не может отрицать факт его совершения благодаря использованию персональных закрытых ключей GPG или SSH.
- **Хостовый аудит (Host Audit / FIM)**: Мониторинг целостности файлов и системных вызовов ядра ОС (через Linux `auditd`) на управляющих и рабочих узлах кластера. Позволяет зафиксировать прямой дрейф в обход K8s API (модификация `/etc/kubernetes/manifests`, `kubelet`, `/etc/kubernetes/pki`).
- **Верификация источника (Source Verification)**: Проверка криптографических подписей коммитов (GPG/SSH) или OCI-артефактов непосредственно GitOps-контроллером перед синхронизацией (`GitRepository.spec.verify` во Flux, GPG Commit Verification в Argo CD).

## Базовые концепции

### Четырехуровневая модель аудита GitOps

Надежный аудит в on-premise и bare-metal архитектуре строится на сопоставлении событий четырех независимых уровней:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Git-уровень (Намерение — Why & Who): Репозиторий & CI               │
│    - GPG/SSH-подписи коммитов и тегов                                  │
│    - Merge Request approvals, обсуждения, результаты CI                │
│    - Серверные аудит-логи (GitLab Audit Events / Gitea logs)           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Webhook / Poll (Commit SHA)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Уровень контроллера (Действие & Валидация — How & When)             │
│    - Атрибуция пользователя через SSO / OIDC (Keycloak, Dex)           │
│    - Верификация подписи источника (Flux spec.verify / Argo GPG check) │
│    - Журналы синхронизации (OperationStarted, ReconciliationSucceeded) │
│    - Вычисление diff, фиксация drift, попытки самоисцеления            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ K8s API Requests (ServiceAccount)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Уровень кластера (Фактическое состояние — What): Kubernetes API     │
│    - kube-apiserver Audit Logs (audit.k8s.io/v1)                       │
│    - Kubernetes Events (TTL ~ 1 час)                                   │
│    - Метаданные ресурсов (argocd.argoproj.io/tracking-id, Flux labels) │
│    - Admission-контроль (Kyverno PolicyReports, Validating Webhooks)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Host / OS-level Bypass
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Уровень операционной системы узлов (Хостовая целостность — Where)   │
│    - Linux auditd: мониторинг /etc/kubernetes/manifests (static pods)  │
│    - Контроль бинарников и drop-in файлов kubelet, containerd          │
│    - Мониторинг прямого выполнения команд (auid, sudo, crictl)         │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Git-уровень (Намерение — Why & Who)**:
   - Отвечает на вопросы: кто создал изменение, кто провел код-ревью, какие автотесты прошли успешно.
   - Фиксирует личность через криптографическую подпись коммита (`git commit -S`) и записи в аудит-логе Git-сервера (GitLab, Gitea).
   - Защитные механизмы: Protected Branches блокируют прямые push-запросы; правила `CODEOWNERS` гарантируют обязательное согласование ответственными инженерами.

2. **Уровень GitOps-контроллера (Действие & Валидация — How & When)**:
   - Отвечает на вопросы: когда манифест был взят в работу, какой ревизией коммита была вызвана синхронизация, прошла ли криптографическая проверка подписи коммита, была ли синхронизация автоматической или ручной (`Hard Refresh`).
   - Контроллер обогащает метаданные: Argo CD генерирует события `OperationStarted` с указанием пользователя из OIDC-токена; Flux публикует события `Progressing` и `ReconciliationSucceeded` на объектах `Kustomization` и `HelmRelease`.

3. **Уровень Kubernetes (Фактическое состояние — What)**:
   - Фиксирует конкретные вызовы API-сервера (`CREATE`, `UPDATE`, `PATCH`, `DELETE`).
   - Позволяет отличить легитимную работу контроллера от несанкционированного ручного вмешательства: запросы контроллера идут от системного `ServiceAccount` (например, `system:serviceaccount:argocd:argocd-application-controller`), тогда как ручные правки инженеров фиксируют их персональные имена пользователей и User-Agent `kubectl`.

4. **Уровень операционной системы узлов (Хостовая целостность — Where & Bypass Detection)**:
   - В bare-metal и on-premise кластерах администраторы или злоумышленники с SSH/root-доступом к нодам Control Plane могут вносить правки в обход API-сервера:
     - Прямое редактирование статических манифестов в `/etc/kubernetes/manifests/` (подмена `kube-apiserver`, `etcd`, `kube-controller-manager`).
     - Изменение конфигурации `kubelet` в `/var/lib/kubelet/config.yaml` или параметров запуска в systemd drop-in файлах.
     - Модификация локальных TLS-сертификатов в `/etc/kubernetes/pki/`.
   - `kube-apiserver` аудит принципиально не видит эти действия. Контроль на этом уровне обеспечивает демон `auditd` ядра Linux, регистрирующий системные вызовы изменения файлов с привязкой к исходному пользователю (`auid`).

### Сквозная цепочка трассируемости

Для полного расследования инцидента SRE-инженер связывает события от рантайма до исходного кода и хостовой ОС:

```text
Runtime Pod UID
   ├── auditd log (хост): фиксация отсутствия прямых правок /etc/kubernetes/manifests
   └── k8s-audit.log: запрос create от ServiceAccount argocd-application-controller
         └── Аннотация ресурса: argocd.argoproj.io/tracking-id: "payments:apps/Deployment:prod/api"
               └── Событие Argo CD OperationStarted: Sync to revision 7b3d1f8 by sso_user: alex@corp.local
                     └── Git Commit 7b3d1f8: GPG Key ID 4A8B9C0D (автор: Alex), MR !412 (одобрен: Maria)
                           └── OCI Image Digest: harbor.corp.local/apps/api@sha256:e3b0c442...
                                 └── SBOM & Cosign Signature в Harbor
```

Разрыв любого из звеньев этой цепочки (например, использование общего локального аккаунта `admin` в Argo CD или отключенная проверка подписей) лишает инфраструктуру доказательной базы.

### Безопасность цепочки поставок (Supply Chain Integrity)

В self-hosted контурах без внешних сервисов соблюдение уровней SLSA Build L1–L3 реализуется за счет связки локальных компонентов:
- **Локальный реестр артефактов (Harbor)**: хранит Docker-образы, Helm-чарты, OCI-артефакты, а также прикрепленные подписи и SBOM-файлы.
- **Подпись артефактов (Cosign)**: пайплайн CI собирает образ в изолированном раннере, генерирует SBOM с помощью `syft`, подписывает образ закрытым ключом и отправляет подпись в Harbor (`cosign sign --key k8s://...`).
- **Admission-контроль (Kyverno)**: перехватывает запросы на создание подов в кластере, проверяет наличие и валидность подписи в локальном Harbor через `imageVerify`-правила и блокирует неподписанные образы. Подробный разбор механики подписания приведен в руководстве [Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md).

### Расчет объемов и сайзинг дисков для системных администраторов

Журнал `kube-apiserver` в режиме `RequestResponse` для мутирующих запросов и `Metadata` для чтения генерирует существенный объем I/O:
- В кластере среднего размера (50–100 нод, 2000 подов) при нагрузке 100 запросов/сек средний размер одной записи аудита составляет от 1.5 до 3 КБ.
- Входящий поток: `100 req/s * 2.5 KB ≈ 250 KB/s` (~21.6 ГБ/сутки несжатых JSON-логов).
- При пиковых нагрузках (500 req/s) поток достигает `1.25 MB/s` (~108 ГБ/сутки).
- **Требование к файловой системе**: Раздел `/var/log/kubernetes` должен монтироваться на отдельный NVMe/SSD диск с опцией `noatime`, чтобы I/O подсистемы аудита не блокировал запись системного журнала `systemd-journald` и etcd.
- **Сжатие архивов**: При потоковой отправке агентом Vector в локальный MinIO компрессия алгоритмом `zstd` сокращает объем хранения в 6–8 раз (до ~3–4 ГБ/сутки на 100 RPS).

## Практические сценарии

### Сценарий 1: Корреляция действий пользователя через Argo CD и on-premise OIDC

**Предварительные требования**: развернутый Argo CD с подключением к корпоративному IdP (Keycloak или Dex) по протоколу OIDC; доступ `kubectl` с правами администратора в namespace `argocd`.

**Проблема**: В production-окружении произошло внеплановое применение конфигурации приложения `billing`. Требуется установить, кто инициировал синхронизацию и какую ревизию коммита указал.

**Действия**:

1. **Просмотр событий объекта `Application`**:
   Argo CD публикует структурированные события жизненного цикла приложения в кластерный журнал событий:
   ```bash
   kubectl events -n argocd --for application/billing
   # → result:
   # LAST SEEN   TYPE      REASON              OBJECT                MESSAGE
   # 4m          Normal    OperationStarted    Application/billing   argocd-server alex@corp.local initiated sync to HEAD (9f8a12c)
   # 3m          Normal    OperationCompleted  Application/billing   Sync operation to 9f8a12c succeeded
   ```
   В строке события зафиксированы: субъект (`alex@corp.local`), целевой коммит (`9f8a12c`) и результат операции.

2. **Анализ структурированных логов `argocd-server`**:
   При включенном флаге `--logformat json` в развертывании `argocd-server`, события API содержат метаданные аутентификации:
   ```bash
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=500 | \
     grep "initiated sync" | jq '{time, user: .msg, level}'
   # → result:
   # {
   #   "time": "2026-10-11T17:15:22Z",
   #   "user": "User 'alex@corp.local' initiated sync of app 'billing' to revision '9f8a12c'",
   #   "level": "info"
   # }
   ```

3. **Сверка ревизии с историей коммитов в Git**:
   ```bash
   git log -1 --show-signature 9f8a12c
   # → result:
   # commit 9f8a12c4b8e2d1f0a9c8b7e6d5c4b3a2f1e0d9c8
   # gpg: Signature made Sun Oct 11 17:10:05 2026 MSK
   # gpg: using RSA key 5F4E3D2C1B0A9876
   # gpg: Good signature from "Alex Engineer <alex@corp.local>" [ultimate]
   # Author: Alex Engineer <alex@corp.local>
   # Date:   Sun Oct 11 17:10:05 2026 +0300
   # 
   #     fix(billing): update database connection pool limits
   ```

**Ограничение**: Если инженеры используют встроенную локальную учетную запись `admin`, идентификация конкретного человека становится невозможной. Для production-контуров учетную запись `admin` следует отключать через параметр `admin.enabled: "false"` в ConfigMap `argocd-cm`, оставив аутентификацию исключительно через SSO (см. [Argo CD: Настройка SSO через GitLab](../ArgoCD/argocd_sso_gitlab.md)).

### Сценарий 2: Форензик-анализ ручных изменений (Drift Forensics)

**Предварительные требования**: включенный аудит-лог на `kube-apiserver`; журнал сохраняется в `/var/log/kubernetes/audit.log` на контрольных узлах (control plane).

**Проблема**: В приложении `api-gateway` изменилось количество реплик и параметры лимитов памяти. В Git-репозитории изменений не было. GitOps-контроллер (Argo CD или Flux) зафиксировал расхождение (`OutOfSync` / `Drift`). Требуется установить, кто выполнил ручной `kubectl edit` или `kubectl patch`.

**Действия**:

1. **Проверка статуса в GitOps-контроллере**:
   Для Argo CD:
   ```bash
   argocd app get api-gateway --refresh
   # → result:
   # Name:               argocd/api-gateway
   # Project:            default
   # Server:             https://kubernetes.default.svc
   # Namespace:          prod
   # URL:                https://argocd.corp.local/applications/api-gateway
   # Sync Status:        OutOfSync
   # Health Status:      Healthy
   # 
   # GROUP  KIND        NAMESPACE  NAME         STATUS     HEALTH   HOOK  MESSAGE
   # apps   Deployment  prod       api-gateway  OutOfSync  Healthy        deployment.apps/api-gateway configured
   ```

   Для Flux:
   ```bash
   flux get kustomizations -n apps
   # → result:
   # NAME         REVISION             SUSPENDED  READY  MESSAGE
   # api-gateway  main@sha1:9f8a12c    false      True   Applied revision: main@sha1:9f8a12c
   ```

2. **Поиск источника вмешательства в `kube-apiserver` audit log**:
   Используем `jq` для выборки мутирующих запросов (`patch`, `update`, `delete`) к целевому ресурсу, отфильтровывая запросы от системного ServiceAccount GitOps-контроллера:
   ```bash
   jq -c 'select(.objectRef.resource == "deployments" and .objectRef.name == "api-gateway")
     | select(.verb == "patch" or .verb == "update")
     | select((.user.username | test("system:serviceaccount:(argocd|flux-system)")) | not)
     | {timestamp: .stageTimestamp, user: .user.username, verb: .verb, client: .userAgent, ip: .sourceIPs[0]}' \
     /var/log/kubernetes/audit.log
   # → result:
   # {"timestamp":"2026-10-11T17:42:10.128Z","user":"ivan.petrov","verb":"patch","client":"kubectl/v1.31.1 (linux/amd64) kubernetes/ad2b5a1","ip":"192.168.10.45"}
   ```

3. **Сверка последствий и автоматического восстановления**:
   Если в Argo CD включена опция `selfHeal: true` (автоматическое устранение дрейфа), в логе будет видно следующее событие через интервал реконсиляции:
   ```bash
   jq -c 'select(.objectRef.name == "api-gateway" and .stageTimestamp > "2026-10-11T17:42:10Z")
     | {timestamp: .stageTimestamp, user: .user.username, verb: .verb}' \
     /var/log/kubernetes/audit.log | head -n 2
   # → result:
   # {"timestamp":"2026-10-11T17:42:10.128Z","user":"ivan.petrov","verb":"patch"}
   # {"timestamp":"2026-10-11T17:42:15.892Z","user":"system:serviceaccount:argocd:argocd-application-controller","verb":"patch"}
   ```
   Контроллер перезаписал несанкционированные изменения обратно в состояние, зафиксированное в Git.

### Сценарий 3: Настройка политики аудита Kubernetes API для on-premise кластеров

Для исключения чрезмерного объема логов при сохранении максимальной информативности в bare-metal/on-premise инсталляциях (kubeadm, rke2) настраивается специализированная политика `audit-policy.yaml`.

1. **Создание манифеста политики**:
   ```yaml
   # /etc/kubernetes/audit/audit-policy.yaml
   apiVersion: audit.k8s.io/v1
   kind: Policy
   omitStages:
     - "RequestReceived"
   rules:
     # 1. Полный аудит модификаций от GitOps-контроллеров и людей
     - level: RequestResponse
       verbs: ["create", "update", "patch", "delete"]
       resources:
         - group: "apps"
           resources: ["deployments", "statefulsets", "daemonsets"]
         - group: "batch"
           resources: ["jobs", "cronjobs"]
         - group: "networking.k8s.io"
           resources: ["ingresses", "networkpolicies"]
         - group: ""
           resources: ["services", "configmaps", "persistentvolumeclaims"]

     # 2. Безопасный аудит секретов (только метаданные во избежание утечки паролей в лог)
     - level: Metadata
       resources:
         - group: ""
           resources: ["secrets"]

     # 3. Аудит изменений CRD самих GitOps-операторов
     - level: RequestResponse
       verbs: ["create", "update", "patch", "delete"]
       resources:
         - group: "argoproj.io"
           resources: ["applications", "appprojects", "applicationsets"]
         - group: "source.toolkit.fluxcd.io"
           resources: ["gitrepositories", "ocirepositories", "helmrepositories"]
         - group: "kustomize.toolkit.fluxcd.io"
           resources: ["kustomizations"]
         - group: "helm.toolkit.fluxcd.io"
           resources: ["helmreleases"]

     # 4. Логирование чтения критических ресурсов только на уровне метаданных
     - level: Metadata
       verbs: ["get", "list", "watch"]
       resources:
         - group: ""
           resources: ["secrets", "configmaps"]

     # 5. Исключение высокочастотных системных запросов проверки жизнеспособности (kubelet, kube-proxy)
     - level: None
       users:
         - "system:kube-proxy"
         - "system:nodes"
       verbs: ["get", "list", "watch"]
       resources:
         - group: ""
           resources: ["endpoints", "endpointslices", "nodes", "nodes/status"]

     # 6. Финальное правило по умолчанию: минимальные метаданные для всех прочих запросов
     - level: Metadata
   ```

2. **Подключение политики к `kube-apiserver` (static pod в kubeadm)**:
   Отредактируйте `/etc/kubernetes/manifests/kube-apiserver.yaml` на контрольных узлах:
   ```yaml
   spec:
     containers:
       - command:
           - kube-apiserver
           - --audit-policy-file=/etc/kubernetes/audit/audit-policy.yaml
           - --audit-log-path=/var/log/kubernetes/audit.log
           - --audit-log-format=json
           - --audit-log-maxage=365
           - --audit-log-maxbackup=10
           - --audit-log-maxsize=200
           - --audit-log-batch-buffer-size=20000
           - --audit-log-batch-max-wait=1s
         volumeMounts:
           - mountPath: /etc/kubernetes/audit
             name: k8s-audit-config
             readOnly: true
           - mountPath: /var/log/kubernetes
             name: k8s-audit-log
     volumes:
       - hostPath:
           path: /etc/kubernetes/audit
           type: DirectoryOrCreate
         name: k8s-audit-config
       - hostPath:
           path: /var/log/kubernetes
           type: DirectoryOrCreate
         name: k8s-audit-log
   ```

3. **Проверка работоспособности**:
   ```bash
   kubectl create configmap audit-test --from-literal=status=ok -n default
   # → result:
   # configmap/audit-test created

   tail -n 1 /var/log/kubernetes/audit.log | jq '{verb, user: .user.username, obj: .objectRef.name}'
   # → result:
   # {"verb":"create","user":"kubernetes-admin","obj":"audit-test"}

   kubectl delete configmap audit-test -n default
   # → result:
   # configmap "audit-test" deleted
   ```

### Сценарий 4: Экспорт событий контроллеров и решение проблемы TTL

Kubernetes Events удаляются сборщиком мусора `etcd` спустя 1 час (`--event-ttl=1h0m0s`). Для обеспечения доказательной базы расследований события контроллеров экспортируются в постоянное хранилище (Loki, Elasticsearch или Kafka) с помощью open-source демона `kubernetes-event-exporter` или нативных механизмов уведомлений.

1. **Развертывание `kubernetes-event-exporter`**:
   Манифест конфигурации для фильтрации и отправки событий GitOps в локальный лог-агрегатор Vector / Fluent Bit:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: event-exporter-cfg
     namespace: monitoring
   data:
     config.yaml: |
       logLevel: info
       logFormat: json
       route:
         routes:
           - match:
               - receiver: "stdout-router"
       receivers:
         - name: "stdout-router"
           stdout: {}
   ```

2. **Настройка нативного алертинга во Flux (`notification-controller`)**:
   Flux может автоматически отправлять все события реконсиляции во внешний HTTP-webhook локальной SIEM или платформы мониторинга:
   ```yaml
   apiVersion: notification.toolkit.fluxcd.io/v1beta3
   kind: Provider
   metadata:
     name: local-siem-webhook
     namespace: flux-system
   spec:
     type: generic
     address: http://vector-aggregator.monitoring.svc.cluster.local:8088/flux-events
   ---
   apiVersion: notification.toolkit.fluxcd.io/v1beta3
   kind: Alert
   metadata:
     name: flux-audit-alert
     namespace: flux-system
   spec:
     providerRef:
       name: local-siem-webhook
     eventSeverity: info
     eventMetadata:
       cluster: onprem-prod-01
     eventSources:
       - kind: Kustomization
         name: "*"
       - kind: HelmRelease
         name: "*"
   ```

3. **Проверка доставки событий**:
   ```bash
   flux reconcile kustomization apps -n flux-system
   # → result:
   # ► annotating Kustomization apps in flux-system namespace
   # ✔ Kustomization annotated
   # ◎ waiting for Kustomization reconciliation
   # ✔ Kustomization apps is ready
   ```
   В логах Vector фиксируется JSON-событие от Flux с указанием версии манифестов и хэша коммита.

### Сценарий 5: Неизменяемое WORM-хранилище на базе локального MinIO (PCI DSS v4.0.1)

Согласно требованиям PCI DSS v4.0.1 (раздел 10.5.1), журналы аудита должны храниться минимум 12 месяцев с гарантией невозможности их изменения или удаления даже администратором системы. В изолированных контурах это реализуется с помощью локального MinIO кластера с активированным режимом **Object Lock**.

1. **Создание бакета с блокировкой Object Lock в MinIO**:
   Бакет создается с флагом `--object-lock`, после чего включается политика удержания по умолчанию в режиме `COMPLIANCE`:
   ```bash
   # Подключение MinIO Client (mc) к локальному кластеру
   mc alias set minio-local https://minio.corp.local:9000 minio_admin SecretKeyPass123
   # → result:
   # Added `minio-local` successfully.

   # Создание бакета с поддержкой блокировки
   mc mb --with-lock minio-local/k8s-audit-archive
   # → result:
   # Bucket created successfully `minio-local/k8s-audit-archive`.

   # Установка периода хранения 365 дней в режиме COMPLIANCE (необратимая блокировка)
   mc retention set --default COMPLIANCE 365d minio-local/k8s-audit-archive
   # → result:
   # Default retention period set to 365d in COMPLIANCE mode for `minio-local/k8s-audit-archive`.
   ```

2. **Конфигурация сборщика Vector для отправки аудита в MinIO S3**:
   Vector читает файл `/var/log/kubernetes/audit.log` и выгружает батчи с партиционированием по дате:
   ```yaml
   # /etc/vector/vector.yaml
   sources:
     k8s_audit_file:
       type: file
       include:
         - /var/log/kubernetes/audit.log
       read_from: beginning

   sinks:
     minio_worm_archive:
       type: s3
       inputs:
         - k8s_audit_file
       endpoint: https://minio.corp.local:9000
       bucket: k8s-audit-archive
       key_prefix: "audit/%Y/%m/%d/"
       region: "custom-onprem"
       compression: zstd
       encoding:
         codec: json
       auth:
         access_key_id: "audit-shipper"
         secret_access_key: "ShipperSecretKey456"
   ```

3. **Верификация неизменяемости (проверка WORM)**:
   ```bash
   # Проверка статуса блокировки загруженного файла
   mc retention info minio-local/k8s-audit-archive/audit/2026/10/11/
   # → result:
   # Object: audit/2026/10/11/k8s_audit_file-1.json.zst
   #   Mode: COMPLIANCE
   #   Retain Until: 2027-10-11 17:00:00 MSK

   # Попытка принудительного удаления файла
   mc rm minio-local/k8s-audit-archive/audit/2026/10/11/k8s_audit_file-1.json.zst --force
   # → result:
   # mc: <ERROR> An error occurred: The specified object is protected by a compliance mode retention period and cannot be deleted.
   ```

### Сценарий 6: Контроль целостности на уровне Git-сервера (Server-side Hooks)

Для предотвращения попадания неподписанных коммитов или коммитов от поддельных авторов в репозиторий развертывается серверный `pre-receive` хук на Git-сервере (GitLab, Gitea или bare Git).

1. **Скрипт серверного хука `pre-receive`**:
   Скрипт проверяет, что каждый входящий коммит имеет валидную GPG/SSH подпись и имя автора соответствует домену компании:
   ```bash
   #!/usr/bin/env bash
   # /var/opt/gitlab/git-data/repositories/@hashed/.../custom_hooks/pre-receive
   set -euo pipefail

   ZERO_COMMIT="0000000000000000000000000000000000000000"

   while read -r old_rev new_rev ref_name; do
     # Пропускаем удаление веток
     if [ "$new_rev" = "$ZERO_COMMIT" ]; then
       continue
     fi

     # Определяем диапазон коммитов
     if [ "$old_rev" = "$ZERO_COMMIT" ]; then
       rev_list="$new_rev --not --branches"
     else
       rev_list="$old_rev..$new_rev"
     fi

     for commit in $(git rev-list $rev_list); do
       # Проверка наличия и валидности криптографической подписи (GPG/SSH)
       if ! git verify-commit "$commit" >/dev/null 2>&1; then
         echo "ОШИБКА: Коммит $commit не имеет валидной подписи (GPG/SSH)!" >&2
         echo "В GitOps-репозитории разрешены только подписанные коммиты (git commit -S)." >&2
         exit 1
       fi

       # Проверка домена автора коммита
       author_email=$(git log -1 --format='%ae' "$commit")
       if [[ ! "$author_email" =~ @corp\.local$ ]]; then
         echo "ОШИБКА: Автор $author_email в коммите $commit не принадлежит корпоративному домену @corp.local!" >&2
         exit 1
       fi
     done
   done
   exit 0
   ```

2. **Тестирование отклонения неподписанного коммита**:
   ```bash
   git commit -m "unverified direct change" --no-gpg-sign
   git push origin main
   # → result:
   # Enumerating objects: 5, done.
   # Writing objects: 100% (3/3), 320 bytes | 320.00 KiB/s, done.
   # Total 3 (delta 1), reused 0 (delta 0), pack-reused 0
   # remote: ОШИБКА: Коммит c4d3e2a не имеет валидной подписи (GPG/SSH)!
   # remote: В GitOps-репозитории разрешены только подписанные коммиты (git commit -S).
   # To git.corp.local:infra/k8s-prod.git
   #  ! [remote rejected] main -> main (pre-receive hook declined)
   # error: failed to push some refs to 'git.corp.local:infra/k8s-prod.git'
   ```

### Сценарий 7: Криптографическая верификация источников контроллерами GitOps

Даже при наличии серверных проверок в Git, GitOps-контроллер обязан независимо проверять криптографические подписи коммитов перед синхронизацией, чтобы исключить применение коммитов из скомпрометированных веток или при атаках типа Man-in-the-Middle.

#### Вариант А: Верификация коммитов во Flux v2 (`spec.verify`)

1. **Создание секрета с публичными ключами GPG**:
   ```bash
   gpg --export --armor alex@corp.local > /tmp/alex-pubkey.asc
   kubectl create secret generic gpg-allowed-keys \
     --namespace=flux-system \
     --from-file=alex-pubkey.asc=/tmp/alex-pubkey.asc
   # → result:
   # secret/gpg-allowed-keys created
   ```

2. **Подключение верификации в `GitRepository`**:
   ```yaml
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: GitRepository
   metadata:
     name: podinfo
     namespace: flux-system
   spec:
     interval: 1m
     url: https://git.corp.local/infra/podinfo.git
     ref:
       branch: main
     verify:
       mode: head # Проверять подпись коммита на вершине ветки (HEAD)
       secretRef:
         name: gpg-allowed-keys
   ```

3. **Реакция на неподписанный или поддельный коммит**:
   Если в ветку попадает коммит без доверенной подписи, `source-controller` блокирует генерацию артефакта:
   ```bash
   flux get sources git -n flux-system
   # → result:
   # NAME     REVISION               SUSPENDED  READY  MESSAGE
   # podinfo  main@sha1:e8a3b1c      false      False  Git verification failed: commit 'e8a3b1c' is not signed by a trusted key
   ```

#### Вариант Б: Проверка подписей коммитов в Argo CD (Source Integrity)

1. **Добавление доверенных публичных GPG-ключей в ConfigMap**:
   ```bash
   kubectl create configmap argocd-gpg-keys-cm \
     -n argocd \
     --from-file=alex.asc=/tmp/alex-pubkey.asc
   # → result:
   # configmap/argocd-gpg-keys-cm created
   ```

2. **Включение проверки подписей в `argocd-cm`**:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: argocd-cm
     namespace: argocd
   data:
     gpg.verification.enabled: "true"
   ```

3. **Результат блокировки синхронизации**:
   При попытке синхронизации с неподписанным коммитом контроллер выставляет статус `ComparisonError`:
   ```bash
   argocd app get billing --refresh
   # → result:
   # Name:               argocd/billing
   # Sync Status:        Unknown
   # Health Status:      Missing
   # Condition:          ComparisonError: gpg: Signature made Sun Oct 11 17:10:05 2026 MSK: Can't check signature: No public key
   ```

### Сценарий 8: Обнаружение и расследование скрытого дрейфа на уровне хоста через Linux Auditd

**Проблема**: Инженер с правами `sudo` на контрольном узле bare-metal кластера изменил параметры статического пода `/etc/kubernetes/manifests/kube-apiserver.yaml` напрямую через SSH, добавив недопустимый флаг. API-сервер перезапустился с новой конфигурацией. Журнал `kube-apiserver` audit log не содержит записей, так как запрос не проходил через K8s API.

**Действия**:

1. **Настройка постоянных правил `auditd` для каталогов Kubernetes**:
   Создайте файл правил `/etc/audit/rules.d/k8s-manifests.rules` на всех узлах Control Plane:
   ```text
   # /etc/audit/rules.d/k8s-manifests.rules
   # Отслеживание записи, удаления и изменения атрибутов статических подов
   -w /etc/kubernetes/manifests/ -p wa -k k8s_static_pods

   # Отслеживание конфигурации kubelet
   -w /var/lib/kubelet/config.yaml -p wa -k k8s_kubelet_config

   # Отслеживание PKI сертификатов и ключей
   -w /etc/kubernetes/pki/ -p wa -k k8s_pki
   ```

   Применение правил:
   ```bash
   augenrules --load
   # → result:
   # Loaded 3 rules from /etc/audit/rules.d/k8s-manifests.rules

   auditctl -l | grep k8s
   # → result:
   # -w /etc/kubernetes/manifests -p wa -k k8s_static_pods
   # -w /var/lib/kubelet/config.yaml -p wa -k k8s_kubelet_config
   # -w /etc/kubernetes/pki -p wa -k k8s_pki
   ```

2. **Поиск событий модификации статических манифестов**:
   Используем `ausearch` для поиска инцидентов по ключу правила:
   ```bash
   ausearch -k k8s_static_pods --start recent -i
   # → result:
   # type=PROCTITLE msg=audit(10/11/2026 18:22:14.512:4981) : proctitle=vi /etc/kubernetes/manifests/kube-apiserver.yaml
   # type=PATH msg=audit(10/11/2026 18:22:14.512:4981) : item=0 name=/etc/kubernetes/manifests/kube-apiserver.yaml inode=1052643 dev=08:02 mode=file,600 ouid=root ogid=root
   # type=CWD msg=audit(10/11/2026 18:22:14.512:4981) : cwd=/root
   # type=SYSCALL msg=audit(10/11/2026 18:22:14.512:4981) : arch=x86_64 syscall=openat success=yes exit=3 a0=0xffffff9c a1=0x55dc1284a120 a2=0x241 a3=0x1b6 items=1 ppid=1420 pid=2105 auid=dmitry.ivanov uid=root gid=root euid=root suid=root tty=pts0 ses=4 comm=vi exe=/usr/bin/vi key=k8s_static_pods
   ```

3. **Форензик-вывод**:
   - Поле `auid=dmitry.ivanov` четко идентифицирует реального пользователя, который залогинился по SSH под своей учетной записью до выполнения `sudo -i`.
   - Поле `exe=/usr/bin/vi` и `proctitle` подтверждают факт интерактивного ручного редактирования файла в обход репозитория GitOps.
   - С системного администратора снята неопределенность: инцидент зафиксирован и атрибутирован. Подробнее о работе с подсистемой аудита ядра Linux см. [auditd: Аудит событий безопасности](../../Linux/SystemAdministration/Logging/auditd.md).

## Операции и команды

Справочная таблица основных команд для расследования инцидентов и аудита в GitOps-окружении:

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **История синхронизаций Argo CD** | `argocd app history <app-name>` | Просмотр хронологии деплоев, ревизий коммитов и меток времени. |
| **События приложения Argo CD** | `kubectl events -n argocd --for application/<app-name>` | Определение инициатора (OIDC identity) и параметров запуска синхронизации. |
| **События Flux Kustomization** | `flux events --for Kustomization/<name> -n flux-system` | Анализ результатов последней реконсилиации и обнаруженного дрейфа. |
| **Статус верификации коммитов Flux** | `flux get sources git -A` | Контроль прохождения криптографической проверки подписей источников. |
| **Поиск ручных правок в K8s Audit** | `jq 'select(.verb == "patch" or .verb == "update") \| select(.objectRef.name == "<res-name>")' audit.log` | Извлечение фактов вызова `kubectl edit/patch` с User-Agent и IP-адресом. |
| **Проверка статуса подписи коммита** | `git verify-commit <commit-sha>` | Проверка криптографической валидности подписи GPG/SSH. |
| **Проверка статуса подписи тега** | `git tag -v <tag-name>` | Верификация подписанного релизного тега. |
| **Проверка блокировки WORM в MinIO** | `mc retention info <alias>/<bucket>/<path>` | Проверка срока удержания объекта и режима защиты (`COMPLIANCE`). |
| **Список приостановленных Kustomizations** | `kubectl get kustomizations -A -o jsonpath='{range .items[?(@.spec.suspend==true)]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'` | Поиск временно отключенных GitOps-пайплайнов, скрывающих дрейф. |
| **Проверка хостовых правил auditd** | `auditctl -l` | Просмотр активных правил аудита ядра Linux для манифестов K8s. |
| **Поиск модификаций статических подов** | `ausearch -k k8s_static_pods -i` | Извлечение событий хостовых ручных правок в обход API-сервера. |

## Диагностика и устранение неполадок

| Проблема / Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **События синхронизации отсутствуют при расследовании инцидента недельной давности** | Превышен TTL объектов `Event` в Kubernetes (по умолчанию 1 час). | `kubectl get events -n <ns>` возвращает пустоту или события только за последний час. | Развернуть `kubernetes-event-exporter` (Сценарий 4) для потоковой пересылки событий в Vector / Loki. |
| **Все действия в Argo CD атрибутируются как пользователь `admin`** | Команда использует общую локальную учетную запись вместо OIDC/SSO. | В логах `argocd-server` все записи содержат `user="admin"`. | Настроить интеграцию с Dex/Keycloak; отключить локальный `admin` через `admin.enabled: "false"` в `argocd-cm`. |
| **Записи о чтении секретов отсутствуют в `audit.log`** | Правило аудита секретов расположено ниже общего правила или имеет уровень `None`. | Проверка порядка блоков в `/etc/kubernetes/audit/audit-policy.yaml`. | Поместить правило `level: Metadata` для ресурса `secrets` выше общих правил (правила применяются до первого совпадения сверху вниз). |
| **Переполнение диска контрольного узла логами аудита (`audit.log`)** | Слишком большой объем детализации (`RequestResponse` для системных компонентов), некорректная ротация. | `df -h /var/log/kubernetes`; сообщения в `dmesg` о нехватке места. | Вынести `/var/log/kubernetes` на выделенный NVMe-диск; исключить шумные ресурсы (`endpoints`, `nodes`); настроить `--audit-log-maxsize` и `--audit-log-maxbackup`. |
| **Сбои `kube-apiserver` при недоступности Webhook Backend аудита** | Вебхук аудита настроен в блокирующем режиме (`--audit-webhook-mode=blocking`). | Логи API-сервера содержат ошибки таймаутов вебхука; API блокирует клиентские вызовы. | Использовать пакетный асинхронный режим (`--audit-webhook-mode=batch`) либо локальный файловый бэкенд с последующей отправкой логов отдельным агентом (Vector). |
| **Не сходятся метки времени между Git, контроллером и K8s** | Рассинхронизация часов узлов кластера (clock skew). | `chronyc tracking` или `timedatectl` показывает расхождение системного времени более чем на 100 мс. | Настроить службу синхронизации времени `chrony` на всех физических серверах с локальными NTP-источниками Stratum 1/2. |
| **Шторм событий аудита и постоянные перезаписи полей** | Конфликт контроллеров: HPA управляет `replicas`, а GitOps-контроллер пытается вернуть значение из Git. | В логе аудита непрерывно чередуются запросы `patch` от HPA и `argocd-application-controller`. | Добавить поле в `ignoreDifferences` (Argo CD) или `.spec.ignore` (Flux); не указывать фиксированное число `replicas` в Git при активном HPA. |
| **Подозрительный пропуск событий при пиковых нагрузках** | Переполнение буфера файлового бэкенда API-сервера. | Метрика `apiserver_audit_requests_rejected_total > 0`. | Увеличить `--audit-log-batch-buffer-size` (например, до 50000) и `--audit-log-batch-max-wait=1s`. |
| **Flux блокирует синхронизацию: `Git verification failed`** | В репозиторий попал коммит без подписи или с ключом, отсутствующим в `secretRef`. | `flux get sources git` возвращает ошибку `commit is not signed by a trusted key`. | Добавить открытый GPG-ключ автора в Kubernetes Secret или подписать коммит доверенным ключом (`git commit -S --amend`). |
| **Argo CD ComparisonError: `Can't check signature: No public key`** | Публичный GPG-ключ разработчика не загружен в связку ключей Argo CD. | `argocd app get <app>` выводит ошибку проверки GPG. | Экспортировать GPG-ключ и обновить ConfigMap `argocd-gpg-keys-cm`. |
| **Скрытый дрейф статических подов не отображается в k8s audit log** | Изменения внесены локально на узле Control Plane в обход API-сервера. | Конфигурация кластера изменилась, но в `/var/log/kubernetes/audit.log` нет записей. | Проверить журналы `auditd` командой `ausearch -k k8s_static_pods -i` (Сценарий 8). |

## Лучшие практики

1. **Сегрегация обязанностей (Separation of Duties, SoD)**:
   - Разработчики и DevOps-инженеры не должны иметь прав на прямую модификацию production-кластера через `kubectl`. Все права на мутацию (`create`, `update`, `patch`, `delete`) делегируются исключительно ServiceAccount GitOps-контроллера.
   - Права на изменение репозиториев контролируются через матрицу `CODEOWNERS` с обязательным правилом «четырех глаз» (минимум два подтверждения от ведущих инженеров).

2. **Защита целостности журнала аудита**:
   - Файлы `/var/log/kubernetes/audit.log` на контрольных узлах должны иметь права доступа `0600` и принадлежать только пользователю `root`.
   - Немедленный экспорт во внешнее WORM-хранилище (MinIO Object Lock в режиме `COMPLIANCE`) гарантирует невозможность подделки доказательств даже при компрометации отдельного кластерного узла.
   - Сервисный аккаунт для отправки логов (Vector/Fluent Bit) должен иметь минимально достаточные права S3: разрешены `s3:PutObject` и `s3:PutObjectRetention`, но категорически запрещены `s3:DeleteObject` и `s3:DeleteObjectVersion`.

3. **Синхронизация времени высокой точности**:
   - Для корректного форензик-анализа и сопоставления миллисекундных событий между распределенными серверами обязательно использование службы `chrony` с внутренними корпоративными NTP-серверами Stratum 1/2. Допустимое расхождение часов между серверами — не более 10 мс.

4. **Минимизация шума без потери контекста**:
   - Не используйте уровень `RequestResponse` глобально. Ограничьте его только критическими ресурсами (`apps`, `networking.k8s.io`, `batch`) и CRD GitOps-контроллеров.
   - Для секретов применяйте строго `level: Metadata` во избежание попадания приватных ключей и паролей в журналы аудита.

5. **Мониторинг самой системы аудита (SRE SLIs & Metrics)**:
   Настройте алертинг в Prometheus по метрикам `kube-apiserver` и коллекторов:
   - **Скорость генерации событий**:
     ```promql
     sum(rate(apiserver_audit_event_total[5m]))
     ```
     Падение скорости до нуля свидетельствует об отказе подсистемы аудита.
   - **Потерянные события из-за переполнения буфера**:
     ```promql
     increase(apiserver_audit_requests_rejected_total[5m]) > 0
     ```
     Критический алерт: указывает на нехватку памяти/буфера или деградацию дискового ввода-вывода.
   - **Ошибки записи журнала**:
     ```promql
     increase(apiserver_audit_error_total[5m]) > 0
     ```
   - **Задержка буфера отправки Vector**:
     ```promql
     vector_buffer_byte_size{component_kind="sink", component_type="s3"} > 5e+8
     ```
     Предупреждение о накоплении более 500 МБ неотправленных логов в локальном буфере Vector.

## Дополнительная информация

Для углубленного изучения смежных механизмов безопасности и аудита обратитесь к следующим разделам базы знаний:
- **[Аудит в Kubernetes](../../Kubernetes/Security/audit.md)** — архитектура подсистемы аудита `kube-apiserver`, схема событий `audit.k8s.io/v1`, детальная настройка вебхук-бэкендов.
- **[auditd: Аудит событий безопасности](../../Linux/SystemAdministration/Logging/auditd.md)** — подсистема аудита ядра Linux, настройка правил для системных вызовов и контроль доступа к файлам.
- **[Обзор аудита и комплаенса](../../Security/audit_and_compliance_overview.md)** — регуляторные требования (PCI DSS v4.0.1, SOX, ISO 27001), методология сбора доказательств и цепочка custody.
- **[Логирование: глубокое погружение](../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)** — архитектура высоконагруженного сбора логов (Vector, Fluent Bit, форматы JSON и OpenTelemetry).
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — практическое применение Cosign, генерация SBOM и верификация подписей на admission.
- **[Управление политиками безопасности через GitOps](./gitops-policy-management.md)** — централизованная доставка политик безопасности (Kyverno, Gatekeeper) и сбор PolicyReports.
- **[Argo CD: Методы отслеживания ресурсов](../ArgoCD/argocd_resource_tracking.md)** — механизмы `annotation`, `label`, `tracking-id` для выявления принадлежности ресурсов.
- **[Argo CD: Настройка SSO через GitLab](../ArgoCD/argocd_sso_gitlab.md)** — интеграция с корпоративным OIDC-провайдером для персонализированной атрибуции действий.
- **[Argo CD Notifications](../ArgoCD/argocd_notifications.md)** — маршрутизация событий синхронизации во внешние системы аудита.
- **[GitOps: обзор методологии](../GitOps_overview.md)** — базовые принципы OpenGitOps, модели Push/Pull и детекция дрейфа.

Внешние стандарты и спецификации:
- [OpenGitOps Principles v1.0.0](https://github.com/open-gitops/documents/blob/main/PRINCIPLES.md) — вендор-нейтральный стандарт GitOps.
- [SLSA: Supply-chain Levels for Software Artifacts v1.2](https://slsa.dev/spec/v1.2/) — спецификация безопасности цепочки сборки и поставки.
- [Kubernetes Documentation: Auditing](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/) — официальное руководство по настройке аудита в Kubernetes.
- [Argo CD Documentation: Auditing](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/#auditing) — аудит и логирование безопасности в Argo CD.
- [Flux Documentation: Monitoring & Alerts](https://fluxcd.io/flux/monitoring/events/) — мониторинг событий и отправка алертов во Flux.
