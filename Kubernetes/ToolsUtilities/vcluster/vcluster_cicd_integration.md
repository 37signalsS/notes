# vCluster — интеграция с CI/CD

> Документ описывает паттерны использования vCluster в CI/CD: ephemeral environments, review apps, тестирование PR, интеграция с GitLab CI, GitHub Actions и Jenkins. Установка — в [vcluster_installation.md](./vcluster_installation.md), GitOps — в [vcluster_gitops_integration.md](./vcluster_gitops_integration.md).

## Определения

**Ephemeral Environment** — временное окружение, автоматически создаваемое для тестирования и автоматически удаляемое после завершения. В контексте vCluster — это виртуальный кластер, живущий столько, сколько нужен пайплайн.

**Review App** — приложение, автоматически разворачиваемое для ревью кода (Pull Request / Merge Request). Разработчик получает URL для тестирования изменений до слияния в main.

**Pipeline** — последовательность автоматизированных шагов (build, test, deploy). vCluster используется как изолированное окружение для этапов test и deploy.

**Runner** — агент, выполняющий задачи CI/CD пайплайна. Для Kubernetes-based runners — это поды в кластере, для Docker runners — контейнеры на хосте.

**Cleanup Hook** — механизм гарантированного удаления временных ресурсов при завершении пайплайна (успех или падение). В bash — `trap`, в CI — `after_script` / `always`.

## Основные концепции

### Паттерн 1: Ephemeral vCluster для каждого PR

```text
┌─────────────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline                                │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Build   │→ │  Test    │→ │ Deploy   │→ │ Cleanup  │       │
│  │  image   │  │  unit    │  │ in vC    │  │  vCluster│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                     │              │             │
│                                     ▼              ▼             │
│                          ┌──────────────┐  ┌──────────────┐     │
│                          │ vCluster PR- │  │ Удаление     │     │
│                          │ 123-abc      │  │ vCluster     │     │
│                          └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Паттерн 2: Review App с автоматическим URL

```text
PR #123 создан
    │
    ├── CI pipeline стартует
    │   ├── Создаёт vCluster "pr-123"
    │   ├── Разворачивает приложение внутри vCluster
    │   ├── Создаёт Ingress для pr-123.example.com
    │   └── Комментирует PR с URL: https://pr-123.example.com
    │
PR #123 смержен
    │
    ├── CI pipeline стартует
    │   └── Удаляет vCluster "pr-123"
```

### Паттерн 3: Matrix testing (много vCluster одновременно)

```yaml
# GitHub Actions: тестирование на разных версиях K8s
strategy:
  matrix:
    k8s-version: ["1.33", "1.34", "1.35"]
    include:
      - k8s-version: "1.33"
        vcluster-version: "v0.33.0"
      - k8s-version: "1.34"
        vcluster-version: "v0.34.0"
      - k8s-version: "1.35"
        vcluster-version: "v0.35.0"
