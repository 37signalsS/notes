# Argo CD: Практическое руководство по установке и настройке

## Определения

**Установка Argo CD** — процесс развёртывания компонентов системы GitOps в Kubernetes-кластере, включающий установку определений ресурсов (CRD), сервисов управления и механизмов контроля доступа.

**Высокая доступность (HA)** — режим работы Argo CD, при котором ключевые компоненты (API, Repo Server, Controller) дублируются для обеспечения отказоустойчивости и возможности горизонтального масштабирования.

**Server-Side Apply (SSA)** — механизм Kubernetes, необходимый для установки Argo CD v3.x, позволяющий корректно обрабатывать манифесты большого объема (особенно CRD).

## Базовые концепции

### Компоненты системы

Архитектура Argo CD состоит из нескольких независимых сервисов, работающих как поды:

| Компонент | Назначение |
| :--- | :--- |
| `argocd-server` | API и веб-интерфейс. Управляет аутентификацией и визуализацией. |
| `argocd-repo-server` | Клонирование Git-репозиториев и рендеринг манифестов (Helm, Kustomize). |
| `argocd-application-controller` | Основной контроллер: сравнение состояний и выполнение синхронизации. |
| `argocd-dex-server` | Сервис аутентификации через внешние поставщики (LDAP, SAML, OAuth). |
| `argocd-redis` | Кеширование состояния кластера и данных о приложениях. |
| `argocd-notifications-controller` | Отправка уведомлений (Slack, Email, Telegram). |
| `argocd-image-updater` | (Опционально) Автоматическое обновление тегов образов в Git. |

### Модели установки

1. **Declarative (GitOps):** Установка через Helm или Kustomize, когда конфигурация самого Argo CD хранится в Git.
2. **Imperative:** Быстрая установка через `kubectl apply`.
3. **HA (High Availability):** Режим с репликацией всех критических узлов и шардированием контроллера (рекомендуется для Production в 2026 году).

## Практические сценарии

### Сценарий 1: Установка Argo CD v3.x (HA-режим)

Для современных инсталляций v3.x использование Server-Side Apply является обязательным.

```bash
# 1. Создание пространства имен
kubectl create namespace argocd

# 2. Установка через HA-манифесты (рекомендуется для v3.x)
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/ha/install.yaml

# 3. Проброс порта для доступа к UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# 4. Получение начального пароля admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### Сценарий 2: Установка Argo CD CLI

```bash
# Скачивание бинарного файла (Linux amd64)
curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

# Авторизация
argocd login localhost:8080 --username admin
```

### Сценарий 3: Настройка доступа через Ingress с SSL

Для работы через Ingress с SSL-терминацией необходимо отключить встроенный HTTPS в `argocd-server`.

**1. Патч для Deployment (отключение TLS):**
```yaml
spec:
  template:
    spec:
      containers:
      - name: argocd-server
        command: ["argocd-server", "--insecure"]
```

**2. Пример Ingress-ресурса (Nginx):**
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

#### Шаг 1: Подготовка в GitLab
1. Создайте **Project Access Token** (или Group Access Token).
2. Выдайте права `Developer` (или `Reporter`).
3. Scopes: `read_api`, `read_repository`.

#### Шаг 2: Подключение GitLab к Argo CD

**Вариант А: Через HTTPS (Declarative Secret)**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-repo-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  url: https://gitlab.example.com/group/repo.git
  username: "gitlab-bot"
  password: "<access_token>"
```

**Вариант Б: Через CLI**
```bash
argocd repo add https://gitlab.example.com/group/repo.git --username <user> --password <token>
```

#### Шаг 3: Подключение Harbor (OCI-репозиторий)
Argo CD поддерживает Helm-чарты как OCI-артефакты.

1. Перейдите в **Settings** → **Repositories** → **Connect Repo**.
2. Method: `VIA HTTP/HTTPS`, Type: `oci`.
3. Repo URL: `harbor.example.com`, Project: `library`.
4. Введите данные робот-аккаунта Harbor.

### Сценарий 5: Настройка доверенных TLS-сертификатов (Internal CA)

Если GitLab/Harbor используют самоподписанные сертификаты, добавьте корневой сертификат в доверенные:

```bash
# Создание ConfigMap с сертификатом
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=internal-root.ca=/path/to/root-ca.crt \
  -o yaml --dry-run=client | kubectl apply -f -
```

### Сценарий 6: Масштабирование и шардирование (v3.x)

Если количество приложений превышает 1000, используйте шардирование контроллера.

**Настройка в `argocd-cmd-params-cm`:**
```yaml
data:
  controller.sharding.algorithm: round-robin
  controller.replicas: "2"
```

### Сценарий 7: Установка в изолированном контуре (Offline)

1. Перенос образов в локальный реестр:
   ```bash
   docker pull quay.io/argoproj/argocd:v3.4.4
   docker tag quay.io/argoproj/argocd:v3.4.4 harbor.local/argocd:v3.4.4
   docker push harbor.local/argocd:v3.4.4
   ```
2. Обновление манифестов: Замените пути к образам и добавьте `imagePullSecrets` через патчи Kustomize.

## Технический справочник

### Рекомендации по ресурсам (HA-режим)

| Компонент | CPU (Min/Max) | Memory (Min/Max) | Реплики |
| :--- | :--- | :--- | :--- |
| `argocd-application-controller` | 1 / 2 | 2Gi / 8Gi | 2+ (шардинг) |
| `argocd-repo-server` | 0.5 / 1 | 1Gi / 4Gi | 3+ |
| `argocd-server` | 0.2 / 0.5 | 512Mi / 1Gi | 3+ |
| `argocd-redis` | 0.5 / 1 | 1Gi / 2Gi | 3 (Sentinel) |

### Диагностика и обслуживание

```bash
# Просмотр расхождений (diff)
argocd app diff <app-name>

# Статус контроллера и шардов
argocd admin cluster stats

# Проверка mTLS (v3.5+)
# Включите global.tls.enabled=true в Helm для шифрования между компонентами
```

### См. также

- [Argo CD: Обзор системы](./argocd_overview.md)
- [Argo CD: Синхронизация и её политики](./synchronization.md)
- [Argo CD: Интеграция с Vault](./argocd_vault_integration.md)
- [Официальная документация (HA)](https://argo-cd.readthedocs.io/en/stable/operator-manual/high-availability/)
