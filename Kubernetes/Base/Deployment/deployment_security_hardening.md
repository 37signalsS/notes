# Безопасность Deployment в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

Практическое руководство по комплексному hardening манифестов `Deployment` для production-среды: изоляция контейнеров, разграничение прав ядра Linux, предотвращение эскалации привилегий, интеграция с Pod Security Admission, нативная валидация через CEL (ValidatingAdmissionPolicy) и Kyverno, сетевая изоляция и эксплуатационная диагностика в контексте DevOps, SRE и системного администрирования.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes v1.30+ (версии с GA-поддержкой встроенного контроллера `ValidatingAdmissionPolicy`, нативного поля `securityContext.appArmorProfile` с v1.31 и стабильного Pod Security Admission).
- Установленный и настроенный CLI-клиент `kubectl` с правами администратора или оператора пространства имен.
- Базовое понимание объектов ядра: [Deployment](./index.md), [Манифест Deployment](./deployment_manifest.md), [Pod Security Context](../../Security/pod_security_context.md), [Pod Best Practices](../Pod/pod_best_practices.md) и [Основы Secret](../secrets/secrets_basics.md).
- Настроенный сетевой плагин (CNI) с поддержкой NetworkPolicy (Cilium, Calico или kube-ovn).
- Утилиты статического анализа и валидации: `kubeconform` (см. [Kubeconform](../../ToolsUtilities/kubeconform_overview.md)), `kubesec` (см. [Kubesec](../../Security/kubesec.md)) или `trivy` (см. [Trivy: сканирование уязвимостей](../../../Docker/Docker_security/vulnerability_scanning.md)).

---

## 1. Определения

**Hardening Deployment** — процесс устранения избыточных прав, закрытия векторов атак и ужесточения конфигурации объекта `Deployment` и его шаблона пода (`spec.template`) в соответствии с отраслевыми стандартами (CIS Kubernetes Benchmark, NSA/CISA Kubernetes Hardening Guidance).

**Defense in Depth (Многоуровневая защита)** — стратегия информационной безопасности, при которой защита выстраивается на независимых эшелонах (Admission Control → Namespace PSA → Pod/Container SecurityContext → NetworkPolicy → RBAC / ServiceAccount), гарантируя, что преодоление одного барьера не приводит к компрометации узла или кластера.

**Pod Security Standards (PSS)** — официальная спецификация Kubernetes, определяющая три профиля безопасности для подов:
- `Privileged` — полное отсутствие ограничений (для системных компонентов, CNI, DaemonSet хранения).
- `Baseline` — минимальные ограничения, предотвращающие известные эскалации привилегий при сохранении стандартных настроек образов.
- `Restricted` — жестко изолированный профиль для production-нагрузок (запрет root, mandatory drop capabilities, запрет privilege escalation, seccomp).

**Pod Security Admission (PSA)** — встроенный admission-плагин ядра Kubernetes, контролирующий создание подов на соответствие профилям PSS на основе меток пространства имен (`enforce`, `audit`, `warn`).

**Security Context** — декларативная спецификация прав процесса в Linux-контейнере, настраиваемая на уровне пода (`spec.template.spec.securityContext`) и на уровне контейнера (`spec.template.spec.containers[*].securityContext`).

**Linux Capabilities** — механизм разделения суперпользовательских привилегий `root` на дискретные разрешения (например, `CAP_NET_BIND_SERVICE`, `CAP_CHOWN`, `CAP_SYS_ADMIN`), позволяющий забрать у процесса все системные права (`drop: ["ALL"]`) и выдать только строго необходимые.

**Seccomp (Secure Computing Mode)** — механизм ядра Linux, фильтрующий доступные системные вызовы (syscalls) для процесса контейнера. Профиль `RuntimeDefault` блокирует опасные системные вызовы, не требующиеся типовым приложениям.

**AppArmor** — модуль безопасности ядра Linux (LSM), реализующий мандатный контроль доступа (MAC) на основе путей к файлам. Начиная с Kubernetes 1.30 (Beta) и 1.31 (GA), настраивается через нативное поле `securityContext.appArmorProfile`, заменив устаревшие аннотации.

