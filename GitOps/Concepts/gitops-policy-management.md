# Управление политиками безопасности через GitOps (GitOps-мозг)

Этот документ описывает архитектурный подход к централизованному управлению политиками безопасности в множестве Kubernetes-кластеров с использованием ArgoCD, Teleport и движков политик (Gatekeeper, Kyverno). Такой подход превращает политики из разрозненных ручных настроек каждого кластера в версионируемый, тестируемый и автоматически доставляемый артефакт — то есть применяет к безопасности те же практики, что и к приложениям.

## Определения

**GitOps-мозг (Policy Brain)** — концепция централизованного управляющего кластера (Management Cluster), который выступает единым авторитетным источником для политик безопасности всей организации. Он доставляет конфигурации во все подключенные кластеры, обеспечивая единообразие и наблюдаемость. Термин подчеркивает роль Hub-кластера как «мозга», принимающего решения о том, какая политика где должна работать.

**Teleport Access Plane** — инфраструктурное решение для управления доступом, используемое в данной архитектуре как защищенный прокси-слой. Оно позволяет ArgoCD подключаться к API-серверам удаленных кластеров без прямого сетевого доступа и VPN: весь трафик идет через аутентифицированный Proxy с кратковременными сертификатами и полным журналированием сессий.

**Gatekeeper (OPA)** — агент безопасности в целевых кластерах, выполняющий проверку ресурсов на соответствие политикам, написанным на языке **Rego**. Политики оформляются парой ресурсов: `ConstraintTemplate` (логика на Rego или CEL + схема параметров) и `Constraint` (экземпляр политики с параметрами и областью действия). Актуальная линейка версий — v3.23.x (со встроенным OPA v1.17.x); поддерживаются два последних минорных релиза.

**Kyverno** — K8s-native движок политик, использующий YAML для описания правил валидации, мутации и генерации ресурсов. Ресурсы политик: `ClusterPolicy` (кластерная область) и `Policy` (namespace-scoped). Актуальная линейка — v1.19 (август 2026, Kubernetes 1.33–1.35); релиз поддерживается до выхода релиза через один (около 3 месяцев).

**ValidatingAdmissionPolicy (VAP)** — встроенный механизм валидации Kubernetes на языке CEL (стабилен с версии 1.30). Не требует установки дополнительного агента в целевой кластер, но ограничен логикой одного запроса без референциальных проверок. Рассматривается как «третья опция» для простых политик там, где нежелателен вес Gatekeeper/Kyverno.

**tbot (Teleport Bot)** — компонент Teleport Machine & Workload Identity для машинной аутентификации: генерирует кратковременные сертификаты и обновляет их автоматически для работы ArgoCD. В актуальных версиях Teleport (v17/v18) tbot имеет официальный выходной сервис `kubernetes/argo-cd`, который сам создает и ротирует секреты кластеров для Argo CD.

**opus-scorecard** — специализированный внутренний экспортер для Gatekeeper, преобразующий детальную информацию о нарушениях (violations) из статусов CRD `Constraint` в метрики формата Prometheus. Решение не является публичным проектом; для публичных альтернатив см. раздел «Наблюдаемость» ниже.

**execProviderConfig** — механизм в ArgoCD (с v1.8.0), позволяющий использовать внешние скрипты для получения учетных данных (kubeconfig/tokens) при подключении к удаленным кластерам. Классический способ интеграции с Teleport до появления официального output-service tbot.

**PolicyReport** — стандартизованный CRD (формат policy-reporter-workgroup), описывающий результаты проверки ресурсов политиками: список нарушений, серьезность, источники. Kyverno генерирует PolicyReports нативно; для Gatekeeper результаты доступны в статусе Constraint'ов и через экспортеры. На этом формате строится Policy Reporter UI.

**Режимы Audit и Enforce** — два режима работы любого движка политик. `Audit` только фиксирует нарушения (в статусах, отчетах, метриках), пропуская ресурсы; `Enforce` (deny/validate) блокирует невалидные ресурсы на admission. Перевод политики из Audit в Enforce — обязательный этап безопасного внедрения.

---

## Базовые концепции

### Архитектура решения

Центральным компонентом является **ArgoCD**, развернутый в Hub-кластере, который:
1. Забирает политики (Rego/YAML) и манифесты из Git.
2. Подключается к удаленным кластерам (Spokes) через **Teleport Proxy**.
3. Доставляет объекты `ConstraintTemplate`, `Constraint` (Gatekeeper) или `ClusterPolicy` (Kyverno).
4. Отслеживает состояние синхронизации и наличие нарушений.

