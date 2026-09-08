# Профилактика CreateContainerConfigError

## Определения

**Профилактика CreateContainerConfigError** — стратегия упреждающего контроля конфигураций, направленная на минимизацию риска возникновения ошибок при формировании спецификации контейнера в рантайме. В отличие от реактивной диагностики, профилактика фокусируется на «сдвиге влево» (Shift-Left) — проверке зависимостей (ConfigMap, Secret, PVC, RBAC) на этапах разработки, CI/CD и Admission Control.

Основная цель — гарантировать, что к моменту, когда `kubelet` начнет создание контейнера, все внешние ссылки в `PodSpec` будут валидными и доступными.

## Основные концепции

### Механизм возникновения и точки вмешательства (Prevention Targets)

Чтобы эффективно предотвращать ошибку, необходимо понимать, **на каком этапе** kubelet формирует конфигурацию и **где именно** зависимость может потеряться. Цикл синхронизации пода (Pod Worker) включает следующие фазы:

```text
SyncPod Loop (kubelet)
  1. Получение спецификации пода от API-сервера (Watch/GET)
  2. Volume Admission и монтирование (VolumeManager)
  3. Dependency Resolution — критическая фаза:
     ├── Запрос ConfigMap/Secret через API-сервер (env, envFrom, volumes)
     ├── Генерация Downward API (fieldRef, status.podIP и др.)
     ├── Генерация ServiceAccountToken (projected volume)
     └── Разрешение imagePullSecrets для Private Registry
  4. CRI Config Generation — сборка ContainerConfig для container runtime
  5. CRI.CreateContainer — передача конфигурации в containerd/CRI-O
```

Ошибка `CreateContainerConfigError` возникает на **фазе 3 (Dependency Resolution)**: если любой из запрошенных ресурсов возвращает 404 Not Found, 403 Forbidden или содержит некорректный ключ, kubelet не может собрать `ContainerConfig` и блокирует переход к фазе 5. Поскольку CRI-вызов `CreateContainer` никогда не выполняется, контейнер не создается в container runtime, и `kubectl logs`/`kubectl exec` недоступны.

**Ключевой вывод для профилактики:** поскольку зависимости разрешаются на стороне API-сервера (а не на узле), проверка наличия связей можно выполнить **до** попадания манифеста в кластер — на этапах CI/CD и admission. Это есть суть «сдвига влево» (Shift-Left).

### Эшелонированная защита (Prevention Layers)

Предотвращение ошибок конфигурации строится на четырех уровнях, каждый из которых закрывает узкие места, оставленные предыдущим:

1.  **Клиентский уровень (Pre-commit/IDE):** Использование линтеров и расширений (например, vscode-kubernetes, `kube-linter`), которые подсвечивают отсутствие ресурсов и опечатки в именах. Быстрая обратная связь на этапе написания манифеста.
2.  **Уровень CI (Pipeline Validation):** Статический анализ манифестов (`kubeconform`, `conftest`, `kube-score`, `polaris`) и проверка существования зависимостей в целевом окружении через `--dry-run=server`.
3.  **Уровень Admission Control (Cluster Guardrails):** Использование Policy Engines (Kyverno, OPA/Gatekeeper) или встроенных `ValidatingAdmissionPolicy` (CEL) для блокировки подов, ссылающихся на несуществующие или недопустимые ресурсы.
4.  **Уровень приложения (Graceful Degradation):** Использование флага `optional: true` для второстепенных настроек, позволяющее приложению запуститься даже при отсутствии конфига.

### Стратегии предотвращения

| Стратегия | Механизм | Результат |
|-----------|----------|-----------|
| **Статическая валидация** | Проверка схем API и Best Practices до деплоя | Исключение синтаксических ошибок и использования deprecated полей |
| **Генерация с хешированием** | `configMapGenerator` в Kustomize / Helm | Гарантированная консистентность: под всегда ссылается на конкретную версию ресурса |
| **Семантическая проверка** | Кастомные скрипты в CI или Policy Engines | Проверка логических связей (например, наличие секрета для `imagePullSecrets`) |
| **Admission Enforcement** | Блокировка запроса на создание Pod через Webhooks | Предотвращение попадания некорректных спецификаций в `etcd` |

