# Trivy Operator: непрерывное сканирование уязвимостей в Kubernetes

**Актуально для:** Trivy Operator 0.35.0 (Helm chart 0.37.0)

`trivy image` в CI ловит уязвимости на этапе сборки. Но что с образами, которые уже работают в продакшене? Trivy Operator непрерывно сканирует все рабочие нагрузки в кластере и публикует результаты в виде Kubernetes-ресурсов — с метриками Prometheus для алертов.

## Определения

**Trivy Operator** — Kubernetes-оператор от Aqua Security, который использует Trivy для непрерывного сканирования кластера Kubernetes на наличие проблем безопасности. Результаты сканирования публикуются как Kubernetes CRD (Custom Resource Definitions), доступные через Kubernetes API.

**VulnerabilityReport** — CRD, содержащий результаты сканирования уязвимостей (CVE) в образах контейнеров.

**ConfigAuditReport** — CRD, содержащий результаты аудита конфигурации Kubernetes (отсутствие securityContext, privileged-контейнеры и т.д.).

**RbacAssessmentReport** — CRD, содержащий результаты оценки RBAC-конфигурации на избыточные привилегии.

**InfraAssessmentReport** — CRD, содержащий результаты проверки настроек компонентов control plane (kube-apiserver, kubelet, etcd и др.) согласно рекомендациям CIS Benchmark и NSA/CISA.

**Standalone (режим Trivy)** — режим, в котором Trivy скачивает базу уязвимостей прямо в каждой джобе сканирования. Подходит для изолированных сред с ограниченным доступом к сети.

**ClientServer (режим Trivy)** — режим, в котором Trivy клиент запрашивает базу уязвимостей у централизованного Trivy Server. Эффективнее для больших кластеров: база загружается один раз на сервер, а не в каждую джобу.

## Архитектура и принцип работы

Trivy Operator работает по принципу наблюдателя (watch) за изменениями в кластере Kubernetes:

1. **Обнаружение изменений:** оператор подписывается на события создания/изменения рабочих нагрузок (Pod, ReplicaSet, Deployment, DaemonSet, StatefulSet, CronJob, Job).
2. **Запуск сканирования:** при обнаружении изменения оператор создаёт Kubernetes Job, который запускает сканер Trivy внутри кластера. Джоба копирует образ контейнера и сканирует его на CVE, уязвимости конфигурации, экспонированные секреты и нарушения RBAC.
3. **Публикация результатов:** результаты сканирования записываются как CRD (VulnerabilityReport, ConfigAuditReport, RbacAssessmentReport, InfraAssessmentReport) в том же неймспейсе, что и сканируемая рабочая нагрузка. CRD имеет `ownerReference`, привязанную к сканируемому объекту — при удалении объекта отчёт удаляется автоматически через garbage collector Kubernetes.
4. **Обновление:** отчёты обновляются периодически. По умолчанию TTL отчёта составляет 24 часа (`scannerReportTTL: "24h"`), после чего отчёт удаляется и создаётся заново.
5. **Метрики:** оператор экспортирует метрики в формате Prometheus на `/metrics` эндпоинте (порт 8080 по умолчанию). ServiceMonitor при использовании с kube-prometheus-stack автоматически обнаруживает эти метрики.

```text
┌─────────────────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Workload (Pod/Deployment/DaemonSet/etc.)               │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │  Container Image                                  │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  Trivy Operator (controller)                           │   │
│  │  - watches for workload changes                         │   │
│  │  - creates ScanJobs                                     │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  Trivy ScanJob (Job)                                   │   │
│  │  - downloads Trivy DB (Standalone)                     │   │
│  │  - scans image for CVE/config/RBAC/exposed secrets     │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  Report CRDs                                           │   │
│  │  - VulnerabilityReport                                 │   │
│  │  - ConfigAuditReport                                   │   │
│  │  - RbacAssessmentReport                                │   │
│  │  - InfraAssessmentReport                               │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────▼────────────────────────────────┐   │
│  │  Prometheus Metrics (/metrics)                         │   │
│  │  - trivy_image_vulnerabilities                         │   │
│  │  - trivy_resource_configaudits                         │   │
│  │  - trivy_role_rbacassessments                          │   │
│  │  - trivy_resource_infraassessments                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Установка и настройка

### Предварительные требования

- **Kubernetes 1.21+** (рекомендуется 1.27+ для поддержки всех фич)
- **Helm 3.8+** для установки через Helm
- **Argo CD** (опционально) для установки через GitOps
- **kube-prometheus-stack** (опционально) для 수 수бы мониторинга метрик

### Установка через Helm

```bash
helm repo add aquasecurity https://aquasecurity.github.io/helm-charts/
helm repo update