Такая модель Hub-and-Spoke выбрана не случайно: она дает единую точку аудита (кто и когда изменил политику — видно по истории Git и логам ArgoCD), исключает расхождение версий политик между кластерами и позволяет масштабироваться до сотен кластеров без роста команды безопасности — добавление кластера сводится к регистрации его в Teleport и присвоению меток.

Важно понимать распределение ролей: ArgoCD отвечает только за **доставку** объектов политик. Само применение политик выполняется локальными агентами в Spoke-кластерах (webhook Gatekeeper/Kyverno перехватывает запросы к API). Даже при недоступности Hub-кластера существующие политики продолжают действовать — это осознанное преимущество перед централизованным admission-proxy.

### Схема взаимодействия
`Git (Policies) → ArgoCD (Hub) → Teleport Proxy → Remote Clusters (Gatekeeper/Kyverno)`

### Выбор движка политик

Перед развертыванием важно осознанно выбрать движок — они решают разные классы задач:

| Критерий | Gatekeeper (OPA) | Kyverno | ValidatingAdmissionPolicy |
| :--- | :--- | :--- | :--- |
| Язык политик | Rego (или CEL в `code[]`) | YAML (+ JMESPath-выражения) | CEL |
| Порог входа для ИБ/платформы | Высокий (функциональный язык) | Низкий (декларативный YAML) | Средний (CEL) |
| Мутация ресурсов | Да (Assign CRDs) | Да (нативно, зрелая поддержка) | Нет (только валидация) |
| Генерация ресурсов | Ограниченно | Да (generate-правила) | Нет |
| Референциальные проверки (по другим объектам) | Да (`data.inventory`) | Да (`context.apiResource`) | Нет |
| Внешние компоненты в Spoke-кластере | Контроллер + аудит | Контроллер + фон-сканер | Не требуются (встроен в kube-apiserver 1.30+) |
| Экосистема готовых политик | gatekeeper-library | Официальная библиотека политик Kyverno | Растущая библиотека CEL |
| Когда выбирать | Сложные референциальные и кросс-ресурсные правила | Быстрый старт, мутации, команды без опыта Rego | Простые проверки без установки агентов |

Практика показывает жизнеспособную комбинацию: Kyverno для массовых мутаций и простых валидаций, Gatekeeper — для сложных референциальных политик, VAP — как базовый уровень гигиены в managed-кластерах, где нельзя ставить агенты.

## Практические сценарии

### Сценарий 1: Подключение Spoke-кластеров через Teleport

**Предварительные требования**: кластеры зарегистрированы в Teleport (`tctl status` показывает их имена); в Hub-кластере установлен ArgoCD; для современного способа — Helm 3 и возможность создавать ServiceAccount `argocd:tbot`; бот-роль в Teleport с доступом к целевым кластерам (`kubernetes_labels`).

#### Вариант A (рекомендуемый): официальный output-service tbot

Начиная с актуальных версий Teleport, интеграция выполняется без ручных скриптов: tbot развертывается рядом с Argo CD и сам создает секреты вида `argocd.argoproj.io/secret-type: cluster` с кратковременными сертификатами, непрерывно их ротируя.

1. **Создайте бота и join-токен** (метод присоединения `kubernetes` со статическим JWKS — токен проверяет JWT пода tbot):
   ```yaml
   kind: token
   version: v2
   metadata:
     name: example-join-token
   spec:
     roles: [Bot]
     bot_name: example-bot
     join_method: kubernetes
     kubernetes:
       type: static_jwks
       static_jwks:
         jwks: |
           # Публичный ключ ServiceAccount argocd:tbot (вывод curl к JWKS-эндпоинту API)
           {"keys":[...]}
     allow:
     - service_account: "argocd:tbot" # namespace:service_account
   ```
2. **Разверните tbot официальным Helm-чартом** в namespace Argo CD:
   ```yaml
   # tbot-values.yaml
   clusterName: "prod.teleport.sh"          # имя Teleport-кластера (tctl status)
   teleportProxyAddress: "prod.teleport.sh:443"
   token: "example-join-token"
   defaultOutput:
     enabled: false
   argocd:
     enabled: true                          # включает output-service kubernetes/argo-cd
     clusterSelectors:
       - labels:
           environment: production          # какие кластеры отдать Argo CD
   ```
   ```bash
   helm repo add teleport https://charts.releases.teleport.dev && helm repo update
   helm install tbot teleport/tbot --namespace argocd --values tbot-values.yaml
   ```