### Инструменты валидации и анализа

Инструменты валидации делятся на две категории: офлайн-проверка (без доступа к кластеру) и онлайн-проверка (с доступом к API-серверу). Комбинация обеих категорий дает максимальное покрытие.

**Офлайн-валидация (CI без доступа к кластеру, air-gapped):**

```bash
# 1. Kubeconform (валидация схем OpenAPI)
kubeconform -strict -summary -kubernetes-version 1.31 manifests/

# 2. Conftest (проверка Rego-политик)
conftest test manifests/ --policy policies/

# 3. Kube-score (проверка best practices и security)
kube-score score manifests/

# 4. Polaris (проверка на соответствие best practices)
polaris audit manifests/ --audit-path .
```

**Онлайн-валидация (CI/CD с доступом к кластеру, pre-deploy):**

```bash
# 5. Server-side dry-run (самый надежный метод — проверяет RBAC и admission)
kubectl apply -f manifests/ --dry-run=server

# 6. Kubectl diff (просмотр изменений перед применением)
kubectl diff -f manifests/
```

> **Важно:** `kubectl apply --dry-run=server` отправляет объект через полную admission-цепочку API-сервера без сохранения в `etcd`. Это проверяет не только синтаксис и схемы, но и права доступа (RBAC), политики безопасности (PSA, Kyverno, OPA/Gatekeeper) и валидирующие вебхуки. В отличие от `kubeconform`, который работает только с JSON-схемами, `dry-run=server` ловит конфликты, связанные с admission-контроллерами и мутирующими вебхуками.

> **Комбинированный подход:** используйте `kubeconform` (быстрая схематическая проверка) + `conftest` (политики безопасности) + `--dry-run=server` (финальная проверка перед применением). Порядок — от быстрой к дорогой проверке.

## Практические сценарии

### Сценарий 1: Управление зависимостями через Kustomize (Immutable-подход)

Использование генераторов ресурсов решает проблему «зависших» подов при обновлении конфигурации.

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  files:
  - config.properties
generatorOptions:
  disableNameSuffixHash: false # По умолчанию false, добавляет хеш к имени
```

**Почему это предотвращает ошибку:**
1. К имени ConfigMap добавляется хеш (например, `app-config-847h79777f`).
2. При изменении файла создается НОВЫЙ объект с новым хешем.
3. Kustomize автоматически обновляет ссылку в Deployment.
4. Kubernetes запускает Rolling Update. Старый под продолжает работать со старым конфигом, пока новый не перейдет в `Ready`.

### Сценарий 2: Использование опциональных зависимостей (Optional Flags)

Для параметров, которые не являются критическими для старта приложения, всегда используйте флаг `optional`.

```yaml
env:
- name: DEBUG_TOOLS_CONFIG
  valueFrom:
    configMapKeyRef:
      name: non-critical-config
      key: debug-level
      optional: true # Под запустится, даже если ConfigMap отсутствует
```

### Сценарий 3: Проверка RBAC и ServiceAccount в CI

Частая причина `CreateContainerConfigError` — отсутствие прав у `ServiceAccount` на чтение секретов. Это можно проверить в CI пайплайне перед деплоем.

```bash
# Имитация прав ServiceAccount для проверки доступа
kubectl auth can-i get secret --as=system:serviceaccount:my-namespace:my-app-sa
# → yes (или no)

# Проверка в скрипте CI
if ! kubectl auth can-i get secret/my-secret --as=system:serviceaccount:prod:app-sa; then
  echo "CRITICAL: ServiceAccount lacks permissions to read secrets!"
  exit 1
