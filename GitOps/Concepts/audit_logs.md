# GitOps: Журналы аудита и трассируемость

В GitOps-подходе, где Git является единым источником истины, журналы аудита и механизмы трассируемости обеспечивают критически важную возможность отслеживать жизненный цикл любого изменения — от коммита до работающего в кластере приложения. Это фундамент для соблюдения требований безопасности и комплаенса в современных инфраструктурах.

## Определения

- **Журнал аудита (Audit Log)**: Неизменяемая, хронологически упорядоченная запись о событиях в системе. В контексте GitOps фиксирует, "кто, что, когда и где изменил" как в репозитории, так и внутри GitOps-контроллера.
- **Трассируемость (Traceability)**: Способность проследить полную цепочку изменений. Включает связку: `Автор → Pull Request → Commit SHA → Pipeline ID → Image Digest → GitOps Sync ID → Kubernetes Resource UID`.
- **Kubernetes Audit Logs**: Журналы запросов к API-серверу Kubernetes (схема `audit.k8s.io/v1`). Единственный источник, фиксирующий все обращения к Control Plane — включая действия GitOps-контроллеров, операторов и людей — независимо от инструмента, которым они были выполнены.
- **Kubernetes Events**: Объекты `kind: Event`, которые генерируют компоненты системы (включая Argo CD и контроллеры Flux) для описания изменений состояния ресурсов. Хранятся в etcd с TTL по умолчанию около 1 часа (`--event-ttl` kube-apiserver) — ключевое ограничение, из-за которого события требуют отдельного механизма экспорта для долгосрочного аудита.
- **SLSA (Supply-chain Levels for Software Artifacts)**: Фреймворк безопасности для обеспечения целостности артефактов (актуальная версия спецификации — v1.2; уровни организованы в треки, основной трек `Build L0–L3`). GitOps реализует SLSA через проверку аттестаций и подписей на этапе развертывания.
- **SBOM (Software Bill of Materials)**: Формализованный перечень всех компонентов, библиотек и зависимостей программного обеспечения. В GitOps аудит включает проверку SBOM на наличие уязвимостей и соответствие лицензиям.
- **VSA (Verification Summary Attestation)**: Сводная аттестация, агрегирующая результаты проверки подписей и SLSA-уровней; используется admission-контроллерами для принятия решения о деплое. Подробности — в разделе [Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md).
- **Отклонение (Drift)**: Состояние расхождения между эталонной конфигурацией в Git и фактическим состоянием ресурсов в Runtime. Аудит дрейфа позволяет выявлять несанкционированные ручные изменения (`kubectl edit`).
- **OIDC (OpenID Connect)**: Протокол идентификации, используемый для проброса личности пользователя из системы управления кодом (GitLab, GitHub) или корпоративного IdP (Okta, Keycloak) в GitOps-инструменты (через Dex или встроенные механизмы).
- **WORM (Write Once Read Many)**: Модель хранения, при которой данные записываются однократно и не подлежат изменению или удалению в течение заданного периода (реализуется, например, через S3 Object Lock).

## Базовые концепции

### Роль аудита в GitOps-архитектуре

1.  **Безопасность (Forensics)**: Возможность восстановить хронологию инцидента. Например, если в кластер попал вредоносный образ, аудит покажет, какой коммит обновил тег и кто его одобрил.
2.  **Комплаенс (Compliance)**: Автоматизированный сбор доказательств для аудиторов (SOX, PCI DSS v4.0.1, HIPAA). Git-история с подписанными коммитами служит юридически значимым подтверждением контроля изменений.
3.  **Устранение неполадок (Root Cause Analysis)**: Мгновенное сопоставление ошибки в приложении с конкретной ревизией манифестов.
4.  **Неотказуемость (Non-repudiation)**: Использование GPG/SSH-подписей коммитов гарантирует, что автор не сможет отрицать внесение изменений.

### Трехуровневая модель прослеживаемости

Эффективный аудит требует корреляции данных на трех уровнях:

1.  **Уровень Git (Намерение)**:
    - Журналы событий репозитория (Audit Events).
    - История слияний (Merge/Pull Requests) с комментариями и результатами проверок (Check Runs).
    - Подписи коммитов для верификации Identity.
    - Защитные механики платформы: protected branches, обязательные approvals и CODEOWNERS превращают историю PR в доказательство процедуры контроля изменений, а не просто список коммитов.
