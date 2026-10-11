# Service Mesh и GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

*   **Service Mesh** — инфраструктурный слой для управления коммуникациями между микросервисами. Предоставляет observability, traffic management, security (mTLS) и resilience без изменения кода приложений.
*   **Istio** — популярный open-source service mesh (CNCF). Использует sidecar-прокси Envoy для управления трафиком.
*   **Linkerd** — легковесный service mesh (CNCF), ориентированный на simplicity и performance.
*   **Sidecar Proxy** — дополнительный контейнер (Envoy), внедряемый рядом с приложением для перехвата всего сетевого трафика.
*   **mTLS (Mutual TLS)** — двусторонняя TLS-аутентификация между сервисами mesh.
*   **Traffic Shifting** — Gradual migration трафика между версиями (canary release).
*   **VirtualService** — ресурс Istio для управления маршрутизацией трафика.
*   **DestinationRule** — ресурс Istio для определения политик после маршрутизации.
*   **Kiali** — консоль управления и визуализации Istio mesh.
*   **GitLab Agent for Kubernetes (KAS)** — агент для безопасного взаимодействия GitLab с Kubernetes-кластерами.

> **Примечание:** Общие концепции service mesh, canary deployment стратегии и Istio архитектура описаны в **[Canary deployment](../../Deployment_Strategies/canary_deployment.md)** и **[Shadow deployment](../../Deployment_Strategies/shadow_deployment.md)**. Ниже — GitLab CI pipeline-интеграция с mesh.

## Базовые концепции

### Service Mesh в контексте CI/CD

Service mesh влияет на CI/CD на нескольких этапах:

1.  **Валидация конфигурации**: Проверка Istio/Linkerd манифестов в пайплайне.
2.  **Тестирование**: Развертывание в изолированном namespace с mesh для интеграционных тестов.
3.  **Сканирование безопасности**: Проверка mTLS политик, аудит доступа.
4.  **Canary deployment**: Gradual traffic shifting через mesh.
5.  **Observability**: Трейсинг запросов через mesh (Jaeger, Kiali).

### Архитектура интеграции

```
[GitLab CI Pipeline]
    │
    ├─── Валидация манифестов (istioctl analyze)
    ├─── Развертывание в staging namespace
    ├─── Интеграционные тесты через mesh
    ├─── Traffic shifting (canary)
    └─── Observability (Kiali, Jaeger)
           │
           ▼
[Kubernetes Cluster with Service Mesh]
    │
    ├─── Istio Control Plane (istiod)
    ├─── Sidecar Proxies (Envoy)
    ├─── Kiali (UI)
    └─── Jaeger (Tracing)
```

## Предпосылки

Перед запуском пайплайнов, интегрированных с service mesh, убедитесь, что выполнены следующие условия:

*   **GitLab Runner** с поддержкой Kubernetes executor или доступ к кластеру через GitLab Agent for Kubernetes (KAS).
*   **kubectl** с настроенным `kubeconfig` (при использовании Shell executor) или KAS, настроенный в проекте GitLab.
*   **Istio 1.22+** (рекомендуется) или **Linkerd** установлен в целевом кластере. Для Istio рекомендуется использовать API `networking.istio.io/v1`.
*   **Права RBAC** на деплой манифестов, проверку политик и просмотр метрик в namespace окружения.
*   **Сервисная учетная запись (Service Account)** с минимально необходимыми правами (least privilege) для операций деплоя и проверки.
*   **Сетевые политики** разрешают трафик между Runner'ом и API-сервером кластера, а также между сервисами mesh.

## Практические сценарии

### Сценарий 1: Валидация Istio конфигурации в пайплайне

```yaml
stages:
  - validate
  - test
  - deploy

validate_istio:
  stage: validate
  image: curlimages/curl:8.12.1
  script:
    # Установка istioctl
    - curl -L https://istio.io/downloadIstio | sh -
    - export PATH=$PWD/istio-*/bin:$PATH

    # Валидация манифестов
    - istioctl analyze manifests/

    # Проверка конфигурации (требует подключения к кластеру)
    - istioctl verify-install || true
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - k8s/istio/**/*
        - k8s/**/*.yaml
```

### Сценарий 2: Развертывание с Istio sidecar injection

```yaml
deploy_staging:
  stage: deploy
  image: bitnami/kubectl:1.30
  script:
    # Применение манифестов с автоматической инжекцией sidecar
    - kubectl apply -f k8s/istio/
    - kubectl rollout status deployment/my-app -n staging --timeout=300s

    # Проверка, что sidecar injected
    - kubectl get pods -n staging -l app=my-app -o jsonpath='{.items[0].spec.containers[*].name}'
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
```

### Сценарий 3: Canary deployment через Istio VirtualService