fi
```

### Сценарий 4: Блокировка через Kyverno (Admission Control)

Политика Kyverno может предотвратить создание пода, если он ссылается на Secret, помеченный как «чувствительный», но не имеющий необходимых меток. Более практичный пример — блокировка подов без обязательных `envFrom`-зависимостей или с ссылкой на несуществующие секреты.

```yaml
# Политика: запрет создания подов без deployment-аннотации checksum/config
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-config-checksum-annotation
spec:
  validationFailureAction: Audit
  rules:
  - name: check-deployment-annotation
    match:
      any:
      - resources:
          kinds:
          - Deployment
    validate:
      message: "Deployment должен содержать аннотацию checksum/config для отслеживания изменений ConfigMap"
      pattern:
        spec:
          template:
            metadata:
              annotations:
                checksum/config: "?*"
```

Для более легковесного контроля без установки внешних компонентов используйте встроенный `ValidatingAdmissionPolicy` (Сценарий 7).

### Сценарий 5: Мониторинг и проактивный алертинг

Настройка Prometheus для раннего обнаружения аномалий в статусах контейнеров.

```yaml
groups:
- name: kubernetes.config.alerts
  rules:
  - alert: KubernetesContainerConfigErrorRate
    # Оповещение при появлении ошибки в пространстве имен
    expr: sum by (namespace) (kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError"}) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Обнаружена ошибка CreateContainerConfigError в namespace {{ $labels.namespace }}"
      description: "Один или несколько подов не могут сформировать конфигурацию контейнера. Проверьте соответствие ConfigMap/Secret."
  ```

### Сценарий 6: Интеграция валидации в CI/CD pipeline

Многоуровневая проверка манифестов в пайплайне. Порядок проверок — от быстрого к дорогому: схема → политики → dry-run.

```yaml
# .github/workflows/deploy.yaml (фрагмент стадии валидации)
name: Deploy
on:
  push:
    branches: [main]

jobs:
  validate-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Render manifests
        run: |
          kustomize build overlays/production > rendered.yaml

      - name: Схематическая проверка (kubeconform)
        run: |
          kubeconform -strict -kubernetes-version 1.31 rendered.yaml

      - name: Политики безопасности (conftest)
        run: |
          conftest test rendered.yaml --policy policies/

      - name: Проверка best practices (kube-score)
        run: |
          kube-score score rendered.yaml

      - name: Server-side dry-run
        run: |
          kubectl apply -f rendered.yaml --dry-run=server
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG_RO }}

      - name: Apply with diff
        run: |
          kubectl diff -f rendered.yaml
          kubectl apply -f rendered.yaml
```

### Сценарий 7: Валидация через ValidatingAdmissionPolicy (CEL)

Встроенный механизм валидации Kubernetes на языке CEL (GA с v1.30). Не требует установки Kyverno или OPA — работает внутри API-сервера с микросекундной задержкой.

```yaml
# VAP: запрет создания пода без ServiceAccount или с опечаткой в имени Secret
apiVersion: admission.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: pod-dependency-check
spec:
  matchConstraints:
    namespaceSelector:
      matchLabels:
        env: production
    scope: Namespaced
    raw:
      rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
  - identifier: required-service-account
    expression: |
      (has(object.spec.serviceAccountName) && object.spec.serviceAccountName != "")
      || (has(object.spec.serviceAccountSelector) && object.spec.serviceAccountSelector != null)
    message: "Pod должен указывать serviceAccountName"
  - identifier: secret-exists-check
    expression: |
      object.spec.containers.all(c, c.env.all(e,
        !has(e.valueFrom.secretKeyRef) ||
        api.objectHasStrict('secrets', e.valueFrom.secretKeyRef.name)
      ))
    message: "Secret, указанный в secretKeyRef, не существует в этом namespace"
---
# Привязка политики к конкретному namespace
apiVersion: admission.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: pod-dependency-check-binding
spec:
  policyName: pod-dependency-check