**Read-only Root Filesystem** — режим монтирования корневой файловой системы контейнера только для чтения (`readOnlyRootFilesystem: true`), блокирующий модификацию бинарных файлов, подмену библиотек и загрузку вредоносных скриптов при компрометации приложения.

**Least Privilege ServiceAccount** — паттерн назначения выделенного сервисного аккаунта с отключенным автомонтированием токена (`automountServiceAccountToken: false`), исключающий возможность несанкционированного взаимодействия с `kube-apiserver` в случае захвата пода.

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA с v1.30) механизм валидации манифестов на базе Common Expression Language (CEL), работающий внутри процесса `kube-apiserver` без сетевых задержек и риска отказа внешних вебхуков.

---

## 2. Базовые концепции и архитектура

### Эшелонированная модель защиты Deployment

Hardening stateless-нагрузки охватывает пять изолированных уровней:

```text
Запрос в API (kubectl / CI/CD)
       │
       ▼
[Уровень 1: Admission Control] ────────► ValidatingAdmissionPolicy (CEL) / Kyverno
       │                                  (Блокировка манифестов без hardening)
       ▼
[Уровень 2: Pod Security Admission] ───► Проверка Namespace (enforce: restricted)
       │                                  (Контроль профилей PSS ядром API-сервера)
       ▼
[Уровень 3: SecurityContext (Pod/Ctr)] ─► Linux Namespaces, Capabilities, Seccomp,
       │                                  AppArmor, UID/GID, readOnlyRootFilesystem
       ▼
[Уровень 4: Изоляция хранилища/DoS] ───► emptyDir с sizeLimit, квоты CPU/Memory/PIDs
       │
       ▼
[Уровень 5: Сетевая изоляция] ─────────► NetworkPolicy (Default Deny Ingress/Egress)
```

### Разграничение Pod SecurityContext и Container SecurityContext

Поля контекста безопасности разделены по уровням ответственности и наследования:

| Параметр | Уровень Pod (`spec.template.spec.securityContext`) | Уровень Container (`spec.containers[*].securityContext`) | Поведение и область действия |
|:---|:---:|:---:|:---|
| `runAsNonRoot` | Да | Да | Контейнер переопределяет значение пода. Требует UID != 0. |
| `runAsUser` / `runAsGroup` | Да | Да | Задает явные UID/GID. Контейнер переопределяет значение пода. |
| `fsGroup` | Да | Нет | Применяется ко всем томам, монтируемым в под. |
| `fsGroupChangePolicy` | Да | Нет | `OnRootMismatch` предотвращает задержки рекурсивного `chown`. |
| `seccompProfile` | Да | Да | Профиль seccomp для фильтрации системных вызовов ядра. |
| `appArmorProfile` | Да | Да | Профиль AppArmor (нативное поле с v1.30+, GA с v1.31). |
| `allowPrivilegeEscalation` | Нет | Да | Управляет флагом ядра `no_new_privs`. |
| `readOnlyRootFilesystem` | Нет | Да | Монтирует rootfs контейнера в режиме `ro`. |
| `capabilities` | Нет | Да | Добавление (`add`) и сброс (`drop`) Linux capabilities. |
| `privileged` | Нет | Да | Запуск с полными правами суперпользователя на хосте (запрещено). |

> Подробный теоретический разбор всех параметров см. в [Pod Security Context](../../Security/pod_security_context.md).

### Особенность взаимодействия Deployment и Pod Security Admission