```yaml
stages:
  - deploy_canary
  - verify
  - promote

deploy_canary:
  stage: deploy_canary
  image: bitnami/kubectl:1.30
  script:
    # Деплой canary версии (v2)
    - kubectl apply -f k8s/istio/my-app-v2.yaml

    # Traffic shifting: 10% на v2, 90% на v1
    - kubectl apply -f - <<EOF
      apiVersion: networking.istio.io/v1
      kind: VirtualService
      metadata:
        name: my-app
        namespace: prod
      spec:
        hosts:
          - my-app
        http:
          - route:
              - destination:
                  host: my-app
                  subset: v1
                weight: 90
              - destination:
                  host: my-app
                  subset: v2
                weight: 10
      EOF
  environment:
    name: production

verify_canary:
  stage: verify
  image: bitnami/kubectl:1.30
  script:
    # Проверка метрик через Kiali (требует доступности Kiali из Runner'а)
    - curl -s "http://kiali:20001/api/namespaces/prod/workloads/my-app" | jq .

    # Проверка ошибок через Prometheus
    - PROMETHEUS_POD=$(kubectl get pods -n istio-system -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}')
    - ERROR_RATE=$(kubectl exec -n istio-system -c prometheus "$PROMETHEUS_POD" -- \
      curl -s 'http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5..",app="my-app"}[5m])' | \
      jq '.data.result[0].value[1]' -r)

    - echo "$ERROR_RATE" | awk -v threshold=0.05 '{
      if ($1 > threshold) {
        print "Error rate too high: " $1
        exit 1
      } else {
        exit 0
      }
    }' || { kubectl delete -f k8s/istio/my-app-v2.yaml; exit 1; }
  environment:
    name: production

promote_canary:
  stage: promote
  image: bitnami/kubectl:1.30
  script:
    # Полный переход на v2 (100%)
    - kubectl apply -f - <<EOF
      apiVersion: networking.istio.io/v1
      kind: VirtualService
      metadata:
        name: my-app
        namespace: prod
      spec:
        hosts:
          - my-app
        http:
          - route:
              - destination:
                  host: my-app
                  subset: v2
      EOF
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 4: Валидация mTLS политик

```yaml
stages:
  - validate
  - test

validate_mtls:
  stage: validate
  image: bitnami/kubectl:1.30
  script:
    # Установка istioctl
    - curl -L https://istio.io/downloadIstio | sh -
    - export PATH=$PWD/istio-*/bin:$PATH

    # Проверка mTLS политик через анализ конфигурации
    - istioctl analyze -n prod

    # Проверка статуса mTLS для каждого сервиса
    - |
      for svc in $(kubectl get services -n prod -o jsonpath='{.items[*].metadata.name}'); do
        echo "Checking mTLS for $svc..."
        istioctl authn tls-check $svc.prod.svc.cluster.local || true
      done
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 5: Интеграция с Kiali для observability

> **Примечание:** Доступ к Kiali API по адресу `http://kiali:20001` возможен только если GitLab Runner выполняется в той же сети, что и кластер (например, при использовании Kubernetes executor с настроенной сетевой политикой). Для Shell executor требуется port-forward или exposed Ingress.

```yaml
stages:
  - deploy
  - verify

deploy:
  stage: deploy
  image: bitnami/kubectl:1.30
  script:
    - kubectl apply -f k8s/istio/
  environment:
    name: staging

verify_mesh:
  stage: verify
  image: bitnami/kubectl:1.30
  script:
    # Получение графа трафика из Kiali API
    - curl -s "http://kiali:20001/api/namespaces/staging/graph?namespaces=staging&graphType=app" | jq .

    # Проверка health сервисов
    - curl -s "http://kiali:20001/api/namespaces/staging/health" | jq .
  environment:
    name: staging
```

### Сценарий 6: Linkerd интеграция (lightweight alternative)

```yaml
stages:
  - validate
  - deploy

validate_linkerd:
  stage: validate
  image: bitnami/kubectl:1.30
  before_script:
    - curl -sL https://run.linkerd.io/install | sh
    - export PATH=$HOME/.linkerd2/bin:$PATH
  script:
    # Проверка конфигурации Linkerd
    - linkerd check --pre

    # Валидация сервисов
    - linkerd viz check
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

deploy_with_linkerd:
  stage: deploy
  image: bitnami/kubectl:1.30
  before_script:
    - curl -sL https://run.linkerd.io/install | sh
    - export PATH=$HOME/.linkerd2/bin:$PATH
  script:
    # Инъекция sidecar Linkerd
    - linkerd inject k8s/deployment.yaml | kubectl apply -f -

    # Проверка статуса
    - linkerd check
  environment:
    name: staging
```

## Устранение неполадок