helm install trivy-operator aquasecurity/trivy-operator \
  --namespace trivy-system \
  --create-namespace \
  --version 0.37.0
# → Release "trivy-operator" has been installed
```

### Установка через Argo CD (Application)

**Файл `trivy-operator-application.yaml`:**

```yaml
# argo-application.yaml — манифест Argo CD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: trivy-operator
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: security
  source:
    repoURL: https://aquasecurity.github.io/helm-charts
    chart: trivy-operator
    targetRevision: "0.37.0"
    helm:
      releaseName: trivy-operator
      values: |
        operator:
          vulnerabilityScannerEnabled: true
          configAuditScannerEnabled: true
          rbacAssessmentScannerEnabled: true
          infraAssessmentScannerEnabled: true
          metricsVulnIdEnabled: true
          scanJobsConcurrentLimit: 2
        trivy:
          ignoreUnfixed: true
          mode: Standalone
          severity: UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL
        serviceMonitor:
          enabled: true
          labels:
            release: kube-prom-stack
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 1000m
            memory: 2048Mi
  destination:
    server: https://kubernetes.default.svc
    namespace: trivy-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

**Требования:**
- Argo CD (версии 2.11+) для управления объектом `Application`
- Namespace `argocd` для размещения объекта `Application` и `AppProject` с именем `security`
- Helm-репозиторий `https://aquasecurity.github.io/helm-charts` зарегистрирован в Argo CD
- Namespace `trivy-system` для развертывания Trivy Operator
- ServiceMonitor с меткой `release: kube-prom-stack` для сбора метрик через kube-prometheus-stack

**Валидация:**
```bash
# 1. Проверка статуса Application
argocd app get trivy-operator
# → Name:               trivy-operator
# → Server:             https://kubernetes.default.svc
# → Namespace:          trivy-system
# → Sync Status:        Synced to 0.37.0
# → Health Status:      Healthy

# 2. Проверка подов Trivy Operator
kubectl get pods -n trivy-system -l app.kubernetes.io/name=trivy-operator
# → trivy-operator-xxx   1/1   Running

# 3. Проверка CRD и отчётов
kubectl get crd vulnerabilityreports.aquasecurity.github.io
kubectl get vulnerabilityreport -A --no-headers | wc -l
```

**Ключевые параметры конфигурации:**

| Параметр | Значение по умолчанию | Описание |
|---|---|---|
| `operator.vulnerabilityScannerEnabled` | `true` | Включить сканирование уязвимостей (CVE) |
| `operator.configAuditScannerEnabled` | `true` | Включить аудит конфигурации Kubernetes |
| `operator.rbacAssessmentScannerEnabled` | `true` | Включить оценку RBAC-привилегий |
| `operator.infraAssessmentScannerEnabled` | `true` | Включить проверку hardening control plane |
| `operator.scanJobsConcurrentLimit` | `10` | Максимум одновременных джоб сканирования |
| `operator.metricsVulnIdEnabled` | `false` | Экспортировать ID CVE в метрики Prometheus |
| `trivy.ignoreUnfixed` | `false` | Показывать только уязвимости с доступным исправлением |
| `trivy.mode` | `Standalone` | Режим работы Trivy: `Standalone` или `ClientServer` |
| `trivy.severity` | `UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL` | Уровни severity, включаемые в отчёт |
| `excludeNamespaces` | `""` | Пространства имён, исключаемые из сканирования |
| `operator.scannerReportTTL` | `"24h"` | Время жизни отчёта перед пересозданием |

> **`ignoreUnfixed: true` критически важен:** уязвимости без исправлений неустранимы. Без этого флага дашборды забиваются тысячами CVE, с которыми ничего сделать нельзя. Флаг отображает только те уязвимости, для которых существует fix — остальные отбрасываются.
>
> **`scanJobsConcurrentLimit`** — без лимита оператор при первой установке одновременно запускает по одной джобе на каждую рабочую нагрузку и перегружает ноды. Рекомендуется установить значение 2–3 для продакшена.
>
> **`mode: Standalone`** — Trivy скачивает базу уязвимостей (vuln-list) прямо в джобе сканирования. Для изолированных (air-gapped) окружений используйте `ClientServer` с внутренним Trivy Server или предварительно загруженной базой.

