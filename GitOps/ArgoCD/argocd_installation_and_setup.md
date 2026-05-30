# ArgoCD: Практическое руководство по установке и настройке

## Определения

**ArgoCD Installation** — процесс развёртывания компонентов ArgoCD в Kubernetes-кластере, включающий установку **CRD (Custom Resource Definition)**, сервисов и настройку механизмов доступа.

## Базовые концепции

### Компоненты ArgoCD

Архитектура ArgoCD состоит из нескольких сервисов, работающих как поды в Kubernetes:

| Компонент | Назначение |
| :--- | :--- |
| `argocd-server` | **API (Application Programming Interface)** и веб-интерфейс управления. |
| `argocd-repo-server` | Клонирование Git-репозиториев и рендеринг манифестов (Helm, Kustomize). |
| `argocd-application-controller` | Основной контроллер: сравнение состояний и выполнение синхронизации. |
| `argocd-dex-server` | Аутентификация через внешние поставщики личности (LDAP, SAML, OAuth). |
| `argocd-redis` | Кеширование состояния кластера и данных о приложениях. |
| `argocd-notifications-controller` | Отправка уведомлений о событиях жизненного цикла приложений. |
| `argocd-image-updater` | Автоматическое обновление тегов образов в Git (опциональный компонент). |

### Модели установки

1. **Declarative (рекомендуется для production):** Установка через GitOps, когда конфигурация самого ArgoCD хранится в Git.
2. **Imperative (для тестирования):** Быстрая установка через прямые команды `kubectl apply` или CLI.
3. **Helm-чарт:** Наиболее гибкий способ для настройки параметров через `values.yaml`.
4. **Kustomize:** Использование для кастомизации базовых манифестов в сложных или изолированных (offline) средах.

## Практические сценарии

### Сценарий 1: Быстрая установка для тестирования

**Требования:** Kubernetes 1.25+, `kubectl`, доступ к кластеру.

```bash
# 1. Создание namespace
kubectl create namespace argocd

# 2. Установка ArgoCD (используем --server-side для v3.x из-за размера CRD)
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 3. Проброс порта для доступа к UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# 4. Получение начального пароля admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```
Вход: `https://localhost:8080` (логин: `admin`).

### Сценарий 2: Установка ArgoCD CLI

```bash
# Скачивание бинарного файла (Linux amd64)
curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

# Авторизация
argocd login localhost:8080 --username admin
```

### Сценарий 3: Настройка доступа через Ingress с SSL

Для корректной работы через Ingress с SSL-терминацией необходимо отключить встроенный HTTPS в `argocd-server`.

```yaml
# Патч для Deployment argocd-server
spec:
  template:
    spec:
      containers:
      - name: argocd-server
        command: ["argocd-server", "--insecure"]
```

Пример Ingress-ресурса (nginx):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
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
  - hosts: ["argocd.example.com"]
    secretName: argocd-tls
```

### Сценарий 4: Добавление репозиториев и создание приложения

```bash
# Добавление приватного SSH репозитория
argocd repo add git@github.com:my-org/my-repo.git --ssh-private-key-path ~/.ssh/id_rsa

# Создание приложения через CLI
argocd app create my-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated --auto-prune --self-heal
```

### Сценарий 5: Настройка пользователей и RBAC

Конфигурация прав доступа выполняется через `ConfigMap` в неймспейсе `argocd`.

**1. Создание пользователя (`argocd-cm`):**
```yaml
data:
  accounts.myuser: apiKey,login
```

**2. Назначение роли (`argocd-rbac-cm`):**
```yaml
data:
  policy.csv: |
    g, myuser, role:admin
```

### Сценарий 6: Установка в изолированном контуре (Offline / Air-gapped)

Процесс включает предварительное скачивание образов и манифестов во внешней сети с последующим переносом в приватный реестр (например, Harbor).

1. **Загрузка образов в Harbor:**
   ```bash
   docker pull quay.io/argoproj/argocd:v3.3.0
   docker tag quay.io/argoproj/argocd:v3.3.0 harbor.local/platform/argocd:v3.3.0
   docker push harbor.local/platform/argocd:v3.3.0
   ```

2. **Адаптация манифестов:** Необходимо заменить пути к образам в `install.yaml` на адреса локального реестра и добавить `imagePullSecrets` через Kustomize патчи.

## Дополнительная информация

### Проверка состояния и диагностика

```bash
# Список приложений и их статусы
argocd app list

# Просмотр расхождений (diff)
argocd app diff <app-name>

# История и откат
argocd app history <app-name>
argocd app rollback <app-name> <id>
```

### Удаление

```bash
kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl delete namespace argocd
```

### См. также

- [ArgoCD: Обзор системы](./argocd_overview.md)
- [ArgoCD: Синхронизация и её политики](./synchronization.md)
- [ArgoCD Notifications: Настройка уведомлений](./argocd_notifications.md)
- [Официальная документация ArgoCD](https://argo-cd.readthedocs.io/)
