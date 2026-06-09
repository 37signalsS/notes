# Развертывание Dev-контейнера с помощью Helm

Практическое руководство по развертыванию изолированного рабочего пространства в кластере K3s (Kubernetes K3s) с использованием Helm-чарта. Чарт управляет `Deployment`, `Service`, `ConfigMap` и персистентностью домашней директории.

> **Контекст:** Продолжение руководства по созданию [Dev-контейнера с SSH](./dev_container_ssh.md) (Secure Shell). Предварительно требуется создание [вспомогательного образа kubeutils](./kubeutils_image.md) для пайплайнов CI/CD (Continuous Integration / Continuous Deployment).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Init Container** | Вспомогательный контейнер, запускаемый до основного. В данном сценарии используется для подготовки SSH-ключей и директории `.ssh` |
| **HostPath Volume** | Тип тома, монтирующий файл или директорию с хост-узла в под. Используется для персистентности домашней директории пользователя. Подробнее см. [Pod Volumes](../../Base/Pod/volume_types/volumes_basics.md) |
| **OCI-реестр** | Реестр OCI (Open Container Initiative) для хранения контейнеров и Helm-чартов. В данном сценарии используется [Harbor](../../../Docker/Docker_registries/Harbor/overview.md) |
| **GitOps** | Подход к управлению инфраструктурой через Git. В сценарии применяется [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) для развертывания чарта |

**Навигация по Helm:** [Обзор Helm](../../ToolsUtilities/Helm/helm_overview.md) | [Структура чарта](../../ToolsUtilities/Helm/helm_chart_structure.md) | [Безопасность](../../ToolsUtilities/Helm/Advanced/security_best_practices.md)

---

## Основные концепции

### Архитектура решения

Helm-чарт развертывает под с двумя контейнерами:

1. **Init Container** — подготовка окружения для SSH-доступа
2. **Dev-container** — основной рабочий контейнер с SSH-сервером

**Ключевые особенности:**

- **Персистентность:** Домашняя директория сохраняется на узле K3s через `hostPath`
- **Безопасность:** SSH-доступ только по публичным ключам
- **Доверие к CA:** CA (Certificate Authority) сертификат монтируется из `ConfigMap` для работы с внутренними ресурсами (Harbor)
- **Изоляция:** Отдельный пользователь с заданным UID/GID (User ID / Group ID) внутри контейнера

### Принцип работы Init Container

Init Container выполняет подготовку окружения при первом запуске пода:

1. Проверяет наличие директории `.ssh` в домашнем каталоге
2. Создает `.ssh/authorized_keys` с правильными правами (`chmod 700` для директории, `chmod 600` для файла)
3. Добавляет публичные SSH-ключи из `values.yaml`
4. Устанавливает владельца (`chown`) на директорию `.ssh`

**Типичная ошибка:** Отсутствие `then` после условия `if` в shell-скрипте приводит к `CrashLoopBackOff`. Синтаксис должен быть:

```bash
if [ ! -d "/home/user/.ssh" ]; then
    # действия
fi
```

### Конфигурация через values.yaml

Файл `values.yaml` следует принципу [единого источника конфигурации](../../ToolsUtilities/Helm/helm_chart_structure.md#файл-valuesyaml):

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

# CA сертификат в формате plain-text
caCrt: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----

# Настройки сервиса для доступа по SSH
service:
  type: NodePort
  sshPort: 32022
```

---

## Практические сценарии

### Структура Helm-чарта

#### `deployment.yaml` — Основная логика

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dev-container
spec:
  template:
    spec:
      initContainers:
        - name: init-ssh
          image: ubuntu:24.04
          command: ["/bin/sh", "-c"]
          args:
            - |
              #!/bin/sh
              if [ ! -d "/home/{{ .Values.user.name }}/.ssh" ]; then
                mkdir -p /home/{{ .Values.user.name }}/.ssh
                chmod 700 /home/{{ .Values.user.name }}/.ssh
                touch /home/{{ .Values.user.name }}/.ssh/authorized_keys
                chmod 600 /home/{{ .Values.user.name }}/.ssh/authorized_keys
                {{- range .Values.publicKeys }}
                echo "{{ . }}" >> /home/{{ .Values.user.name }}/.ssh/authorized_keys
                {{- end }}
                chown -R {{ .Values.user.id }}:{{ .Values.user.id }} /home/{{ .Values.user.name }}/.ssh
              fi
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
      containers:
        - name: dev-container
          image: ubuntu:24.04
          env:
            - name: DEV_USER_NAME
              value: {{ .Values.user.name | quote }}
            - name: DEV_USER_ID
              value: {{ .Values.user.id | quote }}
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
            - name: ca-certs
              mountPath: /etc/ssl/certs/dfca.crt
              subPath: dfca.crt
      volumes:
        - name: home-dir
          hostPath:
            path: /home/{{ .Values.user.name }}
            type: DirectoryOrCreate
        - name: ca-certs
          configMap:
            name: dev-container-ca-certs
```

> **Внимание:** `hostPath` небезопасен для промышленной эксплуатации (production). Используйте только для локальной разработки.

### Публикация чарта в OCI-реестр (Harbor)

Пайплайн использует образ [`kubeutils`](./kubeutils_image.md) для доступа к команде `helm`.

#### `.gitlab-ci.yml`

```yaml
build-chart:
  stage: build
  image: $dev.registry/library/kube-utils:v1.28.6
  script:
    # 1. Добавляем CA в доверенные
    - cp $dev.se /usr/local/share/ca-certificates/custom-ca.crt
    - update-ca-certificates
    # 2. Логин в OCI-реестр
    - helm registry login $dev.registry -u $dev.registry-user -p $dev.registry-password
    # 3. Упаковка и публикация
    - helm package ./dev-container
    - helm push dev-container-*.tgz oci://$dev.registry/charts
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

**Преимущества OCI-реестров:**

- Единый интерфейс для контейнеров и чартов
- Встроенная аутентификация через `docker login`
- Интеграция с CI/CD без дополнительных плагинов

### Развертывание через ArgoCD

GitOps-подход с использованием [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md).

#### Манифест `Application`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'oci://harbor.your-domain.com/charts'
    chart: dev-container
    targetRevision: 0.1.0
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

#### Подключение к контейнеру

После синхронизации ArgoCD развернет `dev-container`. Подключение по SSH:

```bash
ssh -p 32022 artur@<k3s-node-ip>
```

---

## Дополнительная информация

### Связанные темы

- **Dev-контейнер:** [Создание образа с SSH](./dev_container_ssh.md)
- **Инфраструктура:** [Архитектура K3s](./k3s_architecture.md)
- **CI/CD:** [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)
- **Helm:** [Обзор Helm](../../ToolsUtilities/Helm/helm_overview.md), [Структура чарта](../../ToolsUtilities/Helm/helm_chart_structure.md)
- **Безопасность:** [Best practices Helm](../../ToolsUtilities/Helm/Advanced/security_best_practices.md)
- **volumes:** [Pod Volumes](../../Base/Pod/volume_types/volumes_basics.md)

### Предупреждения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **hostPath** | Доступ к файловой системе узла | Только для dev-окружений |
| **SSH по NodePort** | Открытый порт на узле | Ограничьте доступ через firewall (межсетевой экран) |
| **Секреты в values.yaml** | Ключи в открытом виде | Используйте [helm-secrets](https://github.com/jkroepke/helm-secrets) или External Secrets |
