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
4. **Kustomize:** Кастомизация базовых манифестов (рекомендуется для Offline и сложных конфигураций)

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

### Сценарий 8: Offline-установка в закрытый контур (Air-gapped)

**Суть:** Скачивание манифестов и образов во внешней сети с последующим переносом и развертыванием в изолированном сегменте через приватный реестр (например, Harbor).

#### 1. Подготовка во внешней сети

```bash
# Определение актуальной версии
export ARGO_VERSION=$(curl --silent "https://api.github.com/repos/argoproj/argo-cd/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')

# Скачивание манифеста
curl -LO https://raw.githubusercontent.com/argoproj/argo-cd/$ARGO_VERSION/manifests/install.yaml

# Определение версий вспомогательных компонентов из манифеста
DEX_VERSION=$(grep 'dex:' install.yaml | awk -F: '{print $NF}')
REDIS_VERSION=$(grep 'redis:' install.yaml | awk -F: '{print $NF}')

# Скачивание и сохранение Docker-образов
docker pull quay.io/argoproj/argocd:$ARGO_VERSION
docker pull redis:$REDIS_VERSION
docker pull ghcr.io/dexidp/dex:$DEX_VERSION

docker save quay.io/argoproj/argocd:$ARGO_VERSION -o argocd.tar
docker save redis:$REDIS_VERSION -o redis.tar
docker save ghcr.io/dexidp/dex:$DEX_VERSION -o dex.tar
```

#### 2. Загрузка в приватный реестр (Harbor)

После переноса архивов в закрытый контур:

```bash
# Загрузка локально
docker load -i argocd.tar
docker load -i redis.tar
docker load -i dex.tar

# Настройка переменных (пример: v3.3.0)
export ARGO_VERSION=v3.3.0
export HARBOR=harbor.domain.local
export PROJECT=platform

# Тегирование и отправка в Harbor
docker tag quay.io/argoproj/argocd:$ARGO_VERSION $HARBOR/$PROJECT/argocd:$ARGO_VERSION
docker push $HARBOR/$PROJECT/argocd:$ARGO_VERSION

docker tag redis:$REDIS_VERSION $HARBOR/$PROJECT/redis:$REDIS_VERSION
docker push $HARBOR/$PROJECT/redis:$REDIS_VERSION

docker tag ghcr.io/dexidp/dex:$DEX_VERSION $HARBOR/$PROJECT/dex:$DEX_VERSION
docker push $HARBOR/$PROJECT/dex:$DEX_VERSION

# Замена путей к образам в манифесте
sed -i "s#quay.io/argoproj/argocd:$ARGO_VERSION#$HARBOR/$PROJECT/argocd:$ARGO_VERSION#g" install.yaml
sed -i "s#public.ecr.aws/docker/library/redis:$REDIS_VERSION#$HARBOR/$PROJECT/redis:$REDIS_VERSION#g" install.yaml
sed -i "s#ghcr.io/dexidp/dex:$DEX_VERSION#$HARBOR/$PROJECT/dex:$DEX_VERSION#g" install.yaml
```

#### 3. Настройка Kustomize для закрытого контура

Для работы в изолированном кластере часто требуется `imagePullSecrets` для всех компонентов.

**Структура каталогов:**

```text
argocd/
├── base/
│   ├── install.yaml
│   └── kustomization.yaml
└── overlays/
    ├── kustomization.yaml
    └── sa-patch.yaml
```

**base/kustomization.yaml:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - install.yaml
```

**overlays/sa-patch.yaml (Патч для ServiceAccounts/Deployments):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-server
spec:
  template:
    spec:
      imagePullSecrets:
        - name: cred-harbor
---
# ... аналогично пропатчить argocd-repo-server, argocd-applicationset-controller, 
# argocd-dex-server, argocd-redis, argocd-notifications-controller через Deployment
# и argocd-application-controller через StatefulSet
```

**overlays/kustomization.yaml:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: argocd
resources:
  - ../base
patchesStrategicMerge:
  - sa-patch.yaml
```

#### 4. Развертывание и настройка Insecure-режима

```bash
# Создание секрета для Harbor
kubectl -n argocd create secret docker-registry cred-harbor \
  --docker-server=harbor.domain.local \
  --docker-username='robot$platform+argocd-puller' \
  --docker-password='PASSWORD'

# Применение конфигурации
kubectl apply -k overlays/

# Включение insecure-режима (HTTP) через ConfigMap
kubectl -n argocd patch configmap argocd-cmd-params-cm \
  -p '{"data":{"server.insecure":"true"}}'

# Перезапуск сервера
kubectl -n argocd rollout restart deploy argocd-server
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

- [Обзор ArgoCD](./argocd_overview.md)
- [Синхронизация](./synchronization.md)
- [Уведомления](./argocd_notifications.md)
- [Официальная документация](https://argo-cd.readthedocs.io/en/stable/)
