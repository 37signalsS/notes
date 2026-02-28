# Rancher Pipelines

## Определения

**Rancher Pipelines** — это встроенный в Rancher механизм CI/CD, основанный на Jenkins, который позволяет автоматизировать процессы сборки, тестирования и развертывания приложений в Kubernetes-кластерах. Pipelines интегрирован непосредственно в интерфейс Rancher и не требует отдельного развертывания Jenkins.

## Базовые концепции

### Архитектура

Rancher Pipelines построен на базе Jenkins. При запуске Pipeline Rancher автоматически развертывает Jenkins Agent (slave pod) в кластере, который выполняет все этапы сборки. После завершения Jenkins Agent удаляется.

### Компоненты Pipeline

- **Stage (Этап)**: Логическая группа шагов (например, Build, Test, Deploy).
- **Step (Шаг)**: Конкретное действие внутри этапа (например, Clone, Build Image, Deploy YAML).
- **Trigger (Триггер)**: Событие, инициирующее запуск Pipeline (push в Git, ручной запуск).

### Поддерживаемые провайдеры

- **GitHub**: Наиболее распространенный вариант интеграции.
- **GitLab**: Также поддерживается.
- **Bitbucket**: Менее распространен.

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

1. **Ограничения**: При изменении только манифестов (без изменения кода) все равно выполняется полная пересборка образа — это известное ограничение Rancher Pipelines.
2. **Ресурсы**: Pipeline требует дополнительных ресурсов кластера для запуска Jenkins Agent.
3. **Webhooks**: При наличии внешнего доступа к кластеру возможна автоматическая активация Pipeline при push в репозиторий.

## Дополнительная информация

- Для доступа к приватным образам из Kubernetes необходимо использовать `imagePullSecrets`.
- Рекомендуется всегда указывать конкретные теги образов (не `latest`) для обеспечения воспроизводимости сборок.
- Настройка `imagePullPolicy: IfNotPresent` предотвращает автоматическое обновление образа без изменения тега, косвенно стимулируя использование версий.