```

> **Сравнение с Kyverno/OPA:** VAP проще в развертывании (нет внешних компонентов), но ограничен логикой одного запроса. CEL быстрее (in-process), а webhooks добавляют 10–100мс сетевого round-trip. Для простых политик (`required`, `pattern match`) используйте VAP; для сложных сценариев с внешними вызовами — Kyverno/Gatekeeper.

### Сценарий 8: Предотвращение CreateContainerConfigError из-за imagePullSecrets

Отсутствие или недоступность `imagePullSecret` блокирует не фазу Dependency Resolution (как ConfigMap/Secret), а фазу **Volume Admission** — kubelet не может подготовить конфиг тома для аутентификации в реестре.

```yaml
# 1. Создаем Docker Registry Secret (в CI, из переменных окружения)
kubectl create secret docker-registry regcred \
  --docker-server=registry.internal \
  --docker-username="${REGISTRY_USER}" \
  --docker-password="${REGISTRY_PASS}" \
  --docker-email="ci@company.internal" \
  -n "${TARGET_NAMESPACE}"

# 2. Связываем Secret с ServiceAccount (автоматическая инъекция)
kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}' -n "${TARGET_NAMESPACE}"

# 3. Проверка в CI перед деплоем
if ! kubectl get secret regcred -n "${TARGET_NAMESPACE}" >/dev/null 2>&1; then
  echo "CRITICAL: imagePullSecret 'regcred' не найден в namespace ${TARGET_NAMESPACE}"
  exit 1
fi
```

**Почему это предотвращает ошибку:** если `imagePullSecret` отсутствует, kubelet выставит статус `CreateContainerConfigError` с сообщением `secret "regcred" not found` на этапе подготовки тома. Связывание через `ServiceAccount` вместо прямого указания в каждом Pod устраняет риск забыть добавить `imagePullSecrets` в манифест.

### Сценарий 9: Автоматический перезапуск при изменении ConfigMap/Secret (Helm)

Для env-based зависимостей (переменные окружения не перечитываются без перезапуска) используется checksum-аннотация в `spec.template.metadata.annotations`. Хеш изменения контента ConfigMap/Secret гарантирует, что при любом обновлении создается новая ревизия ReplicaSet.

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
      annotations:
        # Автоматический перезапуск при изменении конфигурации
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
    spec:
      serviceAccountName: my-app-sa
      containers:
      - name: app
        image: "registry.internal/my-app:{{ .Chart.AppVersion }}"
        envFrom:
        - configMapRef:
            name: my-app-config
        - secretRef:
            name: my-app-secret
```

**Миграция на immutable + new-name (Production):** для критичных конфигураций сочетайте `immutable: true` с переименованием объекта через хеш. Это гарантирует, что старый объект не исчезнет, пока все поды не перейдут на новый.

### Сценарий 10: Init Container для проверки зависимостей на runtime

Даже при идеальной CI/CD, в продакшене ConfigMap/Secret могут быть удалены вручную. Init Container задействуется **до** основного контейнера и проверяет доступность зависимостей, прежде чем приложение получит управление.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  template:
    spec:
      initContainers:
      - name: wait-for-config
        image: curlimages/curl:8.10.0
        command:
        - /bin/sh
        - -c
        - |
          # Проверка наличия ConfigMap в API (5 попыток с 10s backoffer)
          for i in $(seq 1 5); do
            kubectl get configmap app-config -n "$(POD_NAMESPACE)" && break
            echo "ConfigMap not ready, retrying in 10s..."
            sleep 10
          done
          kubectl get configmap app-config -n "$(POD_NAMESPACE)" || exit 1
        env:
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        volumeMounts:
        - name: kube-api-access
          mountPath: /var/run/secrets/kubernetes.io/serviceaccount
          readOnly: true
      containers:
      - name: app
        image: registry.internal/my-app:1.5.0
        envFrom:
        - configMapRef:
            name: app-config
        - secretRef:
            name: app-secret
        volumeMounts:
        - name: config-volume
          mountPath: /etc/config
          readOnly: true
      volumes:
      - name: kube-api-access
        projected:
          sources:
          - serviceAccountToken:
              path: token
          - configMap:
              name: kube-root-projection
          - downwardAPI:
              items:
              - path: "namespace"
                fieldRef:
                  fieldPath: metadata.namespace
      - name: config-volume
        configMap:
          name: app-config
      serviceAccountName: my-app-sa
      automountServiceAccountToken: true