2.  **Уровень GitOps-контроллера (Действие)**:
    - Логи синхронизации (Argo CD Application logs, Flux source-controller logs).
    - Записи об аутентификации пользователей через SSO.
    - События изменения состояния приложения (`Healthy` -> `Degraded`).
    - Kubernetes Events от контроллеров: Argo CD публикует события `OperationStarted` ("`<user>` initiated sync to `<revision>`") и `OperationCompleted` прямо на объекте `Application`; контроллеры Flux публикуют `Progressing`, `ReconciliationSucceeded`, `ValidationFailed` на объектах `Kustomization`/`HelmRelease`.
3.  **Уровень Kubernetes (Реальность)**:
    - `K8s Audit Logs`: Фиксация запросов к API-серверу.
    - Аннотации и лейблы ресурсов, связывающие ресурс с источником в Git: Argo CD добавляет лейбл `app.kubernetes.io/instance` (имя приложения) и аннотацию `argocd.argoproj.io/tracking-id`; контроллеры Flux — лейблы `kustomize.toolkit.fluxcd.io/name` и `kustomize.toolkit.fluxcd.io/namespace`.

### Целостность цепочки поставок (SLSA и SBOM)

Для достижения уровня SLSA Build L3 в GitOps-процессе аудит должен включать:
- **Проверку подписей образов**: Использование `Cosign` или `Notation`. GitOps-оператор (например, с помощью Kyverno или Policy Agent) блокирует деплой образов без валидной подписи.
- **Аттестацию происхождения (Provenance)**: Проверка метаданных сборки, подтверждающих, что образ был собран в доверенном окружении (например, GitHub Actions или GitLab Runner) из конкретного коммита.
- **Аудит SBOM**: Автоматическое сопоставление Digest образа с его SBOM в OCI-репозитории для верификации состава ПО перед рантаймом.
- **Сводную верификацию (VSA)**: В зрелых контурах admission-решение принимается не по сырым аттестациям, а по Verification Summary Attestation, агрегирующей все проверки. Практические политики Kyverno описаны в [Подписи артефактов](../../Security/Supply_Chain_Security/artifact_signing.md).

## Практические сценарии

### Сценарий 1: Корреляция действий пользователя через Argo CD и SSO

**Предварительные требования**: настроенный SSO/OIDC (Dex или прямой OIDC-провайдер), чтобы каждое действие в UI/API привязывалось к реальной личности, а не к общему аккаунту `admin`; доступ `kubectl` к namespace `argocd`.

**Проблема**: Необходимо узнать, кто инициировал принудительную синхронизацию (`Hard Refresh`) приложения.

**Действия**:

1.  **Первичный источник — Kubernetes Events на объекте `Application`**: Argo CD фиксирует там каждое действие с указанием инициатора и ревизии (официальный раздел "Auditing" документации безопасности Argo CD).
    ```bash
    # События конкретного приложения (Argo CD v2.x/v3.x)
    kubectl events -n argocd --for application/payments
    # → result:
    # LAST SEEN  TYPE     REASON              OBJECT                MESSAGE
    # 2m         Normal   OperationStarted    Application/payments  argocd-server admin@example.com initiated sync to HEAD (d4e5f6g...)
    # 1m         Normal   OperationCompleted  Application/payments  Sync operation to d4e5f6g... succeeded
    ```
    Сообщение события `OperationStarted` содержит имя пользователя (полученное из OIDC/JWT-токена) и целевую ревизию — это и есть связка "личность → ревизия".
2.  **Поиск в логах `argocd-server`**: При интеграции с Dex/OIDC логи содержат `email` или `username`. Для машинной обработки включите JSON-формат логов (флаг `--logformat json` у компонентов Argo CD).
    ```bash
    # Поиск события синхронизации для конкретного приложения
    kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server | grep "initiated sync"
    # → result:
    # {"time":"2026-08-05T12:00:00Z","level":"info","msg":"User 'admin@example.com' initiated sync of app 'payments' to revision 'd4e5f6g'"}
    ```
    Дополнительно: логи API-запросов Argo CD помечаются служебным полем `security`, что упрощает их фильтрацию в SIEM.
3.  **Проверка Audit Logs в UI**: Вкладка "Status History" в Argo CD отображает историю синхронизаций с указанием ревизии и инициатора.

**Валидация**: выполните тестовую синхронизацию под своей учетной записью SSO и убедитесь, что в событии `OperationStarted` фигурирует ваш логин, а не `admin`.

