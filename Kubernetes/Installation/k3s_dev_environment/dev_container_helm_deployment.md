# Развертывание Dev-контейнера с помощью Helm

Практическое руководство по развертыванию изолированного рабочего пространства в кластере K3s (Kubernetes K3s) с использованием Helm-чарта. Чарт управляет объектами `Deployment`, `Service`, `ConfigMap` и обеспечивает персистентность домашней директории.

> **Контекст:** Продолжение руководства по созданию [Dev-контейнера с SSH](./dev_container_ssh.md). Предварительно требуется создание [вспомогательного образа kubeutils](./kubeutils_image.md) для пайплайнов CI/CD.

---

## Надежность и актуальность

- **Уровень надежности:** 9 (Базируется на внутренних стандартах и проверенных сценариях развертывания)
- **Дата последнего обновления:** Июль 2024
- **Актуальность:** Проверено для Kubernetes v1.28–v1.30, Helm v3.14+

---

## Определения

| Термин | Описание |
|--------|----------|
| **Init Container** | Вспомогательный контейнер, запускаемый до основного. В данном сценарии используется для подготовки SSH-ключей и директории `.ssh`. Подробнее: [Init-контейнеры](../../Base/Pod/pod_init_containers.md) |
| **HostPath Volume** | Тип тома, монтирующий файл или директорию с хост-узла в под. Используется для персистентности данных. См. [Тома в Kubernetes](../../Base/Pod/volume_types/volume_types.md) |
| **OCI-реестр** | Реестр Open Container Initiative для хранения образов и Helm-чартов. Пример: [Harbor](../../../Docker/Docker_registries/Harbor/overview.md) |
| **GitOps** | Методология управления инфраструктурой через Git. В сценарии применяется [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) |

**Навигация по Helm:** [Обзор Helm](../../ToolsUtilities/Helm/helm_overview.md) | [Структура чарта](../../ToolsUtilities/Helm/helm_chart_structure.md) | [Безопасность Helm](../../ToolsUtilities/Helm/Advanced/security_best_practices.md)

---

## Основные концепции

### Архитектура решения

Helm-чарт развертывает под (Pod) с двумя контейнерами:

1. **Init Container** — подготовка окружения для SSH-доступа.
2. **Dev-container** — основной рабочий контейнер с SSH-сервером.

**Ключевые особенности:**

- **Персистентность:** Домашняя директория сохраняется на узле K3s через `hostPath` или `Local Persistent Volume`.
- **Безопасность:** SSH-доступ строго по публичным ключам.
- **Доверие к CA:** Сертификат центра сертификации (Certificate Authority) монтируется из `ConfigMap` или `Secret` для взаимодействия с внутренним реестром.
- **Изоляция:** Запуск от имени пользователя с фиксированным UID/GID (User ID / Group ID).

### Принцип работы Init Container

Инициализирующий контейнер обеспечивает идемпотентность настройки:

1. Создает директорию `.ssh`, если она отсутствует.
2. Перезаписывает файл `authorized_keys` актуальными ключами из параметров чарта.
3. Устанавливает корректные права доступа (`700` для папки, `600` для файла).
4. Рекурсивно меняет владельца на целевого пользователя.

**Важное замечание по Shell:** При использовании многострочных команд в YAML-манифестах Kubernetes всегда проверяйте синтаксис условий, чтобы избежать `CrashLoopBackOff`.

### Конфигурация через values.yaml