```

## Практические сценарии

### GitLab CI: полный паттерн

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - deploy-preview
  - cleanup

variables:
  VC_NAME: "pr-${CI_MERGE_REQUEST_IID:-${CI_COMMIT_SHORT_SHA}}"
  VC_NS: "ci-${CI_MERGE_REQUEST_IID:-${CI_COMMIT_SHORT_SHA}}"
  VC_VERSION: "v0.34.0"

# Cleanup при завершении (успех или падение)
cleanup-preview:
  stage: cleanup
  when: always
  script:
    - vcluster delete "$VC_NAME" -n "$VC_NS" 2>/dev/null || true
    - kubectl delete namespace "$VC_NS" --ignore-not-found 2>/dev/null || true
    - kubectl config delete-context "vcluster_${VC_NAME}_${VC_NS}" 2>/dev/null || true

deploy-preview:
  stage: deploy-preview
  script:
    # 1. Установить vCluster CLI
    - curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/download/${VC_VERSION}/vcluster-linux-amd64"
    - chmod +x vcluster && sudo mv vcluster /usr/local/bin/

    # 2. Создать namespace и vCluster
    - kubectl create namespace "$VC_NS" || true
    - vcluster create "$VC_NAME" -n "$VC_NS" -f ci/vcluster.yaml --no-connect --skip-wait
    - vcluster wait --ready "$VC_NAME" -n "$VC_NS" --timeout 5m

    # 3. Подключиться
    - vcluster connect "$VC_NAME" -n "$VC_NS" --update-current

    # 4. Развернуть приложение
    - kubectl apply -f k8s/preview/
    - kubectl rollout status deployment/myapp -n preview --timeout=3m

    # 5. Создать Ingress
    - |
      cat <<EOF | kubectl apply -f -
      apiVersion: networking.k8s.io/v1
      kind: Ingress
      metadata:
        name: myapp-preview
        namespace: preview
        annotations:
          nginx.ingress.kubernetes.io/ssl-passthrough: "true"
      spec:
        ingressClassName: nginx
        rules:
          - host: ${VC_NAME}.preview.example.com
            http:
              paths:
                - path: /
                  pathType: Prefix
                  backend:
                    service:
                      name: myapp
                      port:
                        number: 80
      EOF

    # 6. Дождаться готовности
    - |
      for i in $(seq 1 30); do
        if curl -sk "https://${VC_NAME}.preview.example.com/healthz" | grep -q "ok"; then
          echo "Preview is ready at https://${VC_NAME}.preview.example.com"
          exit 0
        fi
        sleep 10
      done
      echo "Preview failed to become ready"
      exit 1
  environment:
    name: preview/$CI_MERGE_REQUEST_IID
    url: https://$VC_NAME.preview.example.com
    on_stop: cleanup-preview
```

### GitHub Actions: полный паттерн

```yaml
# .github/workflows/preview.yaml
name: Preview Environment

on:
  pull_request:
    types: [opened, synchronize, reopened]

env:
  VC_NAME: pr-${{ github.event.pull_request.number }}
  VC_NS: preview-${{ github.event.pull_request.number }}

jobs:
  deploy-preview:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install vCluster CLI
        run: |
          curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/download/v0.34.0/vcluster-linux-amd64"
          chmod +x vcluster
          sudo mv vcluster /usr/local/bin/

      - name: Configure kubeconfig
        run: |
          echo "${{ secrets.KUBECONFIG }}" | base64 -d > $HOME/.kube/config

      - name: Create vCluster
        run: |
          kubectl create namespace ${{ env.VC_NS }} || true
          vcluster create ${{ env.VC_NAME }} \
            -n ${{ env.VC_NS }} \
            -f ci/vcluster.yaml \
            --no-connect \
            --skip-wait
          vcluster wait --ready ${{ env.VC_NAME }} \
            -n ${{ env.VC_NS }} --timeout 5m

      - name: Connect to vCluster
        run: |
          vcluster connect ${{ env.VC_NAME }} \
            -n ${{ env.VC_NS }} --update-current

      - name: Deploy application
        run: |
          kubectl apply -f k8s/preview/
          kubectl rollout status deployment/myapp \
            -n preview --timeout=3m

      - name: Create Ingress
        run: |
          cat <<EOF | kubectl apply -f -
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          metadata:
            name: myapp-preview
            namespace: preview
          spec:
            ingressClassName: nginx
            rules:
              - host: pr-${{ github.event.pull_request.number }}.preview.example.com
                http:
                  paths:
                    - path: /
                      pathType: Prefix
                      backend:
                        service:
                          name: myapp
                          port:
                            number: 80
          EOF

      - name: Comment PR with URL
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `Preview deployed: https://pr-${{ context.issue.number }}.preview.example.com`
            })

  cleanup-preview:
    runs-on: ubuntu-latest
    if: always()
    needs: deploy-preview
    steps:
      - name: Configure kubeconfig
        run: |
          echo "${{ secrets.KUBECONFIG }}" | base64 -d > $HOME/.kube/config

      - name: Install vCluster CLI
        run: |
          curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/download/v0.34.0/vcluster-linux-amd64"
          chmod +x vcluster
          sudo mv vcluster /usr/local/bin/

      - name: Delete vCluster
        run: |
          vcluster delete ${{ env.VC_NAME }} \
            -n ${{ env.VC_NS }} 2>/dev/null || true
          kubectl delete namespace ${{ env.VC_NS }} \
            --ignore-not-found 2>/dev/null || true
