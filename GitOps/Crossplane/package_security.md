# Crossplane: Безопасность цепочки поставок пакетов

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

## Определения

**Supply Chain Security (безопасность цепочки поставок) в Crossplane** — комплекс мер по контролю целостности, подлинности и изоляции пакетов расширения Crossplane (`Provider`, `Configuration`, `Function`), распространяемых в формате OCI-артефактов (`.xpkg`). Поскольку пакеты содержат исполняемый код контроллеров, gRPC-серверы и определения CustomResourceDefinitions (CRD), компрометация пакета эквивалентна компрометации всего кластера управления (Control Plane).

**xpkg (Crossplane OCI Package)** — OCI-образ со спецификацией Crossplane, содержащий метаданные пакета (`package.yaml`), определения кастомных ресурсов (CRD), схемы композиций (`Composition`, `CompositeResourceDefinition`) и манифесты развертывания контроллеров или функций.

**Подписание и верификация (Cosign / Sigstore)** — криптографическая подпись OCI-манифеста пакета закрытым ключом автора и последующая проверка подписи в Crossplane по публичному ключу (`--validation-pem`) или в корпоративной инфраструктуре Sigstore (Fulcio/Rekor).

**Digest Pinning (`@sha256:...`)** — фиксация точного криптографического хеша (дайджеста) манифеста OCI-образа вместо плавающего тега (`:v1.3.0`). Гарантирует абсолютную неизменяемость артефакта и защищает от подмены содержимого в реестре.

**packagePullSecrets** — ссылка на секрет Kubernetes типа `kubernetes.io/dockerconfigjson` в пространстве имен управляющего контура, используемый пакетным менеджером Crossplane для аутентификации в защищенных корпоративных OCI-реестрах (Harbor, Nexus).

**DeploymentRuntimeConfig (DRC)** — системный ресурс Crossplane (`pkg.crossplane.io/v1beta1`), управляющий параметрами рантайма подов провайдеров и функций (SecurityContext, ServiceAccount, лимиты CPU/RAM, монтирование томов, переменные окружения).

---

## Базовые концепции и архитектура

### Архитектура пакетного менеджера Crossplane

Пакетный менеджер Crossplane исполняется внутри пода `crossplane` (namespace `crossplane-system`) и отвечает за жизненный цикл пакетов:

```
[ GitOps / SRE ]
       │ (kubectl apply)
       ▼
 [ Provider / Function CRD ]
       │
       ▼
[ Crossplane Package Manager ] ──── (1. Запрос манифеста) ───► [ Корпоративный OCI-реестр ]
       │                                                                │ (Harbor / Nexus)
       ├───── (2. Проверка подписи Cosign via --validation-pem) ◄──────┤
       │                                                                │
       ├───── (3. Загрузка OCI-слоев .xpkg) ────────────────────────────┘
       │
       ▼
 [ Создание ProviderRevision ]
       │
       ├──► Распаковка и регистрация CRD в Kubernetes API
       │
       └──► Генерация Deployment контроллера (с учетом DeploymentRuntimeConfig)
```

1. **Декларация пакета:** Администратор создает ресурс `Provider`, `Configuration` или `Function`.
2. **Создание ревизии:** Пакетный менеджер формирует иммутабельный дочерний ресурс ревизии (`ProviderRevision`, `FunctionRevision`).
3. **Загрузка и верификация:** Менеджер обращается к OCI-реестру. Если активирован флаг `--enable-signature-verification`, Crossplane скачивает сигнатуру Cosign из реестра и сверяет ее с доверенным публичным ключом. При несовпадении или отсутствии подписи процесс блокируется.
4. **Установка компонентов:** При успешной проверке распаковываются CRD, валидируются схемы зависимостей, после чего запускается под контроллера провайдера или gRPC-рантайм функции.

### Векторы атак и риски безопасности

В инфраструктуре On-Premise и Bare-Metal к пакетам Crossplane применимы следующие ключевые риски:

1. **Мутабельность тегов и атака TOCTOU (GHSA-wfqx-gjrf-g28r):**
   Теги OCI-образов (`:v1.3.0`, `:latest`) могут быть перезаписаны в реестре. Уязвимость класса Time-of-Check to Time-of-Use (TOCTOU) возникает, когда проверка подписи выполняется для одной версии манифеста по тегу, а фактическая загрузка слоев или запуск пода контроллера происходит из обновленного (скомпрометированного) образа.
   *Защита:* Использование исключительно иммутабельных дайджестов вида `@sha256:<hash>`.
2. **Внедрение вредоносных CRD и эскалация привилегий:**
   Провайдеры регистрируют CRD на уровне кластера и требуют широких прав доступа (ClusterRole) для управления объектами. Злоумышленник, подменивший пакет, может внедрить мутирующие вебхуки или захватить права `cluster-admin`.
   *Защита:* Ограничение прав через `DeploymentRuntimeConfig`, отказ от автоматической установки зависимостей (`skipDependencyResolution: true`), аудит манифестов в CI.
3. **Небезопасный профиль выполнения контроллеров:**
   По умолчанию контроллеры провайдеров могут запускаться с привилегиями root и полным доступом к файловой системе контейнера.
   *Защита:* Принудительное применение профиля `restricted` Pod Security Standards через `DeploymentRuntimeConfig`.
4. **Утечка учетных данных реестра:**
   Хранение открытых токенов и паролей реестра в Git.
   *Защита:* Доставка секретов через специализированные операторы (ESO, SOPS) и разделение прав доступа в OCI-реестре.

### Модель эшелонированной защиты (Defense-in-Depth)

Надежная безопасность цепочки поставок Crossplane строится на трех независимых эшелонах:

* **Эшелон 1 (CI/CD Pipeline):** Сборка `.xpkg`, статическое сканирование манифестов (Trivy), подписание криптографическим ключом Cosign и публикация в защищенный реестр.
* **Эшелон 2 (Cluster Admission Control):** Политики Kyverno или Kubernetes ValidatingAdmissionPolicy перехватывают создание объектов `Provider`, `Function` и `Configuration`, блокируя манифесты без `@sha256:` или из недоверенных источников.
* **Эшелон 3 (Crossplane Package Engine):** Встроенная проверка криптографической подписи (`--enable-signature-verification`), контроль целостности и изоляция исполнения контроллеров через `DeploymentRuntimeConfig`.

---

## Практические сценарии и настройка

### Предварительные требования

* Кластер Kubernetes v1.28–1.32+ с установленным Crossplane v1.18+ / v2.x.
* Утилита **Cosign v2.4+** или v3.x, установленная на рабочей станции/раннере.
* Утилита **Crossplane CLI v2.x** (`crossplane`).
* Корпоративный OCI-реестр с поддержкой OCI Image Specification v1.1+ (например, **Harbor v2.10+**), развернутый с доверенным TLS-сертификатом.

Проверка версии Cosign:

```bash
cosign version
# → GitVersion:    v2.4.1
# → GitCommit:     ...
# → GoVersion:     go1.23.x
```

---

### Сценарий 1: Генерация ключей и подписание пакета в CI/CD

Для подписи пакетов в закрытом контуре используется ключевая пара Cosign (ECDSA P-256).

#### 1. Генерация пары ключей подписи

```bash
# Генерация закрытого (cosign.key) и открытого (cosign.pub) ключей
cosign generate-key-pair
# → Enter password for private key: **********
# → Private key written to cosign.key
# → Public key written to cosign.pub
```

> Публичный ключ `cosign.pub` размещается в кластере Kubernetes для верификации. Закрытый ключ `cosign.key` и пароль передаются в защищенные переменные CI/CD (GitLab CI Masked Variables / HashiCorp Vault).

#### 2. Сборка и подпись OCI-пакета Crossplane