Критический архитектурный нюанс для инженеров DevOps и SRE:
1. При применении манифеста `Deployment` в пространство имен с политикой `pod-security.kubernetes.io/enforce: restricted` объект `Deployment` создается успешно, если валидация схемы API пройдена. API-сервер возвращает предупреждение (`Warning: would violate PodSecurity`), но **не отклоняет** сам Deployment.
2. Контроллер `deployment-controller` успешно создает дочерний объект `ReplicaSet`.
3. Контроллер `replicaset-controller` пытается создать объект `Pod`.
4. Запрос на создание пода перехватывается admission-плагином PSA в фазе `enforce`. Так как под нарушает требования `restricted`, API-сервер **блокирует создание пода** с ошибкой `403 Forbidden` (`violates PodSecurity "restricted:latest"`).
5. Итог: Deployment переходит в состояние ожидания с `0/N` готовых реплик. Ошибка не видна в `kubectl get pods` (поды отсутствуют) и фиксируется только в событиях `ReplicaSet` (`kubectl describe rs`).

### Архитектура Read-Only Root Filesystem и временных каталогов

При включении `readOnlyRootFilesystem: true` контейнер теряет возможность производить запись в любые директории, кроме явно примонтированных томов. Большинству приложений требуются каталоги для временных файлов (`/tmp`), кэша (`/var/cache`) и сокетов:

- Запись должна перенаправляться в специализированные тома `emptyDir`.
- **Защита от DoS диска хоста:** Неограниченный `emptyDir` позволяет процессу исчерпать дисковое пространство узла (root volume). Обязательно задается параметр `sizeLimit`.
- **Использование оперативной памяти:** Для высокопроизводительных временных файлов или повышения безопасности (данные удаляются при остановке пода и не пишутся на диск) используется `emptyDir.medium: Memory` (tmpfs). Объем tmpfs учитывается в `resources.limits.memory` контейнера.

---

## 3. Практические сценарии

### Сценарий 1: Эталонный production-манифест Deployment (PSS Restricted)

Манифест полностью удовлетворяет требованиям CIS Kubernetes Benchmark и профилю Pod Security Standards Restricted:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-service
  namespace: production
  labels:
    app.kubernetes.io/name: secure-service
    app.kubernetes.io/instance: secure-service-prod
    app.kubernetes.io/version: "1.4.2"
    app.kubernetes.io/part-of: billing-system
    app.kubernetes.io/managed-by: gitops
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 300
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: secure-service
  template:
    metadata:
      labels:
        app.kubernetes.io/name: secure-service
        app.kubernetes.io/instance: secure-service-prod
    spec:
      # Уровень 1: Безопасность на уровне Pod
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        fsGroupChangePolicy: "OnRootMismatch"
        seccompProfile:
          type: RuntimeDefault
        appArmorProfile:
          type: RuntimeDefault

      # Отключение автомонтирования токена ServiceAccount
      automountServiceAccountToken: false
      serviceAccountName: secure-service-sa

      # Изоляция ядра: запрет доступа к пространствам имен узла
      hostNetwork: false
      hostPID: false
      hostIPC: false

      # Защита от вытеснения критичных нагрузок
      priorityClassName: high-priority

      # Корректное завершение соединений
      terminationGracePeriodSeconds: 45

      containers:
      - name: app
        # Пиннинг образа по криптографическому дайджесту для гарантии неизменяемости
        image: internal-registry.corp/apps/secure-service:1.4.2@sha256:7b55f171097fa6089e900996fa1548e351ff8cfd6006e87f2ffbe7912da6d895
        imagePullPolicy: IfNotPresent

        # Уровень 2: Жесткие ограничения процессов контейнера
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          privileged: false
          runAsNonRoot: true
          runAsUser: 10001
          runAsGroup: 10001
          capabilities:
            drop:
            - ALL

        ports:
        - name: http
          containerPort: 8080
          protocol: TCP

        # Защита от Resource Exhaustion (DoS)
        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
            ephemeral-storage: "128Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
            ephemeral-storage: "256Mi"

        startupProbe:
          httpGet:
            path: /healthz
            port: http
          failureThreshold: 30
          periodSeconds: 5
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 3
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /live
            port: http
          initialDelaySeconds: 5
          periodSeconds: 15

        # Монтирование доступных для записи каталогов при read-only rootfs
        volumeMounts:
        - name: tmp-dir
          mountPath: /tmp
        - name: cache-dir
          mountPath: /var/cache/app

      volumes:
      # tmpfs в оперативной памяти с квотой для сессионных временных файлов
      - name: tmp-dir
        emptyDir:
          medium: Memory
          sizeLimit: 64Mi
      # Изолированный том для дискового кэша с защитой от переполнения узла
      - name: cache-dir
        emptyDir:
          sizeLimit: 128Mi
