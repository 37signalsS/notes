# Сравнение движков политик: Kyverno vs OPA Gatekeeper vs ValidatingAdmissionPolicy

## Определения

**OPA Gatekeeper** — реализация Open Policy Agent для Kubernetes. Использует язык Rego для описания политик через Constraint Templates (шаблоны) и Constraints (экземпляры). Валидирующий webhook с фоновым аудитом.

**Kyverno** — движок политик, разработанный специально для Kubernetes. Описывает политики в нативном YAML-формате. Поддерживает валидацию, мутацию и генерацию ресурсов. Два поколения API: v1 (ClusterPolicy) и v2 (ValidatingPolicy + MutatingPolicy + GeneratingPolicy).

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA в v1.30) механизм декларативной валидации на базе CEL. Работает внутри процесса API-сервера без вызова внешних вебхуков.

---

## Сравнительная таблица

| Критерий | OPA Gatekeeper | Kyverno v2 (CEL) | Kyverno v1 (Webhook) | VAP (Kubernetes) |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Rego | CEL (Common Expression Language) | YAML + CEL | CEL |
| **Тип вебхука** | External | Internal (интегрирован в v2) | External | Нет (нативный) |
| **Задержка** | 20-50ms | <1ms (v2), 10-30ms (v1) | 10-30ms | <1ms |
| **Валидация** | ✅ | ✅ | ✅ | ✅ |
| **Мутация** | ❌ | ✅ (отдельный компонент) | ✅ | ❌ |
| **Генерация** | ❌ | ✅ | ✅ | ❌ |
| **Фоновый аудит** | ✅ | ✅ | ✅ | ❌ (только admission) |
| **Audit Interval** | 60s (по умолчанию) | 60s (по умолчанию) | 60s | Нет |
| **Обнаружение дрейфа** | ✅ | ✅ | ✅ | ❌ |
| **Pod Disruption Budget** | Да | Да | Да | Нет |
| **Потребление RAM** | 150-300MB | 100-200MB | 200-400MB | 0MB |
| **Сложность развертывания** | Средняя | Низкая (v2) | Средняя | Нулкая (ядро K8s) |
| **Переносимость** | Высокая (OPA на любом K8s) | Средняя (Kubernetes-native) | Средняя | Низкая (зависимость от версии K8s) |

---

## Практические сценарии

### Сценарий 1: Выбор движка для нового кластера

**Условия:** Production-кластер, 200 нод, 5000 подов. Требуется валидация + мутация.

**Анализ:**
- VAP: Нет мутации → не подходит
- Gatekeeper: Мутация не поддерживается → не подходит
- Kyverno v2 (CEL): Валидация + мутация через разные компоненты → подходит
- Kyverno v1: Валидация + мутация в одном компоненте → подходит

**Решение:** Kyverno v2 (ValidatingPolicy + MutatingPolicy)

```yaml
# Пример: Валидация образа (CEL)
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: validate-image-registry
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "object.spec.template.spec.containers.all(c, has(c.image) && c.image.startsWith('ghcr.io/myorg/'))"
      message: "Образы должны быть из ghcr.io/myorg/"

---
# Пример: Мутация лейблов (CEL)
apiVersion: v2.kyverno.io/v1
kind: MutatingPolicy
metadata:
  name: add-owner-label
spec:
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  mutations:
    - patchType: JSONPatch
      jsonPatch:
        expression: '[{"op": "add", "path": "/metadata/labels/owner", "value": "platform-team"}]'
```

### Сценарий 2: Миграция с Gatekeeper на Kyverno

**Условия:** Существующий кластер с 50 Constraint Templates. Требуется поэтапная миграция.

**Пошаговый процесс:**

```bash
# Шаг 1: Экспорт существующих политик
kubectl get constrainttemplates -o json | \
  jq -r '.items[] | .metadata.name' | while read ct; do
    echo "--- $ct ---"
    kubectl get constrainttemplate $ct -o yaml > "gatekeeper/$ct.yaml"
  done

# Шаг 2: Конвертация Constraint Template в Kyverno ClusterPolicy
python3 convert_gatekeeper.py --input gatekeeper/ --output kyverno/

# Шаг 3: Параллельная работа (оба движка)
helm install kyverno kyverno/kyverno -n kyverno --set validationFailureAction=Audit

# Шаг 4: Постепенная активация Kyverno
kubectl patch clusterpolicy <policy-name> --type merge \
  -p '{"spec":{"validationFailureAction":"Enforce"}}'

# Шаг 5: Отключение Gatekeeper после полного перехода
kubectl delete constrainttemplates -l gatekeeper.sh/constraint=audit
helm uninstall gatekeeper -n gatekeeper-system
```

**Матрица миграции:**

| Gatekeeper | Kyverno v2 | Kyverno v1 | Комментарий |
| :--- | :--- | :--- | :--- |
| ConstraintTemplate с Rego | ValidatingPolicy (CEL) | ClusterPolicy (CEL) | Прямая замена |
| ConstraintTemplate (malignity) | MutatingPolicy | ClusterPolicy (mutate) | Разные компоненты |
| Audit Config | Background Scan | Background Scan | Аналогичные параметры |
| Config (Data Sync) | GlobalContext | GlobalContext | Кэширование данных |

