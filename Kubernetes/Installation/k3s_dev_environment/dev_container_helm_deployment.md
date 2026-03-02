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
