# Руководство: Настройка среды разработки на базе K3s

В данном руководстве описывается процесс создания изолированной среды разработки внутри однонодового кластера Kubernetes (K3s). Подход основан на использовании кастомных Docker-контейнеров в качестве рабочего пространства, что является нетрадиционным, но гибким решением.

**Цель**: Развернуть полноценную среду разработки, включая CI/CD и реестр образов, минимизируя "загрязнение" основной хост-системы, на которой запущен K3s.

**Ключевые компоненты**:
- **Платформа**: K3s
- **CI/CD**: GitLab
- **Реестр контейнеров**: Harbor
- **Инструменты сборки**: Kaniko
- **Управление сертификатами**: Cert-manager

---
## 1. Корректировка конфигурации GitLab

При развертывании GitLab через Helm-чарт в связке с внешним реестром (Harbor) может возникнуть проблема, когда внутренние сервисы GitLab некорректно пытаются использовать встроенный реестр, даже если он отключен.

**Решение**: Необходимо явно отключить реестр в двух секциях файла `values.yaml` для Helm-чарта GitLab.

```yaml
# gitlab-values.yaml

global:
  registry:
    enabled: false
...
registry:
  enabled: false
...
```

После внесения изменений необходимо применить конфигурацию повторно с помощью `helm upgrade`.

---
## 2. Настройка GitLab для работы с Harbor

Для интеграции CI/CD-пайплайнов с внешним реестром Harbor необходимо централизованно задать параметры доступа.

#### 2.1. Создание группы и переменных

1.  **Создайте корневую группу** в GitLab (например, `dev`). Это позволит изолировать переменные и проекты.
2.  **Добавьте переменные CI/CD** на уровне группы (`Settings -> CI/CD -> Variables`). Это избавит от необходимости прописывать их в каждом проекте.

| Ключ | Значение | Тип | Описание |
|:---|:---|:---:|:---|
| `dev.registry` | `harbor.your-domain.com` | `Var` | Адрес вашего Harbor-инстанса. |
| `dev.registry-user` | `admin` | `Var` | Имя пользователя для push-доступа в Harbor. |
| `dev.registry-password`| `YourHarborPassword` | `Var`| Пароль пользователя. **Рекомендуется** делать маскированным (`Masked`). |
| `dev.se` | (содержимое `ca.crt`) | `File`| Корневой сертификат вашего CA. Используется для доверия к Harbor. |

> **Примечание**: Переменная `dev.se` типа `File` создается для удобной передачи CA-сертификата в пайплайны. GitLab Runner сохранит ее содержимое во временный файл, путь к которому будет доступен в переменной окружения `dev.se`. Источником сертификата обычно является секрет, созданный `cert-manager` (например, `dfca` в неймспейсе `cert-manager`).

---
## 3. Создание вспомогательного образа `kubeutils`

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

---
## 4. Создание рабочего контейнера с SSH

Это нетрадиционный подход, но он позволяет получить изолированное рабочее пространство внутри кластера.

#### Dockerfile (`dev-container/Dockerfile`)

```dockerfile
FROM ubuntu:24.04

# Устанавливаем SSH-сервер и базовые утилиты
RUN apt-get update && apt-get install -y --no-install-recommends 
    openssh-server 
    sudo 
    git 
    curl 
    && rm -rf /var/lib/apt/lists/*

# Копируем и настраиваем скрипт инициализации
COPY init-container.sh /init-container.sh
RUN chmod +x /init-container.sh

# Открываем порт для SSH
EXPOSE 22

# Скрипт инициализации будет запущен при старте контейнера
ENTRYPOINT ["/init-container.sh"]
```

#### Скрипт инициализации (`dev-container/init-container.sh`)

Скрипт создает пользователя и группу при старте контейнера, используя переменные окружения, а также добавляет CA-сертификат в доверенные.

```bash
#!/bin/sh
set -e

# Переменные окружения, передаваемые при запуске пода
USER_NAME=${DEV_USER_NAME:-user}
GROUP_NAME=${DEV_GROUP_NAME:-user}
USER_ID=${DEV_USER_ID:-1000}
GROUP_ID=${DEV_GROUP_ID:-1000}

# Создание группы и пользователя
addgroup -g ${GROUP_ID} ${GROUP_NAME}
adduser -u ${USER_ID} -G ${GROUP_NAME} -s /bin/bash -D ${USER_NAME}
echo "${USER_NAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Добавление CA в доверенные, если он был смонтирован в контейнер
CA_CERT_PATH="/etc/ssl/certs/dfca.crt"
if [ -f "$CA_CERT_PATH" ]; then
    cp "$CA_CERT_PATH" /usr/local/share/ca-certificates/
    update-ca-certificates
fi

# Запуск SSH-демона
/usr/sbin/sshd -D
```

Развертывание этого контейнера в кластере будет рассмотрено в отдельном руководстве по созданию соответствующего Helm-чарта. Он будет запускать контейнер как `Deployment` и передавать в него переменные окружения и CA-сертификат через `ConfigMap`.
