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

### Сценарий 4: Подключение приватных репозиториев (GitLab и Harbor)

Для реализации GitOps необходимо предоставить ArgoCD доступ к исходному коду (Git) и артефактам (Helm-чарты в Harbor).

#### Шаг 1: Подготовка доступа в GitLab
1. Создайте в GitLab пользователя `argocd` (или используйте существующего бота).
2. Выдайте права `Developer` (или `Reporter` для чтения) на группу или проект.
3. Сформируйте **Project Access Token** или **Group Access Token**:
   - **Scopes**: `read_api`, `read_repository`.
   - **Role**: `Developer`.

#### Шаг 2: Подключение GitLab к ArgoCD

**Вариант А: Через веб-интерфейс (HTTPS)**
1. **Settings** → **Repositories** → **Connect Repo**.
2. **Method**: `VIA HTTP/HTTPS`.
3. **Type**: `git`.
4. **Repo URL**: Адрес репозитория (внутренний адрес кластера предпочтительнее для ускорения трафика, например: `http://gitlab-webservice.gitlab.svc.cluster.local:8181/group/repo.git`).
5. **Username/Password**: Имя пользователя и созданный Token.

**Вариант Б: Через Kubernetes Secret (Declarative)**
Используйте этот метод для автоматизации настройки самого ArgoCD.

```bash
# 1. Создание секрета с учетными данными
kubectl -n argocd create secret generic gitlab-repo-creds \
  --from-literal=url=http://gitlab-webservice.gitlab.svc.cluster.local:8181/ \
  --from-literal=username=<GITLAB_USER> \
  --from-literal=password=<TOKEN>

# 2. Добавление метки, чтобы ArgoCD распознал секрет как репозиторий
kubectl -n argocd patch secret gitlab-repo-creds -p '{"metadata": {"labels": {"argocd.argoproj.io/secret-type": "repo-creds"}}}'
```

#### Шаг 3: Подключение Harbor (OCI-репозиторий)
ArgoCD поддерживает Helm-чарты, хранящиеся в Harbor как OCI-артефакты.

1. **Settings** → **Repositories** → **Connect Repo**.
2. **Method**: `VIA HTTP/HTTPS`.
3. **Type**: `oci`.
4. **Repo URL**: Адрес реестра (например, `harbor.example.com`).
5. **Project**: Название проекта в Harbor (например, `library`).
6. **Username/Password**: Учетные данные робот-аккаунта Harbor.

### Сценарий 5: Настройка доверенных TLS-сертификатов

Если GitLab или Harbor используют самоподписанные сертификаты (Internal CA), ArgoCD будет выдавать ошибку `x509: certificate signed by unknown authority`.

Для решения необходимо добавить корневой сертификат (Root CA) в доверенные:

```bash
# Создание или обновление ConfigMap с сертификатами
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=my-root.ca=/path/to/root-ca.crt \
  -o yaml --dry-run=client | kubectl apply -f -
```

После применения `argocd-server` и `argocd-repo-server` автоматически подхватят изменения.

### Сценарий 6: Настройка пользователей и RBAC

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
