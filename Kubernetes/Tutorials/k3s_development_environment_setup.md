# Руководство: Настройка среды разработки на базе K3s

## 1. Обзор и Концепция

Данное руководство описывает процесс создания полноценной, изолированной среды разработки на базе одного сервера. Цель — построить самодостаточную лабораторию для изучения DevOps-практик и написания кода, минимизируя при этом "загрязнение" хост-системы лишними инструментами и зависимостями.

### 1.1. Архитектура

В основе решения лежит один сервер (физический или виртуальный), на котором развернут легковесный дистрибутив Kubernetes — **K3s**. Все вспомогательные сервисы, необходимые для разработки, запускаются внутри этого кластера в виде контейнеров.

**Ключевые компоненты стека:**
- **Платформа**: [K3s](../kubernetes_overview.md) — будет использован вместо "ванильного" Kubernetes для простоты развертывания на одном узле.
  - **Ingress Controller**: Стандартный Traefik будет заменен на более распространенный [NGINX Ingress Controller](../../Networking/Ingress/overview.md).
  - **Хранилище**: Будет использоваться встроенный [Local Path Provisioner](../Storage/local-path-provisioner.md) с оговоркой, что он не поддерживает `ReadWriteMany` и подходит только для однонодовых инсталляций.
- **CI/CD**: [GitLab](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) — для хранения исходного кода и автоматизации CI/CD пайплайнов.
- **Развертывание**: [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) — для реализации GitOps-подхода к развертыванию приложений.
- **Реестр контейнеров**: [Harbor](../../../Docker/Docker_registries/Harbor/overview.md) — в качестве основного хранилища Docker-образов и Helm-чартов. Выбран вместо встроенного реестра GitLab из-за большей гибкости.
- **S3 Хранилище**: [Minio](https://min.io/) — для объектного хранения артефактов.
- **База данных**: [PostgreSQL](../../../Databases/PostgreSQL/postgresql_overview.md) — в качестве основной реляционной СУБД.

### 1.2. Рабочий процесс "Dev-контейнер"

Ключевая особенность этой среды — отказ от установки языков программирования (Go, Python, Java) и других инструментов напрямую на хост-систему или на локальные машины разработчиков.

Вместо этого предлагается следующий рабочий процесс:
1. **Создание "Dev-контейнера"**: Специальный Docker-образ на базе Ubuntu, внутри которого установлен SSH-сервер и все необходимые для разработки инструменты (компиляторы, SDK и т.д.).
2. **Развертывание в K3s**: Этот контейнер запускается в кластере как обычный `Deployment`.
3. **Персистентность кода**: Домашняя директория пользователя (`/home/user`) с хост-машины монтируется внутрь Dev-контейнера с помощью `hostPath` Volume. Весь код и рабочие файлы хранятся на хосте и переживают перезапуски контейнера.
4. **Удаленная разработка**: Разработчик подключается к этому контейнеру напрямую из своего локального редактора (например, **VS Code** через расширение **Remote - SSH**). Локальная машина, таким образом, выступает в роли "тонкого клиента", а вся работа (компиляция, запуск, отладка) происходит внутри изолированного контейнера в кластере.

Этот подход обеспечивает унифицированную и воспроизводимую среду разработки, не зависящую от операционной системы на ноутбуке разработчика.

---
## 2. Корректировка конфигурации GitLab

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
## 3. Настройка GitLab для работы с Harbor

Для интеграции CI/CD-пайплайнов с внешним реестром Harbor необходимо централизованно задать параметры доступа.

#### 3.1. Создание группы и переменных

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

---
## 5. Создание рабочего контейнера с SSH

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

---
## 6. Развертывание Dev-контейнера с помощью Helm

Продолжая предыдущий раздел, где был создан образ `dev-container`, здесь мы рассмотрим его развертывание в кластере с помощью Helm-чарта. Чарт будет управлять `Deployment`, `Service`, `ConfigMap` и персистентностью домашней директории.

### 6.1. Структура Helm-чарта

Чарт состоит из стандартных шаблонов. Ключевые аспекты его реализации описаны ниже.

#### `deployment.yaml` — Основная логика

`Deployment` запускает под с двумя контейнерами: `initContainer` для подготовки и основной `dev-container`.

- **`initContainer`**:
  - **Задача**: Подготовить окружение для SSH-доступа по ключу.
  - **Логика**: При первом запуске скрипт проверяет наличие директории `.ssh` в домашнем каталоге пользователя. Если ее нет, он создает `.ssh/authorized_keys`, устанавливает корректные права (`chmod`) и добавляет в него публичные SSH-ключи, указанные в `values.yaml`.
  - **Пример скрипта**:
    ```bash
    #!/bin/sh
    # ...
    if [ ! -d "/home/{{ .Values.user.name }}/.ssh" ]; then
        mkdir -p /home/{{ .Values.user.name }}/.ssh
        chmod 700 /home/{{ .Values.user.name }}/.ssh
        touch /home/{{ .Values.user.name }}/.ssh/authorized_keys
        chmod 600 /home/{{ .Values.user.name }}/.ssh/authorized_keys
        # Добавление ключей из values.yaml
        {{- range .Values.publicKeys }}
        echo "{{ . }}" >> /home/{{ .Values.user.name }}/.ssh/authorized_keys
        {{- end }}
        chown -R {{ .Values.user.id }}:{{ .Values.user.id }} /home/{{ .Values.user.name }}/.ssh
    fi
    ```
    > **Примечание о баге**: В оригинальном видео была допущена ошибка — отсутствовало слово `then` после условия `if`. Это приводило к `CrashLoopBackOff` у `initContainer`. Такие синтаксические ошибки в shell-скриптах являются частой причиной проблем при инициализации подов.

- **Основной контейнер (`dev-container`)**:
  - **Образ**: Использует образ `ubuntu:24.04` с SSH, созданный ранее.
  - **Переменные окружения**: Принимает `DEV_USER_NAME` и `DEV_USER_ID` из `values.yaml` для создания пользователя внутри контейнера с нужными UID/GID. Это критически важно для совпадения прав с `hostPath` томом.
  - **Тома (Volumes)**:
    - **Домашняя директория**: Монтируется как `hostPath` том. Это позволяет сохранять данные пользователя на узле K3s даже после перезапуска пода.
      ```yaml
      volumes:
        - name: home-dir
          hostPath:
            path: /home/{{ .Values.user.name }}
            type: DirectoryOrCreate
      ```
      > **Внимание**: Использование `hostPath` является небезопасной практикой в производственных окружениях, но допустимо для локальной среды разработки. Подробнее см. в [Pod Volumes](../Base/Pod/pod_volumes.md).
    - **Сертификат CA**: Монтируется из `ConfigMap`, чтобы контейнер доверял внутренним ресурсам (например, Harbor).
      ```yaml
      volumeMounts:
        - name: ca-certs
          mountPath: /etc/ssl/certs/dfca.crt
          subPath: dfca.crt
      ```

#### `values.yaml` — Конфигурация

Файл `values.yaml` содержит все настраиваемые параметры.

```yaml
# Пользователь, создаваемый в контейнере и владелец home-директории
user:
  name: artur
  id: 1001

# Путь на хосте для домашней директории
baseHostPath: /home

# Массив публичных SSH-ключей для доступа
publicKeys:
  - "ssh-rsa AAAA..."

# CA сертификат в формате base64 или plain-text
caCrt: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----

# Настройки сервиса для доступа по SSH
service:
  type: NodePort
  sshPort: 32022 # Порт для SSH-доступа
```

### 6.2. Публикация Helm-чарта в OCI-репозиторий (Harbor)

Современные Helm-чарты можно хранить в OCI-совместимых реестрах, таких как [Harbor](../../../Docker/Docker_registries/Harbor/overview.md), вместе с Docker-образами.

#### `.gitlab-ci.yml` для публикации чарта

Пайплайн использует образ `kubeutils` (созданный ранее), чтобы получить доступ к команде `helm`.

```yaml
build-chart:
  stage: build
  image: $dev.registry/library/kube-utils:v1.28.6
  script:
    # 1. Добавляем наш CA в доверенные, чтобы helm мог общаться с Harbor
    - cp $dev.se /usr/local/share/ca-certificates/custom-ca.crt
    - update-ca-certificates
    # 2. Логинимся в OCI-репозиторий
    - helm registry login $dev.registry -u $dev.registry-user -p $dev.registry-password
    # 3. Упаковываем и публикуем чарт
    - helm package ./dev-container
    - helm push dev-container-*.tgz oci://$dev.registry/charts
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

### 6.3. Развертывание с помощью ArgoCD

GitOps-подход с использованием [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) является предпочтительным способом развертывания.

#### Манифест `Application` для ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
  namespace: argocd
spec:
  project: default
  source:
    # Указываем OCI-репозиторий
    repoURL: 'oci://harbor.your-domain.com/charts'
    # Имя чарта
    chart: dev-container
    # Версия чарта
    targetRevision: 0.1.0
    # Переопределяем values
    helm:
      values: |
        user:
          name: artur
          id: 1001
        publicKeys:
          - "ssh-rsa AAAA..."
        caCrt: |
          -----BEGIN CERTIFICATE-----
          ...
          -----END CERTIFICATE-----
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

После синхронизации ArgoCD развернет `dev-container`, и к нему можно будет подключиться по SSH через `NodePort` сервиса.

`ssh -p 32022 artur@<k3s-node-ip>`


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

---
## 5. Развертывание Dev-контейнера с помощью Helm

Продолжая предыдущий раздел, где был создан образ `dev-container`, здесь мы рассмотрим его развертывание в кластере с помощью Helm-чарта. Чарт будет управлять `Deployment`, `Service`, `ConfigMap` и персистентностью домашней директории.

### 5.1. Структура Helm-чарта

Чарт состоит из стандартных шаблонов. Ключевые аспекты его реализации описаны ниже.

#### `deployment.yaml` — Основная логика

`Deployment` запускает под с двумя контейнерами: `initContainer` для подготовки и основной `dev-container`.

- **`initContainer`**:
  - **Задача**: Подготовить окружение для SSH-доступа по ключу.
  - **Логика**: При первом запуске скрипт проверяет наличие директории `.ssh` в домашнем каталоге пользователя. Если ее нет, он создает `.ssh/authorized_keys`, устанавливает корректные права (`chmod`) и добавляет в него публичные SSH-ключи, указанные в `values.yaml`.
  - **Пример скрипта**:
    ```bash
    #!/bin/sh
    # ...
    if [ ! -d "/home/{{ .Values.user.name }}/.ssh" ]; then
        mkdir -p /home/{{ .Values.user.name }}/.ssh
        chmod 700 /home/{{ .Values.user.name }}/.ssh
        touch /home/{{ .Values.user.name }}/.ssh/authorized_keys
        chmod 600 /home/{{ .Values.user.name }}/.ssh/authorized_keys
        # Добавление ключей из values.yaml
        {{- range .Values.publicKeys }}
        echo "{{ . }}" >> /home/{{ .Values.user.name }}/.ssh/authorized_keys
        {{- end }}
        chown -R {{ .Values.user.id }}:{{ .Values.user.id }} /home/{{ .Values.user.name }}/.ssh
    fi
    ```
    > **Примечание о баге**: В оригинальном видео была допущена ошибка — отсутствовало слово `then` после условия `if`. Это приводило к `CrashLoopBackOff` у `initContainer`. Такие синтаксические ошибки в shell-скриптах являются частой причиной проблем при инициализации подов.

- **Основной контейнер (`dev-container`)**:
  - **Образ**: Использует образ `ubuntu:24.04` с SSH, созданный ранее.
  - **Переменные окружения**: Принимает `DEV_USER_NAME` и `DEV_USER_ID` из `values.yaml` для создания пользователя внутри контейнера с нужными UID/GID. Это критически важно для совпадения прав с `hostPath` томом.
  - **Тома (Volumes)**:
    - **Домашняя директория**: Монтируется как `hostPath` том. Это позволяет сохранять данные пользователя на узле K3s даже после перезапуска пода.
      ```yaml
      volumes:
        - name: home-dir
          hostPath:
            path: /home/{{ .Values.user.name }}
            type: DirectoryOrCreate
      ```
      > **Внимание**: Использование `hostPath` является небезопасной практикой в производственных окружениях, но допустимо для локальной среды разработки. Подробнее см. в [Pod Volumes](../Base/Pod/pod_volumes.md).
    - **Сертификат CA**: Монтируется из `ConfigMap`, чтобы контейнер доверял внутренним ресурсам (например, Harbor).
      ```yaml
      volumeMounts:
        - name: ca-certs
          mountPath: /etc/ssl/certs/dfca.crt
          subPath: dfca.crt
      ```

#### `values.yaml` — Конфигурация

Файл `values.yaml` содержит все настраиваемые параметры.

```yaml
# Пользователь, создаваемый в контейнере и владелец home-директории
user:
  name: artur
  id: 1001

# Путь на хосте для домашней директории
baseHostPath: /home

# Массив публичных SSH-ключей для доступа
publicKeys:
  - "ssh-rsa AAAA..."

# CA сертификат в формате base64 или plain-text
caCrt: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----

# Настройки сервиса для доступа по SSH
service:
  type: NodePort
  sshPort: 32022 # Порт для SSH-доступа
```

### 5.2. Публикация Helm-чарта в OCI-репозиторий (Harbor)

Современные Helm-чарты можно хранить в OCI-совместимых реестрах, таких как [Harbor](../../../Docker/Docker_registries/Harbor/overview.md), вместе с Docker-образами.

#### `.gitlab-ci.yml` для публикации чарта

Пайплайн использует образ `kubeutils` (созданный ранее), чтобы получить доступ к команде `helm`.

```yaml
build-chart:
  stage: build
  image: $dev.registry/library/kube-utils:v1.28.6
  script:
    # 1. Добавляем наш CA в доверенные, чтобы helm мог общаться с Harbor
    - cp $dev.se /usr/local/share/ca-certificates/custom-ca.crt
    - update-ca-certificates
    # 2. Логинимся в OCI-репозиторий
    - helm registry login $dev.registry -u $dev.registry-user -p $dev.registry-password
    # 3. Упаковываем и публикуем чарт
    - helm package ./dev-container
    - helm push dev-container-*.tgz oci://$dev.registry/charts
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

### 5.3. Развертывание с помощью ArgoCD

GitOps-подход с использованием [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) является предпочтительным способом развертывания.

#### Манифест `Application` для ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
  namespace: argocd
spec:
  project: default
  source:
    # Указываем OCI-репозиторий
    repoURL: 'oci://harbor.your-domain.com/charts'
    # Имя чарта
    chart: dev-container
    # Версия чарта
    targetRevision: 0.1.0
    # Переопределяем values
    helm:
      values: |
        user:
          name: artur
          id: 1001
        publicKeys:
          - "ssh-rsa AAAA..."
        caCrt: |
          -----BEGIN CERTIFICATE-----
          ...
          -----END CERTIFICATE-----
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

После синхронизации ArgoCD развернет `dev-container`, и к нему можно будет подключиться по SSH через `NodePort` сервиса.

`ssh -p 32022 artur@<k3s-node-ip>`

