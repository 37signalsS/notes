# CI/CD для мониторинга

## Определения

**CI/CD мониторинга** — практика автоматизации проверки, доставки и версионирования конфигурации мониторинга (правила, ServiceMonitor, AlertmanagerConfig) через пайплайны непрерывной интеграции и доставки.

**PromQL Validation** — проверка синтаксиса PromQL-выражений и YAML-структуры PrometheusRule через `promtool check rules` и `kubectl apply --dry-run=server` на этапе CI до деплоя в кластер.

**GitOps для мониторинга** — подход, при котором конфигурация мониторинга хранится в Git, а ArgoCD или FluxCD контролируют актуальное состояние кластера относительно репозитория.

> **См. также:** [PrometheusRule CRD](./kubernetes/operator/crd/prometheusrule.md), [ServiceMonitor CRD](./kubernetes/operator/crd/servicemonitor.md), [AlertmanagerConfig CRD](./kubernetes/operator/crd/alertmanagerconfig.md).

## Базовые концепции

### Зачем нужен CI/CD для мониторинга

1. **Предотвращение инцидентов** — невалидное правило PromQL может уронить Prometheus или создатьThousands алертов
2. **Аудит изменений** — кто, когда и почему изменил порог алерта или добавил новый receiver
3. **Откат** — при проблемах можно быстро откатить через `git revert`
4. **Единообразие** — Dev/Staging/Production конфигурации синхронизируются через Git
5. **Коллаборация** — Pull Request с обзором изменений перед применением

### Жизненный цикл изменения

```
Git Commit --> CI (lint + validate + test) --> CD (apply --dry-run) --> Review --> CD (apply) --> Reconciliation
```

### Инструменты валидации

| Инструмент | Назначение | Команда |
|:---|:---|:---|
| **promtool** | Валидация PromQL и структуры правил | `promtool check rules rules.yaml` |
| **promtool test** | Модульное тестирование правил | `promtool test test.yaml` |
| **kubectl dry-run** | Серверная валидация CRD | `kubectl apply --dry-run=server -f rules.yaml` |
| **kubeconform** | Валидация YAML по схемам K8s | `kubeconform -summary rules.yaml` |
| **yamllint** | Проверка стиля YAML | `yamllint -d relaxed rules.yaml` |

## Практические сценарии

### Сценарий 1: CI пайплайн для PrometheusRule

```yaml
# .github/workflows/prometheus-rules.yaml
name: Validate Prometheus Rules

on:
  pull_request:
    paths:
      - 'monitoring/prometheusrules/**'
      - 'monitoring/servicemonitors/**'
      - 'monitoring/alertmanagerconfigs/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install promtool
        run: |
          PROM_VERSION=2.53.0
          curl -sL https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-amd64.tar.gz | tar xz
          sudo cp prometheus-${PROM_VERSION}.linux-amd64/promtool /usr/local/bin/

      - name: Lint YAML
        run: yamllint -d relaxed monitoring/

      - name: Validate PrometheusRule
        run: find monitoring/prometheusrules -name '*.yaml' -exec promtool check rules {} +

      - name: Dry-run apply
        run: kubectl apply --dry-run=server -f monitoring/
```

### Сценарий 2: Модульное тестирование правил

Файл теста `tests/high_error_rate_test.yaml`:

```yaml
rule_files:
  - ../prometheusrules/api-health.yaml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'http_requests_total{job="api", status="500"}'
        values: "0+10x10"
      - series: 'http_requests_total{job="api", status="200"}'
        values: "100+0x10"
    alert_rule_test:
      - eval_time: 10m
        alertname: HighErrorRate
        exp_alerts:
          - exp_labels:
              severity: critical
```

Запуск тестов:

```bash
promtool test tests/high_error_rate_test.yaml
```

### Сценарий 3: GitLab CI с kubeconform

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy

variables:
  KUBERNETES_VERSION: "1.30.0"

validate-rules:
  stage: validate
  image: alpine:3.19
  before_script:
    - apk add --no-cache curl yq
    - curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz -C /usr/local/bin
    - curl -sL https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz | tar xz
    - cp prometheus-2.53.0.linux-amd64/promtool /usr/local/bin/
  script:
    - yamllint -d relaxed monitoring/
    - find monitoring/prometheusrules -name '*.yaml' -exec promtool check rules {} +
    - kubeconform -summary -kubernetes-version ${KUBERNETES_VERSION} monitoring/**/*.yaml

deploy-rules:
  stage: deploy
  script:
    - kubectl apply -f monitoring/
  only:
    - main
  when: manual
```

### Сценарий 4: Структура репозитория

```
monitoring/
  base/
    prometheusrules/
      api-health.yaml
      infrastructure.yaml
      slo-burn-rate.yaml
    servicemonitors/
      api-service-monitor.yaml
    alertmanagerconfigs/
      slack-config.yaml
  overlays/
    production/
      kustomization.yaml
    staging/
      kustomization.yaml
  tests/
    high_error_rate_test.yaml
    latency_regression_test.yaml
