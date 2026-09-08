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

### Структура Helm-чарта

Чарт `dev-container` включает минимальный набор файлов для production-ready развертывания. Детали см. в [Структура Helm-чарта](../../ToolsUtilities/Helm/helm_chart_structure.md).

```text
dev-container/
├── Chart.yaml
├── Chart.lock
├── values.yaml
├── values.schema.json
├── README.md
├── .helmignore
├── files/
│   └── init-ssh.sh
└── templates/
    ├── _helpers.tpl
    ├── deployment.yaml
    ├── service.yaml
    ├── configmap.yaml
    ├── serviceaccount.yaml
    ├── networkpolicy.yaml
    └── tests/
        └── ssh-connection-test.yaml
```

### Файл Chart.yaml

```yaml
apiVersion: v2
name: dev-container
description: Helm chart for isolated SSH dev workspace in K3s
type: application
version: 1.2.0
appVersion: "2026.1.2"
keywords:
  - dev-container
  - ssh
  - workspace
  - k3s
maintainers:
  - name: devops-team
    email: devops@example.com
```

### Иерархия значений (Values Hierarchy)

Helm v4 использует Server-Side Apply (SSA), что позволяет внешним контроллерам (HPA, cert-manager) изменять ресурсы без конфликтов. Порядок применения значений (от высшего к низшему приоритету):

1.  `--set` / `--set-string` флаги CLI
2.  Файлы `-f values.yaml` (последний файл перезаписывает предыдущий)
3.  Значения по умолчанию из `values.yaml` чарта

Для dev-container рекомендуется использовать слойную стратегию:
- `values.yaml` — базовые настройки (образ, ресурсы)
- `values-dev.yaml` — переопределения для среды разработки
- `values-prod.yaml` — переопределения для продакшена (если используется)

### ServiceAccount и безопасность

Чарт создает выделенный `ServiceAccount` с минимальными правами. По умолчанию dev-container не требует доступа к API Kubernetes, но ServiceAccount необходим для работы с `imagePullSecrets`.

### NetworkPolicy

В K3s по умолчанию используется Flannel (CNI), который не поддерживает NetworkPolicy. Для работы сетевых политик требуется установка Calico или Cilium. Если NetworkPolicy не поддерживается CNI, пода остается доступной в рамках кластерной сети.

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация | Назначение |
| :--- | :--- | :--- | :--- |
| **K3s** | v1.30+ | v1.36.3+k3s1 | Оркестратор Kubernetes |
| **Helm** | 3.14+ | v4.2.3 | Управление чартами |
| **kubectl** | Совпадает с версией K3s | v1.36.3 | Управление ресурсами кластера |
| **Docker / Podman** | 24.0+ | 27.x | Сборка и публикация образа |
| **SSH-клиент** | OpenSSH 8.0+ | OpenSSH 9.8+ | Подключение к контейнеру |
| **regctl** | 0.5.0+ | Latest | Инспекция манифестов в реестре |

### Требования к кластеру K3s

- **Storage Class:** Наличие `local-path` (встроенный в K3s) или CSI-драйвера (Longhorn, OpenEBS) для персистентных томов.
- **Namespace:** Namespace `dev-workspaces` должен существовать до установки чарта.
- **Registry Access:** Кластер должен иметь возможность тянуть образы из Harbor (настроенный `imagePullSecrets` или insecure registry в containerd).
- **CNI:** Flannel (встроенный) достаточен для базового сценария. Calico/Cilium требуются для NetworkPolicy.

### Предварительные шаги

1.  **Проверка состояния K3s:**
    ```bash
    kubectl get nodes
    # → NAME     STATUS   ROLES                  AGE   VERSION
    # → server   Ready    control-plane,master   2m    v1.36.3+k3s1
    ```

2.  **Создание namespace:**
    ```bash
    kubectl create namespace dev-workspaces
    # → namespace/dev-workspaces created
    ```

