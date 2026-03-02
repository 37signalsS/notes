## 4. Создание вспомогательного образа `kubeutils`

Для выполнения различных задач в пайплайнах и для ручной работы с кластером полезно иметь вспомогательный образ с набором необходимых утилит.

**Состав образа**:
- **`kubectl`**: Основной инструмент для взаимодействия с Kubernetes API.
- **`helm`**: Менеджер пакетов для Kubernetes.
- **`reg-client`**: Утилита для работы с реестрами контейнеров. Полезна для ручных манипуляций с образами.
- **`kubeconform`**: Валидатор манифестов Kubernetes для проверки их соответствия схемам API.

#### Dockerfile (`kubeutils/Dockerfile`)

```dockerfile
# Версии утилит передаются как build-args
ARG KUBE_VERSION=v1.28.6
ARG HELM_VERSION=v3.13.0
ARG REGCLIENT_VERSION=v0.5.6
ARG KUBECONFORM_VERSION=v0.6.4

FROM alpine:3.18

# Установка kubectl
RUN wget -q "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/amd64/kubectl" -O /usr/local/bin/kubectl && 
    chmod +x /usr/local/bin/kubectl

# Установка Helm
RUN wget -q "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" -O - | tar -xzO linux-amd64/helm > /usr/local/bin/helm && 
    chmod +x /usr/local/bin/helm

# Установка regclient
RUN wget -q "https://github.com/regclient/regclient/releases/download/${REGCLIENT_VERSION}/regctl-linux-amd64" -O /usr/local/bin/regctl && 
    chmod +x /usr/local/bin/regctl

# Установка kubeconform
RUN wget -q "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" -O - | tar -xzO kubeconform > /usr/local/bin/kubeconform && 
    chmod +x /usr/local/bin/kubeconform

# Проверка версий
RUN kubectl version --client && helm version && regctl version && kubeconform -v
```

#### GitLab CI (`.gitlab-ci.yml`)

Сборка осуществляется с помощью Kaniko. Пайплайн запускается вручную.

```yaml
build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.9.0-debug
    entrypoint: [""]
  tags:
    - global # Тег вашего GitLab Runner
  script:
    # 1. Подготовка аутентификации для Kaniko
    - echo "{"auths":{"$dev.registry":{"username":"$dev.registry-user","password":"$dev.registry-password"}}}" > /kaniko/.docker/config.json
    # 2. Сборка и push образа
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination "$dev.registry/library/kube-utils:${CI_COMMIT_TAG:-$KUBE_VERSION}" # Тег по версии kubectl
      --build-arg KUBE_VERSION=${KUBE_VERSION}
      --build-arg HELM_VERSION=${HELM_VERSION}
      --registry-certificate $dev.se # Передача CA-сертификата для Harbor
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
  variables:
    KUBE_VERSION: "v1.28.6"
    HELM_VERSION: "v3.13.0"
```