Сборка пакета конфигурации или провайдера и публикация в локальный реестр Harbor:

```bash
# 1. Сборка пакета
crossplane xpkg build \
  --package-root=./package \
  --output=provider-kubernetes.xpkg
# → created package: provider-kubernetes.xpkg

# 2. Публикация пакета во внутренний OCI-реестр
crossplane xpkg push \
  --package-files=provider-kubernetes.xpkg \
  harbor.corp.local/crossplane/provider-kubernetes:v1.3.0
# → pushed package to harbor.corp.local/crossplane/provider-kubernetes:v1.3.0

# 3. Получение точного дайджеста опубликованного манифеста
IMAGE_DIGEST=$(crane digest harbor.corp.local/crossplane/provider-kubernetes:v1.3.0)
echo "Digest: ${IMAGE_DIGEST}"
# → Digest: sha256:8b4e723a1fbc9c01824d55aa610b2e3f019a77b81239c5132de984f8812c80aa

# 4. Подписание пакета строго по дайджесту
COSIGN_PASSWORD="SecretPassword123" cosign sign \
  --key cosign.key \
  --tlog-upload=false \
  "harbor.corp.local/crossplane/provider-kubernetes@${IMAGE_DIGEST}"
# → Pushing signature to: harbor.corp.local/crossplane/provider-kubernetes
```

> **Важно:** Флаг `--tlog-upload=false` обязателен для изолированных on-premise сетей без доступа к публичному журналу прозрачности Rekor (Sigstore Public Good Instance).

#### 5. Верификация подписи через CLI

```bash
cosign verify \
  --key cosign.pub \
  --insecure-ignore-tlog=true \
  "harbor.corp.local/crossplane/provider-kubernetes@${IMAGE_DIGEST}"
# → Verification for harbor.corp.local/crossplane/provider-kubernetes@sha256:... --
# → The following checks were performed on each of these signatures:
# →   - The cosign claims were validated
# →   - Existence of the claims in the transparency log was skipped
# →   - The signatures were verified against the specified public key
```

---

### Сценарий 2: Развертывание Crossplane с включенной верификацией подписей

Для включения проверки подписей ядром Crossplane требуются флаги `--enable-signature-verification` и `--validation-pem`.

#### 1. Создание Secret с публичным ключом верификации

Публичный ключ сохраняется в пространстве имен `crossplane-system`:

```bash
kubectl create namespace crossplane-system --dry-run=client -o yaml | kubectl apply -f -
# → namespace/crossplane-system configured

kubectl -n crossplane-system create secret generic cosign-package-signing-key \
  --from-file=cosign.pub=./cosign.pub
# → secret/cosign-package-signing-key created
```

#### 2. Настройка Helm values для Crossplane

Конфигурация `values.yaml` для официального чарта `crossplane-stable/crossplane`:

```yaml
# values-crossplane-security.yaml
args:
  - "core"
  - "start"
  - "--enable-signature-verification"
  - "--validation-pem=/etc/crossplane/certs/cosign.pub"

extraVolumes:
  - name: cosign-public-key
    secret:
      secretName: cosign-package-signing-key
      defaultMode: 0444
  # Монтирование внутреннего CA для валидации HTTPS-сертификата корпоративного Harbor
  - name: corp-ca-certs
    configMap:
      name: corporate-root-ca

extraVolumeMounts:
  - name: cosign-public-key
    mountPath: /etc/crossplane/certs
    readOnly: true
  - name: corp-ca-certs
    mountPath: /etc/ssl/certs/corp-ca.crt
    subPath: corp-ca.crt
    readOnly: true

# Ограничение системных привилегий пода ядра Crossplane
securityContext:
  runAsNonRoot: true
  runAsUser: 65532
  runAsGroup: 65532
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL
```

Применение конфигурации:

```bash
helm upgrade --install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  -f values-crossplane-security.yaml
# → Release "crossplane" has been upgraded. Happy Helming!
```

