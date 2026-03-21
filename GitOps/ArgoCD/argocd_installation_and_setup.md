# ArgoCD: Практическое руководство по установке и настройке

> **Актуальная версия:** v3.3 (февраль 2026). Для установки используются флаги `--server-side --force-conflicts` из-за размера CRD.

## Определения

**ArgoCD Installation** — процесс развёртывания компонентов ArgoCD в Kubernetes-кластере, включающий установку CRD, сервисов и настройку доступа.

## Базовые концепции

### Компоненты ArgoCD

| Компонент | Назначение |
| :--- | :--- |
| `argocd-server` | Веб-интерфейс и API |
| `argocd-repo-server` | Клонирование репозиториев, рендеринг манифестов |
| `argocd-application-controller` | Сравнение состояний, синхронизация |
| `argocd-dex-server` | Аутентификация через внешние IdP (LDAP, SAML, OAuth) |
| `argocd-redis` | Кеширование состояния и данных |
| `argocd-notifications-controller` | Отправка уведомлений (Slack, Telegram) |
| `argocd-image-updater` | Автоматическое обновление образов (опционально) |

### Модели установки

1. **Declarative (рекомендуется для production):** Применение манифестов через GitOps
2. **Imperative (для тестирования):** Установка через CLI/UI
3. **Helm-чарт:** Гибкая настройка через values.yaml
4. **Kustomize:** Кастомизация базовых манифестов

## Практические сценарии

### Сценарий 1: Быстрая установка для тестирования

**Требования:** Kubernetes 1.25+, kubectl, доступ к кластеру

```bash
# 1. Создание namespace
kubectl create namespace argocd

# 2. Установка ArgoCD (используем --server-side для v3.x)
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 3. Проверка статуса подов
kubectl get pods -n argocd

# 4. Проброс порта для доступа к UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# 5. Получение начального пароля admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# 6. Вход: https://localhost:8080 (admin / <пароль>)
```

### Сценарий 2: Установка ArgoCD CLI

```bash
# Linux (amd64)
curl -sSL -o argocd-linux-amd64 \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64

# Установка
chmod +x argocd-linux-amd64
sudo mv argocd-linux-amd64 /usr/local/bin/argocd

# Проверка версии
argocd version

# Логин (локально)
argocd login localhost:8080 --username admin

# Логин (через Ingress)
argocd login argocd.example.com --username admin --grpc-web
```

### Сценарий 3: Настройка доступа через Ingress с SSL

**Требования:** Ingress Controller (nginx), cert-manager (см. [Интеграция с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/ingress/scenarios.md))

```yaml
# argocd-server-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-passthrough: "false"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: nginx
  rules:
  - host: argocd.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              name: http
  tls:
  - hosts:
    - argocd.example.com
    secretName: argocd-tls
```

**Важно:** Для Ingress с SSL-терминацией отключите встроенный HTTPS в argocd-server:

```yaml
# Патч для argocd-server Deployment
command:
  - argocd-server
  - --insecure  # Отключает встроенный HTTPS
```

### Сценарий 4: Добавление Git-репозитория

```bash
# Публичный репозиторий
argocd repo add https://github.com/argoproj/argocd-example-apps.git

# Приватный репозиторий (SSH)
argocd repo add git@github.com:my-org/my-repo.git \
  --ssh-private-key-path ~/.ssh/id_rsa

# Приватный репозиторий (HTTPS с токеном)
argocd repo add https://github.com/my-org/my-repo.git \
  --username my-token --password <GITHUB_TOKEN>

# Проверка
argocd repo list
```

### Сценарий 5: Создание приложения

**Через CLI:**

```bash
argocd app create guestbook \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated \
  --auto-prune \
  --self-heal
```

**Через манифест:**

```yaml
# my-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: guestbook-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
```

### Сценарий 6: Настройка локального пользователя и RBAC

**1. Создание пользователя (argocd-cm ConfigMap):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # apiKey — создание токенов, login — вход через UI/CLI
  accounts.myuser: apiKey,login
```

**2. Назначение роли (argocd-rbac-cm ConfigMap):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    g, myuser, role:admin
    # role:admin — полный доступ
    # role:readonly — только чтение
```

**3. Установка пароля:**

```bash
# Для admin
argocd account update-password --account admin

# Для myuser
argocd account update-password --account myuser
```

### Сценарий 7: Настройка проекта (AppProject)

Проекты изолируют приложения и ограничивают доступ:

```yaml
# production-project.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-apps
  namespace: argocd
spec:
  description: "Производственные приложения"
  sourceRepos:
  - 'https://github.com/my-org/production-repo.git'
  destinations:
  - namespace: 'prod'
    server: 'https://kubernetes.default.svc'
  clusterResourceBlacklist:
  - group: 'rbac.authorization.k8s.io'
    kind: 'ClusterRoleBinding'
  roles:
  - name: developer
    description: "Разработчики"
    policies:
    - p, proj:production-apps:developer, applications, get, production-apps/*, allow
    - p, proj:production-apps:developer, applications, sync, production-apps/*, allow
```

## Дополнительная информация

### Удаление ArgoCD

```bash
# Удаление всех ресурсов ArgoCD
kubectl delete -n argocd --cascade=true -f \
  https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Удаление namespace
kubectl delete namespace argocd
```

### Проверка статуса

```bash
# Список приложений
argocd app list

# Детали приложения
argocd app get <app-name>

# История синхронизаций
argocd app history <app-name>

# Различия между Git и кластером
argocd app diff <app-name>
```

### Ссылки

- **[Обзор ArgoCD](./argocd_overview.md)**
- **[Синхронизация](./synchronization.md)**
- **[Уведомления](./argocd_notifications.md)**
- **[Официальная документация](https://argo-cd.readthedocs.io/en/stable/)**