### Исключение инфраструктурных namespace'ов

```yaml
values:
  excludeNamespaces: "kube-system,argocd,cert-manager"
```

Это снижает шум и убирает лишние джобы сканирования для инфраструктурных компонентов, которые управляются отдельно.

## Сканируемые отчёты

Оператор создаёт джобы сканирования и публикует результаты как CRD:

```bash
kubectl get vulnerabilityreport -A
kubectl get configauditreport -N
kubectl get rbacassessmentreport -N
kubectl get infraassessmentreport -N
```

Результаты хранятся как Kubernetes CRD в том же неймспейсе, что и рабочая нагрузка. Имена отчётов следуют шаблону `<workload-kind>-<workload-name>-<container-name>`.

### Чтение VulnerabilityReport

```bash
# Сводка по уязвимостям
kubectl get vulnerabilityreport -n app my-app-deployment-my-container \
  -o jsonpath='{.report.summary}'
# → {"criticalCount":0,"highCount":3,"lowCount":47,"mediumCount":12,"unknownCount":0}

# Детали HIGH CVE
kubectl get vulnerabilityreport -n app my-app-deployment-my-container \
  -o json | jq '.report.vulnerabilities[] | select(.severity=="HIGH") | {id: .vulnerabilityID, pkg: .resource, fixed: .fixedVersion}'
# → {"id":"CVE-2024-12345","pkg":"libssl3","fixed":"3.0.13-0+deb12u1"}
```

Поля VulnerabilityReport:

| Поле | Описание |
|---|---|
| `.report.summary.criticalCount` | Количество CRITICAL уязвимостей |
| `.report.summary.highCount` | Количество HIGH уязвимостей |
| `.report.summary.mediumCount` | Количество MEDIUM уязвимостей |
| `.report.summary.lowCount` | Количество LOW уязвимостей |
| `.report.vulnerabilities[]` | Массив уязвимостей с полями: `vulnerabilityID`, `severity`, `resource`, `installedVersion`, `fixedVersion`, `score`, `title` |

## Метрики Prometheus и алерты

Trivy Operator экспортирует метрики на `/metrics` (порт 8080) по умолчанию. С включённым `serviceMonitor.enabled: true` и меткой `release: kube-prom-stack`, Prometheus автоматически сканирует метрики.

**Важно:** значения метки `severity` в Prometheus-метриках используют стандартный регистр (`High`, `Critical`, `Medium`, `Low`, `Unknown`), а не верхний регистр (`HIGH`, `CRITICAL`). Это связано с тем, как Trivy Operator нормализует severity при экспорте в метрики.

```promql
# CRITICAL CVE по всем рабочим нагрузкам
sum(trivy_image_vulnerabilities{severity="Critical"}) by (namespace, resource_name)

# HIGH CVE по всем рабочим нагрузкам
sum(trivy_image_vulnerabilities{severity="High"}) by (namespace, resource_name)

# ConfigAudit: критические нарушения конфигурации
sum(trivy_resource_configaudits{severity="Critical"}) by (namespace, resource_name)

# RBAC assessment: нарушения среднего уровня
sum(trivy_role_rbacassessments{severity="Medium"}) by (namespace, resource_name)

# Подробные метрики по ID CVE (требует metricsVulnIdEnabled: true)
trivy_vulnerability_id{severity="Critical"}
```

```yaml
# rules/prometheus-alerts-trivy.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: trivy-operator-alerts
  namespace: monitoring
spec:
  groups:
    - name: trivy-operator
      rules:
        - alert: TrivyCriticalVulnerabilities
          expr: sum(trivy_image_vulnerabilities{severity="Critical"}) by (namespace, resource_name) > 0
          for: 10m
          labels:
            severity: high
          annotations:
            summary: "{{ $labels.resource_name }} в {{ $labels.namespace }}: {{ $value }} CRITICAL CVE"
            description: "Обновите базовый образ или добавьте .trivyignore для принятых рисков"

        - alert: TrivyHighVulnerabilities
          expr: sum(trivy_image_vulnerabilities{severity="High"}) by (namespace, resource_name) > 0
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "{{ $labels.resource_name }} в {{ $labels.namespace }}: {{ $value }} HIGH CVE"

        - alert: TrivyConfigAuditFailed
          expr: trivy_resource_configaudits{severity="Critical"} > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Config audit: критическая находка в {{ $labels.resource_name }}"
```

