# Настройка динамических окружений (Review Apps) с Kubernetes

## Определения

**Review App** — временное, изолированное окружение, автоматически создаваемое для каждой ветки (Merge Request). Позволяет тестировать изменения в реальных условиях до слияния (Merge) в основную ветку.

**GitLab Agent for Kubernetes (KAS)** — основной механизм интеграции, обеспечивающий безопасный доступ пайплайнов к кластеру через **CI/CD Tunnel**. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**.

**Эфемерный Namespace (Ephemeral Namespace)** — временное пространство имен в Kubernetes, в которое разворачивается Review App. Оно должно быть удалено вместе с окружением для предотвращения «засорения» кластера.

**Wildcard DNS & Ingress** — конфигурация, позволяющая автоматически направлять трафик на динамические URL (например, `https://feature-123.review.example.com`).

**Wildcard Certificate** — SSL/TLS сертификат, действующий для всех поддоменов определенного уровня (например, `*.review.example.com`). Обычно выпускается через Let's Encrypt с использованием DNS-01 challenge.

## Основные концепции

### Предварительные требования (Prerequisites)

Для работы Review Apps в Kubernetes-кластере должны быть установлены и настроены следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **GitLab** | 16.0+ | Поддержка `glrt-` токенов и KAS. |
| **GitLab Agent for Kubernetes (KAS)** | 1.0+ (встроен в GitLab 16.0+) | Защищенный туннель CI/CD Tunnel. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**. |
| **Ingress Controller** | nginx-ingress 1.9+ или traefik 3.0+ | Маршрутизация трафика по `Host` заголовкам для динамических URL. |
| **cert-manager** | 1.13+ | Автоматическое создание SSL/TLS сертификатов (Wildcard или per-MR). |
| **Helm** | 3.12+ | Управление наборами ресурсов (чартами) для Review Apps. |
| **kubectl** | 1.27+ | Управление кластером из задач пайплайна. |

#### Проверка готовности кластера

```bash
# Проверка наличия Ingress Controller
kubectl get pods -n ingress-nginx
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-xxx                1/1     Running   0          30d

# Проверка cert-manager
kubectl get pods -n cert-manager
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → cert-manager-xxx                           1/1     Running   0          30d
# → cert-manager-cainjector-xxx                1/1     Running   0          30d
# → cert-manager-webhook-xxx                   1/1     Running   0          30d

# Проверка GitLab Agent
kubectl get pods -n gitlab-agent
# → NAME                        READY   STATUS    RESTARTS   AGE
# → agentk-xxx                  1/1     Running   0          15d
```

### Четыре ключевых принципа

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

---

### Сценарий 2: Мульти-сервисное приложение (Frontend + Backend + DB)

Для реальных приложений часто нужно развернуть несколько компонентов одновременно.

```yaml
stages:
  - build
  - deploy
  - cleanup

# === Сборка образов ===
build_backend:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE/backend:$CI_COMMIT_REF_SLUG ./backend
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE/backend:$CI_COMMIT_REF_SLUG

build_frontend:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE/frontend:$CI_COMMIT_REF_SLUG ./frontend
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE/frontend:$CI_COMMIT_REF_SLUG

# === Деплой всех компонентов ===
deploy_review:
  stage: deploy
  image: alpine/k8s:1.30.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    RELEASE_NAME: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

    # Создание секрета для БД
    - |
      kubectl create secret generic review-db-credentials \
        --namespace $NAMESPACE \
        --from-literal=username=review_user \
        --from-literal=password=$(openssl rand -base64 16) \
        --dry-run=client -o yaml | kubectl apply -f -

    # Деплой через Helm
    - |
      helm upgrade --install $RELEASE_NAME ./charts/full-app \
        --namespace $NAMESPACE \
        --set backend.image.tag=$CI_COMMIT_REF_SLUG \
        --set frontend.image.tag=$CI_COMMIT_REF_SLUG \
        --set postgresql.auth.existingSecret=review-db-credentials \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com \
        --wait --timeout 5m

    # Ожидание готовности подов
    - kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --timeout=120s
    - kubectl wait --for=condition=ready pod -l app=frontend -n $NAMESPACE --timeout=120s
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID

# === Очистка ===
stop_review:
  stage: cleanup
  image: alpine/k8s:1.30.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    RELEASE_NAME: "review-$CI_COMMIT_REF_SLUG"
    GIT_STRATEGY: none
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm uninstall $RELEASE_NAME --namespace $NAMESPACE || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual
```