```

> **Ограничение:** Init Container требует ServiceAccount с правом `get` на ConfigMap/Secret. Для сервисов без доступа к API используйте проверку через файлы в mounted-томах (`test -f /etc/config/app.properties`).

### Сценарий 11: Безопасный rollout с kubectl diff и проверкой статуса

Перед выкатом новой версии с измененными зависимостями используйте `kubectl diff`, чтобы увидеть, какие изменения будут внесены, и `kubectl rollout status`, чтобы дождаться готовности.

```bash
# 1. Просмотр изменений перед применением
kubectl diff -f new-deployment.yaml
# → выводит diff: какие поля изменятся

# 2. Применение (с dry-run сначала, если есть сомнения)
kubectl apply -f new-deployment.yaml

# 3. Мониторинг статуса rollout
kubectl rollout status deployment/my-app --timeout=120s
# → deployment "my-app" successfully rolled out

# 4. Проверка на отсутствие CreateContainerConfigError
kubectl get pods -l app=my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].state.waiting.reason}{"\n"}{end}'
# → если reason == CreateContainerConfigError — откат ниже
```

**Откат при ошибке:**
```bash
# 1. Быстрый откат на последнюю удачную ревизию
kubectl rollout undo deployment/my-app

# 2. Или откат на конкретную ревизию
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE
# → 3         kubectl apply --filename=...
# → 2         <previous>
kubectl rollout undo deployment/my-app --to-revision=2
```

## Граничные случаи (Edge Cases)

| Ситуация | Почему возникает CreateContainerConfigError | Как предотвратить |
| :--- | :--- | :--- |
| **`subPath` с несуществующим ключом** | `subPath` ссылается на ключ, которого нет в ConfigMap/Secret | Убедитесь, что ключи в ресурсе соответствуют именам файлов в `subPath`; используйте `subPathExpr` для вычисляемых путей |
| **binaryData вместо data** | Попытка записать бинарный контент (сертификаты) в `data` — ошибка UTF-8 кодировки | Используйте поле `binaryData` для сертификатов, `.jks`, `.pem` |
| **Переменные envFrom с невалидными именами** | Ключи в ConfigMap содержат символы, недопустимые для env-переменных (точки, дефисы) | `kubelet` молча пропускает невалидные ключи в `envFrom`; используйте явный `env` с `name` |
| **Immutable ConfigMap после удаления** | Попытка обновить `immutable: true` объект вызывает ошибку; удаление и повторное создание приводит к `CreateContainerConfigError` на время | Планируйте замену immutable объектов как создание нового с хеш-суффиксом |
| **Объем Secret > 1 MiB** | Данные не помещаются в etcd объект | Разделяйте на несколько Secret; для больших данных используйте внешнее хранилище или PVC |
| **NodeRestriction блокирует доступ** | Admission-контроллер запрещает kubelet читать Secret/ConfigMap, не используемые подами на этом узле | Создавайте Secret/ConfigMap в том же Namespace; не используйте `namespaceSelector` в ServiceAccount |
| **ServiceAccount без токена** | `automountServiceAccountToken: false` при необходимости доступа к API | Всегда явно указывайте `automountServiceAccountToken: true` или используйте отдельный SA |

## Очистка и откат (Cleanup & Rollback)

### Допрос ссылок перед удалением ConfigMap/Secret

Перед удалением объекта убедитесь, что на него нет ссылок в работающих подах. Несвоевременное удаление — одна из самых частых причин `CreateContainerConfigError` в продакшене.

```bash
# Проверка использования Secret по всем namespace
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.volumes != null) | .spec.volumes[]? | select(.secret != null) | .secret.secretName' | sort -u
# → список всех Secret, используемых в volumes