```

---

### Сценарий 2: Настройка Pod Security Admission (PSA) в Namespace

Для принудительного соблюдения стандартов безопасности пространство имен размечается стандартными метками PSA:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Блокировать создание подов, нарушающих Restricted
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    # Логировать нарушения в audit log API-сервера
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    # Выдавать предупреждения в stderr клиента при kubectl apply
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
```

Проверка соответствия Deployment политикам пространства имен без фактического создания ресурсов:

```bash
kubectl apply -f deployment.yaml --dry-run=server -n production
# → deployment.apps/secure-service created (server dry run)
```

Если манифест содержит нарушения (например, отсутствует `drop: ["ALL"]` или включен `privileged: true`), сервер вернет отказ:

```bash
# Пример вывода при наличии нарушений:
# → Error from server (Forbidden): error when creating "deployment.yaml":
# → pods "secure-service-..." is forbidden: violates PodSecurity "restricted:latest":
# → allowPrivilegeEscalation != false, unrestricted capabilities, runAsNonRoot != true
```

---

### Сценарий 3: Сетевая микросегментация через NetworkPolicy

Каждый hardened Deployment изолируется сетевыми политиками. По умолчанию блокируется весь входящий и исходящий трафик (Default Deny), после чего разрешаются только легитимные потоки:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: secure-service-isolation
  namespace: production
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: secure-service
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешен вход только от Ingress-контроллера или сервиса фронтенда
  - from:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
      namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: production
    ports:
    - protocol: TCP
      port: 8080
  egress:
  # 1. Доступ к кластерному DNS (CoreDNS)
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # 2. Доступ к базе данных PostgreSQL во внутреннем контуре
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: postgresql
    ports:
    - protocol: TCP
      port: 5432
```

> Полная база сценариев сетевой фильтрации: [NetworkPolicy: практические сценарии](../../Networking/Network/NetworkPolicy/practical_scenarios.md).

---

### Сценарий 4: Нативная валидация Deployment через ValidatingAdmissionPolicy (CEL)

Kubernetes 1.30+ поддерживает нативную валидацию манифестов без развертывания внешних вебхуков. Политика проверяет манифесты `Deployment` на этапе запроса к API:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: enforce-deployment-hardening
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: ["apps"]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["deployments"]
  validations:
  # Проверка запрета запуска от root
  - expression: "object.spec.template.spec.securityContext.runAsNonRoot == true || object.spec.template.spec.containers.all(c, has(c.securityContext) && c.securityContext.runAsNonRoot == true)"
    message: "В Deployment обязателен параметр runAsNonRoot: true на уровне Pod или всех контейнеров."
  # Проверка запрета эскалации привилегий
  - expression: "object.spec.template.spec.containers.all(c, has(c.securityContext) && c.securityContext.allowPrivilegeEscalation == false)"
    message: "Все контейнеры Deployment обязаны иметь allowPrivilegeEscalation: false."
  # Проверка сброса всех capabilities
  - expression: "object.spec.template.spec.containers.all(c, has(c.securityContext) && has(c.securityContext.capabilities) && has(c.securityContext.capabilities.drop) && c.securityContext.capabilities.drop.exists(cap, cap == 'ALL'))"
    message: "Все контейнеры Deployment обязаны сбрасывать capabilities (drop: ['ALL'])."
  # Проверка режима read-only для корневой файловой системы
  - expression: "object.spec.template.spec.containers.all(c, has(c.securityContext) && c.securityContext.readOnlyRootFilesystem == true)"
    message: "Корневая файловая система контейнеров обязана быть только для чтения (readOnlyRootFilesystem: true)."
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: enforce-deployment-hardening-binding
spec:
  policyName: enforce-deployment-hardening
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kube-system", "kube-node-lease"]
```