**Дашборд Grafana:** импортируйте дашборд [Trivy Operator Dashboard](https://grafana.com/grafana/dashboards/17813) (ID 17813) для визуализации метрик через kube-prometheus-stack.

### Автоматический импорт дашборда через Helm

```yaml
# values для kube-prometheus-stack
grafana:
  dashboards:
    default:
      trivy-operator-dashboard:
        gnetId: 17813
        datasource: Prometheus
        revision: 2
```

## CI vs Trivy Operator: нужны оба

CI (сканер `trivy image` в пайплайне) ловит уязвимости до попадания в продакшен. Оператор ловит то, что появляется после деплоя:

1. **Новое CVE в ОС базового образа** — образ был чистым месяц назад, но в базе NVD только что появилась новая уязвимость для его версии пакета.
2. **Зависимость добавлена в NVD** — работающий образ содержит пакет, но CVE для него опубликованы спустя время после сборки.
3. **Хотфикс или ручной `kubectl apply`** — новая рабочая нагрузка развёрнута мимо CI без сканирования.

Не выбирайте один инструмент — используйте оба: CI как quality gate на этапе сборки, и Trivy Operator для непрерывного мониторинга в продакшене.

### Trivy в GitLab CI

```yaml
trivy-scan:
  image: aquasec/trivy:latest
  script:
    - trivy image \
        --format json \
        --output trivy-report.json \
        --severity HIGH,CRITICAL \
        --exit-code 1 \
        registry.example.com/myapp:$CI_COMMIT_SHORT_SHA
  artifacts:
    reports:
      container_scanning: trivy-report.json
    when: always
```

`--exit-code 1` останавливает пайплайн при находках HIGH или CRITICAL. Известные ложные срабатывания подавляются через `.trivyignore`:

```text
# .trivyignore
# CVE-2023-12345: известный false-positive, исправления нет (2026-02-26)
CVE-2023-12345
```

Коммитьте `.trivyignore` рядом с Dockerfile — так подавление на виду и его легко проверить при аудите.

## Устранение неполадок

### Ошибка: оператор не сканирует нагрузки

```bash
# Проверка статуса подов
kubectl get pods -n trivy-system
# → trivy-operator-xxx   1/1   Running

# Проверка логов
kubectl logs -n trivy-system deployment/trivy-operator

# Проверка ConfigMap с конфигурацией
kubectl get cm -n trivy-system trivy-operator-trivy-config -o yaml
```

**Причины:**
- Namespace не входит в `targetNamespaces` или помещён в `excludeNamespaces`
- Сканирование отключено для типа `vulnerabilityScannerEnabled: false`
- ServiceAccount не имеет RBAC-разрешений для создания Job

### Ошибка: джобы сканирования зависают или перегружают ноды

```bash
# Просмотр активных джоб
kubectl get jobs -A | grep trivy
kubectl describe job <job-name> -n <namespace>

# Проверка resource limits
kubectl get job <job-name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[*].resources}'
```

**Решение:** установите `operator.scanJobsConcurrentLimit: 2` (или меньше), чтобы ограничить параллельность. Также настройте resource limits для scan job:

```yaml
values:
  trivy:
    resources:
      limits:
        cpu: 500m
        memory: 1Gi
      requests:
        cpu: 100m
        memory: 128Mi
```

### Ошибка: метрики Trivy Operator не попадают в Prometheus

```bash
# Проверка ServiceMonitor
kubectl get servicemonitor -A
# → trivy-operator   trivy-operator   2m

# Проверка Endpoint в Prometheus
kubectl exec -n monitoring deploy/prometheus-kube-prometheus-stack-prometheus -- \
  /bin/prometheus-toolkit --command=tsdb list rules | grep trivy
```

**Решение:** убедитесь, что `serviceMonitor.enabled: true` и метка `serviceMonitor.labels` совпадает с тем, что ожидает ваш Prometheus (обычно `release: kube-prom-stack`).

### Ошибка: отчёты не обновляются (stale)

```bash
# Проверка TTL
kubectl get vulnerabilityreport -n app <report-name> -o jsonpath='{.metadata.annotations}'

# Принудительное удаление для пересоздания
kubectl delete vulnerabilityreport -n app <report-name>
# → trivy-operator автоматически создаст новый отчёт
```

**Решение:** проверьте `operator.scannerReportTTL`. Если установлено в `""`, отчёты не удаляются и не обновляются.

### Ошибка: Trivy не может загрузить базу уязвимостей (Standalone режим)

```bash
# Проверка логов джобы сканирования
kubectl logs job/<scan-job-name> -n <namespace>
# → level=error msg="error during server status check"
```

**Решение для изолированных сред:** переключитесь на `ClientServer` режим с внутренним Trivy Server, либо используйте `trivy.clientServerSkipUpdate: true` с предварительно загруженной базой.

## Лучшие практики

1. **`ignoreUnfixed: true`** — всегда включайте. Уязвимости без исправлений не поддаются устранению и только забивают дашборды.
2. **Ограничьте параллельность сканов** (`scanJobsConcurrentLimit: 2–3`) — без лимита оператор при первой установке одновременно запускает джобы на всех рабочих нагрузках, что может привести к нехватке ресурсов на нодах.
3. **Исключайте инфраструктурные namespace'ы** (`excludeNamespaces: "kube-system,argocd,cert-manager"`) — снижает шум и нагрузку.
4. **Используйте `ClientServer` режим для больших кластеров** — централизованный Trivy Server экономит трафик и время на загрузку базы уязвимостей.
5. **Настраивайте алерты только на реально эксплуатируемые CVE** — используйте EPSS-оценку или VEX-отчёты для приоритизации. См. [SBOM в продакшене](../../Security/Supply_Chain_Security/sbom_in_production.md).
6. **Resource limits для scan job** — устанавливайте лимиты CPU и памяти, чтобы сканирование не перегружало кластер.
7. **Регулярно обновляйте Trivy Operator и образ Trivy** — уязвимости в самом операторе или сканере могут стать целью атаки. Используйте фиксированные теги версий (не `latest`).
8. **Комбинируйте CI и Operator** — CI блокирует сборку с новыми CRITICAL CVE, Operator ловит уязвимости в уже запущенных образах.
9. **SBOM для дополнительного контекста** — включите `sbomGenerationEnabled: true` для получения данных о составе компонентов образов.

## Дополнительная информация

### Базовые команды Trivy CLI (Standalone)

Для локального сканирования и CI/CD без оператора:

```bash
# Сканировать образ (только HIGH/CRITICAL, игнорировать unfixed)
trivy image --severity HIGH,CRITICAL --ignore-unfixed myimage:tag

# Сканировать образ с JSON выводом
trivy image --format json -o results.json myimage:tag

# Сканировать образ в формате SARIF для CI/IDE
trivy image --format sarif --output results.sarif myimage:tag

# Сканировать файловую систему (локальную директорию)
trivy fs --severity HIGH,CRITICAL .

# Сканировать конфигурационные файлы (IaC: Terraform, K8s, Helm)
trivy config --severity MEDIUM,HIGH,CRITICAL ./terraform

# Сканировать Helm чарт
trivy config ./my-chart

# Сканировать Kubernetes кластер (все рабочие нагрузки)
trivy k8s --report summary cluster

# Сканировать конкретный неймспейс
trivy k8s --namespace production --report summary all

# Сканировать SBOM файл
trivy sbom ./sbom.json

# Предварительно скачать базу уязвимостей (для offline/air-gapped)
trivy image --download-db-only

# Фильтр по тяжести (HIGH/CRITICAL)
trivy image --severity HIGH,CRITICAL myimage:tag

# Игнорировать уязвимости без патча (unfixed)
trivy image --ignore-unfixed --severity HIGH,CRITICAL myimage:tag
```

### Связанные документы

- **[Сканирование Docker-образов на уязвимости](../../Docker/Docker_security/vulnerability_scanning.md)** — сканирование образов в CI/CD с Trivy, Grype, Docker Scout.
- **[Безопасный релиз в CI/CD](../../CI-CD/DevSecOps/secure_release_pipeline.md)** — end-to-end пайплайн с Trivy, Cosign и security gates.
- **[Интеграция с Kyverno](./kyverno/integrations.md)** — блокировка подов с критичными CVE через политики Kyverno.
- **[SBOM в продакшене](../../Security/Supply_Chain_Security/sbom_in_production.md)** — реакция на CVE через SBOM, VEX, reachability analysis.

### Источники

- [Trivy Operator Documentation](https://aquasecurity.github.io/trivy-operator/)
- [GitHub: aquasecurity/trivy-operator](https://github.com/aquasecurity/trivy-operator)
- [Helm Chart: trivy-operator](https://artifacthub.io/packages/helm/trivy-operator/trivy-operator)
- [Grafana Dashboard 17813](https://grafana.com/grafana/dashboards/17813)
- [Trivy Documentation](https://trivy.dev/docs/)
