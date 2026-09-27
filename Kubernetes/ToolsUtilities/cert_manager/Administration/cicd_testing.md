# Cert-manager: Тестирование и валидация в CI/CD

## Определения

**Преддеплойная валидация cert-manager** — комплекс проверок манифестов Ingress, Issuer и Certificate перед применением в кластере: структурная (kubeconform), семантическая (conftest/OPA) и интеграционная (dry-run).

**kubeconform** — быстрый валидатор JSON-схем Kubernetes API, заменяющий устаревший kubeval. Поддерживает CRD через OpenAPI-схемы, включая cert-manager.

**conftest** — инструмент для проверки манифестов по политикам (Rego/OPA). Позволяет накладывать организационные стандарты (алгоритмы ключей, сроки действия, обязательные аннотации).

**Server-Side Dry-Run** — проверка манифеста через реальный API-сервер Kubernetes без сохранения в etcd. Ловит ошибки admission-контроллеров, RBAC и валидирующих вебхуков, которые не видят offline-валидаторы.

**Cert-Manager Linter (cmlint)** — утилита для проверки конфигурации cert-manager: валидация аннотаций, проверка ссылок на Issuer, корректность SAN.

---

## Основные концепции

### Уровни валидации

```
┌─────────────────────────────────────────────────────────────┐
│                    Уровни валидации                          │
├─────────────────────────────────────────────────────────────┤
│  1. Schema    │ kubeconform     │ Структура YAML/API       │
│  2. Policy    │ conftest/OPA    │ Организационные стандарты │
│  3. Semantic  │ cmlint          │ Специфика cert-manager    │
│  4. Dry-Run   │ kubectl         │ Реальный API-сервер       │
└─────────────────────────────────────────────────────────────┘
```

**Порядок проверки:** От быстрой (schema) к дорогой (dry-run). Каждый уровень фильтрует определенный класс ошибок.

### Что проверять

| Что проверяем | Инструмент | Тип ошибки |
| :--- | :--- | :--- |
| Валидность YAML | `kubeconform` | Синтаксические ошибки |
| Соответствие API | `kubeconform` | Неверная версия API |
| Аннотации cert-manager | `conftest` | Отсутствие обязательных аннотаций |
| Алгоритм ключа | `conftest` | RSA вместо ECDSA |
| Срок действия | `conftest` | Слишком длинный/короткий TTL |
| Ссылка на Issuer | `conftest` | Несуществующий Issuer |
| SAN | `conftest` | Отсутствие доменов |
| dry-run | `kubectl` | RBAC, admission, webhook |

---

## Практические сценарии

### Сценарий 1: kubeconform для cert-manager CRD

#### Установка

```bash
# macOS
brew install kubeconform

# Linux
curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz \
  | tar xz -C /usr/local/bin kubeconform
```

#### Валидация Ingress с аннотациями cert-manager

```bash
# Базовая проверка
kubeconform -summary ingress.yaml

# Строгий режим (ошибки = fail)
kubeconform -strict -summary ingress.yaml

# Проверка конкретной версии Kubernetes
kubeconform -strict -kubernetes-version 1.31.0 ingress.yaml

# Валидация всех манифестов в директории
find . -name "*.yaml" -o -name "*.yml" | xargs kubeconform \
  -strict \
  -summary \
  -kubernetes-version 1.31.0
```

#### Валидация CRD cert-manager

```bash
# Валидация Certificate resource
kubeconform -strict -summary certificate.yaml

# Валидация ClusterIssuer
kubeconform -strict -summary cluster-issuer.yaml

# Валидация с CRD-схемами (если cert-manager установлен в кластере)
kubeconform \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/cert-manager/cert-manager/master/deploy/crds/*.crd.yaml' \
  -strict \
  -summary \
  certificate.yaml
```

### Сценарий 2: conftest для политик cert-manager

#### Установка

```bash
# macOS
brew install conftest

# Linux
curl -sL https://github.com/open-policy-agent/conftest/releases/latest/download/conftest_Linux_x86_64.tar.gz \
  | tar xz -C /usr/local/bin conftest
```

#### Политика: Обязательные аннотации

```rego
# policy/annotations.rego
package main

deny[msg] {
  input.kind == "Ingress"
  not input.metadata.annotations["cert-manager.io/cluster-issuer"]
  not input.metadata.annotations["cert-manager.io/issuer"]
  msg := "Ingress должен содержать аннотацию cert-manager.io/cluster-issuer или cert-manager.io/issuer"
}

deny[msg] {
  input.kind == "Ingress"
  input.metadata.annotations["cert-manager.io/cluster-issuer"]
  not input.spec.tls
  msg := "Ingress с cert-manager аннотацией должен содержать секцию spec.tls"
}
```