### Сценарий 3: Использование VAP + Kyverno (гибрид)

**Условия:** Кластер Kubernetes 1.30+. Требуется максимальная производительность.

**Архитектура:**

```text
┌─────────────────────────────────────────────────────────────────┐
│  Уровень 1: ValidatingAdmissionPolicy (CEL, нативный)          │
│  ────────────────────────────────────────────────────────────  │
│  Проверки: образ registry, labels, resource requests           │
│  Задержка: <1ms                                                 │
│  Количество: ~80% всех политик                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Уровень 2: Kyverno ValidatingPolicy (CEL, admission)           │
│  ────────────────────────────────────────────────────────────  │
│  Проверки: сложные условия, apiCall, мутация                    │
│  Задержка: 1-5ms                                                │
│  Количество: ~15% политик                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Уровень 3: Kyverno ClusterPolicy (v1, webhook)                │
│  ────────────────────────────────────────────────────────────  │
│  Проверки: мутация, генерация, сложные Rego-подобные условия    │
│  Задержка: 10-30ms                                              │
│  Количество: ~5% политик                                         │
└─────────────────────────────────────────────────────────────────┘
```

**Пример распределения:**

```yaml
# VAP для базовых проверок (нативный Kubernetes)
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-labels
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: "has(object.metadata.labels) && has(object.metadata.labels['app'])"
      message: "Label 'app' is required"

---
# Kyverno для сложной логики
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: check-image-digest
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  validations:
    - expression: "object.spec.containers.all(c, has(c.image) && c.image.contains('@sha256:'))"
      message: "Все образы должны содержать digest (@sha256:)"
  variables:
    - name: "trustedRegistries"
      expression: "'ghcr.io,registry.k8s.io,docker.io'"
```

### Сценарий 4: Интервью — какой движок выбрать

**Вопрос:** "У нас Kubernetes кластер. Какой движок политик выбрать?"

**Структурированный ответ:**

```
1. Анализ требований:
   - Если только валидация + нужна максимальная производительность → VAP (Kubernetes-native)
   - Если нужна мутация + генерация → Kyverno
   - Если нужна сложная Rego-логика → Gatekeeper (OPA)
   - Если команда не знает Rego → Kyverno (YAML + CEL)

2. Практические ограничения:
   - Kubernetes <1.30 → VAP не GA, нужен Kyverno или Gatekeeper
   - Мультикластер (5+ кластеров) → Kyverno (PolicyReport + лицензия)
   - Существующий OPA → Gatekeeper (минимальная миграция)

3. Рекомендация для типичного DevOps/SRE:
   - Начать с VAP + Kyverno ValidatingPolicy
   - По мере необходимости добавлять MutatingPolicy/GeneratingPolicy
   - Избегать v1 ClusterPolicy (низкая производительность)

4. Пример архитектуры:
   - VAP: require-labels, resource-limits, image-registry
   - Kyverno v2: add-sidecar, generate-networkpolicy, check-image-digest
   - Kyverno v1: complex-mutation (только если v2 не покрывает)
```

---

## Дополнительная информация

### Миграция с Rego на CEL

```python
# Скрипт конвертации Constraint Template → ValidatingPolicy
import yaml
import json

def convert_gatekeeper_to_kyverno(ct_path):
    with open(ct_path) as f:
        ct = yaml.safe_load(f)

    policy = {
        "apiVersion": "v2.kyverno.io/v1",
        "kind": "ValidatingPolicy",
        "metadata": {
            "name": f"check-{ct['metadata']['name'].lower()}"
        },
        "spec": {
            "validationActions": ["Deny"],
            "matchConstraints": {
                "resourceRules": [{
                    "apiGroups": ["*"],
                    "apiVersions": ["*"],
                    "operations": ["CREATE", "UPDATE"],
                    "resources": ["*"]
                }]
            },
            "validations": [{
                "expression": convert_rego_to_cel(ct['spec']['targets'][0]['rego']),
                "message": "Policy violation"
            }]
        }
    }
    return policy

def convert_rego_to_cel(rego_code):
    # Упрощенная конвертация Rego → CEL
    # В реальности нужен полноценный парсер Rego
    if "deny" in rego_code.lower():
        return "!(input.review.object.spec.containers.all(c, has(c.resources.limits.memory)))"
    return "true"
```

### См. также
- [Ограничения OPA и Kyverno](../../../Security/rbac/limitations_opa.md) — детальное сравнение для собеседований
- [Управление политиками в GitOps](../../../GitOps/Concepts/gitops-policy-management.md) — интеграция с Argo CD
- [Определения и понятия](./definitions_and_concepts.md) — архитектура Kyverno v1/v2
- [CEL-политики](./definitions_and_concepts.md#определения) — синтаксис и примеры