3. **Проверьте регистрацию кластеров**:
   ```bash
   kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster
   # → result:
   # NAME                              TYPE                 DATA   AGE
   # argocd-cluster-prod-cluster-01    Opaque               4      2m
   argocd cluster list
   # → result: кластеры из Teleport видны со статусом Successful
   ```

**Граничные случаи**:
- Если кластер удален из Teleport или перестал соответствовать `clusterSelectors`, из Argo CD он **не удаляется автоматически** (для безопасности), но tbot прекращает обновлять его сертификаты — соединение умрет по истечении TTL. Такие «осиротевшие» секреты нужно удалять вручную.
- Новые совпадающие кластеры регистрируются при ближайшем обновлении сертификатов; форсировать можно сигналом `pkill -USR1 tbot`.
- Метки секретов можно шаблонизировать значениями меток кластера Teleport (`secret_labels` c Go-шаблонами `{{index .Labels "region"}}`) — поддерживается начиная с Teleport v18.6.0. Это критично для генераторов ApplicationSet (см. Сценарий 2).
- Для разделения прав между проектами используйте impersonation Argo CD: роль бота должна содержать `kubernetes_users` с wildcard, а сами группы `kubernetes_groups` при этом убираются — иначе границы привилегий смешаются.

#### Вариант B (legacy): execProviderConfig и скрипт аутентификации

Подходит для старых версий Teleport или когда output-service недоступен. Идея: ArgoCD вызывает скрипт при каждом обращении к кластеру, скрипт получает временные учетные данные через tbot.

1. **Настройка секрета кластера в ArgoCD**:

В секрете, описывающем удаленный кластер, настраивается секция `execProviderConfig`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: remote-cluster-secret
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  config: |
    {
      "execProviderConfig": {
        "command": "/usr/local/bin/teleport-auth.sh",
        "args": ["--cluster-name", "prod-cluster-01"],
        "apiVersion": "client.authentication.k8s.io/v1beta1"
      }
    }
  name: prod-cluster-01
  # Использование локального сервиса-прокси для обхода ограничений ArgoCD на уникальность URL
  server: https://cluster-prod-01-proxy.argocd.svc.cluster.local:3026
```

2. **Скрипт аутентификации (teleport-auth.sh)**

Скрипт использует утилиту `tbot` (Teleport Bot) для получения временных учетных данных. Рекомендуется режим фонового обновления сертификатов `tbot`: tbot работает как sidecar или DaemonSet и постоянно держит актуальные креды в общем volume.

```bash
#!/bin/bash
# Аргументы передаются из execProviderConfig
CLUSTER_NAME=$2

# Получение актуального kubeconfig через tbot
# Предполагается, что tbot запущен как sidecar или daemonset с доступом к /var/lib/tbot
tbot proxy kube --cluster-name="${CLUSTER_NAME}" --out-file="/tmp/kubeconfig-${CLUSTER_NAME}" > /dev/null 2>&1

# Возврат JSON для Kubernetes exec credential plugin
cat "/tmp/kubeconfig-${CLUSTER_NAME}" | jq -c '.auth_info' # Пример упрощенной логики
```

3. **Решение проблемы уникальности эндпоинтов (ExternalName)**

ArgoCD может некорректно обрабатывать несколько кластеров, если у них один и тот же URL прокси (Teleport).
**Решение:** Создание объектов `Service` типа `ExternalName` для каждого кластера в namespace ArgoCD — каждый кластер получает свой DNS-псевдоним, указывающий на общий Proxy.

```yaml
kind: Service
apiVersion: v1
metadata:
  name: cluster-prod-01-proxy
  namespace: argocd
spec:
  type: ExternalName
  externalName: teleport.example.com # Реальный адрес Teleport Proxy
