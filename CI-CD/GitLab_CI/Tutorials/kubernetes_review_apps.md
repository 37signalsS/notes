# Настройка динамических окружений (Review Apps) с Kubernetes

## Определения

**Review App** — временное, изолированное окружение, автоматически создаваемое для каждой ветки (Merge Request). Позволяет тестировать изменения в реальных условиях до слияния (Merge) в основную ветку.

**GitLab Agent for Kubernetes (KAS)** — основной механизм интеграции, обеспечивающий безопасный доступ пайплайнов к кластеру через **CI/CD Tunnel**. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**.

**Эфемерный Namespace (Ephemeral Namespace)** — временное пространство имен в Kubernetes, в которое разворачивается Review App. Оно должно быть удалено вместе с окружением для предотвращения «засорения» кластера.

**Wildcard DNS & Ingress** — конфигурация, позволяющая автоматически направлять трафик на динамические URL (например, `https://feature-123.review.example.com`).

**Wildcard Certificate** — SSL/TLS сертификат, действующий для всех поддоменов определенного уровня (например, `*.review.example.com`). Обычно выпускается через Let's Encrypt с использованием DNS-01 challenge.

## Основные концепции

Использование динамических окружений в Kubernetes строится на четырех ключевых принципах:

1.  **Изоляция (Isolation):** Каждое MR-окружение разворачивается в свой Namespace. Это обеспечивает полную изоляцию ресурсов (Pods, Services, Secrets) и позволяет применять специфичные квоты и политики безопасности.
2.  **Динамическая маршрутизация (Dynamic Routing):** Ingress-контроллер (Nginx, Traefik, Istio) автоматически создает правила маршрутизации на основе `Host` заголовков.
3.  **Автоматическое управление жизненным циклом (Lifecycle Management):** Использование хуков `on_stop` и параметра `auto_stop_in` в GitLab CI для автоматического удаления ресурсов в кластере при закрытии MR или неактивности.
4.  **Безопасность (Security):** Доступ к кластеру осуществляется через GitLab Agent, что исключает передачу статических `kubeconfig` файлов и токенов в переменные окружения пайплайна.

Общие принципы описаны в **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**.

## Практический сценарий: Развертывание через KAS и Helm

Современный подход исключает использование статических токенов `ClusterAdmin`. Доступ осуществляется через защищенный туннель Агента.

### Шаг 1: Подготовка инфраструктуры

Для корректной работы Review Apps в кластере должны быть настроены компоненты автоматизации трафика.

#### 1. Wildcard DNS
Настройте A-запись в вашем DNS-провайдере:
- **Name:** `*.review.example.com`
- **Value:** Внешний IP вашего LoadBalancer (Ingress Controller).

#### 2. Cert-Manager и DNS-01 Challenge
Для динамических окружений нельзя использовать HTTP-01 challenge, так как Ingress для каждого MR создается «на лету». Используйте **DNS-01 challenge**.

Пример ClusterIssuer для Cloudflare:
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-dns01-account-key
    solvers:
    - dns01:
        cloudflare:
          email: admin@example.com
          apiTokenSecretRef:
            name: cloudflare-api-token-secret
            key: api-token
```

#### 3. Wildcard Certificate (пре-генерация)
Рекомендуется создать один Wildcard сертификат в общем пространстве имен (например, `istio-system` или `nginx-ingress`) и использовать его для всех Review Apps, либо настроить Cert-Manager на создание сертификата для каждого Ingress.

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

## Безопасность и изоляция

Для обеспечения безопасности кластера при использовании Review Apps необходимо следовать принципу наименьших привилегий.

### 1. Сетевая изоляция (Network Policies)
Review Apps часто содержат экспериментальный код. Ограничьте их доступ к внутренней сети кластера, чтобы предотвратить обращение к Production или Staging базам данных.

```yaml
# k8s/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-internal-only
  namespace: review-feature-branch
spec:
  podSelector: {} # Применить ко всем подам в namespace
  policyTypes:
  - Ingress
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system # Разрешить DNS
    ports:
    - protocol: UDP
      port: 53
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8 # Запретить доступ к внутренним подсетям (пример)
```

### 2. RBAC для GitLab Agent
Агент должен иметь доступ только к определенным пространствам имен. В конфигурации агента (`config.yaml`) ограничьте область действия:

```yaml
user_access:
  access_as:
    agent: {}
  projects:
  - id: path/to/project
    default_namespace: review-*
```

## Работа с базами данных

Review Apps по умолчанию должны быть **Stateless**. Если приложению требуется БД, используйте один из подходов:

### 1. Эфемерная БД в составе Helm-чарта
Самый надежный способ изоляции. БД разворачивается вместе с приложением и удаляется при очистке.

```yaml
# charts/my-app/values.yaml
postgresql:
  enabled: true
  auth:
    database: myapp_db
    username: user
  persistence:
    enabled: false # Данные не сохраняются после удаления
```

### 2. Общая база данных (Shared Database)
Использование одного инстанса БД (например, в Staging) с созданием уникальных схем/логических БД для каждого MR.
- **Плюсы:** Экономия ресурсов кластера.
- **Минусы:** Сложность очистки (нужны дополнительные скрипты для DROP DATABASE) и риск влияния Review Apps на стабильность Staging БД.

## Отладка и мониторинг

### Просмотр логов
Для отладки Review Apps используйте `kubectl` через туннель агента или интерфейс GitLab (Environments -> Review App -> Terminal).

```bash
# Просмотр логов пода в динамическом namespace
kubectl logs -f -l app=my-app -n review-$CI_COMMIT_REF_SLUG
```

### Мониторинг ресурсов
В Grafana рекомендуется создать отдельный Dashboard для Review Apps, отфильтрованный по префиксу Namespace `review-*`. Это поможет выявить «зависшие» окружения, которые потребляют ресурсы.

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

### Горизонтальное масштабирование (HPA)
В Review Apps рекомендуется **отключать** HPA или устанавливать минимальные лимиты (например, `maxReplicas: 1`), чтобы избежать неконтролируемого роста потребления ресурсов при тестах.

### Graceful Shutdown
Убедитесь, что ваше приложение корректно обрабатывает `SIGTERM`. При удалении Namespace Kubernetes завершает все поды. Если приложение не успеет закрыть соединения, это может привести к ошибкам в логах или повреждению данных в общих БД.

### Удаление Registry-образов
После удаления Review App и слияния MR, в Container Registry остаются временные образы. Настройте **Registry Cleanup Policy** в настройках проекта для удаления тегов, не соответствующих `main` или `tags`.

## Дополнительная информация

### Смотрите также

- **[Окружения и деплой в GitLab CI](../Concepts/environments_and_deployments.md)** — общие концепции и tiers.
- **[ArgoCD: Динамические окружения с Crossplane](../../../GitOps/ArgoCD/dynamic_environments_crossplane.md)** — продвинутый GitOps-подход с использованием ApplicationSet.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Агента и CI/CD Tunnel.
- **[Переменные и секреты в GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — управление доступом к секретам.
- **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)** — если Review App нужны секреты из Vault.