```

### Jenkins: паттерн с Declarative Pipeline

```groovy
// Jenkinsfile
pipeline {
    agent any

    environment {
        VC_NAME = "pr-${env.CHANGE_ID ?: env.BUILD_NUMBER}"
        VC_NS = "ci-${env.CHANGE_ID ?: env.BUILD_NUMBER}"
        VC_VERSION = 'v0.34.0'
    }

    stages {
        stage('Setup vCluster') {
            steps {
                sh '''
                    curl -L -o vcluster \
                      "https://github.com/loft-sh/vcluster/releases/download/${VC_VERSION}/vcluster-linux-amd64"
                    chmod +x vcluster
                    sudo mv vcluster /usr/local/bin/

                    kubectl create namespace ${VC_NS} || true
                    vcluster create ${VC_NAME} \
                      -n ${VC_NS} \
                      -f ci/vcluster.yaml \
                      --no-connect \
                      --skip-wait
                    vcluster wait --ready ${VC_NAME} \
                      -n ${VC_NS} --timeout 5m
                '''
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    vcluster connect ${VC_NAME} \
                      -n ${VC_NS} --update-current
                    kubectl apply -f k8s/preview/
                    kubectl rollout status deployment/myapp \
                      -n preview --timeout=3m
                '''
            }
        }

        stage('Test') {
            steps {
                sh '''
                    # Запуск интеграционных тестов
                    ./tests/run.sh \
                      --endpoint https://${VC_NAME}.preview.example.com
                '''
            }
        }
    }

    post {
        always {
            sh '''
                vcluster delete ${VC_NAME} \
                  -n ${VC_NS} 2>/dev/null || true
                kubectl delete namespace ${VC_NS} \
                  --ignore-not-found 2>/dev/null || true
            '''
        }
    }
}
```

### Оптимизация: переиспользование vCluster

Для ускорения пайплайнов можно переиспользовать vCluster вместо создания нового каждый раз:

```yaml
# .gitlab-ci.yml с persistent preview
deploy-preview:
  script:
    # Проверить, существует ли vCluster
    - |
      if vcluster list -n preview | grep -q "pr-${CI_MERGE_REQUEST_IID}"; then
        echo "Reusing existing vCluster"
        vcluster connect "pr-${CI_MERGE_REQUEST_IID}" -n preview --update-current
      else
        echo "Creating new vCluster"
        vcluster create "pr-${CI_MERGE_REQUEST_IID}" -n preview -f ci/vcluster.yaml --no-connect
        vcluster wait --ready "pr-${CI_MERGE_REQUEST_IID}" -n preview --timeout 5m
        vcluster connect "pr-${CI_MERGE_REQUEST_IID}" -n preview --update-current
      fi
    # Обновить приложение (helm upgrade или kubectl apply)
    - kubectl apply -f k8s/preview/
    - kubectl rollout restart deployment/myapp -n preview
```

### Конфигурация vCluster для CI/CD

```yaml
# ci/vcluster.yaml
controlPlane:
  distro:
    k3s:
      enabled: true  # K3s быстрее стартеет для ephemeral окружений

  backingStore:
    etcd:
      embedded:
        enabled: true
        size: "2Gi"

  statefulSet:
    replicas: 1  # Для CI достаточно 1 реплики
    resources:
      requests:
        cpu: 100m
        memory: 150Mi
      limits:
        cpu: 500m
        memory: 512Mi

sync:
  toHost:
    pods:
      enabled: true
    services:
      enabled: true
    ingresses:
      enabled: true
  fromHost:
    storageClasses:
      enabled: true
    ingressClasses:
      enabled: true
    nodes:
      enabled: true

sleepMode:
  enabled: false  # Для CI не используем sleep

policies:
  podSecurityStandard: baseline  # Baseline для CI, не restricted
  networkPolicy:
    enabled: false  # Упрощение для CI
```

### Ограничения ресурсов для CI

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| `controlPlane.statefulSet.replicas` | 1 | CI — ephemeral, HA не нужен |
| `controlPlane.statefulSet.resources.requests.cpu` | 100m | Экономия CPU для параллельных job |
| `controlPlane.statefulSet.resources.requests.memory` | 150Mi | Минимум для K3s |
| `backingStore.etcd.embedded.size` | 2Gi | Мало объектов в CI |
| `policies.podSecurityStandard` | baseline | restricted может сломать тесты |
| `sleepMode.enabled` | false | CI не требует sleep |

### Cleanup: гарантированное удаление

```bash
#!/usr/bin/env bash
# cleanup.sh — вызывается в after_script / post { always }
set -euo pipefail

VC_NAME="${1:?Usage: cleanup.sh <vcluster-name> <namespace>}"
VC_NS="${2:?Usage: cleanup.sh <vcluster-name> <namespace>}"

echo ">>> Cleanup vCluster ${VC_NAME} in namespace ${VC_NS}"

# 1. Удалить vCluster
vcluster delete "$VC_NAME" -n "$VC_NS" 2>/dev/null || true

# 2. Дождаться удаления namespace
kubectl delete namespace "$VC_NS" --ignore-not-found --timeout=60s 2>/dev/null || true

# 3. Если namespace не удалился — принудительно
kubectl get namespace "$VC_NS" 2>/dev/null && \
  kubectl delete namespace "$VC_NS" --force --grace-period=0 2>/dev/null || true

# 4. Очистить контекст
kubectl config delete-context "vcluster_${VC_NAME}_${VC_NS}" 2>/dev/null || true
kubectl config delete-user "vcluster_${VC_NAME}_${VC_NS}" 2>/dev/null || true
kubectl config delete-cluster "vcluster_${VC_NAME}_${VC_NS}" 2>/dev/null || true

# 5. Проверить, что PVC удалены (опционально)
kubectl get pvc -n "$VC_NS" 2>/dev/null && \
  kubectl delete pvc --all -n "$VC_NS" 2>/dev/null || true

echo ">>> Cleanup completed"
```

### Диагностика проблем CI/CD

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `vcluster create` timeout в CI | Нет доступа к registry | Проверить `imagePullSecret`, registry доступность |
| Preview URL не работает | Ingress не создался | Проверить `sync.toHost.ingresses.enabled` |
| Cleanup не удаляет vCluster | Finalizer на namespace | `kubectl patch namespace <ns> -p '{"metadata":{"finalizers":null}}'` |
| CI job падает после cleanup | Cleanup в `post` не отработал | Добавить `|| true` ко всем командам cleanup |
| vCluster не справляется с нагрузкой | 1 реплика для CI | Увеличить `resources.limits.cpu/memory` |
| Конфликт имён при параллельных job | Одинаковые `VC_NAME` | Использовать уникальные имена: `pr-${IID}-${JOB_ID}` |

### Лучшие практики

- **Уникальные имена:** Каждый PR/branch получает уникальный vCluster. Избегайте коллизий имён.
- **Cleanup в post/always:** Гарантированное удаление даже при падении pipeline.
- **Timeout на создание:** `vcluster wait --ready ... --timeout 5m`. Не бесконечное ожидание.
- **K3s для CI:** Быстрее стартует, меньше ресурсов.
- **baseline PSA:** restricted может сломать тесты. Используйте baseline для CI.
- **Ограничение.parallel:** Не создавайте >10 vCluster одновременно — нагрузка на хост.
- **Мониторинг CI кластера:** Следите за ресурсами host-кластера, чтобы CI jobs не Consumed всё.
- **Отключение sleep для CI:** Sleep mode замедляет pipeline.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — GitOps интеграция](./vcluster_gitops_integration.md)
- [vCluster — обзор и архитектура](./vcluster_overview.md)

### См. также

- [GitLab CI — базовые концепции](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)
- [GitHub Actions](../../Obsidian/github.md)
- [GitLab Runner — Kubernetes executor](../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)

### Внешние ссылки

- [vCluster CI/CD Guide](https://www.vcluster.com/docs/use-cases/ci-cd)
- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