```

**Валидация (оба варианта)**: `argocd cluster list` показывает кластер со статусом `Successful`; принудительная синхронизация тестового приложения проходит; в журнале Teleport появляется сессия доступа от имени бота.

### Сценарий 2: Git-структура политик и доставка через ApplicationSet

Для гибкого управления политиками репозиторий разделяется на логические уровни:

1.  **`white/`** — глобальные политики для всех кластеров (например, запрет privileged-контейнеров, обязательные лейблы).
2.  **`zones/`** — группировка по зонам ответственности (production, test, pci-dss).
3.  **`clusters/`** — специфические исключения или настройки для конкретного кластера.

Такое наслоение реализует принцип наследования: базовый уровень безопасности одинаков везде, зональные требования добавляют строгость, а кластерный уровень — только точечные исключения, каждое из которых видно в Git и проходит code review.

**Механизм доставки:**
ArgoCD использует **ApplicationSet** с генераторами (`Git` или `Cluster`), которые считывают метаданные кластеров и автоматически подключают соответствующие папки из Git.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: policy-deployment
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            security-tier: high
  template:
    metadata:
      name: 'policies-{{name}}'
    spec:
      source:
        path: policies/zones/high-security
        repoURL: https://git.example.com/sec/policies.git
      destination:
        server: "{{server}}"
        namespace: gatekeeper-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - ServerSideApply=true
```

**Ключевые детали**:
- Генератор `clusters` берет метки из секрета кластера (при варианте B их задают вручную, при варианте A — шаблонизированные `secret_labels` tbot). Генератор `Git` вместо этого читает список кластеров из файла в репозитории — удобно, если состав фермой управляет отдельный процесс.
- `ServerSideApply=true` обязателен для крупных CRD политик: ConstraintTemplate содержит Rego-код в поле размером в десятки КБ и может превышать лимит аннотации `last-applied-configuration` (~256 КБ суммарно) при классическом client-side apply.
- Для упорядочивания доставки используйте sync-waves: `argocd.argoproj.io/sync-wave: "-10"` у ConstraintTemplate, `-5` у Constraint — шаблон всегда создается раньше инстанса, иначе синхронизация падает с ошибкой отсутствия CRD.

### Сценарий 3: Развертывание политики в Gatekeeper

Политика в Gatekeeper — это всегда пара: `ConstraintTemplate` (логика) + `Constraint` (экземпляр с параметрами).

1. **ConstraintTemplate** (apiVersion `templates.gatekeeper.sh/v1`; схема параметров должна быть структурной, т.е. содержать `type` на каждом уровне):

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels          # имя CRD-инстанса политики
      validation:
        openAPIV3Schema:
          type: object                    # структурная схема обязательна для v1
          properties:
            labels:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8srequiredlabels
        violation[{"msg": msg, "details": {"missing_labels": missing}}] {
          provided := {label | input.review.object.metadata.labels[label]}
          required := {label | label := input.parameters.labels[_]}
          missing := required - provided
          count(missing) > 0
          msg := sprintf("you must provide labels: %v", [missing])
        }
```

2. **Constraint** (экземпляр политики):

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: ns-must-have-owner
spec:
  enforcementAction: dryrun               # dryrun | warn | deny — этапность внедрения
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Namespace"]
    excludedNamespaces:
      - kube-system
  parameters:
    labels: ["owner", "cost-center"]
```

**Пояснения**:
- `enforcementAction`: `dryrun` — нарушения только пишутся в статус Constraint; `warn` — запрос проходит, но пользователю показывается предупреждение; `deny` (по умолчанию) — запрос блокируется. Продвижение `dryrun → warn → deny` и есть управляемый rollout.
- Rego-код выше использует классический синтаксис v0 — он остается рабочим по умолчанию. В Gatekeeper 3.19+ доступен opt-in синтаксис Rego v1 через блок `code:` (`engine: Rego`, `source.version: "v1"`), а также CEL (`engine: CEL`) — CEL имеет более высокий приоритет вычисления при наличии обоих.

3. **Валидация**:

```bash
kubectl get constrainttemplates
# → result: k8srequiredlabels   AGE 5m   (без ошибок компиляции)
kubectl get k8srequiredlabels ns-must-have-owner -o jsonpath='{.status.violations}' | jq
# → result: [{"enforcementAction":"dryrun","group":"","kind":"Namespace","message":"you must provide labels: {\"owner\"}","name":"sandbox"}]
kubectl create ns test-ns
# → result: namespace/test-ns created   (dryrun не блокирует; при deny — Error from server ([ns-must-have-owner] you must provide labels...)
```

Для типовых политик используйте каталог gatekeeper-library через CLI: `gator policy install --bundle pod-security-baseline --enforcement-action=warn --dry-run` (предпросмотр) — см. Сценарий 5.

### Сценарий 4: Развертывание политики в Kyverno