> Подробнее о механизмах CEL и сравнении движков политик см. в [Ограничения RBAC и ValidatingAdmissionPolicy](../../Security/rbac/limitations_opa.md).

---

### Сценарий 5: Валидация безопасности Deployment через Kyverno ClusterPolicy

Если в кластере развернут Kyverno, политика гарантирует, что ни один Deployment не попадет в кластер с небезопасными настройками:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-unhardened-deployments
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: check-security-context
    match:
      any:
      - resources:
          kinds:
          - Deployment
    exclude:
      any:
      - resources:
          namespaces:
          - kube-system
    validate:
      message: "Deployment не соответствует требованиям hardening (readOnlyRootFilesystem, drop ALL, allowPrivilegeEscalation=false)."
      pattern:
        spec:
          template:
            spec:
              automountServiceAccountToken: false
              containers:
              - securityContext:
                  allowPrivilegeEscalation: false
                  readOnlyRootFilesystem: true
                  capabilities:
                    drop:
                    - ALL
```

> Концепции и практики работы с Kyverno: [Kyverno](../../Security/kyverno/concepts.md).

---

### Сценарий 6: Профили Security Context под разные типы рабочих нагрузок

| Стек / Технология | Особенности запуска | Рекомендуемая конфигурация SecurityContext | Необходимые точки монтирования (emptyDir) |
|:---|:---|:---|:---|
| **Go / Rust / C++ (статические бинарники)** | Образы `scratch` или `distroless`, статические бинарники, отсутствие оболочки sh/bash | `readOnlyRootFilesystem: true`<br>`runAsNonRoot: true`<br>`runAsUser: 65534` (nobody)<br>`drop: ["ALL"]`<br>`seccompProfile: RuntimeDefault` | `/tmp` (если приложение создает временные файлы сокетов) |
| **Java / JVM (Spring Boot, Quarkus)** | Требует запись в каталог временных файлов JVM, кэш JIT-компилятора, `cgroup` память | `readOnlyRootFilesystem: true`<br>`runAsNonRoot: true`<br>`runAsUser: 10001`<br>`drop: ["ALL"]`<br>JVM флаг: `-Djava.io.tmpdir=/tmp` | `/tmp` (emptyDir, sizeLimit: 256Mi)<br>`/app/cache` (emptyDir) |
| **Nginx (Unprivileged)** | Порты <1024 заблокированы для non-root; Nginx пишет в pid-файлы и кэш proxy | `readOnlyRootFilesystem: true`<br>`runAsNonRoot: true`<br>`runAsUser: 101` (nginx)<br>`drop: ["ALL"]`<br>Слушать порт 8080 вместо 80 | `/tmp`<br>`/var/run` (для `nginx.pid`)<br>`/var/cache/nginx` (размер по нагрузке) |
| **Node.js / Python** | Интерпретируемые языки; возможна компиляция pyc/кэш npm в домашнем каталоге | `readOnlyRootFilesystem: true`<br>`runAsNonRoot: true`<br>`runAsUser: 10001`<br>`drop: ["ALL"]`<br>ENV `HOME=/tmp` или выделенный путь | `/tmp`<br>`/app/.cache`<br>`/var/log/app` |
| **PostgreSQL / MySQL (On-Prem / Stateful)** | Требует согласования прав на тома хранения (PV/PVC) под конкретный системный UID | `runAsNonRoot: true`<br>`runAsUser: 999` (postgres)<br>`fsGroup: 999`<br>`fsGroupChangePolicy: "OnRootMismatch"` | `/var/lib/postgresql/data` (PVC)<br>`/var/run/postgresql` (emptyDir) |

---

### Сценарий 7: Проверка целостности цепочки поставок (Supply Chain) и Cosign

Для исключения подмены образов в манифестах `Deployment` используется валидация криптографических подписей через Kyverno и Cosign:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-deployment-images
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-signature-rule
    match:
      any:
      - resources:
          kinds:
          - Deployment
    verifyImages:
    - imageReferences:
      - "internal-registry.corp/apps/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE7p+Yf3p8kR2hC9qX6eQ2Lz5F9r8Y
              mN3sW2v8xY0uP1q4t6jK5nN2u8qP7v1wX0yZ3A4bC5dE6fG7hI8jK9lM0w==
              -----END PUBLIC KEY-----
```