3.  **Создание Secret для imagePullSecrets (если Harbor приватный):**
    ```bash
    kubectl create secret docker-registry harbor-registry \
      --namespace=dev-workspaces \
      --docker-server=harbor.example.com \
      --docker-username=robot$dev-workspaces \
      --docker-password=<robot-password>
    # → secret/harbor-registry created
    ```

4.  **Подготовка директории на хосте (для hostPath):**
    ```bash
    # На хосте K3s
    sudo mkdir -p /mnt/data/homes
    sudo chmod 755 /mnt/data/homes
    ```

5.  **Публикация образа dev-container в Harbor:**
    ```bash
    docker tag dev-container:2026 harbor.example.com/library/dev-container:2026
    docker push harbor.example.com/library/dev-container:2026
    # → The push refers to repository [harbor.example.com/library/dev-container]
    # → 2026: digest: sha256:abc123... size: 1362
    ```

---

## Практические сценарии

### 1. Подготовка репозитория чарта

Создайте стандартную структуру чарта через `helm create` и адаптируйте шаблоны под dev-container:

```bash
helm create dev-container
cd dev-container

# Удаление стандартных шаблонов
rm -rf templates/tests/ tests/
rm templates/hpa.yaml templates/ingress.yaml templates/service.yaml templates/ NOTES.txt

# Создание структуры
mkdir -p files templates/tests
```

**Валидация:**
```bash
ls -la dev-container/
# → Chart.yaml  Chart.lock  values.yaml  templates/  files/
```

### 2. Полный values.yaml

```yaml
# Параметры пользователя внутри контейнера
user:
  name: developer
  id: 1000
  home: /home/developer

# Образ контейнера (из Harbor)
image:
  repository: harbor.example.com/library/dev-container
  tag: "2026.1.2"
  pullPolicy: IfNotPresent
  imagePullSecrets: []

# SSH-ключи (Ed25519 рекомендуется)
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
  annotations: {}

# ServiceAccount
serviceAccount:
  create: true
  name: ""

# NetworkPolicy (требует Calico/Cilium)
networkPolicy:
  create: false
  allowedCIDRs:
    - 192.168.1.0/24

# Node selector и tolerations (опционально)
nodeSelector: {}
tolerations: []

# Пространство имен
namespace: dev-workspaces

# Реплики
replicas: 1
```

**Валидация:**
```bash
helm lint ./dev-container
# → == Linting ./dev-container
# → 0 chart(s) linted, 0 chart(s) failed
```

### 3. Шаблон _helpers.tpl

```yaml
{{- define "dev-container.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dev-container.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}
```

### 4. Шаблон configmap.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "dev-container.fullname" . }}-ca
  namespace: {{ .Values.namespace }}
data:
  custom-ca.crt: |
{{ .Values.caCrt | indent 4 }}
```

### 5. Шаблон deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "dev-container.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    app: dev-container
    chart: {{ include "dev-container.chart" . }}
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels:
      app: dev-container
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: dev-container
        chart: {{ include "dev-container.chart" . }}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .Values.user.id }}
        fsGroup: {{ .Values.user.id }}
        seccompProfile:
          type: RuntimeDefault
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "dev-container.fullname" . }}
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
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: home-dir
              mountPath: /home/{{ .Values.user.name }}
      containers:
        - name: dev-container
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop:
                - ALL
          env:
            - name: DEV_USER_NAME
              value: {{ .Values.user.name | quote }}
            - name: DEV_USER_ID
              value: {{ .Values.user.id | quote }}
            - name: DEV_GROUP_ID
              value: {{ .Values.user.id | quote }}
          ports:
            - containerPort: 22
              name: ssh
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          readinessProbe:
            tcpSocket:
              port: ssh
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          livenessProbe:
            tcpSocket:
              port: ssh
            initialDelaySeconds: 30
            periodSeconds: 30
            timeoutSeconds: 3
            failureThreshold: 3
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
            items:
              - key: custom-ca.crt
                path: custom-ca.crt
      {{- if .Values.image.pullSecrets }}
      imagePullSecrets:
        {{- toYaml .Values.image.pullSecrets | nindent 8 }}
      {{- end }}
```