---

### Сценарий 3: Настройка защищенного доступа к приватному реестру

Для скачивания OCI-пакетов из защищенного Harbor реестра используется `packagePullSecrets` в сочетании с фиксацией по `@sha256:`.

#### 1. Создание секрета аутентификации в OCI-реестре

```bash
kubectl -n crossplane-system create secret docker-registry harbor-package-pull-secret \
  --docker-server=harbor.corp.local \
  --docker-username=robot-crossplane-pull \
  --docker-password=RobotTokenPassword123
# → secret/harbor-package-pull-secret created
```

#### 2. Декларация Provider с привязкой к дайджесту и секрету

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  # Обязательная фиксация по дайджесту (Digest Pinning)
  package: harbor.corp.local/crossplane/provider-kubernetes@sha256:8b4e723a1fbc9c01824d55aa610b2e3f019a77b81239c5132de984f8812c80aa
  packagePullPolicy: IfNotPresent
  packagePullSecrets:
    - name: harbor-package-pull-secret
  runtimeConfigRef:
    name: hardened-provider-runtime
```

Проверка статуса установки:

```bash
kubectl get provider provider-kubernetes
# → NAME                  INSTALLED   HEALTHY   PACKAGE                                                      AGE
# → provider-kubernetes   True        True      harbor.corp.local/crossplane/provider-kubernetes@sha256:...  45s
```

---

### Сценарий 4: Ужесточение рантайма контроллеров (DeploymentRuntimeConfig)

После распаковки пакета Crossplane запускает Deployment контроллера. Для соответствия требованиям безопасности CIS Benchmark и Pod Security Standards `restricted` параметры пода настраиваются через `DeploymentRuntimeConfig`.

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: hardened-provider-runtime
spec:
  deploymentTemplate:
    spec:
      replicas: 1
      template:
        metadata:
          labels:
            security.corp.local/tier: platform-controller
        spec:
          securityContext:
            runAsNonRoot: true
            runAsUser: 65532
            runAsGroup: 65532
            fsGroup: 65532
            seccompProfile:
              type: RuntimeDefault
          containers:
            - name: package-runtime
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop:
                    - ALL
              resources:
                limits:
                  cpu: "1000m"
                  memory: "1Gi"
                requests:
                  cpu: "250m"
                  memory: "256Mi"
```

Применение манифеста:

```bash
kubectl apply -f hardened-runtime.yaml
# → deploymentruntimeconfig.pkg.crossplane.io/hardened-provider-runtime created
```

#### Сетевая изоляция рантайма через NetworkPolicy

Контроллеры провайдеров должны иметь доступ только к Kubernetes API серверу и внутренним целевым эндпоинтам. Доступ в публичный интернет блокируется:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: isolate-crossplane-providers
  namespace: crossplane-system
spec:
  podSelector:
    matchLabels:
      pkg.crossplane.io/provider: provider-kubernetes
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем скрейпинг метрик только от инстанса Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 8080
  egress:
    # Разрешаем доступ только к kube-apiserver и DNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    - to:
        - ipBlock:
            cidr: 10.96.0.1/32 # IP адрес kube-apiserver Service
      ports:
        - protocol: TCP
          port: 443