Kyverno описывает всё одной политикой. Пример комбинации validate + mutate:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: standard-pod-security
spec:
  validationFailureAction: Audit        # Audit | Enforce — глобальный режим политики
  background: true                        # проверять уже существующие ресурсы фоновым сканером
  rules:
    - name: require-requests
      match:
        any:
          - resources:
              kinds: ["Pod"]
      validate:
        message: "Контейнеры обязаны задавать resources.requests/limits."
        pattern:
          spec:
            containers:
              - resources:
                  requests:
                    memory: "?*"
                    cpu: "?*"
    - name: add-image-pull-policy
      match:
        any:
          - resources:
              kinds: ["Pod"]
      mutate:
        patchStrategicMerge:
          spec:
            containers:
              - (image): "*:latest"
                imagePullPolicy: "Always" # мутация: для :latest всегда Always
    - name: exclude-ci-runner             # исключение по метке контроллера CI
      match:
        any:
          - resources:
              kinds: ["Pod"]
              selector:
                matchLabels:
                  runner: gitlab-ci
      preconditions:
        all:
          - key: "{{ request.operation }}"
            operator: Equals
            value: "CREATE"
      validate:
        pattern:
          metadata:
            annotations:
              audit/*: "?*"             # формальная проверка аннотации аудита вместо паттерна ресурсов
```

**Пояснения**:
- `validationFailureAction: Audit` — режим «только фиксировать»; переводится в `Enforce` после анализа PolicyReports. Переопределение на уровне namespace — через `validationFailureActionOverrides`.
- Исключения оформляются отдельными правилами с `match.selector` или блоком `exclude` — гибкое отсечение ресурсов по именам, ролям и меткам без изменения основной логики.
- Kyverno генерирует `PolicyReport`/`ClusterPolicyReport` автоматически — их читает Policy Reporter UI (см. раздел Наблюдаемость).

**Валидация**:

```bash
kubectl get clusterpolicy standard-pod-security
# → result: NAME ... BACKGROUND   VALIDATE ACTION   READY
#           standard-pod-security  true         Audit       True
kubectl apply -f bad-pod.yaml   # под без requests
# → result: pod/bad-pod created (Audit пропускает); в PolicyReport появляется violation
kubectl get policyreports -n default
# → result: policyreport-... RESULT: fail, RULE: require-requests
```

### Сценарий 5: Тестирование политик до доставки в кластеры

Политики безопасности напрямую влияют на доступность API-сервера: ошибка в Rego-коде или YAML-манифесте Kyverno способна заблокировать критические процессы. Поэтому тестирование выполняется локально, в пайплайне репозитория политик.

**Gatekeeper / OPA**:
1. `conftest` или `opa test` — проверка логики Rego-правил на синтетических манифестах перед фиксацией в Git.
2. Нативный CLI Gatekeeper — **gator**:
   ```bash
   # Разовая проверка манифеста против папки с шаблонами и констрейнтами
   gator test -f=my-manifest.yaml -f=templates-and-constraints/
   # → result: violations выводятся в stdout, exit code 1 (как при реальном deny)
   ```
3. Юнит-тесты в формате Suite (`test.gatekeeper.sh/v1alpha1`) — декларативные кейсы pass/fail с точными ассертами на количество и текст нарушений:
   ```yaml
   apiVersion: test.gatekeeper.sh/v1alpha1
   kind: Suite
   tests:
     - name: required-labels
       template: template.yaml
       constraint: constraint.yaml
       cases:
         - name: ns-without-owner
           object: samples/ns-no-owner.yaml
           assertions:
             - violations: yes
               message: "you must provide labels"
         - name: ns-valid
           object: samples/ns-ok.yaml
           assertions:
             - violations: no
   ```
   ```bash
   gator verify ./...
   # → result: ok      required-labels/ns-without-owner
   #           FAIL    required-labels/ns-valid (если нарушение неожиданно появилось)
   ```

**Kyverno**: CLI `kyverno test` прогоняет политики над фикстурами со сравнением ожидаемых результатов pass/fail:
```bash
kyverno test ./policies/
# → result:
# Applying 2 policies to 3 resources...
# │───│──────────────────────│────────│────────│
# │ # │ POLICY               │ RULE   │ RESULT │
# │───│──────────────────────│────────│────────│
# │ 1 │ standard-pod-security│ require-requests │ Pass │
```

### Пайплайн продвижения

Рекомендуемый процесс доставки политик:
`Linting & Unit Tests (gator verify / kyverno test) → Validation in Sandbox → Audit Mode in Staging → Enforce Mode in Production`

Каждая ступень — отдельный Git-окружение/зона из Сценария 2; переход политики между ступенями оформляется PR'ом с изменением `enforcementAction`/`validationFailureAction` и ревью владельца целевой зоны.

## Наблюдаемость и мониторинг нарушений

Стандартный Gatekeeper не экспортирует детали нарушений (какой именно объект нарушил политику) в стандартные метрики — агрегированное число доступно, но для расследований нужен разрез по объектам. Ниже три уровня решения.

### Использование opus-scorecard
Решение `opus-scorecard` собирает информацию о `violations` из статуса объектов `Constraint` и предоставляет их по эндпоинту `/metrics`. Это внутренний экспортер: он читает поле `.status.violations` каждого Constraint (Gatekeeper заполняет его фоновым аудитом) и превращает в серийные метрики с лейблами namespace/kind/name нарушившего объекта.

**Ключевые метрики для Grafana:**
- `gatekeeper_violations` — общее количество нарушений.
- `gatekeeper_constraint_status` — состояние синхронизации политик.

Пример PromQL для дашборда «топ нарушающих неймспейсов»:
```promql
topk(10, sum by (namespace) (rate(gatekeeper_violations[1h])))
```

### Нативные средства Gatekeeper
- **Статус Constraint**: поле `.status.violations` содержит полный список нарушений с указанием объекта и сообщения — источник данных для любых экспортеров. Обновляется фоновым аудитом (интервал настраивается флагом `--audit-interval`, по умолчанию 60 минут).
- **Метрики контроллера**: `gatekeeper_constraints` (число политик по enforcement action), `gatekeeper_violations` (агрегат), `constraint_template_handler_reconcile_errors` / `gatekeeper_webhook_*` (здоровье вебхука).
- **Экспорт нарушений**: современные версии Gatekeeper имеют встроенный интерфейс экспорта событий аудита во внешние системы (драйверы экспорта) — альтернатива кастомным экспортерам для передачи нарушений в SIEM.

### Policy Reporter
Для Kyverno и Gatekeeper рекомендуется использовать **Policy Reporter UI**, который агрегирует `PolicyReports` и предоставляет удобный интерфейс для ИБ-специалистов, включая отправку уведомлений в Slack/Teams при появлении новых нарушений. Kyverno наполняет отчеты нативно; для Gatekeeper отчеты формируются из результатов аудита через интеграционные компоненты.

Минимальная установка (Helm):
```bash
helm repo add policy-reporter https://kyverno.github.io/policy-reporter && helm repo update
helm install policy-reporter policy-reporter/policy-reporter \
  --set ui.enabled=true \
  --set rest.enabled=true \
  --namespace policy-reporter --create-namespace
kubectl -n policy-reporter port-forward svc/policy-reporter-ui 8080:80
# → result: UI доступен на http://localhost:8080 со списком violations по всем кластерам (при мультитенантном Loki)
```

**Валидация наблюдаемости**: внесите заведомое нарушение в staging (под без лейбла owner), дождитесь цикла аудита и убедитесь, что нарушение видно одновременно в метриках (`gatekeeper_violations > 0`), в статусе Constraint и в Policy Reporter.

## Производительность и масштабирование

При управлении большим количеством кластеров (100+) необходимо:

- **Шардирование контроллера (Controller Sharding):** ArgoCD требует масштабирования `argocd-application-controller` (примерно 1 реплика на 20-30 кластеров в зависимости от количества ресурсов). В современных версиях Argo CD доступны не только round-robin, но и алгоритмы `consistent-hashing` и `least-weighted` (`ARGOCD_CONTROLLER_SHARDING_ALGORITHM`) — они дают более равномерное распределение при разнородных кластерах и позволяют закреплять кластеры за шардами весами. Дополнительно настройте процессоры статуса/операций (`--status-processors`, `--operation-processors`).
- **Оптимизация tbot:** Использование кэширования для токенов Teleport в памяти (tmpfs), чтобы снизить нагрузку на диск и ускорить время отклика `execProviderConfig`. При варианте A нагрузка на скрипты отсутствует вовсе — tbot сам ротирует секреты по расписанию.
- **Лимиты ресурсов:** Увеличьте `memory` для `repo-server`, так как рендеринг множества ApplicationSets требует значительного объема RAM.
- **Tuning ArgoCD:** Установка `ARGOCD_EXEC_TIMEOUT` (по умолчанию 90с) может потребоваться увеличить при медленных ответах через прокси.
- **Аудит Gatekeeper:** фоновый аудит сканирует весь кластер и нагружает etcd/API. При сотнях политик ограничьте `--audit-match-match-only` или распишите `excludedNamespaces`, а интервал аудита увеличьте осознанно — от него зависит свежесть `.status.violations`.

## Исключения и гибкость политик

Исключения могут быть реализованы на трех уровнях:

### 1. На уровне Git
Удаление/добавление манифестов `Constraint` в папках конкретных кластеров через ApplicationSet.

### 2. Параметры Constraint (Gatekeeper)
Использование поля `match.excludedNamespaces` или `match.labelSelector` в манифесте политики.

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: ns-must-have-owner
spec:
  match:
    excludedNamespaces:
      - kube-system
      - istio-system
    labelSelector:
      matchExpressions:
        - {key: security, operator: NotIn, values: [ignored]}
```

### 3. Внутри Rego-кода (OPA)
Проверка специфических меток (labels) на ресурсах через инвентаризацию данных (`data.inventory`). Инвентаризация работает только для ресурсов, включенных в синхронизацию (Config-ресурс Gatekeeper / SyncSet) — без нее `data.inventory` пуст и исключения «не сработают».

```rego
# Пример исключения в Rego
package kubernetes.admission

deny[msg] {
    # Проверка метки исключения на namespace
    not is_excluded_namespace(input.request.namespace)
    # Логика: запрет образов без хэша (sha256)
    [image, tag] := split(input.request.object.spec.containers[_].image, ":")
    not contains(image, "@sha256")
    msg := "Образы должны содержать digest (sha256)."
}

is_excluded_namespace(ns) {
    data.inventory.cluster["v1"]["Namespace"][ns].metadata.labels["security.policy/ignore"] == "true"
}
```

Примечание о версиях языка: пример использует классический синтаксис Rego v0, который остается рабочим по умолчанию в актуальном Gatekeeper. Для новых шаблонов рекомендуется синтаксис Rego v1 (OPA 1.x): правила объявляются через `if` и `contains` (например, `deny contains msg if { ... }`), включение — блоком `code:` c `source.version: "v1"` в ConstraintTemplate.

### 4. Исключения в Kyverno
Использование блока `exclude` в правилах политики, что позволяет гибко отсекать ресурсы по именам, ролям или меткам.

## Жизненный цикл политик

Политики безопасности напрямую влияют на доступность API-сервера, поэтому жизненный цикл строится вокруг безопасного продвижения режимов:

1. **Разработка**: политика пишется в репозитории политик, проходит юнит-тесты (Сценарий 5) и ревью владельцев зон.
2. **Audit/Dryrun**: первичное внедрение всегда в режиме `Audit` (Kyverno) или `dryrun`/`warn` (Gatekeeper) — оценивается влияние на существующие ресурсы без блокировки.
3. **Анализ**: по метрикам opus-scorecard/native и PolicyReport принимается решение о готовности к Enforce; ложные срабатывания устраняются исключениями уровня 2–4 выше.
4. **Enforce**: перевод в `deny`/`Enforce` отдельным PR'ом; отккат — обратный PR (история изменений сохраняется в Git).
5. **Cleanup**: неиспользуемые политики удаляются из Git вместе с их папками зон — ApplicationSet автоматически снимет их с кластеров (`prune: true`).

## Типичные проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Все операции в кластере блокируются после установки политики | Вебхук Gatekeeper/Kyverno отвечает с ошибкой при `failurePolicy: Fail` (недавняя правка Rego/YAML, OOM контроллера) | Проверить логи контроллера; временно отключить вебхук (label `admission.gatekeeper.sh/ignore` на namespace или удаление ValidatingWebhookConfiguration) и откатить политику PR'ом |
| Constraint создан, но не работает | Неструктурная схема параметров в v1-шаблоне или параметры не совпадают с CRD | Проверить `kubectl get constrainttemplates <name> -o yaml` на ошибки компиляции; убедиться, что schema содержит `type: object` |
| `.status.violations` пустой, хотя нарушения очевидны | Аудит еще не прошел (интервал до 60 минут) или ресурсы не попадают под `match` | Запустить аудит вручную (уменьшить `--audit-interval`), проверить `match.kinds/excludedNamespaces` |
| Референциальная политика не видит объекты (`data.inventory` пуст) | Ресурсы этого GVK не включены в репликацию | Добавить GVK в Config-ресурс Gatekeeper или SyncSet; проверить метрику sync-статуса |
| Синхронизация политик падает с «no matches for kind» | Constraint применяется раньше создания ConstraintTemplate | Задать sync-waves: шаблон `-10`, инстанс `-5` (см. Сценарий 2); включить ServerSideApply для больших CRD |
| Ошибка «cluster server URL must be unique» в ArgoCD | Несколько кластеров с одним адресом Teleport Proxy | Создать ExternalName-сервисы по одному на кластер (Сценарий 1B) либо перейти на вариант A — tbot сам создает уникальные секреты |
| Кластеры отваливаются через N часов | Истекшие сертификаты tbot: процесс остановлен или кластер выпал из `clusterSelectors` | Проверить под tbot и его журнал; форсировать обновление `pkill -USR1 tbot`; сверить метки кластеров в Teleport |
| Kyverno мутация зациклилась / конфликтует с GitOps | Мутируемое поле расходится с манифестом в Git — ArgoCD показывает вечный OutOfSync | Исключить поле из сверки (ignoreDifferences) или перенести мутацию в Git; проверить порядок: webhook Kyverno против ServerSideApply ArgoCD |

## Дополнительная информация

### См. также
- **[Эшелонированная защита в IaC](../../CI-CD/DevSecOps/iac-security-defense-in-depth.md)** — общая стратегия многоуровневого контроля безопасности.
- **[OPA Gatekeeper: детали и Rego](../../Kubernetes/Security/rbac/limitations_opa.md)** — глубокий разбор движка OPA.
- **[Интеграция Kyverno с ArgoCD](../../Kubernetes/Security/kyverno/argo-cd.md)** — нюансы Server-Side Diff и мутаций.
- **[ArgoCD: обзор архитектуры](../ArgoCD/argocd_overview.md)** — базовые принципы GitOps.
- **[Управление секретами в GitOps](../secrets_encryption.md)** — шифрование креденшилов для доступа к кластерам.

### Внешние ресурсы
- [Gatekeeper: документация (v3.23)](https://open-policy-agent.github.io/gatekeeper/website/docs/)
- [Gatekeeper: gator CLI](https://open-policy-agent.github.io/gatekeeper/website/docs/gator/)
- [Teleport: Machine & Workload Identity with Argo CD](https://goteleport.com/docs/machine-workload-identity/access-guides/argocd/)
- [Kyverno: документация](https://kyverno.io/docs/)
- [Policy Reporter](https://kyverno.github.io/policy-reporter/)

## Вопросы для собеседования

### Зачем нужны и CI-политики, и admission-контроль одновременно?
Это разные гарантии: CI-политики (conftest) дают быструю обратную связь в PR, но обходятся любым прямым `kubectl apply`. Admission (Kyverno/Gatekeeper) проверяет всё, что реально попадает в кластер, включая GitOps-агент и админские правки. Эшелон: pre-commit → CI → admission → аудит.

### Kyverno или Gatekeeper — критерии выбора?
Gatekeeper: Rego (мощнее для сложных условий), зрелая экосистема OPA, gator для офлайн-тестов. Kyverno: политики на YAML без изучения языка, встроенные mutate/generate правила, ниже порог входа для команд. Типовой выбор: платформенная команда знает Rego и хочет сложные политики — Gatekeeper; нужен быстрый adoption с мутациями — Kyverno.

### Как безопасно раскатить новую блокирующую политику?
Стадии: `audit`/`dryrun` → сбор нарушений через Policy Reports → исправление или исключения для легитимных случаев → `enforce` по одному namespace/кластеру за раз. Блокировка всего флота сразу — типичная причина аварий деплоя.

### Как оформлять исключения из политик, не превращая их в дыру?
Исключение — это изменение в Git с ревью: label/аннотация на ресурсе + параметр constraint'а, ограниченный namespace и reason. Каждое исключение имеет срок (TTL) и владельца; регулярный аудит списка исключений. Глобальное отключение политики = инцидент процесса.

### Что такое Policy Reports и зачем они?
Стандарт Kubernetes (policyreport.wg-plural.dev): единый формат результатов политик как CRD. Kyverno/Gatekeeper пишут нарушения в PolicyReport — Policy Reporter UI агрегирует их по кластерам, что дает один экран «кто и какие политики нарушает» вместо чтения событий каждого контроллера.