#### Политика: Безопасность ключей

```rego
# policy/security.rego
package main

deny[msg] {
  input.kind == "Certificate"
  input.spec.privateKey.algorithm == "RSA"
  input.spec.privateKey.size == 2048
  msg := "RSA 2048 запрещен. Используйте ECDSA P-256 или Ed25519"
}

deny[msg] {
  input.kind == "Certificate"
  not input.spec.privateKey.rotationPolicy
  msg := "Поле rotationPolicy обязательно. Рекомендуется Always"
}

deny[msg] {
  input.kind == "Certificate"
  input.spec.privateKey.rotationPolicy == "Never"
  msg := "rotationPolicy: Never запрещен. Используйте Always"
}
```

#### Политика: Ограничение сроков действия

```rego
# policy/duration.rego
package main

deny[msg] {
  input.kind == "Certificate"
  input.spec.duration
  duration := time.parse_rfc3339_ns(input.spec.duration)
  duration > 7776000000000000  # 90 дней в наносекундах
  msg := "Срок действия сертификата не должен превышать 90 дней"
}

deny[msg] {
  input.kind == "Certificate"
  input.spec.duration
  input.spec.renewBefore
  input.spec.renewBefore < 2592000000000000  # 30 дней
  msg := "renewBefore не должен быть меньше 30 дней"
}
```

#### Политика: Проверка SAN

```rego
# policy/san.rego
package main

deny[msg] {
  input.kind == "Certificate"
  not input.spec.dnsNames
  msg := "Certificate должен содержать поле dnsNames"
}

deny[msg] {
  input.kind == "Certificate"
  count(input.spec.dnsNames) == 0
  msg := "Certificate должен содержать хотя бы одно DNS-имя"
}
```

#### Запуск проверок

```bash
# Проверка одного файла
conftest test ingress.yaml -p policy/

# Проверка всех YAML в директории
find . -name "*.yaml" | xargs conftest test -p policy/

# Вывод только ошибок
conftest test ingress.yaml -p policy/ --output json | jq '.results[] | select(.alerts[] | .severity == "danger")'
```

### Сценарий 3: GitLab CI Pipeline для cert-manager

```yaml
# .gitlab-ci.yml
stages:
- validate
- test
- deploy

variables:
  KUBERNETES_VERSION: "1.31.0"

# Структурная валидация
kubeconform:
  stage: validate
  image: yannh/kubeconform:latest
  script:
  - |
    echo "=== Schema Validation ==="
    find kubernetes/ -name "*.yaml" | xargs kubeconform \
      -strict \
      -summary \
      -kubernetes-version $KUBERNETES_VERSION \
      -output json > kubeconform-report.json
  - cat kubeconform-report.json | jq '.summary'
  - |
    if [ $(cat kubeconform-report.json | jq '.summary.invalidErrors') -gt 0 ]; then
      echo "FAILED: Schema validation errors found"
      exit 1
    fi
  artifacts:
    reports:
      codequality: kubeconform-report.json

# Политики безопасности
conftest:
  stage: validate
  image: openpolicyagent/conftest:latest
  script:
  - |
    echo "=== Policy Validation ==="
    conftest test kubernetes/ \
      -p policy/ \
      --output json > conftest-report.json
  - cat conftest-report.json | jq '.results[] | select(.alerts | length > 0)'
  - |
    if conftest test kubernetes/ -p policy/ 2>&1 | grep -q "FAIL"; then
      echo "FAILED: Policy violations found"
      exit 1
    fi
  artifacts:
    reports:
      codequality: conftest-report.json

# Server-Side Dry-Run
dry-run:
  stage: test
  image: bitnami/kubectl:latest
  environment:
    name: production
  script:
  - |
    echo "=== Server-Side Dry-Run ==="
    for file in $(find kubernetes/ -name "*.yaml"); do
      echo "Checking $file..."
      kubectl apply --dry-run=server -f $file 2>&1
      if [ $? -ne 0 ]; then
        echo "FAILED: Dry-run failed for $file"
        exit 1
      fi
    done
  rules:
  - if: $CI_MERGE_REQUEST_IID
```

### Сценарий 4: GitHub Actions Pipeline