---

## 4. Операции и команды

### Аудит параметров безопасности запущенных Deployment

Проверка наличия опасных настроек (привилегированные контейнеры, root-пользователь, разрешенная эскалация прав) во всех Deployment пространства имен:

```bash
kubectl get deploy -n production -o json | jq -r '.items[] | {
  deployment: .metadata.name,
  containers: [.spec.template.spec.containers[] | {
    name: .name,
    privileged: (.securityContext.privileged // false),
    allowPrivilegeEscalation: (.securityContext.allowPrivilegeEscalation // true),
    readOnlyRootFilesystem: (.securityContext.readOnlyRootFilesystem // false),
    runAsNonRoot: (.securityContext.runAsNonRoot // (.spec.template.spec.securityContext.runAsNonRoot // false)),
    dropCapabilities: (.securityContext.capabilities.drop // [])
  }]
}'
# → {
# →   "deployment": "secure-service",
# →   "containers": [
# →     {
# →       "name": "app",
# →       "privileged": false,
# →       "allowPrivilegeEscalation": false,
# →       "readOnlyRootFilesystem": true,
# →       "runAsNonRoot": true,
# →       "dropCapabilities": ["ALL"]
# →     }
# →   ]
# → }
```

Поиск Deployment, у которых включено автомонтирование токена `ServiceAccount`:

```bash
kubectl get deploy -A -o json | jq -r '.items[] | select(.spec.template.spec.automountServiceAccountToken != false) | "\(.metadata.namespace)/\(.metadata.name)"'
# → kube-system/coredns
# → ingress-nginx/ingress-nginx-controller
```

### Статический анализ и проверка манифестов в CI/CD

Проверка манифеста на соответствие официальной схеме Kubernetes через `kubeconform`:

```bash
kubeconform -strict -summary -kubernetes-version 1.32.0 deployment.yaml
# → Summary: 1 resources found, 1 valid, 0 invalid, 0 errors, 0 skipped
```

Оценка уровня рисков манифеста с помощью `kubesec`:

```bash
kubesec scan deployment.yaml
# → [
# →   {
# →     "object": "Deployment/secure-service.production",
# →     "valid": true,
# →     "score": 9,
# →     "scoring": {
# →       "passed": [
# →         { "id": "ServiceAccountTokenNoAutoMount", "points": 3 },
# →         { "id": "CapDropAll", "points": 1 },
# →         { "id": "ReadOnlyRootFilesystem", "points": 1 },
# →         { "id": "RunAsNonRoot", "points": 1 },
# →         { "id": "PrivilegeEscalation", "points": 3 }
# →       ]
# →     }
# →   }
# → ]
```

Сканирование манифеста на соответствие стандартам CIS и NSA через `trivy`:

```bash
trivy config deployment.yaml --severity HIGH,CRITICAL
# → 2026-10-13T19:25:00Z INFO Misconfiguration scanning is enabled
# → deployment.yaml (kubernetes)
# → Tests: 24 (SUCCESSES: 24, FAILURES: 0, EXCEPTIONS: 0)
# → Failures: 0 (HIGH: 0, CRITICAL: 0)
```

Локальная проверка политик Kyverno через CLI:

```bash
kyverno apply policy.yaml --resource deployment.yaml
# → Applying 1 policy rule(s) to 1 resource(s)...
# → pass: 1, fail: 0, warn: 0, error: 0, skip: 0
```

---