### 6. Шаблон service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "dev-container.fullname" . }}-ssh
  namespace: {{ .Values.namespace }}
  labels:
    app: dev-container
  {{- with .Values.service.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  type: {{ .Values.service.type }}
  selector:
    app: dev-container
  ports:
    - name: ssh
      port: 22
      targetPort: ssh
      protocol: TCP
      {{- if eq .Values.service.type "NodePort" }}
      nodePort: {{ .Values.service.sshPort }}
      {{- end }}
```

### 7. Шаблон serviceaccount.yaml

```yaml
{{- if .Values.serviceAccount.create -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "dev-container.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    app: dev-container
automountServiceAccountToken: false
{{- end }}
```

### 8. Шаблон networkpolicy.yaml

```yaml
{{- if .Values.networkPolicy.create -}}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "dev-container.fullname" . }}
  namespace: {{ .Values.namespace }}
  labels:
    app: dev-container
spec:
  podSelector:
    matchLabels:
      app: dev-container
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - ipBlock:
            cidr: {{ .Values.networkPolicy.allowedCIDRs | toJson }}
      ports:
        - protocol: TCP
          port: 22
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 443
{{- end }}
```

### 9. Установка и валидация

```bash
# 1. Добавление репозитория Harbor (если используется как Helm-реестр)
helm repo add harbor-oci oci://harbor.example.com/charts

# 2. Установка чарта
helm upgrade --install dev-container ./dev-container \
  --namespace dev-workspaces \
  --values values.yaml \
  --atomic \
  --timeout 5m \
  --wait

# → Release "dev-container" has been upgraded. 1 superseded by 1.
# → NAME: dev-container
# → LAST DEPLOYED: Mon Sep  1 19:00:00 2026
# → NAMESPACE: dev-workspaces
# → STATUS: deployed
# → REVISION: 1
```

**Валидация развертывания:**
```bash
# Проверка релиза
helm list -n dev-workspaces
# → NAME            NAMESPACE       REVISION    STATUS      CHART                 APP VERSION
# → dev-container   dev-workspaces  1           deployed    dev-container-1.2.0   2026.1.2

# Проверка подов
kubectl -n dev-workspaces get pods -l app=dev-container
# → NAME                            READY   STATUS    RESTARTS   AGE
# → dev-container-dev-container-xxx 1/1     Running   0          2m

# Проверка сервиса
kubectl -n dev-workspaces get svc dev-container-dev-container-ssh
# → NAME                             TYPE       CLUSTER-IP     PORT(S)         AGE
# → dev-container-dev-container-ssh  NodePort   10.43.x.x      22:32022/TCP    2m

# Проверка готовности
kubectl -n dev-workspaces describe pod dev-container-dev-container-xxx | grep -A 5 "Readiness"
# → Conditions:
# →   Type              Status
# →   Initialized       True
# →   Ready             True
# →   ContainersReady   True
# →   PodScheduled      True
```

### 10. Жизненный цикл релиза (Upgrade, Rollback, Test)

```bash
# Обновление образа
helm upgrade dev-container ./dev-container \
  --namespace dev-workspaces \
  --set image.tag="2026.1.3" \
  --atomic \
  --timeout 10m

# → Release "dev-container" has been upgraded. 1 superseded by 2.
# → LAST DEPLOYED: Mon Sep  1 20:00:00 2026
# → REVISION: 2

# Просмотр истории ревизий
helm history dev-container -n dev-workspaces
# → REVISION    STATUS      CHART                 DESCRIPTION
# → 1           superseded  dev-container-1.2.0    Install complete
# → 2           deployed    dev-container-1.2.0    Upgrade complete

# Откат на предыдущую ревизию
helm rollback dev-container 1 -n dev-workspaces
# → Rollback was a success! Happy Helming!

# Запуск тестов
helm test dev-container -n dev-workspaces --cleanup
# → PASS: dev-container-dev-container-ssh-test
# → Pod Status: Succeeded
```

### 11. Публикация в OCI-реестр и GitOps

#### Автоматизация через CI/CD (.gitlab-ci.yml)

Использование `kubeutils` для работы с Helm 4 и OCI.

```yaml
publish-helm-chart:
  stage: deploy
  image: $dev.registry/library/kubeutils:v1.36.3
  script:
    - helm registry login $dev.registry -u $dev.registry_user -p $dev.registry_password
    - helm package ./dev-container --version $CI_COMMIT_TAG
    - helm push dev-container-$CI_COMMIT_TAG.tgz oci://$dev.registry/charts
    - helm registry logout $dev.registry
  only:
    - tags
```

**Валидация:**
```bash
helm search repo dev-container --versions
# → NAME                            CHART VERSION   APP VERSION   DESCRIPTION
# → harbor-oci/dev-container        1.2.0           2026.1.2      Helm chart for isolated SSH dev workspace
```

#### Развертывание через ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dev-container
  namespace: argocd
spec:
  project: default
  source:
    repoURL: oci://harbor.example.com/charts
    chart: dev-container
    targetRevision: 1.2.0
    helm:
      values: |
        user:
          name: developer
          id: 1000
        image:
          tag: "2026.1.2"
        networkPolicy:
          create: false
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: dev-workspaces
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Валидация:**
```bash
argocd app get dev-container
# → Name:               dev-container
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          dev-workspaces
# → Status:             Healthy
# → Revision:           1.2.0
```

### 12. Проверка подключения

После синхронизации контейнер доступен по SSH (используйте NodePort):

```bash
# Подключение к NodePort сервису
ssh -p 32022 developer@<node-ip>
# → Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.x)

# Проверка пользователя
whoami
# → developer

id
# → uid=1000(developer) gid=1000(developer) groups=1000(developer)

# Проверка персистентности
echo "test" > ~/test-file.txt
# (при перезапуске пода файл сохранится)
```

---

## Очистка и откат

### Удаление релиза Helm

```bash
# Удаление релиза с сохранением PVC (если настроено Resource Policy)
helm uninstall dev-container -n dev-workspaces
# → release "dev-container" uninstalled

# Принудительное удаление всех ресурсов (включая PVC)
kubectl delete namespace dev-workspaces
# → namespace "dev-workspaces" force-deleted
```

### Возврат к предыдущему образу

```bash
# Если обновление завершилось ошибкой, откат на предыдущую ревизию
helm rollback dev-container 1 -n dev-workspaces --force
# → Rollback was a success! Happy Helming!
```

### Удаление созданных ресурсов

```bash
kubectl -n dev-workspaces delete deployment,service,configmap,serviceaccount,networkpolicy \
  -l app=dev-container
# → deployment.apps "dev-container-dev-container" deleted
# → service "dev-container-dev-container-ssh" deleted
# → configmap "dev-container-dev-container-ca" deleted
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: `helm upgrade failed: rendered manifests contain a resource that already exists`

**Причина:** Ресурс с таким именем уже существует в кластере (создан вручную или другим релизом).

```bash
# Поиск конфликтующего ресурса
kubectl -n dev-workspaces get all,configmap,secret,serviceaccount | grep dev-container

# Принудительное взятие контроля (SSA)
helm upgrade dev-container ./dev-container \
  --namespace dev-workspaces \
  --force-conflicts \
  --atomic
```

### Ошибка: `ImagePullBackOff` / `ErrImagePull`

**Причина:** Реестр недоступен или неверные учетные данные.

```bash
# Проверка события пода
kubectl -n dev-workspaces describe pod dev-container-dev-container-xxx | grep -A 10 "Events"
# → Warning  Failed     2s (x2 over 30s)  kubelet  Failed to pull image "harbor.example.com/library/dev-container:2026.1.2": rpc error: code = Unknown desc = failed to pull and unpack image "harbor.example.com/library/dev-container:2026.1.2": failed to resolve reference "harbor.example.com/library/dev-container:2026.1.2": failed to do request: Head "https://harbor.example.com/v2/": dial tcp: lookup harbor.example.com: no such host

# Проверка секрета
kubectl -n dev-workspaces get secret harbor-registry
# → NAME               TYPE                             DATA   AGE
# → harbor-registry    kubernetes.io/docker-configjson 1      5m

# Проверка containerd insecure registry (K3s)
sudo cat /var/lib/rancher/k3s/agent/etc/containerd/config.toml | grep -A 5 "harbor"
```

### Ошибка: `CrashLoopBackOff` с `Permission denied`

**Причина:** Несовпадение UID между образом и `hostPath` томом.

```bash
# Проверка прав на хосте
ls -la /mnt/data/homes/developer/
# → drwx------ developer developer .ssh

# Проверка UID в контейнере
kubectl -n dev-workspaces exec dev-container-dev-container-xxx -- id
# → uid=1000(developer) gid=1000(developer) groups=1000(developer)

# Исправление прав (на хосте K3s)
sudo chown -R 1000:1000 /mnt/data/homes/developer
```

### Ошибка: `Readiness probe failed`

**Причина:** SSH-сервер не запустился или init-container завершился с ошибкой.

```bash
# Просмотр логов init-контейнера
kubectl -n dev-workspaces logs dev-container-dev-container-xxx -c init-ssh
# → + mkdir -p /home/developer/.ssh
# → + chmod 700 /home/developer/.ssh

# Просмотр логов основного контейнера
kubectl -n dev-workspaces logs dev-container-dev-container-xxx
# → Starting sshd for developer (UID: 1000)...

# Проверка listening-портов
kubectl -n dev-workspaces exec dev-container-dev-container-xxx -- ss -tlnp
# → LISTEN  0  128  0.0.0.0:22  0.0.0.0:*  users:(("sshd",pid=1,fd=3))
```

### Ошибка: `helm template` выводит пустоту или ошибку типов

**Причина:** Ошибка в Go-шаблонизации или неверный тип значения в `values.yaml`.

```bash
# Локальный рендеринг с отладкой
helm template dev-container ./dev-container --debug
# → [debug] Error: template: dev-container/templates/deployment.yaml:25:32: executing "dev-container/templates/deployment.yaml" at <.Values.user.id>: invalid value; error converting YAML to JSON: yaml: line 25: cannot unmarshal !!str into int

# Проверка типов в values.yaml
grep -n "user:" values.yaml
```

---

## Особенности и крайние случаи

### K3s и Local Path Provisioner

K3s включает встроенный `local-path-provisioner`, который создает тома `hostPath` в `/var/lib/rancher/k3s/storage`. При использовании `hostPath` напрямую (через `/mnt/data/homes`), убедитесь, что директория существует на **всех** узлах кластера (master + workers), если под может быть запланирован на любой узел.

**Валидация:**
```bash
kubectl get storageclass
# → NAME                    PROVISIONER           RECLAIMPOLICY   VOLUMEBINDINGMODE   AGE
# → local-path (default)   rancher.io/local-path Delete           WaitForFirstConsumer  5m

# Проверка PV
kubectl get pv | grep homes
# → NAME           CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      CLAIM   STORAGECLASS   REASON   AGE
# → pvc-xxx        5Gi        RWO            Delete           Available   -        local-path                2m
```

### Traefik и конфликт портов

K3s по умолчанию устанавливает Traefik Ingress Controller, который использует порты 80 и 443. NodePort в диапазоне 30000-32767 не конфликтует с Traefik, но убедитесь, что выбранный `sshPort` не занят другими сервисами.

**Валидация:**
```bash
kubectl -n dev-workspaces get svc dev-container-dev-container-ssh -o jsonpath='{.spec.ports[?(@.nodePort==32022)].nodePort}'
# → 32022

# Проверка занятости порта на узле
sudo ss -tlnp | grep 32022
# → LISTEN  0  128  0.0.0.0:32022  0.0.0.0:*  users:(("kube-proxy",pid=xxx,fd=xxx))
```

### Pod Security Standards (PSS)

K3s применяет `baseline` PSS к namespace'ам. Dev-container требует исключений:
- `allowPrivilegeEscalation` не должен быть `true`
- `runAsNonRoot` должен быть `true`
- `hostPath` том требует разрешения в PSS (в `baseline` разрешены, в `restricted` запрещены)

Если namespace имеет enforcement `restricted`, добавьте Label:
```bash
kubectl label namespace dev-workspaces \
  pod-security.kubernetes.io/enforce=baseline \
  --overwrite
```

### Containerd и CA-сертификаты

K3s использует containerd вместо Docker. Для работы с приватным Harbor с самоподписанным сертификатом, CA должен быть установлен **на хостах K3s**, а не в контейнере.

**Установка CA на хосте K3s:**
```bash
sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd/certs.d/harbor.example.com
sudo cp custom-ca.crt /var/lib/rancher/k3s/agent/etc/containerd/certs.d/harbor.example.com/ca.crt
sudo systemctl restart k3s-agent
```

**Валидация:**
```bash
sudo ctr images list | grep dev-container
# → docker.io/library/dev-container:2026.1.2
# → harbor.example.com/library/dev-container:2026.1.2
```

### Ресурсы нод и планирование

При использовании `hostPath` томов, K3s планирует под на конкретном узле. Если этого узла нет в расписании (неReady, cordoned, drained), под останется в состоянии `Pending`.

**Валидация:**
```bash
kubectl get events -n dev-workspaces --field-selector reason=FailedScheduling
# → 0 Events

kubectl describe node server | grep -A 5 "Allocated resources"
# → Allocated resources:
# →   cpu:                250m (2%)
# →   memory:            500Mi (1%)
# →   ephemeral-storage: 1Gi (1%)
```

### Обновление SSH-ключей без переустановки

Обновите `values.yaml` и выполните `helm upgrade`. Init-контейнер пересоздаст `authorized_keys`.

```bash
helm upgrade dev-container ./dev-container \
  --namespace dev-workspaces \
  --set publicKeys[0]="ssh-ed25519 NEWKEY..."
```

**Валидация:**
```bash
kubectl -n dev-workspaces logs deploy/dev-container-dev-container -c init-ssh
# → + cat <<EOF > /home/developer/.ssh/authorized_keys
# → + ssh-ed25519 NEWKEY...
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
| **Helm SSA** | Конфликты с внешними контроллерами | Используйте `--force-conflicts` только при необходимости; по умолчанию Helm v4 кооперируется с HPA и другими контроллерами. |
| **Init Container** | Побег изоляции через `securityContext` | Всегда задавайте `allowPrivilegeEscalation: false` и `readOnlyRootFilesystem: true`. |
| **CA в образе** | Устаревание корневых сертификатов | Используйте ConfigMap с CA и регулярно обновляйте через `helm upgrade`. |

### Связанные темы

- **Dev-контейнер:** [Создание базового образа с SSH](./dev_container_ssh.md)
- **CI/CD:** [Интеграция GitLab и Harbor](./gitlab_harbor_integration.md)
- **Утилиты:** [Вспомогательный образ kubeutils](./kubeutils_image.md)
- **Хранилище:** [Типы томов в Pod](../../Base/Pod/volume_types/volume_types.md)
- **Helm:** [Структура чарта](../../ToolsUtilities/Helm/helm_chart_structure.md) | [Команды и workflow](../../ToolsUtilities/Helm/helm_commands_and_workflow.md) | [Тесты и хуки](../../ToolsUtilities/Helm/helm_hooks_and_tests.md)
