# Chaos Engineering в CI/CD Pipelines

## Определения

**Chaos CI/CD** — интеграция хаос-тестирования в конвейер непрерывной интеграции и доставки. Каждый Pull Request или деплой проходит минимальный хаос-тест в Staging перед продвижением в Production.

**Quality Gate** — критерий, который должен быть выполнен для продвижения кода по pipeline. В контексте хаоса: error rate < 1%, latency p99 < baseline * 1.2, все probes passed. Может быть blocking или advisory.

**Shift-Left Chaos** — практика запуска хаос-тестов как можно раньше в lifecycle приложения: на этапе PR, а не только на этапе деплоя. Позволяет выявлять проблемы до merge.

**Pipeline Resilience** — устойчивость самого CI/CD pipeline к сбоям: что если registry недоступен, secrets manager упал, build worker недоступен. Тестируется через dependency chaos.

**Dependency Chaos** — тестирование поведения pipeline при отказе внешних зависимостей: npm/pypi/maven central, Docker Registry, Vault. Используется для проверки fallback и retry логики.

## Основные концепции

### Где вставлять chaos в pipeline

```
PR → Lint → Unit Tests → Integration Tests → Chaos Test (Staging) → Canary Deploy → Production
```

**Chaos Test stage:**
- Время: 2-5 минут (быстрые эксперименты).
- Blast radius: staging environment, 1-5% ресурсов.
- Stop conditions: error rate < 1%, latency p99 < 2x baseline.
- Cleanup: автоматическое удаление экспериментов.

### Типы chaos-тестов в CI/CD

| Тип | Время | Blast Radius | Цель |
|:---|:---|:---|:---|
| **Pod kill** | 30s | 1 под | Проверка self-healing |
| **Network delay** | 1m | 5% трафика | Проверка timeout/retry |
| **CPU hog** | 1m | 1 под | Проверка graceful degradation |
| **Dependency failure** | 2m | 1 внешний сервис | Проверка fallback |
| **Disk full** | 2m | 1 под | Проверка error handling |

### Pipeline resilience testing

**Сценарии, которые нужно тестировать:**
- Registry недоступен (Docker Hub, Harbor).
- Secrets manager упал (Vault, AWS Secrets Manager).
- Build worker недоступен.
- Artifact corruption.
- Network partition между stages.

## Практические сценарии

### Сценарий 1: Chaos test в GitLab CI

**Цель:** Каждый PR проходит хаос-тест в Staging перед merge.

**.gitlab-ci.yml:**

```yaml
stages:
  - build
  - test
  - chaos
  - deploy

chaos-test:
  stage: chaos
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f chaos-experiments/pod-delete.yaml
    - sleep 120  # Ждём завершения эксперимента
    - kubectl delete -f chaos-experiments/pod-delete.yaml
    # Проверяем, что алерты НЕ сработали (system is resilient)
    - |
      ALERTS=$(curl -s http://alertmanager:9093/api/v2/alerts | jq 'length')
      if [ "$ALERTS" -gt 0 ]; then
        echo "Chaos experiment triggered alerts - system not resilient"
        exit 1
      fi
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: on_success
  environment:
    name: staging
  retry:
    max: 2
    when:
      - script_failure
```

### Сценарий 2: Chaos test в GitHub Actions

**Цель:** Запуск хаос-тестов по расписанию и на PR.

**.github/workflows/chaos-tests.yml:**

```yaml
name: Chaos Tests

on:
  schedule:
    - cron: "0 2 * * 1"  # Каждый понедельник в 02:00
  pull_request:
    branches:
      - main

jobs:
  chaos:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy chaos tests
        run: |
          kubectl apply -f chaos/gateway-api-chaos.yaml
          sleep 300  # Ждём 5 минут

      - name: Validate steady state
        run: |
          ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m]))/sum(rate(envoy_cluster_upstream_rq_total[5m])) | jq '.data.result[0].value[1]' -r)
          if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
            echo "FAIL: Error rate $ERROR_RATE exceeds 5% threshold"
            exit 1
          fi
          echo "PASS: Error rate $ERROR_RATE within SLO"

      - name: Cleanup
        if: always()
        run: kubectl delete -f chaos/gateway-api-chaos.yaml
```

### Сценарий 3: Chaos test в Jenkins

**Цель:** Интеграция хаос-тестирования в Jenkins pipeline.

**Jenkinsfile:**

