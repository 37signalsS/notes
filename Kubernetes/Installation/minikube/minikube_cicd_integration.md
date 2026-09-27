# Minikube: интеграция с CI/CD

## Определения

**CI/CD (Continuous Integration / Continuous Delivery)** — методология автоматической сборки, тестирования и доставки приложений. Minikube используется как целевая среда для интеграционного тестирования Kubernetes-манифестов и Helm-чартов в пайплайнах.

**Pipeline** — последовательность автоматических шагов (build → test → deploy), определяемая конфигурационным файлом (`.gitlab-ci.yml`, `.github/workflows/*.yml` и т.д.).

**Dynamic Environment** — временное окружение (namespace + приложение), автоматически создаваемое для каждой ветки или merge request. После завершения тестов окружение уничтожается.

**Helm Chart** — пакет для Kubernetes, содержащий шаблоны манифестов. В CI/CD используется для стандартизации деплоя: `helm upgrade --install` на Minikube воспроизводит identical деплой.

---

## Базовые концепции

### Зачем Minikube в CI/CD

| Задача | Как Minikube помогает |
| :--- | :--- |
| **Интеграционные тесты** | Запуск реального K8s-кластера для проверки манифестов, сервисов, ingress |
| **Валидация Helm-чартов** | Рендеринг и деплой чартов с проверкой `helm test` |
| **E2E-тесты приложений** | Тестирование API-эндпоинтов через порты/Ingress Minikube |
| **Smoke test перед production** | Быстрый деплой в изолированную среду для финальной проверки |

### Архитектура CI/CD с Minikube

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Git Push   │────>│  CI Runner   │────>│   Minikube  │
│  (commit)   │     │  (job)       │     │  (cluster)  │
└─────────────┘     └──────────────┘     └─────────────┘
                           │                    │
                    ┌──────┴──────┐      ┌──────┴──────┐
                    │  Build      │      │  Deploy     │
                    │  (image,    │      │  (kubectl   │
                    │   chart)    │      │   apply)    │
                    └─────────────┘      └─────────────┘
                                              │
                                        ┌─────┴─────┐
                                        │  Test     │
                                        │  (curl,   │
                                        │   pytest) │
                                        └───────────┘
```

### Ограничения Minikube в CI/CD

| Ограничение | Решение |
| :--- | :--- |
| Minikube требует виртуализацию (VM/Docker) | CI-раннер должен поддерживать Docker-in-Docker или VM |
| Время запуска кластера 30-60 сек | Используйте `minikube start` в начале job; сохраняйте образ |
| Нет LB (LoadBalancer) | Используйте `minikube tunnel` или NodePort |
| Ресурсы ограничены | Уменьшите `--cpus` и `--memory` для CI (2 CPU, 4GB достаточно) |

---

## Практические сценарии

### GitLab CI + Minikube

#### Конфигурация `.gitlab-ci.yml`

```yaml
stages:
  - build
  - deploy
  - test
  - cleanup

variables:
  MINIKUBE_CPUS: "2"
  MINIKUBE_MEMORY: "4096"
  APP_NAMESPACE: "ci-$CI_PIPELINE_ID"

# Запуск Minikube для всех job
before_script:
  - curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
  - sudo install minikube-linux-amd64 /usr/local/bin/minikube
  - minikube start --driver=docker --cpus=$MINIKUBE_CPUS --memory=$MINIKUBE_MEMORY --addons=ingress
  - kubectl cluster-info

build:
  stage: build
  script:
    - docker build -t myapp:$CI_COMMIT_SHA .
    - minikube image load myapp:$CI_COMMIT_SHA
    # Обновление image в Helm-чарте
    - sed -i "s|image: myapp:.*|image: myapp:$CI_COMMIT_SHA|g" helm/values.yaml
  only:
    - branches

deploy:
  stage: deploy
  script:
    - kubectl create namespace $APP_NAMESPACE || true
    - helm upgrade --install myapp ./helm
      --namespace $APP_NAMESPACE
      --set image.tag=$CI_COMMIT_SHA
      --wait --timeout 120s
  only:
    - branches

smoke_test:
  stage: test
  script:
    - kubectl get pods -n $APP_NAMESPACE
    - |
      # Проверка доступности сервиса
      SVC_IP=$(minikube service myapp -n $APP_NAMESPACE --url)
      HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" $SVC_IP/health)
      if [ "$HTTP_CODE" != "200" ]; then
        echo "Smoke test failed: HTTP $HTTP_CODE"
        exit 1
      fi
      echo "Smoke test passed: HTTP $HTTP_CODE"
  only:
    - branches

