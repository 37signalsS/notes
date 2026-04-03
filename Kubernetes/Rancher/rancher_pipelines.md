# Rancher Pipelines

## Определения

**Rancher Pipelines** — встроенный в Rancher механизм CI/CD на базе Jenkins, позволяющий автоматизировать сборку, тестирование и развёртывание приложений в Kubernetes-кластерах. Интегрирован в Rancher UI, не требует отдельного развёртывания Jenkins.

> **Важно:** Rancher Pipelines **деприкейтрован** начиная с Rancher v2.5. Рекомендуемая замена — Fleet (GitOps-подход, см. [GitOps Overview](../../../GitOps/GitOps_overview.md)) или внешние CI/CD-системы (GitLab CI, ArgoCD). Функциональность может быть удалена в будущих версиях Rancher.

## Базовые концепции

### Архитектура

Rancher Pipelines использует Jenkins. При запуске Pipeline Rancher разворачивает Jenkins Agent (slave pod) в кластере, который выполняет этапы сборки и удаляется после завершения.

### Компоненты Pipeline

- **Stage**: Логическая группа шагов (Build, Test, Deploy).
- **Step**: Конкретное действие внутри этапа (Clone, Build Image, Deploy YAML).
- **Trigger**: Событие запуска — push в Git или ручной запуск.

### Поддерживаемые провайдеры

- **GitHub** — наиболее распространённый вариант.
- **GitLab** — поддерживается.
- **Bitbucket** — менее распространён.

## Практические сценарии

### Настройка Rancher Pipelines

#### 1. Подготовка проекта и namespace

Создайте проект в Rancher и namespace для приложения. Рекомендуется создать namespace вручную с осмысленным именем, чтобы избежать автоматически сгенерированных Rancher имен.

#### 2. Настройка Docker Hub credentials

Для публикации образов в Docker Hub необходимо создать Registry Credential:

1. Перейдите в проект → Resources → Secrets → Registry Credentials
2. Добавьте новый registry
3. Выберите тип "Docker Hub"
4. Укажите username и password

#### 3. Подключение GitHub репозитория

1. Перейдите в проект → Tools → Pipelines
2. Выберите GitHub в качестве провайдера
3. Зарегистрируйте OAuth приложение в GitHub
4. Введите Client ID и Client Secret
5. Выберите репозитории для Pipeline

#### 4. Конфигурация Pipeline

Pipeline может быть настроен через визуальный интерфейс Rancher или через файл `.rancher-pipeline.yml` в репозитории.

**Пример файла `.rancher-pipeline.yml`:**

```yaml
stages:
  - name: Build
    steps:
      - publishImageConfig:
          dockerfilePath: ./Dockerfile
          imageName: username/repo:tag
          pushRemote: true
          registry: dockerhub
  - name: Deploy
    steps:
      - applyYamlConfig:
          path: ./deployment.yaml
      - applyYamlConfig:
          path: ./service.yaml
```

#### 5. Основные шаги Pipeline

- **Build and Publish Image**: Сборка Docker-образа из Dockerfile и пуш в registry.
- **Deploy YAML**: Применение Kubernetes-манифестов (Deployment, Service и др.).
- **Run Script**: Выполнение произвольных команд в pipeline.

### Пример Dockerfile для приложения Go

Пример multi-stage сборки (подробнее: [Build Optimization](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)):

```dockerfile
FROM golang:1.21-alpine AS builder
WORKDIR /build
COPY . .
RUN go build -o app ./cmd/main

FROM alpine:latest
WORKDIR /app
COPY --from=builder /build/app .
EXPOSE 9000
CMD ["./app"]
```

### Пример Deployment

Для доступа к приватному registry используется [imagePullSecrets](../../../Kubernetes/Base/secrets/creating_secrets.md#docker-registry-secret):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: mynamespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: myapp
        image: username/myapp:001
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 9000
```

### Особенности работы

1. **Ограничения**: При изменении только манифестов (без изменения кода) выполняется полная пересборка образа.
2. **Ресурсы**: Pipeline требует дополнительных ресурсов кластера для Jenkins Agent.
3. **Webhooks**: Автоматическая активация Pipeline при push в репозиторий (требует внешнего доступа к кластеру).

## Дополнительная информация

### Актуальность версий

> **Внимание:** Rancher Pipelines (Jenkins-based) **деприкейтрован** с Rancher v2.5. Рекомендуемая замена — Fleet (GitOps, см. [GitOps Overview](../../../GitOps/GitOps_overview.md)) или внешние CI/CD-системы (GitLab CI, GitHub Actions, Jenkins).

| Компонент | Указанная информация | Статус | Рекомендация |
|-----------|---------------------|--------|--------------|
| **Rancher Pipelines** | Jenkins-based | ⚠️ Deprecated (v2.5+) | Мигрировать на Fleet/GitOps |
| **Fleet** | GitOps-преемник | ✅ Актуален | [GitOps Overview](../../../GitOps/GitOps_overview.md) |
| **Jenkins Agent** | Динамические pods | ✅ Работает | Legacy-развёртывания |

### Best Practices

- Для доступа к приватным образам используйте [imagePullSecrets](../../../Kubernetes/Base/secrets/creating_secrets.md#docker-registry-secret).
- Указывайте конкретные теги образов (не `latest`) для воспроизводимости сборок (подробнее: [Build Optimization](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)).
- `imagePullPolicy: IfNotPresent` предотвращает автоматическое обновление образа без изменения тега.

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