## 5. Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| **`CrashLoopBackOff`** / `ExitCode 1`: `Read-only file system` | Приложение пытается записать файл/лог в каталог, заблокированный `readOnlyRootFilesystem: true`. | `kubectl logs <pod-name> -c app`<br>`kubectl describe pod <pod-name>` | Смонтировать `emptyDir` с ограничением `sizeLimit` в целевой путь или перенаправить логи в `stdout`. |
| **`CreateContainerConfigError`** / `RunContainerError`: `container has runAsNonRoot and image will run as root` | Указан `runAsNonRoot: true`, но в образе задан `USER root` (или нет директивы `USER`), а `runAsUser` не определен в манифесте. | `kubectl describe pod <pod-name>` (событие с описанием ошибки проверки UID). | Задать явный non-root UID в `securityContext.runAsUser: 10001` либо пересобрать образ с директивой `USER 10001`. |
| **Rollout завис на `0/N`**, поды не создаются, `kubectl get pods` пуст | PSA в режиме `enforce` заблокировал создание пода контроллером ReplicaSet. | `kubectl describe rs -l app.kubernetes.io/name=secure-service` | Проверить события `FailedCreate` в ReplicaSet. Добавить недостающие поля (`drop: [ALL]`, `seccompProfile`, `runAsNonRoot`). |
| **`Permission denied`** на подключенном томе (PVC / emptyDir) | Процесс запущен под `runAsUser: 10001`, а файлы тома принадлежат `root:root` (UID 0). | `kubectl logs <pod-name>`<br>`ls -ld /mount/path` внутри контейнера. | Указать `fsGroup: 10001` в `spec.template.spec.securityContext`. Для больших дисков добавить `fsGroupChangePolicy: "OnRootMismatch"`. |
| **`bind: permission denied`** на сетевом сокете при старте | Попытка привязаться к портам <1024 без прав суперпользователя. | Логи контейнера: `listen tcp :80: bind: permission denied`. | Перевести приложение на порты выше 1024 (например, 8080) либо точечно добавить `capabilities: add: ["NET_BIND_SERVICE"]`. |
| **`401/403 Unauthorized`** при обращении приложения к Kubernetes API | Токен пода не смонтирован из-за `automountServiceAccountToken: false`. | `curl -k https://kubernetes.default.svc` возвращает `Unauthorized`. | Если приложению действительно требуется доступ к API, создать выделенный ServiceAccount с минимальной Role/RoleBinding и включить токен для него. |

### Разбор диагностического кейса: Поиск причины зависания развертывания из-за PSA

При обновлении Deployment поды не создаются:

```bash
kubectl get deployment secure-service -n production
# → NAME             READY   UP-TO-DATE   AVAILABLE   AGE
# → secure-service   0/3     0            0           2m
```

Поиск причины через статус `ReplicaSet`:

```bash
kubectl describe rs -l app.kubernetes.io/name=secure-service -n production | grep -A 5 Events:
# → Events:
# →   Type     Reason        Age                    From                   Message
# →   ----     ------        ----                   ----                   -------
# →   Warning  FailedCreate  2m (x12 over 2m)       replicaset-controller  Error creating: pods "secure-service-5d469..." is forbidden: violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false (container "app" must set securityContext.allowPrivilegeEscalation=false), unrestricted capabilities (container "app" must set securityContext.capabilities.drop=["ALL"])
```

**Решение:** Внести исправления в секцию `spec.template.spec.containers[*].securityContext` манифеста Deployment и выполнить повторный `kubectl apply`.

---

## 6. Рекомендации и лучшие практики

### 1. Архитектурный принцип наименьших привилегий (Least Privilege)
- **Запрет root в проде:** Все production-нагрузки обязаны выполняться под непривилегированными пользователями (UID >= 10000). Не используйте UID 0 даже на этапе сборки base-образов.
- **Тотальный сброс capabilities:** Всегда декларируйте `capabilities: drop: ["ALL"]`. Если сервису требуется привязка к низким портам или работа с raw-сокетами, добавляйте только конкретное право (`CAP_NET_BIND_SERVICE`), а не запускайте контейнер как privileged.
- **Флаг no_new_privs:** Всегда выставляйте `allowPrivilegeEscalation: false`. Это блокирует повышение прав через `setuid`/`setgid` бинарные файлы внутри контейнера.

