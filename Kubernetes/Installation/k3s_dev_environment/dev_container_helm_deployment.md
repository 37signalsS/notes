# Развертывание Dev-контейнера с помощью Helm

Практическое руководство по развертыванию изолированного рабочего пространства в кластере K3s с использованием Helm-чарта. Чарт управляет объектами `Deployment`, `Service`, `ConfigMap` и обеспечивает персистентность домашней директории.

> **Контекст:** Продолжение руководства по созданию [Dev-контейнера с SSH](./dev_container_ssh.md). Предварительно требуется создание [вспомогательного образа kubeutils](./kubeutils_image.md) для пайплайнов CI/CD. См. также [Архитектура K3s](./k3s_architecture.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Helm 4** | Современный стандарт пакетного менеджера (с 2025 г.), обеспечивающий нативную поддержку OCI-артефактов и улучшенную безопасность. |
| **OCI-артефакт** | Метод дистрибуции Helm-чартов через Container Registry (Harbor, GitLab Registry), объединяющий жизненный цикл образов и манифестов. |
| **Init Container** | Вспомогательный контейнер для подготовки окружения (SSH-ключи, права доступа) перед запуском основного приложения. Подробнее: [Init-контейнеры](../../Base/Pod/pod_init_containers.md). |
| **Gateway API** | Современная замена Ingress для управления внешним трафиком, обеспечивающая лучшую типизацию и разделение ответственности. |
| **HostPath Volume** | Тип тома, монтирующий директорию с хост-узла в под. Используется для персистентности данных в dev-окружениях. См. [Тома в Kubernetes](../../Base/Pod/volume_types/volume_types.md). |

**Навигация по Helm:** [Обзор Helm](../../ToolsUtilities/Helm/helm_overview.md) | [Структура чарта](../../ToolsUtilities/Helm/helm_chart_structure.md) | [Безопасность Helm](../../ToolsUtilities/Helm/Advanced/security_best_practices.md)

---

## Основные концепции

### Архитектура решения

Helm-чарт развертывает под (Pod) с двумя контейнерами, обеспечивая идемпотентность и безопасность:

1.  **Init Container (Инициализация):**
    - Создает структуру директорий пользователя, если она отсутствует.
    - Перезаписывает файл `authorized_keys` актуальными ключами из параметров чарта (через `cat <<EOF`).
    - Устанавливает корректные права доступа (`700` для папки, `600` для файла) и рекурсивно меняет владельца (`chown`).
2.  **Dev-container (Рабочая среда):**
    - Основной контейнер с SSH-сервером и предустановленным инструментарием.
    - Запускается от имени не-привилегированного пользователя.
    - Монтирует персистентное хранилище и системные CA-сертификаты.

**Ключевые особенности 2026 года:**
- **Персистентность:** Сохранение данных через `hostPath` (для локальных K3s) или CSI-драйверы.
- **Безопасность:** Запрет `runAsRoot`, использование `readinessProbe` для проверки SSH-порта (22).
- **Ресурсы:** Обязательное указание `limits` и `requests` для предотвращения перегрузки ноды.

---

## Практические сценарии

### 1. Конфигурация через values.yaml

Файл параметров следует структуре, обеспечивающей гибкость настройки рабочего пространства:

```yaml
# Параметры пользователя внутри контейнера
user:
  name: artur
  id: 1001

# Образ контейнера (из Harbor)
image:
  repository: harbor.example.com/library/dev-container
  tag: "2026.1.2"
  pullPolicy: IfNotPresent

# Список публичных SSH-ключей (Ed25519 рекомендуется)
publicKeys:
  - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI..."

# Корневой сертификат (CA) для доверия к реестру
caCrt: |
  -----BEGIN CERTIFICATE-----
  ...
  -----END CERTIFICATE-----

# Ресурсы (Стандарт 2026)
resources:
  requests:
    cpu: "500m"
    memory: "1Gi"
  limits:
    cpu: "2000m"
    memory: "4Gi"

# Настройки Service
service:
  type: NodePort
  sshPort: 32022
```

### 2. Описание шаблона deployment.yaml

Манифест включает логику инициализации и современные контексты безопасности.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "dev-container.fullname" . }}
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
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .Values.user.id }}
        fsGroup: {{ .Values.user.id }}
      
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
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          readinessProbe:
            tcpSocket:
              port: 22
            initialDelaySeconds: 5
            periodSeconds: 10
          env:
            - name: DEV_USER_NAME
              value: {{ .Values.user.name | quote }}
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
            - name: ca-certs
              mountPath: /etc/ssl/certs/custom-ca.crt
              subPath: custom-ca.crt
              readOnly: true
      
      volumes:
        - name: home-dir
          hostPath:
            path: "/mnt/data/homes/{{ .Values.user.name }}"
            type: DirectoryOrCreate
        - name: ca-certs
          configMap:
            name: {{ include "dev-container.fullname" . }}-ca
```

### 3. Публикация в OCI-реестр и GitOps

#### Автоматизация через CI/CD (.gitlab-ci.yml)

Использование `kubeutils` для работы с Helm 4 и OCI.

```yaml
publish-helm-chart:
  stage: deploy
  image: $dev.registry/library/kube-utils:v1.36.2
  script:
    - helm registry login $dev.registry -u $dev.registry_user -p $dev.registry_password
    - helm package ./dev-container --version $CI_COMMIT_TAG
    - helm push dev-container-$CI_COMMIT_TAG.tgz oci://$dev.registry/charts
```

#### Развертывание через ArgoCD v3.x

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
spec:
  source:
    repoURL: oci://harbor.example.com/charts
    chart: dev-container
    targetRevision: 1.2.0
    path: .
    helm:
      values: |
        user:
          name: developer
          id: 1000
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: dev-workspaces
```

### 4. Проверка подключения

После синхронизации контейнер доступен по SSH (используйте NodePort или Gateway IP):

```bash
# Подключение к NodePort сервису
ssh -p 32022 developer@<node-ip>
# → Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.x)
```

---

## Дополнительная информация

### Предупреждения и риски

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **hostPath** | Привязка к конкретной ноде | Используйте только для локальной разработки. Для отказоустойчивости используйте **Longhorn**. |
| **Безопасность** | Статические SSH-ключи | Рекомендуется периодическая ротация или переход на OIDC-аутентификацию через **Teleport**. |
| **NodePort** | Открытый порт в сети | Ограничивайте доступ через `NetworkPolicy` или используйте VPN (Tailscale). |
| **Ресурсы** | CrashLoopBackOff при нехватке RAM | Всегда устанавливайте `requests` чуть ниже среднего потребления и `limits` с запасом. |

### Связанные темы

- **Dev-контейнер:** [Создание базового образа с SSH](./dev_container_ssh.md)
- **CI/CD:** [Интеграция GitLab и Harbor](./gitlab_harbor_integration.md)
- **Утилиты:** [Вспомогательный образ kubeutils](./kubeutils_image.md)
- **Хранилище:** [Типы томов в Pod](../../Base/Pod/volume_types/volume_types.md)