```groovy
pipeline {
  agent any

  stages {
    stage('Build') {
      steps {
        sh 'docker build -t api-service:$BUILD_NUMBER .'
      }
    }

    stage('Deploy to Staging') {
      steps {
        sh 'kubectl apply -f k8s/staging/'
        sh 'kubectl rollout status deployment/api-service -n staging --timeout=5m'
      }
    }

    stage('Chaos Test') {
      steps {
        script {
          try {
            sh 'kubectl apply -f chaos-experiments/network-delay.yaml'
            sh 'sleep 180'
            sh 'kubectl delete -f chaos-experiments/network-delay.yaml'

            // Проверяем метрики
            def errorRate = sh(
              script: 'curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[5m]))/sum(rate(http_requests_total[5m])) | jq ".data.result[0].value[1]" -r',
              returnStdout: true
            ).trim()

            if (errorRate.toDouble() > 0.05) {
              error "Chaos experiment failed: error rate ${errorRate} > 5%"
            }
          } catch (Exception e) {
            sh 'kubectl delete -f chaos-experiments/network-delay.yaml || true'
            throw e
          }
        }
      }
    }

    stage('Deploy to Production') {
      steps {
        sh 'kubectl apply -f k8s/production/'
        sh 'kubectl rollout status deployment/api-service -n production --timeout=10m'
      }
    }
  }

  post {
    always {
      sh 'kubectl delete -f chaos-experiments/network-delay.yaml || true'
      archiveArtifacts artifacts: 'chaos-results/**', fingerprint: true
    }
  }
}
```

### Сценарий 4: Dependency chaos (registry, secrets)

**Цель:** Проверить, что pipeline работает при отказе внешних зависимостей.

**Registry failure:**

```bash
# Имитируем недоступность Docker Hub
iptables -A OUTPUT -d registry-1.docker.io -j DROP

# Пытаемся собрать образ
docker build -t api-service:test .

# Ожидаем: fallback на Harbor (если настроен mirror)
# Или: понятное сообщение об ошибке, retry
```

**Secrets manager failure:**

```bash
# Останавливаем Vault
kubectl scale deployment/vault --replicas=0 -n vault

# Запускаем pipeline
# Ожидаем: pipeline использует кэшированные секреты или падает с понятной ошибкой
```

**Скрипт для dependency chaos:**

```bash
#!/bin/bash
# dependency-chaos.sh

# 1. Registry chaos
echo "Testing registry failure..."
iptables -A OUTPUT -d registry-1.docker.io -j DROP
if docker build -t api-service:test .; then
  echo "PASS: Build succeeded with registry down (mirror configured)"
else
  echo "FAIL: Build failed with registry down"
fi
iptables -D OUTPUT -d registry-1.docker.io -j DROP

# 2. Vault chaos
echo "Testing Vault failure..."
kubectl scale deployment/vault --replicas=0 -n vault
if kubectl get secret api-secrets -n staging; then
  echo "PASS: Secrets available from cache"
else
  echo "FAIL: Secrets not available"
fi
kubectl scale deployment/vault --replicas=3 -n vault
```

### Сценарий 5: Automated Game Day workflow (LitmusChaos)

**Цель:** Полностью автоматизированный Game Day в CI/CD.

**ChaosWorkflow:**

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosWorkflow
metadata:
  name: game-day-workflow
  namespace: litmus
spec:
  entrypoint: game-day
  templates:
    - name: game-day
      steps:
        - - name: step-1-delete-pod
            template: pod-delete
        - - name: step-2-check-availability
            template: http-probe
        - - name: step-3-wait
            template: wait-step
        - - name: step-4-network-delay
            template: network-delay

    - name: pod-delete
      chaosEngine:
        spec:
          experiments:
            - name: pod-delete
              spec:
                components:
                  env:
                    - name: TOTAL_CHAOS_DURATION
                      value: "60"
                probe:
                  - name: check-availability
                    type: httpProbe
                    httpProbe/inputs:
                      url: "http://api-gateway:8080/health"
                      method:
                        get:
                          criteria: ==
                          responseCode: "200"
                    mode: Continuous

    - name: network-delay
      chaosEngine:
        spec:
          experiments:
            - name: pod-network-latency
              spec:
                components:
                  env:
                    - name: TOTAL_CHAOS_DURATION
                      value: "300"
                    - name: NETWORK_LATENCY
                      value: "500"
                    - name: JITTER
                      value: "100"
                probe:
                  - name: check-circuit-breaker
                    type: httpProbe
                    httpProbe/inputs:
                      url: "http://api-gateway:8080/health"
                      method:
                        get:
                          criteria: ==
                          responseCode: "200"
                    mode: Continuous
```

### Сценарий 6: Chaos as Code (GitOps)

**Цель:** Хранить хаос-эксперименты в Git рядом с манифестами приложения.

**Структура репозитория:**

```
repo/
├── k8s/
│   ├── production/
│   │   └── api-service.yaml
│   └── staging/
│       └── api-service.yaml
├── chaos/
│   ├── production/
│   │   ├── pod-delete.yaml
│   │   └── network-delay.yaml
│   └── staging/
│       ├── pod-delete.yaml
│       └── network-delay.yaml
├── charts/
│   └── api-service/
└── tests/
    └── chaos-test.sh