```

---

### Сценарий 5: Кластерный Admission-контроль пакетов (Kyverno)

Для гарантированного соблюдения правил безопасности на этапе отправки манифестов (Defense-in-Depth) настраивается политика Kyverno. Она принудительно запрещает использование мутабельных тегов и разрешает скачивание только из корпоративного реестра.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-crossplane-package-security
  annotations:
    policies.kyverno.io/title: "Enforce Crossplane Package Security"
    policies.kyverno.io/severity: "high"
    policies.kyverno.io/description: "Требует использование корпоративного OCI-реестра и фиксацию по sha256 digest для всех пакетов Crossplane."
spec:
  validationFailureAction: Enforce
  rules:
    # Правило 1: Запрет публичных реестров
    - name: require-trusted-registry
      match:
        any:
          - resources:
              kinds:
                - "pkg.crossplane.io/v1/Provider"
                - "pkg.crossplane.io/v1/Configuration"
                - "pkg.crossplane.io/v1/Function"
      validate:
        message: "Пакеты разрешено устанавливать только из доверенного корпоративного реестра 'harbor.corp.local/crossplane/'."
        pattern:
          spec:
            package: "harbor.corp.local/crossplane/*"

    # Правило 2: Запрет тегов и обязательный sha256 digest
    - name: require-digest-pinning
      match:
        any:
          - resources:
              kinds:
                - "pkg.crossplane.io/v1/Provider"
                - "pkg.crossplane.io/v1/Configuration"
                - "pkg.crossplane.io/v1/Function"
      validate:
        message: "Использование плавающих тегов запрещено для предотвращения TOCTOU-атак. Пакет должен быть зафиксирован по digest: '@sha256:<hash>'."
        deny:
          conditions:
            all:
              - key: "{{ request.object.spec.package }}"
                operator: NotEquals
                value: "*@sha256:*"
```

Проверка срабатывания политики:

```bash
# Попытка применить провайдер с мутабельным тегом
kubectl apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: unverified-provider
spec:
  package: harbor.corp.local/crossplane/provider-kubernetes:v1.3.0
EOF
# → Error from server: error when creating "STDIN": admission webhook "validate.kyverno.svc" denied the request:
# → Policy enforce-crossplane-package-security failed: Использование плавающих тегов запрещено для предотвращения TOCTOU-атак. Пакет должен быть зафиксирован по digest: '@sha256:*'.
```

---

### Сценарий 6: Зеркалирование и развертывание в изолированном контуре (Air-Gapped)

В закрытых промышленных контурах без прямого выхода в интернет пакеты предварительно экспортируются на доверенном шлюзе, сканируются, подписываются внутренним ключом и загружаются в изолированный Harbor.

#### 1. Экспорт и сохранение пакета на шлюзе

```bash
# Скачивание пакета с публичного апстрима по дайджесту
crane pull \
  xpkg.upbound.io/crossplane-contrib/provider-kubernetes@sha256:8b4e723a1fbc9c01824d55aa610b2e3f019a77b81239c5132de984f8812c80aa \
  provider-kubernetes-tarball.tar
# → Pulled manifest and layers to provider-kubernetes-tarball.tar

# Проверка контрольной суммы архива
sha256sum provider-kubernetes-tarball.tar > provider-kubernetes.sha256
cat provider-kubernetes.sha256
# → 9f8a3...  provider-kubernetes-tarball.tar
```

#### 2. Проверка уязвимостей через Trivy

```bash
trivy image --input provider-kubernetes-tarball.tar --severity HIGH,CRITICAL --exit-code 1
# → 2026-10-13T17:15:00Z INFO Total: 0 (HIGH: 0, CRITICAL: 0)
```

#### 3. Импорт во внутренний Harbor и локальная подпись

```bash
# Загрузка во внутренний репозиторий
crane push provider-kubernetes-tarball.tar harbor.airgap.local/crossplane/provider-kubernetes:v1.3.0
# → Pushed to harbor.airgap.local/crossplane/provider-kubernetes:v1.3.0

INTERNAL_DIGEST=$(crane digest harbor.airgap.local/crossplane/provider-kubernetes:v1.3.0)

# Подпись внутренним изолированным ключом Cosign
cosign sign --key airgap-cosign.key --tlog-upload=false "harbor.airgap.local/crossplane/provider-kubernetes@${INTERNAL_DIGEST}"
# → Pushed signature to harbor.airgap.local/crossplane/provider-kubernetes
```

---

## Операции и команды

Сводка эксплуатационных команд для инженера DevOps и SRE:

| Категория | Задача | Команда |
| :--- | :--- | :--- |
| **Cosign** | Генерация пары ключей | `cosign generate-key-pair` |
| **Cosign** | Подпись по дайджесту (без tlog) | `cosign sign --key cosign.key --tlog-upload=false <image>@sha256:<hash>` |
| **Cosign** | Проверка подписи по ключу | `cosign verify --key cosign.pub --insecure-ignore-tlog=true <image>@sha256:<hash>` |
| **Crossplane CLI** | Сборка xpkg-артефакта | `crossplane xpkg build --package-root=. -o pkg.xpkg` |
| **Crossplane CLI** | Публикация пакета в OCI | `crossplane xpkg push --package-files=pkg.xpkg <registry>/<repo>:<tag>` |
| **Kubectl / SRE** | Статус ревизий провайдеров | `kubectl get providerrevisions -o wide` |
| **Kubectl / SRE** | Статус ревизий функций | `kubectl get functionrevisions -o wide` |
| **Kubectl / SRE** | Детали ошибки верификации | `kubectl describe providerrevision <name> \| grep -A 8 Conditions:` |
| **Kubectl / SRE** | Проверка логов пакетного менеджера | `kubectl -n crossplane-system logs deploy/crossplane -c crossplane \| grep -E "package\|verification"` |

#### Пример проверки условий ревизии пакета