---

### Сценарий 3: Интеграция с HashiCorp Vault для секретов

Для безопасной передачи секретов в Review App без хранения их в переменных GitLab.

```yaml
deploy_with_vault:
  stage: deploy
  image: alpine/k8s:1.30.0
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    VAULT_ADDR: "https://vault.example.com"
    VAULT_ROLE: "gitlab-review-apps"
  before_script:
    # Аутентификация в Vault через OIDC
    - apk add --no-cache vault jq
    - |
      VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_ROLE \
        jwt=$VAULT_ID_TOKEN)
      export VAULT_TOKEN
    # Получение секретов
    - |
      DB_CREDS=$(vault kv get -format=json secret/review-apps/db-credentials)
      DB_USER=$(echo $DB_CREDS | jq -r '.data.data.username')
      DB_PASS=$(echo $DB_CREDS | jq -r '.data.data.password')
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - |
      kubectl create secret generic review-secrets \
        --namespace $NAMESPACE \
        --from-literal=db-user="$DB_USER" \
        --from-literal=db-password="$DB_PASS" \
        --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set secrets.existingSecret=review-secrets \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

Подробнее см. **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)**.

---

### Сценарий 4: Seed данных (Миграции и начальное заполнение)

Для тестирования Review App с реальными данными.

```yaml
deploy_review:
  stage: deploy
  image: alpine/k8s:1.30.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com

    # Ожидание готовности БД
    - |
      echo "Ожидание готовности PostgreSQL..."
      kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql \
        -n $NAMESPACE --timeout=180s

    # Запуск миграций
    - |
      kubectl exec -n $NAMESPACE deploy/my-app-backend -- \
        python manage.py migrate --no-input

    # Seed данных (только для review, НЕ для production)
    - |
      kubectl exec -n $NAMESPACE deploy/my-app-backend -- \
        python manage.py seed_review_data --clear
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

> **Важно:** Не используйте продакшн-данные для Review Apps. Используйте анонимизированные или синтетические данные.

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

---

## Проверка работоспособности (Validation)

После настройки Review Apps выполните следующие проверки:

### 1. Проверка доступа к кластеру

```bash
# Из задачи пайплайна или локально
kubectl config use-context $KUBE_CONTEXT
kubectl cluster-info
# → Kubernetes control plane is running at https://...
```

### 2. Проверка Wildcard DNS

```bash
# Проверка резолвинга
nslookup feature-branch.review.example.com
# → Address: #53
# → Non-authoritative answer:
# → Name:   feature-branch.review.example.com
# → Address: 203.0.113.50
```

### 3. Проверка SSL/TLS

```bash
# Проверка сертификата
openssl s_client -connect feature-branch.review.example.com:443 -servername feature-branch.review.example.com < /dev/null 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Jan  1 00:00:00 2025 GMT
# → notAfter=Apr  1 00:00:00 2025 GMT
```

### 4. Проверка развернутого приложения

```bash
# Просмотр подов в review namespace
kubectl get pods -n review-feature-branch
# → NAME                                READY   STATUS    RESTARTS   AGE
# → my-app-backend-xxx                  1/1     Running   0          5m
# → my-app-frontend-xxx                 1/1     Running   0          5m
# → postgresql-xxx                      1/1     Running   0          5m

# Просмотр сервисов
kubectl get svc -n review-feature-branch
# → NAME            TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
# → my-app-backend  ClusterIP   10.96.xxx.xxx  <none>        8000/TCP   5m
# → my-app-frontend ClusterIP   10.96.xxx.xxx  <none>        80/TCP     5m
```

### 5. Проверка Ingress

```bash
kubectl get ingress -n review-feature-branch
# → NAME             CLASS   HOSTS                                ADDRESS        PORTS     AGE
# → my-app-ingress   nginx   feature-branch.review.example.com    203.0.113.50   80, 443   5m
```

### 6. Проверка в GitLab UI

1. Перейдите в **Operate > Environments**.
2. Убедитесь, что окружение `review/feature-branch` отображается со статусом **Available**.
3. Нажмите на URL окружения — приложение должно открыться в браузере.

---