```

**ArgoCD Integration:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chaos-experiments
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: HEAD
    path: chaos/production
  destination:
    server: https://kubernetes.default.svc
    namespace: chaos-testing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## Операции и команды

### GitLab CI: chaos stage

```yaml
chaos-test:
  stage: chaos
  script:
    - kubectl apply -f chaos-experiments/pod-delete.yaml
    - sleep 120
    - kubectl delete -f chaos-experiments/pod-delete.yaml
    - |
      ALERTS=$(curl -s http://alertmanager:9093/api/v2/alerts | jq 'length')
      if [ "$ALERTS" -gt 0 ]; then
        echo "Chaos experiment triggered alerts"
        exit 1
      fi
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

### GitHub Actions: chaos workflow

```yaml
name: Chaos Tests
on:
  schedule:
    - cron: "0 2 * * 1"
  pull_request:
    branches: [main]

jobs:
  chaos:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy chaos tests
        run: |
          kubectl apply -f chaos/gateway-api-chaos.yaml
          sleep 300
      - name: Validate steady state
        run: |
          ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(envoy_cluster_upstream_rq_xx{code=~"5.."}[5m]))/sum(rate(envoy_cluster_upstream_rq_total[5m])) | jq '.data.result[0].value[1]' -r)
          if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
            echo "FAIL"
            exit 1
          fi
      - name: Cleanup
        if: always()
        run: kubectl delete -f chaos/gateway-api-chaos.yaml
```

### Jenkins: chaos stage

```groovy
stage('Chaos Test') {
  steps {
    script {
      try {
        sh 'kubectl apply -f chaos-experiments/network-delay.yaml'
        sh 'sleep 180'
        sh 'kubectl delete -f chaos-experiments/network-delay.yaml'

        def errorRate = sh(
          script: 'curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[5m]))/sum(rate(http_requests_total[5m])) | jq ".data.result[0].value[1]" -r',
          returnStdout: true
        ).trim()

        if (errorRate.toDouble() > 0.05) {
          error "Chaos experiment failed: error rate ${errorRate} > 5%"
        }
      } catch (Exception e) {
        sh 'kubectl delete -f chaos-experiments/network-delay.yaml || true'
        throw e
      }
    }
  }
}
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Chaos test падает в CI** | Staging недоступен или ресурсы исчерпаны | Проверьте `kubectl get pods -n staging`, увеличивайте timeout |
| **Registry недоступен** | Docker Hub down или network issue | Настройте mirror (Harbor), используйте `--image` с mirror |
| **Secrets manager недоступен** | Vault down или network partition | Настройте кэширование секретов, используйте init-only injector |
| **Pipeline зависает** | Experiment cleanup не сработал | Добавьте `always()` cleanup, настройте `timeout` для stage |
| **False positive в CI** | Staging не имеет production-метрик | Используйте synthetic monitoring или mirror production metrics |
| **Chaos experiment не применяется** | CRD не установлен в staging | Проверьте `kubectl get crd | grep chaos-mesh` |
| **Alertmanager не настроен** | Алерты не приходят | Проверьте `kubectl get alertmanager`, настройте receivers |

## Лучшие практики

### Интеграция в pipeline

1. **Запускайте chaos на staging** — первый этап после deploy to staging.
2. **Используйте quality gates** — error rate < 1%, latency p99 < 2x baseline.
3. **Автоматизируйте cleanup** — `always()` блок в CI/CD.
4. **Ограничивайте время** — максимум 5-10 минут на chaos stage.
5. **Не блокируйте merge на chaos** — chaos test может быть advisory, а не blocking.

### Pipeline resilience

6. **Тестируйте dependency chaos** — registry, secrets manager, build tools.
7. **Настройте fallback** — mirror registry, cached secrets.
8. **Имейте retry logic** — retry для registry, secrets manager.
9. **Мониторьте pipeline health** — алерты на недоступность CI/CD компонентов.

### Automation

10. **Используйте GitOps** — chaos experiments в Git, ArgoCD/Flux синхронизирует.
11. **Планируйте по расписанию** — ежедневный/еженедельный хаос-тест.
12. **Интегрируйте с LitmusChaos Workflow** — сложные цепочки экспериментов.
13. **Архивируйте результаты** — Grafana snapshots, Prometheus queries, logs.

## Дополнительная информация

### Интеграция с инструментами

- **GitLab CI:** native chaos stage, artifacts, retry.
- **GitHub Actions:** schedule + PR triggers, matrix builds.
- **Jenkins:** pipeline as code, post actions.
- **ArgoCD/Flux:** GitOps для chaos experiments.
- **LitmusChaos:** ChaosWorkflow для сложных сценариев.

### См. также

- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — CI-CD Pipeline с Chaos Testing.
- [Chaos Engineering — инструменты](chaos_engineering_tools.md) — LitmusChaos Workflow.
- [Chaos Engineering — advanced blast radius](chaos_advanced_blast_radius.md) — progressive rollout в CI/CD.