```bash
kubectl describe providerrevision provider-kubernetes-94c8b21ef0
# → Name:         provider-kubernetes-94c8b21ef0
# → Status:
# →   Conditions:
# →     Type       Status   Reason                 Message
# →     ----       ------   ------                 -------
# →     Healthy    True     Success                ProviderRevision is healthy
# →     Installed  True     Success                ProviderRevision is installed
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Команда диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`ErrSignatureVerificationFailed`**<br>`signature verification failed: no matching signatures` | Пакет не подписан, подпись создана другим закрытым ключом, либо нарушена целостность манифеста. | `kubectl describe providerrevision <rev-name>`<br>`cosign verify --key cosign.pub <package-ref>` | 1. Проверить соответствие `cosign.pub` в секрете `cosign-package-signing-key` закрытому ключу CI.<br>2. Переподписать пакет по актуальному sha256 digest.<br>3. Убедиться, что в Helm включен `--insecure-ignore-tlog=true` при работе без Rekor. |
| **`ImagePullBackOff`**<br>`401 Unauthorized` | Не настроен или не привязан `packagePullSecrets`, либо токен робота реестра истек. | `kubectl get secret -n crossplane-system`<br>`kubectl describe provider <name>` | 1. Проверить наличие `packagePullSecrets` в манифесте `Provider`.<br>2. Проверить валидность токена: `docker login -u <user> -p <pass> harbor.corp.local`. |
| **`x509: certificate signed by unknown authority`** | Пакетный менеджер Crossplane не доверяет самоподписанному сертификату корпоративного Harbor. | `kubectl -n crossplane-system logs deploy/crossplane` | Смонтировать корневой CA сертификат компании в под Crossplane через Helm `extraVolumes`/`extraVolumeMounts` в `/etc/ssl/certs/`. |
| **TOCTOU / Image Digest Changed** | Использован плавающий тег, образ в реестре обновился после проверки или кэширования. | `kubectl get provider <name> -o yaml \| grep package` | Заменить тег на неизменяемый digest (`@sha256:...`) во всех манифестах `Provider`, `Configuration`, `Function`. |
| **`admission webhook "validate.kyverno.svc" denied`** | Манифест отклонен admission-контроллером из-за отсутствия sha256 или недоверенного реестра. | `kubectl get clusterpolicy enforce-crossplane-package-security`<br>`kubectl get events -n <ns>` | Скорректировать манифест в Git: указать разрешенный домен реестра `harbor.corp.local` и зафиксировать digest. |
| **`CrashLoopBackOff` подов провайдера** | Провайдер требует привилегий root или записи в корень, но `DeploymentRuntimeConfig` выставил `readOnlyRootFilesystem: true`. | `kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=<name>` | Для провайдеров, требующих временные директории, добавить том `emptyDir` на `/tmp` через `spec.deploymentTemplate.spec.template.spec.volumes` в `DeploymentRuntimeConfig`. |

---

## Рекомендации и Best Practices

1. **Строгий Digest Pinning:** Никогда не используйте плавающие теги (`latest`, `v1.x`) в продакшене. Всегда фиксируйте дайджест: `@sha256:...`. Это исключает подмену образов и защищает от уязвимостей типа TOCTOU (GHSA-wfqx-gjrf-g28r).
2. **Ограничение прав RBAC на ресурсы `pkg.crossplane.io`:** Установка `Provider` или `Function` позволяет внедрять CRD и контроллеры с правами `ClusterRole`. Запретите прикладным разработчикам доступ к API-группе `pkg.crossplane.io`. Доступ на установку пакетов должен быть исключительно у GitOps-контроллера (Argo CD) и системных администраторов платформы.
3. **Обязательная связка DRC со всеми пакетами:** Каждый провайдер и функция должны развертываться с явной ссылкой на `runtimeConfigRef` (`DeploymentRuntimeConfig`), где определены жесткие лимиты ресурсов и строгий `SecurityContext` (`runAsNonRoot: true`, `drop: ["ALL"]`, `seccompProfile: RuntimeDefault`).
4. **Регулярная ротация ключей Cosign:** При компрометации или плановой ротации (рекомендуется раз в 90–180 дней) генерируйте новую пару ключей. Обновляйте `cosign.pub` в секрете `crossplane-system` до публикации новых пакетов.
5. **Очистка устаревших ревизий:** Старые ревизии пакетов (`ProviderRevision`) сохраняются в кластере при обновлении. Настройте ограничение ревизий через `spec.revisionHistoryLimit: 1` в манифестах пакетов для предотвращения разрастания etcd.
6. **Полная изоляция закрытого контура:** В средах On-Premise и Bare-Metal используйте локальный Harbor с обязательным автоматическим сканированием уязвимостей (Trivy) перед подписанием и публикацией пакетов в каталог платформы.

---

## Дополнительная информация

* [Официальная документация Crossplane: Providers Management](https://docs.crossplane.io/latest/packages/providers/)
* [Sigstore Cosign Documentation: Container Signing and Verification](https://docs.sigstore.dev/cosign/verifying/verify)
* [Advisory GHSA-wfqx-gjrf-g28r: Crossplane Package Signature Verification TOCTOU](https://github.com/crossplane/crossplane/security/advisories/GHSA-wfqx-gjrf-g28r)
* [Kyverno Documentation: Image and Manifest Verification](https://kyverno.io/docs/)

Смежные темы в базе знаний:
* [Обзор Crossplane](./overview.md) — общая архитектура, жизненный цикл и концепции Control Plane.
* [Air-Gap установка](./airgap_install.md) — полный bootstrap изолированного контура с нуля (чарты, CLI, провайдеры, CA Bundle).
* [GitOps Integration](./gitops_integration.md) — автоматизированная доставка Crossplane и управление секретами через Argo CD и SOPS.
* [Политики и Governance](./policy_governance.md) — применение Kyverno и OPA Gatekeeper для валидации Claim и XR.
* [Настройка Provider Kubernetes](./provider_kubernetes_setup.md) — развертывание и изоляция базового провайдера для On-Premise кластеров.
* [Функции композиции](./composition_functions.md) — безопасность и runtime-настройка Composition Functions.
* [Защита зависимостей (Usage)](./usage_protection.md) — предотвращение случайного или каскадного удаления инфраструктуры.
* [Обновление и миграция](./upgrade_migration.md) — управление версиями пакетов и безопасное обновление ревизий.
* [Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md) — фундаментальное руководство по Sigstore, Cosign, Notation и инфраструктуре доверия.