cleanup:
  stage: cleanup
  when: always
  script:
    - kubectl delete namespace $APP_NAMESPACE --ignore-not-found
    - minikube stop
  only:
    - branches
```

### GitHub Actions + Minikube

#### Конфигурация `.github/workflows/k8s-test.yml`

```yaml
name: Kubernetes Integration Test

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  minikube-test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Start Minikube
        uses: medyagh/setup-minikube@latest
        with:
          driver: docker
          cpus: 2
          memory: 4096
          addons: "ingress,metrics-server"

      - name: Build image
        run: |
          docker build -t test-app:${{ github.sha }} .
          minikube image load test-app:${{ github.sha }}

      - name: Deploy to Minikube
        run: |
          kubectl create namespace test || true
          helm upgrade --install test-app ./helm \
            --namespace test \
            --set image.tag=${{ github.sha }} \
            --wait

      - name: Run smoke tests
        run: |
          kubectl get pods -n test
          kubectl rollout status deployment/test-app -n test --timeout=60s
          # Проверка health endpoint
          URL=$(minikube service test-app -n test --url 2>/dev/null || echo "pending")
          if [ "$URL" != "pending" ]; then
            curl -sf $URL/health || exit 1
          fi

      - name: Cleanup
        if: always()
        run: |
          kubectl delete namespace test --ignore-not-found
          minikube stop
```

### Тестирование Helm-чартов

```yaml
# В CI job: валидация и деплой Helm-чарта
test_helm:
  stage: test
  script:
    # Линтинг чарта
    - helm lint ./helm --strict

    # Рендеринг шаблонов (проверка без деплоя)
    - helm template test-release ./helm --namespace test > /dev/null

    # Валидация через kubeconform
    - helm template test-release ./helm --namespace test | kubeconform -strict -summary

    # Деплой в Minikube
    - kubectl create namespace test || true
    - helm upgrade --install test-release ./helm --namespace test --wait

    # Тесты чарта (если определены в templates/tests/)
    - helm test test-release -n test --timeout 60s

    # Проверка PodDisruptionBudget (если есть)
    - kubectl get pdb -n test -o wide || echo "No PDB found"

  after_script:
    - helm uninstall test-release -n test 2>/dev/null || true
    - kubectl delete namespace test --ignore-not-found
```

### Тестирование NetworkPolicy в CI

```yaml
netpol_test:
  stage: test
  script:
    # Установка Calico (если CNI не поддерживает NetworkPolicy)
    - helm repo add projectcalico https://docs.tigera.io/calico/charts
    - helm install calico projectcalico/tigera-operator --namespace tigera-operator --create-namespace --wait

    # Применение политик
    - kubectl apply -f tests/network-policies/

    # Проверка изоляции
    - kubectl exec test-client -- curl -s --max-time 3 test-service
    # Ожидаем: timeout (заблокировано NetworkPolicy)

    # Проверка разрешения
    - kubectl exec test-frontend -- curl -s --max-time 3 test-backend
    # Ожидаем: 200 OK
```

### Debug-режим при ошибке CI

```bash
# Если CI job упал — добавьте SSH-доступ для отладки
# GitLab CI:
  after_script:
    - minikube status
    - kubectl get pods -A
    - kubectl logs -l app=myapp --tail=50
    - kubectl describe pods -n test

# GitHub Actions: добавьте step с debug
  - name: Debug on failure
    if: failure()
    run: |
      kubectl get pods -A
      kubectl get events -A --sort-by='.lastTimestamp' | tail -20
      minikube ssh "sudo crictl ps"
```

---

## Дополнительная информация

### См. также

- [Minikube: Определения и концепции](./minikube_concepts.md) — архитектура и запуск
- [Minikube: Практические сценарии](./minikube_practical_scenarios.md) — кластер и интеграция
- [Helm: Обзор](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md) — пакетный менеджер
- [CI-CD: GitLab CI](../../../CI-CD/GitLab_CI/overview.md) — конфигурация пайплайнов

### Полезные ссылки

- [Minikube in CI](https://minikube.sigs.k8s.io/docs/tutorials/setup_minikube_in_ci/) — официальное руководство
- [GitHub Actions: minikube-action](https://github.com/medyagh/setup-minikube) — готовый action
- [GitLab CI: Kubernetes executor](https://docs.gitlab.com/ee/ci/runners/scaled_agents/index.html) — Kubernetes executor