```

### Сценарий 5: ArgoCD Application для мониторинга

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-rules
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal/monitoring/manifests.git
    targetRevision: main
    path: overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=false
  ignoreDifferences:
    - group: monitoring.coreos.com
      kind: PrometheusRule
      jsonPointers:
        - /status
```

### Сценарий 6: Проверка ссылок runbook_url в CI

```bash
#!/bin/bash
set -euo pipefail

echo "Checking runbook_url annotations in PrometheusRule files..."

MISSING_RUNBOOK=0
BROKEN_RUNBOOK=0

for file in $(find monitoring/prometheusrules -name '*.yaml'); do
  # Проверка наличия runbook_url у каждого алерта
  RULES_WITHOUT_RUNBOOK=$(grep -c 'alert:' "$file" || true)
  RUNBOOKS=$(grep -c 'runbook_url:' "$file" || true)

  if [ "$RULES_WITHOUT_RUNBOOK" -gt "$RUNBOOKS" ]; then
    echo "WARNING: $file has alerts without runbook_url"
    MISSING_RUNBOOK=$((MISSING_RUNBOOK + RULES_WITHOUT_RUNBOOK - RUNBOOKS))
  fi

  # Проверка доступности ссылок
  for url in $(grep -oP 'runbook_url: "\K[^"]+' "$file" || true); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$url" --max-time 5 || echo "000")
    if [ "$HTTP_CODE" != "200" ]; then
      echo "WARNING: Broken runbook URL in $file: $url (HTTP $HTTP_CODE)"
      BROKEN_RUNBOOK=$((BROKEN_RUNBOOK + 1))
    fi
  done
done

echo "Missing runbook_url: $MISSING_RUNBOOK"
echo "Broken runbook URLs: $BROKEN_RUNBOOK"

if [ "$BROKEN_RUNBOOK" -gt 0 ]; then
  echo "ERROR: Broken runbook URLs found"
  exit 1
fi
```

### Сценарий 7: Валидация размера конфигурации

```bash
#!/bin/bash
set -euo pipefail

MAX_SECRET_SIZE=1048576  # 1MB limit for Kubernetes Secrets

echo "Validating configuration sizes..."

for file in $(find monitoring/ -name '*.yaml'); do
  SIZE=$(wc -c < "$file")
  if [ "$SIZE" -gt "$MAX_SECRET_SIZE" ]; then
    echo "ERROR: $file exceeds 1MB limit ($SIZE bytes)"
    exit 1
  fi
done

echo "All configuration files within size limits"
```

## Дополнительная информация

### Рекомендуемый workflow

1. Ветка `main` — отражает состояние production
2. Feature-ветки — для изменений с PR
3. CI проверяет каждый PR: `promtool check rules`, `kubectl dry-run`, `kubeconform`
4. После одобрения PR и слияния в `main` CD автоматически применяет изменения
5. ArgoCD/Flux синхронизирует состояние кластера с Git

### Ограничения и крайние случаи

1. **`promtool check rules` проверяет синтаксис, но не семантику** — невалидный label name может пройти проверку
2. **`kubectl dry-run=server` требует доступа к кластеру** — в CI nécessaire service account с RBAC
3. **Агрессивный auto-sync ArgoCD** может перезаписать ручные изменения — используйте `selfHeal: false` для критичных ресурсов
4. **Валидация Secret не работает в CI** — Secret'ы не должны храниться в Git (используйте Sealed Secrets или SOPS)

### Лучшие практики

1. **Храните всё в Git** — PrometheusRule, ServiceMonitor, AlertmanagerConfig, Grafana dashboards
2. **Тестируйте правила** — `promtool test` для каждого нового алерта
3. **Проверяйте runbook_url** — каждый алерт обязан иметь ссылку на инструкцию
4. **Используйте Kustomize overlays** — разделение base и environment-specific конфигураций
5. **Разделяйте namespaces** — monitoring rules в `monitoring`, application rules в namespace приложения
6. **Версионируйте CRD** — обновляйте Prometheus Operator и CRD вместе с правилами
7. **Мониторьте доставку правил** — алерт на `prometheus_config_last_reload_successful == 0`
8. **Ревью изменений** — каждый PR должен проходить как минимум один обзор перед слиянием

### Связанные темы

- [PrometheusRule CRD](./kubernetes/operator/crd/prometheusrule.md) — структура и применение правил
- [ServiceMonitor CRD](./kubernetes/operator/crd/servicemonitor.md) — конфигурация скрейпинга
- [AlertmanagerConfig CRD](./kubernetes/operator/crd/alertmanagerconfig.md) — маршрутизация алертов
- [Promtool и лучшие практики](./promtool_and_best_practices.md) — валидация и тестирование
- [Self-monitoring](./self_monitoring.md) — мониторинг самого Prometheus
- [GitOps (ArgoCD)](../GitOps/ArgoCD/argocd_overview.md) — обзор ArgoCD