```yaml
# .github/workflows/cert-manager-validate.yml
name: Cert-Manager Validation

on:
  pull_request:
    paths:
    - 'kubernetes/**'
    - 'charts/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Install kubeconform
      run: |
        curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz \
          | tar xz -C /usr/local/bin kubeconform

    - name: Schema Validation
      run: |
        echo "=== kubeconform ==="
        find kubernetes/ -name "*.yaml" | xargs kubeconform \
          -strict \
          -summary \
          -kubernetes-version 1.31.0

    - name: Install conftest
      run: |
        curl -sL https://github.com/open-policy-agent/conftest/releases/latest/download/conftest_Linux_x86_64.tar.gz \
          | tar xz -C /usr/local/bin conftest

    - name: Policy Validation
      run: |
        echo "=== conftest ==="
        conftest test kubernetes/ -p policy/

    - name: Dry-Run (needs kubeconfig)
      if: github.event_name == 'pull_request'
      run: |
        echo "=== Dry-Run ==="
        # Требуется настроенный kubeconfig для целевого кластера
        for file in $(find kubernetes/ -name "*.yaml"); do
          kubectl apply --dry-run=server -f $file
        done
      env:
        KUBECONFIG: ${{ secrets.KUBECONFIG }}
```

### Сценарий 5: Helm Template + Валидация

```bash
# Рендеринг Helm-шаблона с cert-manager аннотациями
helm template my-app ./charts/my-app \
  --set ingress.enabled=true \
  --set ingress.certManager.clusterIssuer=letsencrypt-prod \
  > rendered.yaml

# Валидация рендеренных манифестов
kubeconform -strict -summary rendered.yaml

# Проверка политик
conftest test rendered.yaml -p policy/

# Проверка diff с текущим состоянием кластера
kubectl diff -f rendered.yaml
```

---

## Дополнительная информация

### Интеграция с pre-commit

```yaml
# .pre-commit-config.yaml
repos:
- repo: https://github.com/yannh/kubeconform
  rev: v0.6.4
  hooks:
  - id: kubeconform
    args:
    - --strict
    - --summary
    - --kubernetes-version=1.31.0

- repo: https://github.com/open-policy-agent/conftest
  rev: v0.46.0
  hooks:
  - id: conftest
    args:
    - -p
    - policy/
```

### Кастомные скрипты проверки

```bash
#!/bin/bash
# scripts/validate-cert-manager.sh
set -euo pipefail

echo "=== Cert-Manager Validation ==="

# 1. Проверка наличия обязательных аннотаций
echo "--- Checking annotations ---"
for f in $(find kubernetes/ -name "*.yaml" | grep -i ingress); do
  if ! grep -q "cert-manager.io/cluster-issuer\|cert-manager.io/issuer" "$f"; then
    echo "WARNING: $f не содержит аннотации cert-manager"
  fi
done

# 2. Проверка алгоритмов ключей
echo "--- Checking key algorithms ---"
for f in $(find kubernetes/ -name "*.yaml" | grep -i certificate); do
  if grep -q "algorithm: RSA" "$f"; then
    echo "WARNING: $f использует RSA. Рекомендуется ECDSA"
  fi
done

# 3. Проверка сроков действия
echo "--- Checking durations ---"
for f in $(find kubernetes/ -name "*.yaml" | grep -i certificate); do
  if grep -q "duration:" "$f"; then
    duration=$(grep "duration:" "$f" | awk '{print $2}')
    echo "INFO: $f duration=$duration"
  fi
done

echo "=== Validation Complete ==="
```

### Best Practices

1. **Мультиуровневая валидация:** Используйте kubeconform + conftest + dry-run.
2. **CI Gate:** Блокируйте merge при ошибках валидации.
3. **Политики как код:** Храните Rego-политики в Git, версионируйте изменения.
4. **Тестирование в staging:** Прогоняйте dry-run в staging перед production.
5. **Мониторинг:** Настройте алерты на ошибки валидации в CI/CD.
6. **Обратная совместимость:** Проверяйте совместимость с текущей версией cert-manager в кластере.

### Смотрите также

- **[Kubeconform](../../../../Kubernetes/ToolsUtilities/kubeconform_overview.md)** — подробное руководство по валидатору.
- **[Cert-manager: Операции](../Administration/operations.md)** — мониторинг и алертинг.
- **[Cert-manager: Диагностика](../Administration/troubleshooting.md)** — troubleshooting интеграции.
- **[Cert-manager: DNS-провайдеры](../Administration/dns_providers.md)** — настройка DNS-01 для CI/CD.