**Ограничение**: если пользователи работают под общим локальным аккаунтом `admin`, атрибуция невозможна — все действия выглядят одинаково. Для расследований обязателен SSO; локальный `admin` следует отключить или жестко ограничить через RBAC.

### Сценарий 2: Расследование ручных изменений (Drift Audit)

**Проблема**: Ресурс `Deployment` был изменен в обход Git.

**Действия**:

1.  **Детекция в GitOps**:
    - Argo CD пометит приложение как `OutOfSync` (событие `ResourceUpdated` с сообщением вида `Updated sync status: -> OutOfSync`).
    - Flux при каждой реконсилиации (по `spec.interval`, минимум 60 секунд) выполняет server-side apply dry-run, обнаруживает дрейф и перезаписывает поля. Факт коррекции виден в событиях `Progressing` (перечень измененных объектов) и `ReconciliationSucceeded` на объекте `Kustomization`. Отдельного события с причиной типа `DriftDetected` во Flux нет — расхождение диагностируется по содержимому этих событий.
    ```bash
    # Просмотр событий Kustomization во Flux (CLI, Flux v2.x)
    flux events --for Kustomization/webapp -n apps
    # → result:
    # LAST SEEN  TYPE     REASON                   OBJECT                MESSAGE
    # 30s        Normal   Progressing              Kustomization/webapp  Deployment/apps/api-service configured
    # 29s        Normal   ReconciliationSucceeded  Kustomization/webapp  Reconciliation finished in 1.2s, next run in 10m0s
    ```
2.  **Поиск виновного в K8s Audit Logs** — единственный источник, где зафиксирован сам запрос `kubectl edit/patch` вместе с личностью исполнителя:
    ```json
    // Фрагмент K8s Audit Log
    {
      "verb": "patch",
      "user": { "username": "dev-user-01" },
      "objectRef": { "resource": "deployments", "name": "api-service" },
      "userAgent": "kubectl/v1.30.0"
    }
    ```
    Практичный способ поиска в выгруженном журнале — фильтрация через `jq` с исключением действий самого GitOps-контроллера:
    ```bash
    jq 'select(.verb == "patch" or .verb == "update" or .verb == "delete")
        | select(.objectRef.name == "api-service")
        | select((.user.username | startswith("system:serviceaccount:argocd")) | not)
        | {time: .stageTimestamp, user: .user.username, verb: .verb, ua: .userAgent}' audit.log
    # → result:
    # {"time":"2026-08-05T11:58:02Z","user":"dev-user-01","verb":"patch","ua":"kubectl/v1.30.0"}
    ```
3.  **Автоматическое восстановление**: Если включен `Self-healing`, GitOps-контроллер немедленно перезапишет изменения. В журнале аудита это зафиксируется как два последовательных события: `Manual Change` (от пользователя) и `Sync/Reconcile` (от контроллера).

**Граничные случаи**:

- **HPA/операторы как "легитимный дрейф"**: поле `spec.replicas`, управляемое HorizontalPodAutoscaler, будет постоянно перезаписываться GitOps-контроллером и генерировать шум. Корректное решение — исключить поле из сверки (Argo CD: `ignoreDifferences`; Flux: `.spec.ignore`), а не бороться с событиями.
- **Сохранение ручных полей во Flux**: чтобы точечные `kubectl`-правки не затирались, применяйте их field manager'ом `flux-client-side-apply` либо внесите поля в `.spec.ignore`.
- **Suspend скрывает дрейф**: `spec.suspend: true` у `Kustomization` (Flux) или `spec.syncPolicy` с паузой (Argo CD) приостанавливает детекцию и коррекцию расхождений. Список приостановленных объектов должен периодически проверяться:
    ```bash
    kubectl get kustomizations -A -o jsonpath='{range .items[?(@.spec.suspend==true)]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
    # → result:
    # apps/legacy-billing
    ```

### Сценарий 3: Настройка политики аудита для GitOps-агентов

Для минимизации шума и максимальной информативности рекомендуется следующая политика Kubernetes:

```yaml
# audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  # Высокий уровень детализации для действий контроллеров (Argo CD / Flux)
  - level: RequestResponse
    users: 
      - "system:serviceaccount:argocd:argocd-application-controller"
      - "system:serviceaccount:flux-system:kustomize-controller"
    verbs: ["create", "update", "patch", "delete"]
    resources:
      - group: "apps"
        resources: ["deployments", "statefulsets", "daemonsets"]
      - group: ""
        resources: ["secrets", "configmaps", "services"]

  # Логирование только метаданных для чтения (минимизация объема)
  - level: Metadata
    verbs: ["get", "list", "watch"]
```