# Проверка использования ConfigMap в env/envFrom
kubectl get pods -A -o json | jq -r '.items[] | .spec.containers[]?.env[]?.valueFrom.configMapKeyRef.name, .spec.containers[]?.envFrom[]?.configMapRef.name' | sort -u

# Проверка перед удалением конкретного Secret
kubectl get pods -n <namespace> -o json | jq -r '.items[] | select(.spec.serviceAccountName == "my-app-sa") | .metadata.name'
```

### Безопасное удаление

```bash
# 1. Проверить, что ни один под не использует объект
REFCOUNT=$(kubectl get pods -n <ns> -o json | jq --arg name "<obj-name>" '[.items[] | .spec.containers[]? | .env[]?.valueFrom.configMapKeyRef.name, .envFrom[]?.configMapRef.name, .spec.volumes[]?.configMap.name] | map(select(. == $name)) | length')
[[ "$REFCOUNT" -gt 0 ]] && echo "WARNING: $REFCOUNT pods use this object" && exit 1

# 2. Удалить объект
kubectl delete configmap <obj-name> -n <ns>
```

### Откат изменений

```bash
# 1. Просмотр истории изменений
kubectl rollout history deployment/<name>

# 2. Откат на конкретную ревизию
kubectl rollout undo deployment/<name> --to-revision=<n>

# 3. Если ConfigMap был удален — восстановите из Git
git checkout HEAD~1 -- manifests/configmap.yaml
kubectl apply -f manifests/configmap.yaml
kubectl rollout restart deployment/<name>
```

## Список лучших практик (Checklist)

| Категория | Рекомендация |
|-----------|--------------|
| **Версионность** | Используйте `configMapGenerator` или Helm-чарты с `checksum/config` аннотацией. |
| **Валидация** | Интегрируйте `kubeconform`, `conftest`, `kube-score` и `--dry-run=server` в CI/CD пайплайны. |
| **Доступ (RBAC)** | Проверяйте права `ServiceAccount` перед выкаткой новых зависимостей (`kubectl auth can-i`). |
| **Отказоустойчивость** | Используйте `optional: true` для всех некритичных переменных окружения и томов. |
| **Чистота** | Удаляйте старые ConfigMap/Secret только после проверки отсутствия ссылок (см. jq-скрипты выше). |
| **Immutable** | Помечайте стабильные ConfigMap/Secret как `immutable: true` для снижения нагрузки на API-сервер. |
| **imagePullSecrets** | Связывайте реестровые секреты через `ServiceAccount`, а не указывайте в каждом Pod. |
| **Объем** | Не превышайте 1 MiB на один Secret/ConfigMap. |
| **Rollout** | Используйте `kubectl diff` перед применением; проверяйте `kubectl rollout status` после. |
| **Мониторинг** | Настраивайте алерты на `CreateContainerConfigError` в Prometheus (Сценарий 5). |
| **Admission** | Для production-кластеров используйте VAP (CEL) или Kyverno для enforcement политик. |
| **Namespace Correlation** | Убедитесь, что Pod, ServiceAccount, Secret, ConfigMap, PVC находятся в одном Namespace. |

## Дополнительная информация

### Связь с другими практическими руководствами

- Управление секретами: [Безопасность Secret в Kubernetes](../../../Security/application_secrets_management.md)
- Контроллеры допуска: [Контроллеры допуска (Admission Controllers)](../../../Concepts/admission_controllers.md)
- Валидация манифестов: [Kubeconform](../../../ToolsUtilities/kubeconform_overview.md)
- CI/CD pipeline с валидацией: [GitOps: пример пайплайна](../../../GitOps/gitops_pipeline_example.md)
- Управление политиками: [GitOps: управление политиками через GitOps](../../../GitOps/Concepts/gitops-policy-management.md)

### Связанные ресурсы

- [Определения CreateContainerConfigError](./definitions.md)
- [Диагностика ошибки](./diagnostics.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)
- [Проблемы с PVC](./pvc_issues.md)
- [Проблемы с томами](./volume_issues.md)
- [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md)