## Решение проблем (Troubleshooting)

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pod stuck in Pending** | Недостаточно ресурсов в кластере или не выполняются Node Affinity/Tolerations. | Проверьте `kubectl describe pod <pod> -n <ns>`. Убедитесь, что `ResourceQuota` не исчерпаны. |
| **Pod CrashLoopBackOff** | Приложение падает при запуске (ошибка конфигурации, отсутствие БД, неверный образ). | Проверьте логи: `kubectl logs <pod> -n <ns> --previous`. Убедитесь, что образ доступен и переменные заданы. |
| **Ingress не создает правила** | Отсутствует `ingress.class` или Ingress Controller не установлен. | Добавьте аннотацию `kubernetes.io/ingress.class: nginx` или убедитесь, что Ingress Controller запущен. |
| **SSL证书 не выпускается** | cert-manager не может пройти DNS-01 challenge (неверные DNS-записи или API-токен). | Проверьте логи cert-manager: `kubectl logs -n cert-manager deploy/cert-manager`. Убедитесь, что Wildcard DNS-запись настроена. |
| **GitLab Agent не подключается** | KAS не установлен или туннель заблокирован. | Проверьте статус агента: `kubectl get pods -n gitlab-agent`. Проверьте `config.yaml` агента. |
| **Helm install timeout** | Один из подов не становится Ready (长启动, неверные readiness probes). | Увеличьте `--timeout`. Проверьте `kubectl describe pod` для выявления причины. |
| **Namespace не удаляется** | Existìng Finalizers или ResourceQuota блокируют удаление. | Проверьте finalizers: `kubectl get ns <ns> -o yaml`. Временно удалите Quota перед очисткой. |
| **Review App доступна по HTTP, но не по HTTPS** | Wildcard сертификат не привязан к Ingress или отсутствует `tls` секция. | Добавьте `tls` секцию в Ingress и убедитесь, что Secret с сертификатом существует. |
| **Auto-stop не работает** | Отсутствует `on_stop` в `environment` или задача остановки не найдена. | Убедитесь, что `stop_review` существует в `.gitlab-ci.yml` и имеет `environment: action: stop`. |
| **Данные не seed'ятся** | Миграции выполняются до готовности БД или seed-скрипт отсутствует в образе. | Добавьте `kubectl wait` для БД перед миграциями. Проверьте, что seed-команда доступна в контейнере. |
| **ResourceQuota блокирует деплой** | Review App требует больше ресурсов, чем разрешено квотой. | Увеличьте `requests`/`limits` в `ResourceQuota` или уменьшите потребление приложения. |
| **Кэш Helm не обновляется** | `helm upgrade` использует устаревшую версию чарта. | Используйте `helm repo update` перед деплоем или `--force` для принудительного обновления. |

---

## Рекомендации по эксплуатации (Best Practices)

### Оптимизация ресурсов

1. **Всегда устанавливайте `ResourceQuota`** для namespaces Review Apps, чтобы предотвратить неконтролируемое потребление ресурсов.
2. **Отключайте HPA** для Review Apps или ограничивайте `maxReplicas: 1`.
3. **Используйте `auto_stop_in`** с разумными значениями (1-24 часа) для автоматической очистки неактивных окружений.
4. **Настройте Registry Cleanup Policy** для удаления временных образов после слияния MR.

### Безопасность

1. **Network Policies** — ограничьте доступ Review Apps к внутренней сети кластера.
2. **RBAC** — ограничьте права GitLab Agent только необходимыми namespace (`review-*`).
3. **Secrets** — используйте HashiCorp Vault или Kubernetes Secrets вместо переменных GitLab CI.
4. **Protected Runners** — используйте отдельные раннеры для Review Apps и Production.
5. **Audit Events** — мониторьте создание и удаление namespace через GitLab Audit Events.

### Мониторинг

1. **Grafana Dashboard** — создайте отдельный дашборд для Review Apps с фильтрацией по `review-*` namespace.
2. **Prometheus Alerting** — настройте алерты на длительное существование Review Apps (TTL > 24h).
3. **Cost Allocation** — используйте `namespace` labels для атрибуции затрат на команды/проекты.

### Очистка

1. **Ручная очистка** — периодически проверяйте `kubectl get namespaces -l purpose=review` и удаляйте забытые окружения.
2. **Автоматическая очистка** — используйте CronJob в кластере для удаления namespace старше N дней.
3. **Очистка Secret'ов** — убедитесь, что `stop_review` удаляет не только Helm-релиз, но и связанные Secrets.

---

## Дополнительная информация

### Смотрите также

- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка GitLab Agent и CI/CD Tunnel (SSoT для интеграции).
- **[Окружения и деплой в GitLab CI](../Concepts/environments_and_deployments.md)** — общие концепции, tiers, защищенные окружения.
- **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)** — управление секретами для Review Apps.