**Пояснение параметров**:
- `level: RequestResponse` — сохраняет полное тело запроса и ответа (видно, что именно изменил контроллер); для `secrets` это означает запись содержимого в лог, поэтому доступ к журналу должен быть ограничен так же строго, как к самим секретам.
- `level: Metadata` — только заголовки запроса без тел: фиксирует, кто и когда читал, но не раскрывает содержимое.
- Правила применяются сверху вниз, срабатывает первое совпавшее; все, что не совпало ни с одним правилом, попадает под неявное финальное правило `None` (не логируется вовсе). Если нужен полный охват — добавьте последним правилом `- level: Metadata`.
- Для снижения объема добавляйте в правила `omitStages: ["RequestReceived"]` — запись формируется на стадии `ResponseComplete`/`Panic`, а сырой этап приема запроса не дублируется.

**Подключение политики к kube-apiserver** (флаги конфигурации API-сервера):

```yaml
# Фрагмент манифеста static pod / kubeadm-конфигурации kube-apiserver
spec:
  containers:
    - command:
        - kube-apiserver
        - --audit-policy-file=/etc/kubernetes/audit/audit-policy.yaml   # путь к политике внутри пода
        - --audit-log-path=/var/log/kubernetes/audit.log               # файл бэкенда (file backend)
        - --audit-log-format=json                                      # структурированный формат для парсеров
        - --audit-log-maxage=365                                       # ротация: хранить 365 дней (базовый уровень PCI DSS)
        - --audit-log-maxbackup=10                                     # максимальное число ротированных файлов
        - --audit-log-maxsize=200                                      # размер файла (МБ) до ротации
```

Файл политики необходимо смонтировать в под API-сервера как volume. В managed-кластерах (EKS/GKE/AKS) политика настраивается провайдером, а не вручную — используйте облачные механизмы (CloudTrail, Cloud Audit Logs) и их интеграцию с GitOps.

**Валидация**: после перезапуска API-сервера выполните любое изменение (например, `kubectl edit configmap -n default`) и проверьте появление записи:

```bash
tail -n 1 /var/log/kubernetes/audit.log | jq '{verb, user: .user.username, obj: .objectRef.name}'
# → result:
# {"verb":"update","user":"dev-user-01","obj":"kube-root-ca.crt"}
```

### Сценарий 4: Экспорт событий контроллеров (борьба с TTL)

Kubernetes Events живут по умолчанию около 1 часа (`--event-ttl`) — этого недостаточно для расследований. События Argo CD и Flux нужно переносить в постоянное хранилище одним из способов:

1.  **Агрегатор событий**: разверните [event-exporter](https://github.com/opsgenie/kubernetes-event-exporter) или eventrouter, который подписывается на события кластера и отправляет их в Loki/Elasticsearch/S3.
2.  **Argo CD Notifications**: настройте webhook-провайдер, отправляющий события синхронизации во внешнюю систему. Готовый пример триггеров `on-sync-running`/`on-sync-succeeded` — в разделе [Argo CD Notifications](../ArgoCD/argocd_notifications.md).
3.  **Flux notification-controller**: объекты `Alert` пересылают события контроллеров во внешний `Provider` (webhook, Slack, Azure Event Hub):
    ```yaml
    apiVersion: notification.toolkit.fluxcd.io/v1beta3
    kind: Alert
    metadata:
      name: audit-webapp
      namespace: flux-system
    spec:
      providerRef:
        name: audit-webhook          # Provider с endpoint вашей SIEM/лог-платформы
      eventSeverity: info            # info: созданные/измененные объекты + ошибки
      eventMetadata:
        cluster: prod-eu-central     # метка кластера для корреляции в централизованном хранилище
      selector:
        matchLabels:
          kustomize.toolkit.fluxcd.io/name: webapp
    ```

**Валидация**: инициируйте синхронизацию и убедитесь, что событие появилось во внешнем хранилище через время, превышающее TTL (`--event-ttl`), например на следующий день.

### Сценарий 5: Экспорт и долгосрочное хранение (WORM)

Согласно требованию 10.5.1 стандарта PCI DSS v4.0.1, история журналов аудита должна храниться минимум 12 месяцев, при этом журналы за последние 3 месяца должны быть доступны для анализа немедленно (в "горячем" поисковом индексе, без восстановления из архива). Аналогичные и более жесткие требования встречаются в других стандартах (HIPAA — до 6 лет, SOX — до 7 лет); при пересечении нескольких режимов применяется самый длинный срок.

**Реализация**:
1.  **Сбор**: Использование `Vector` или `Fluent Bit` для агрегации логов из Git, GitOps-контроллеров и K8s API.
    ```yaml
    # Фрагмент конфигурации Vector: прием audit.log kube-apiserver и отправка в S3
    # vector.yaml
    sources:
      k8s_audit:
        type: file                 # источник: чтение файла журнала API-сервера
        include:
          - /var/log/kubernetes/audit.log
        read_from: beginning       # не пропускать существующие записи
    sinks:
      s3_archive:
        type: aws_s3
        inputs: ["k8s_audit"]
        bucket: "k8s-audit-archive"
        key_prefix: "audit/%Y/%m/%d/"   # партиционирование по дате — упрощает выборку и lifecycle
        compression: zstd
        encoding:
          codec: json
    ```
2.  **Транспорт**: Отправка в централизованное хранилище (Grafana Loki, Elasticsearch или S3-совместимое хранилище). Для выполнения требования "3 месяца онлайн" используйте двухуровневую схему: поисковый индекс (Loki/Elasticsearch) с retention ≥ 90 дней + архив в объектном хранилище на полный срок.
3.  **Защита**: Включение **Object Lock** (WORM) на бакете S3 для предотвращения удаления или модификации логов в течение заданного периода.
    - Object Lock можно включить только при создании бакета — на существующем бакете это невозможно; планируйте заранее.
    - Режимы: `Governance` (обход возможен у holders специальной привилегии) и `Compliance` (не может быть отключен никем, включая root) — для регуляторных требований выбирайте `Compliance` осознанно, так как это необратимо.

**Валидация**:

```bash
# Проверка политики удержания объекта
aws s3api get-object-retention --bucket k8s-audit-archive --key audit/2026/08/24/1.log
# → result:
# {"Retention":{"Mode":"COMPLIANCE","RetainUntilDate":"2027-08-24T00:00:00+00:00"}}
```

## Типичные проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| События синхронизации отсутствуют при расследовании недельной давности | TTL Kubernetes Events (~1 час), события не экспортировались | Настроить экспорт (Сценарий 4); до внедрения — восстанавливать картину по логам контроллеров и K8s Audit Logs |
| Все действия в Argo CD атрибутированы `admin` | Общий локальный аккаунт вместо SSO/OIDC | Внедрить OIDC/Dex (Сценарий 1), отключить общий аккаунт |
| K8s Audit Logs пишутся не полностью или теряются при пиках нагрузки | File backend буферизует и режет события при переполнении (`--audit-log-truncate-*`, медленный диск) | Мониторить метрики `apiserver_audit_*`; вынести журнал на отдельный быстрый том; при высоких требованиях — webhook backend с гарантиями доставки |
| Часовые метки событий не сходятся между Git, контроллером и K8s | Расхождение часов узлов (clock skew) | NTP/chrony на всех узлах; при корреляции учитывать часовые пояса источников |
| Записи о чтении секретов отсутствуют | Правило аудита не покрывает `get secrets` или стоит правило более низкого уровня выше нужного | Пересмотреть порядок правил политики (Сценарий 3): правила применяются сверху вниз |
| Flux постоянно перезаписывает поле, генерируя ложные события дрейфа | Полем управляет другой контроллер (HPA, cert-manager) | Исключить поле через `.spec.ignore` (Flux) или `ignoreDifferences` (Argo CD) |

## Дополнительная информация

Для глубокого понимания стандартов комплаенса и общих принципов логирования обратитесь к следующим разделам:
- **[Обзор аудита и комплаенса](../../Security/audit_and_compliance_overview.md)** — общие требования (ISO 27001, SOC 2).
- **[Логирование: глубокое погружение](../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)** — архитектура сбора и форматы (JSON, OpenTelemetry).
- **[Детекция и устранение дрейфа](../GitOps_overview.md#детекция-и-устранение-дрейфа-drift-detection)** — механизмы выявления расхождений.
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — Cosign, Notation, VSA и проверка подписей на admission.

Внешние ресурсы:
- [SLSA: Спецификация v1.2 (трек Build L0–L3)](https://slsa.dev/spec/v1.2/)
- [Argo CD: Auditing and Logging (Security)](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/#auditing)
- [Flux: Events monitoring](https://fluxcd.io/flux/monitoring/events/)
