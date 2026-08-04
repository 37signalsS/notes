# Настройка динамических окружений (Review Apps) с Kubernetes

## Определения

**Review App** — временное, изолированное окружение, автоматически создаваемое для каждой ветки (Merge Request). Позволяет тестировать изменения в реальных условиях до слияния (Merge) в основную ветку.

**GitLab Agent for Kubernetes (KAS)** — основной механизм интеграции, обеспечивающий безопасный доступ пайплайнов к кластеру через **CI/CD Tunnel**. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**.

**Эфемерный Namespace (Ephemeral Namespace)** — временное пространство имен в Kubernetes, в которое разворачивается Review App. Оно должно быть удалено вместе с окружением.

**Wildcard DNS & Ingress** — конфигурация, позволяющая автоматически направлять трафик на динамические URL (например, `https://feature-123.review.example.com`).

## Основные концепции

Использование динамических окружений в Kubernetes строится на трех столпах:
1. **Изоляция:** Каждое MR-окружение разворачивается в свой Namespace или имеет уникальный префикс ресурсов.
2. **Динамическая маршрутизация:** Ingress-контроллер (Nginx, Traefik) обрабатывает запросы на основе `Host` заголовков, соответствующих именам веток.
3. **Автоматическая очистка:** Использование хуков `on_stop` и параметра `auto_stop_in` в GitLab CI для удаления ресурсов в кластере.

Общие принципы описаны в **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**.

## Практический сценарий: Развертывание через KAS и Helm

Современный подход исключает использование статических токенов `ClusterAdmin`. Доступ осуществляется через защищенный туннель Агента.

### Шаг 1: Подготовка инфраструктуры

Для корректной работы Review Apps в кластере должны быть настроены:
1. **Wildcard A-запись в DNS:** `*.review.example.com` указывает на IP Ingress-контроллера.
2. **Wildcard Сертификат:** Рекомендуется использовать **Cert-Manager** с DNS-01 challenge для получения валидных SSL-сертификатов на динамические поддомены.

### Шаг 2: Настройка доступа к кластеру

Убедитесь, что GitLab Agent установлен и пайплайн имеет к нему доступ.

```yaml
# .gitlab-ci.yml (фрагмент)
variables:
  KUBE_CONTEXT: "path/to/project:my-agent" # Путь к агенту
```

### Шаг 3: Конфигурация пайплайна

Использование Helm для деплоя позволяет легко управлять набором ресурсов и их удалением.

```yaml
stages:
  - build
  - deploy
  - cleanup

build_image:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG .
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG

deploy_review:
  stage: deploy
  image: alpine/k8s:1.30.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    # Деплой через Helm
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app
        --namespace $NAMESPACE
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
        --set image.tag=$CI_COMMIT_REF_SLUG
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop_review
    auto_stop_in: 1 day # Автоматическая очистка через 24 часа неактивности
  rules:
    - if: $CI_MERGE_REQUEST_ID

stop_review:
  stage: cleanup
  image: alpine/k8s:1.30.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    GIT_STRATEGY: none # Не скачивать репозиторий для очистки
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm uninstall review-$CI_COMMIT_REF_SLUG --namespace $NAMESPACE || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual # Позволяет вручную удалить среду из интерфейса MR
```

## Технические нюансы и ограничения

### Квоты ресурсов (Resource Quotas)
Динамические окружения могут быстро исчерпать ресурсы кластера. **Обязательно** устанавливайте `ResourceQuota` и `LimitRange` в namespaces для Review Apps:

```yaml
# k8s/quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: review-quota
spec:
  hard:
    requests.cpu: "500m"
    requests.memory: "1Gi"
    limits.cpu: "1000m"
    limits.memory: "2Gi"
```

### Хранение данных (PV/PVC)
Review Apps обычно являются **Stateless**. Если приложению нужна БД, рекомендуется:
1. Использовать эфемерную БД внутри пода (без Persistent Volume).
2. Или использовать общую Staging-БД с разделением схем по имени ветки (не рекомендуется из-за риска повреждения данных).

### Удаление Registry-образов
После удаления Review App и слияния MR, в Container Registry остаются временные образы. Настройте **Registry Cleanup Policy** в настройках проекта для удаления тегов, не соответствующих `main` или `tags`.

## Дополнительная информация

### Смотрите также

- **[Окружения и деплой в GitLab CI](../Concepts/environments_and_deployments.md)** — общие концепции и tiers.
- **[ArgoCD: Динамические окружения с Crossplane](../../../GitOps/ArgoCD/dynamic_environments_crossplane.md)** — продвинутый GitOps-подход с использованием ApplicationSet.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Агента и CI/CD Tunnel.
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом к секретам.
- **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)** — если Review App нужны секреты из Vault.