### 2. Защита файловой системы и предотвращение DoS узлов
- **Read-only корень:** Включайте `readOnlyRootFilesystem: true` для всех контейнеров. Это исключает модификацию исполняемых файлов злоумышленником при RCE-уязвимостях.
- **Обязательные sizeLimit:** Любой том `emptyDir` обязан иметь параметр `sizeLimit` (например, `64Mi` или `128Mi`). Это предотвращает переполнение корневого диска рабочей ноды (DiskPressure) процессами, пишущими бесконечные логи или временные файлы.
- **Лимиты ресурсов и PIDs:** Задавайте `requests` и `limits` для CPU, Memory и `ephemeral-storage`. На уровне kubelet используйте `podPidsLimit` для защиты таблицы процессов ядра хоста от fork-бомб.

### 3. Защита ServiceAccount и изоляция метаданных
- **Отключение токенов по умолчанию:** Если приложение не является оператором или мониторинговым агентом, выставляйте `automountServiceAccountToken: false` в шаблоне пода. Это защищает от кражи JWT-токена и эксфильтрации данных через API-сервер.
- **Изолированный ServiceAccount:** Никогда не используйте дефолтный аккаунт `default`. Создавайте выделенный `ServiceAccount` на каждый Deployment с жестко ограниченными правами через `Role` и `RoleBinding`.

### 4. Внедрение политик в CI/CD и Admission Control
- **Shift-Left Security:** Проверяйте манифесты линтерами (`kubeconform`, `kubesec`, `trivy`) на этапе Pull Request до деплоя в кластер.
- **Двухфазное внедрение PSA:** При переводе существующих пространств имен на профиль `restricted` сначала включайте режимы `warn` и `audit`. Переходите в `enforce` только после устранения всех зафиксированных предупреждений в логах аудита.
- **Нативные политики (CEL-first):** Используйте `ValidatingAdmissionPolicy` ядра Kubernetes вместо тяжелых сторонних admission-вебхуков для базовых проверок безопасности — это исключает задержки и зависимость от доступности внешних подов.

---

## 7. Дополнительная информация

### См. также
- [Манифест Deployment](./deployment_manifest.md) — полный разбор полей объекта Deployment и стратегий обновления.
- [Обзор Deployment](./index.md) — архитектурные принципы контроллера stateless-нагрузок.
- [Pod Security Context](../../Security/pod_security_context.md) — SSoT по всем параметрам безопасности подов и контейнеров.
- [Pod Best Practices](../Pod/pod_best_practices.md) — лучшие практики проектирования спецификаций Pod.
- [Основы Secret](../secrets/secrets_basics.md) — типы, создание и базовое использование секретов.
- [Безопасность Secret](../secrets/security.md) — шифрование в etcd, RBAC и защита чувствительных данных.
- [Ограничения RBAC и ValidatingAdmissionPolicy](../../Security/rbac/limitations_opa.md) — встроенные политики CEL и сравнение с OPA Gatekeeper.
- [Kyverno: концепции и архитектура](../../Security/kyverno/concepts.md) — движок политик Admission Control для Kubernetes.
- [NetworkPolicy: практические сценарии](../../Networking/Network/NetworkPolicy/practical_scenarios.md) — сетевая изоляция и микросегментация нагрузок.
- [Kubeconform](../../ToolsUtilities/kubeconform_overview.md) — статическая валидация манифестов по JSON-схемам.
- [Kubesec](../../Security/kubesec.md) — аудит рисков и скоринг безопасности манифестов.
- [Kubescape](../../Security/kubescape_overview.md) — сканер безопасности и проверка фреймворков CIS/NSA.
- [Trivy: сканирование уязвимостей](../../../Docker/Docker_security/vulnerability_scanning.md) — поиск CVE в образах и сканирование конфигураций.