| Ошибка / Симптом | Причина | Диагностика | Решение |
|:---|:---|:---|:---|
| `istioctl analyze` возвращает ошибки валидации | Некорректный API-версия ресурсов (`v1beta1` удален в Istio 1.22+) | `istioctl analyze manifests/` | Перевести манифесты на `networking.istio.io/v1`. |
| Sidecar proxy не инжектируется | Отсутствует label `istio-injection=enabled` в namespace или ресурс `Sidecar` блокирует инжекцию | `kubectl get namespace -n <ns> -o yaml`; `kubectl get sidecar -n <ns>` | Добавить label или настроить `Sidecar` ресурс. Проверить ResourceQuota. |
| mTLS не работает между сервисами | `PeerAuthentication` настроен в `PERMISSIVE` или `DISABLE`; отсутствует `DestinationRule` | `kubectl get peerauthentication -n <ns> -o yaml` | Установить `STRICT` mode при завершении миграции. |
| Kiali API недоступен из Runner'а | Runner находится за пределами кластерной сети; Service `kiali` не exposed | `curl -v http://kiali:20001` из пайплайна | Использовать Kubernetes executor сcluster DNS, настроить port-forward или exposed Ingress. |
| Canary трафик не переключается | `VirtualService` обновлен некорректно; поды не готовы (readiness probe) | `kubectl get virtualservice -n <ns> -o yaml`; `kubectl get pods -n <ns>` | Проверить веса в `VirtualService`; убедиться, что поды имеют статус `Ready`. |
| `linkerd check` падает с ошибкой сети | CNI плагин не установлен или сетевые политики блокируют трафик | `linkerd check` | Установить Linkerd CNI; проверить `NetworkPolicy`. |

## Лучшие практики

### Безопасность

1.  **mTLS по умолчанию**: Включите STRICT mTLS в default DestinationRule.
2.  **Authorization Policies**: Ограничьте доступ между сервисами.
3.  **Аудит через Kiali**: Регулярно проверяйте граф трафика.
4.  **Least Privilege**: Service accounts с минимальными правами.

### Организация

1.  **Namespace isolation**: Отдельные namespace для staging/production.
2.  **GitOps через GitLab**: Манифесты Istio/Linkerd в репозитории, деплой через пайплайн.
3.  **KAS для CI/CD**: Используйте GitLab Agent для Kubernetes для безопасного доступа к кластеру.
4.  **Canary через mesh**: Используйте VirtualService/DestinationRule для traffic shifting.

### Производительность

1.  **Sidecar resource limits**: Ограничьте CPU/memory для Envoy.
2.  **Gradual rollout**: Начинайте с 5-10% трафика.
3.  **Automatic mTLS**: Включите PERMISSIVE mode при миграции.

## Особенности и ограничения (Edge Cases)

### Лимиты

| Параметр | Лимит | Примечание |
|:---|:---|:---|
| Sidecar resource limits | 100m CPU, 128MB RAM | По умолчанию Envoy; корректируйте под нагрузку |
| Istio config size | 1 MB | На ресурс VirtualService |
| Количество services | 1000+ | Требуется оптимизация Istiod |

### Несовместимость

| Конфликт | Описание | Решение |
|:---|:---|:---|
| Istio + HostNetwork | Sidecar не работает с HostNetwork pods | Используйте standard pods |
| mTLS + legacy services | Сервисы без sidecar не поддерживают mTLS | PERMISSIVE mode при миграции |
| KAS + Istio | Конфликт портов/сетевых политик | Отдельные namespace для KAS и приложений |

### Технические ограничения

1.  **Gitaly в Kubernetes**: Gitaly Cluster (HA) не поддерживается в Kubernetes; требуется VM.
2.  **Windows pods**: Istio не поддерживает Windows-контейнеры.
3.  **HostNetwork**: Istio не работает с pods в HostNetwork.

## Дополнительная информация

*   **[Интеграция GitLab с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — GitLab Agent for Kubernetes (KAS).
*   **[Canary deployment](../../Deployment_Strategies/canary_deployment.md)** — прогрессивная раскатка.
*   **[Shadow deployment](../../Deployment_Strategies/shadow_deployment.md)** — тёмный запуск.
*   **[Развертывание и откат](../../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — механизмы автоматизации.
*   **[Istio Documentation](https://istio.io/latest/docs/)** — официальная документация.
*   **[Linkerd Documentation](https://linkerd.io/2/overview/)** — официальная документация.
*   **[Kiali](https://kiali.io/)** — визуализация и управление mesh.

> **Критичные изменения последних версий:**
>
> *   **19.0**: Улучшена интеграция KAS с Istio через dedicated namespace.
> *   **18.0**: Поддержка Istio 1.20+ в Kubernetes-интеграции.
> *   **17.0**: Внедрение GitLab Agent for Kubernetes (KAS) взамен legacy-интеграций.