Файл параметров следует структуре, описанной в [документации по values.yaml](../../ToolsUtilities/Helm/helm_chart_structure.md#файл-valuesyaml):

```yaml
# Параметры пользователя внутри контейнера
user:
  name: artur
  id: 1001

# Базовый путь на хосте для монтирования данных
baseHostPath: /home

# Список публичных SSH-ключей
publicKeys:
  - "ssh-rsa AAAA..."

# Корневой сертификат (CA) в текстовом виде
caCrt: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----

# Настройки Service для внешнего доступа
service:
  type: NodePort
  sshPort: 32022
```

---

## Практические сценарии

### Структура Helm-чарта

#### Описание deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dev-container
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dev-container
  template:
    metadata:
      labels:
        app: dev-container
    spec:
      initContainers:
        - name: init-ssh
          image: ubuntu:24.04
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -e
              USER_HOME="/home/{{ .Values.user.name }}"
              mkdir -p "$USER_HOME/.ssh"
              chmod 700 "$USER_HOME/.ssh"
              
              cat <<EOF > "$USER_HOME/.ssh/authorized_keys"
              {{- range .Values.publicKeys }}
              {{ . }}
              {{- end }}
              EOF
              
              chmod 600 "$USER_HOME/.ssh/authorized_keys"
              chown -R {{ .Values.user.id }}:{{ .Values.user.id }} "$USER_HOME/.ssh"
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
      containers:
        - name: dev-container
          image: ubuntu:24.04
          securityContext:
            runAsUser: {{ .Values.user.id }}
          env:
            - name: DEV_USER_NAME
              value: {{ .Values.user.name | quote }}
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
            - name: ca-certs
              mountPath: /etc/ssl/certs/custom-ca.crt
              subPath: custom-ca.crt
      volumes:
        - name: home-dir
          hostPath:
            path: /home/{{ .Values.user.name }}
            type: DirectoryOrCreate
        - name: ca-certs
          configMap:
            name: dev-container-ca-certs
```

### Публикация чарта в OCI-реестр (Harbor)

Для автоматизации используется вспомогательный образ [`kubeutils`](./kubeutils_image.md).

#### Пример конфигурации .gitlab-ci.yml

```yaml
publish-helm-chart:
  stage: deploy
  image: $dev.registry/library/kube-utils:v1.30.0
  script:
    # Добавление CA в системное хранилище
    - cp $CUSTOM_CA_FILE /usr/local/share/ca-certificates/internal-ca.crt
    - update-ca-certificates
    # Аутентификация в реестре
    - helm registry login $dev.registry -u $dev.registry_user -p $dev.registry_password
    # Сборка и отправка
    - helm package ./dev-container
    - helm push dev-container-*.tgz oci://$dev.registry/charts
  rules:
    - if: '$CI_COMMIT_TAG'
```

### Развертывание через ArgoCD

Использование декларативного подхода [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) для управления жизненным циклом.

#### Манифест типа Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'harbor.your-domain.com/charts'
    chart: dev-container
    targetRevision: 1.0.0
    helm:
      values: |
        user:
          name: developer
          id: 1000
        publicKeys:
          - "ssh-ed25519 AAAAC3Nza..."
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: dev-workspaces
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

#### Проверка подключения

После успешной синхронизации (Sync) контейнер станет доступен по SSH:

```bash
# Подключение к NodePort сервису
ssh -p 32022 developer@<node-ip>
# → Welcome to Ubuntu 24.04 LTS
```

---

## Дополнительная информация

### Связанные темы

- **Dev-контейнер:** [Создание базового образа с SSH](./dev_container_ssh.md)
- **K3s:** [Архитектура кластера K3s](./k3s_architecture.md)
- **Хранилище:** [Типы томов в Pod](../../Base/Pod/volume_types/volume_types.md)
- **CI/CD:** [Интеграция GitLab и Harbor](./gitlab_harbor_integration.md)

### Предупреждения и ограничения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **hostPath** | Небезопасный доступ к узлу | Используйте только в dev-окружениях. Для production рассмотрите CSI-драйверы. |
| **NodePort** | Открытый порт на всех узлах | Ограничивайте доступ на уровне NetworkPolicy или внешнего Firewall. |
| **Секреты** | Хранение ключей в values.yaml | Рекомендуется использовать [Sealed Secrets](../../Security/sealed_secrets_overview.md) или External Secrets. |
| **Безопасность** | Привилегированные контейнеры | Избегайте запуска от root; используйте `securityContext` для ограничения прав. |
