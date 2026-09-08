# Установка и конфигурация Karpenter

## Определения

**Karpenter Helm Chart** — официальный пакет для развёртывания контроллера Karpenter в кластере Kubernetes. Он управляет установкой бинарного файла контроллера, Admission Webhooks (для валидации CRD) и необходимых ресурсов RBAC (ClusterRole, RoleBinding). Начиная с ветки v1.x, установка производится исключительно из OCI-репозиториев (Amazon ECR для AWS, Microsoft Container Registry для Azure).

**NodePool** — основной CRD Karpenter, определяющий правила создания и управления узлами. Подробнее: **[Обзор и основные концепции](./overview.md#определения)**.

**NodeClass (EC2NodeClass / AKSNodeClass)** — ресурс, описывающий инфраструктурные параметры узла для конкретного облака. Подробнее: **[Обзор и основные концепции](./overview.md#определения)**.

**NodeClaim** — immutable-объект, представляющий запрос на создание конкретного инстанса. Подробнее: **[Обзор и основные концепции](./overview.md#определения)**.

**Interruption Queue (AWS)** — очередь Amazon SQS, через которую Karpenter получает события прерывания инстансов (Spot Interruption, Scheduled Maintenance, Instance Rebalance). Позволяет начать graceful drain за 2 минуты до принудительного удаления узла.

## Предварительные требования

**Версия Kubernetes** — для стабильной работы ветки v1.14.x требуется Kubernetes версии **1.30+**. Для поддержки In-Place Pod Resizing в связке с VPA необходимы современные версии планировщика.

**Инструменты CLI:**
- `kubectl` версии, совместимой с кластером
- `helm` v3.12+ (поддержка OCI-репозиториев)
- `aws-cli` / `az-cli` с настроенной аутентификацией и достаточными правами

**Аутентификация в облаке:**
- **AWS:** Рекомендуется **EKS Pod Identity**. В отличие от IRSA, Pod Identity не требует сложной настройки Trust Policy с OIDC-провайдером. Права передаются через `aws-eks-pod-identity-agent`.
- **Azure:** Требуется включенный **Workload Identity** и User-Assigned Managed Identity с ролями `Virtual Machine Contributor`, `Network Contributor` и `Managed Identity Operator`.

**Сетевая связность:**
- Узлы должны иметь доступ к API облачного провайдера (EC2 Fleet / Azure VM API) для запуска инстансов.
- Для AWS Interruption Handling: контроллер должен иметь доступ к SQS и EventBridge.

**IAM-роли (AWS):**
1. **KarpenterControllerRole**: права на `ec2:RunInstances`, `ec2:CreateFleet`, `ec2:TerminateInstances`, чтение параметров из SSM и доступ к SQS.
2. **KarpenterNodeRole**: политики `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy` и `AmazonEC2ContainerRegistryReadOnly`.

## Архитектура развёртывания

Karpenter работает как Deployment, обычно с 2 репликами для высокой доступности (HA). Рекомендуется размещать контроллер на системных узлах, которые он не управляет (например, на узлах managed-пула EKS/AKS), чтобы избежать bootstrap-зависимости при пересоздании узлов.

Контроллер не использует стандартный `kube-scheduler` для создания узлов, а реализует собственный цикл «мониторинг -> бинпакинг -> вызов Cloud API». Это позволяет сократить время появления нового узла с 2-3 минут (Cluster Autoscaler) до 45-60 секунд в AWS и <3 минут в Azure.

## Практические сценарии

### Сценарий 1: Установка в AWS EKS

#### Шаг 1: Создание инфраструктуры и Pod Identity

```bash
# Создание роли контроллера
aws iam create-role --role-name KarpenterControllerRole --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "pods.eks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}'

# Создание ассоциации Pod Identity (связывает ServiceAccount 'karpenter' с IAM-ролью)
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --role-arn arn:aws:iam::123456789012:role/KarpenterControllerRole \
  --namespace karpenter \
  --service-account karpenter
```

#### Шаг 2: Установка контроллера через Helm (OCI)

```bash
export KARPENTER_VERSION="1.14.0"

# Логин в ECR Public для предотвращения Rate Limit
aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin oci://public.ecr.aws

# Установка
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "${KARPENTER_VERSION}" \
  --namespace karpenter --create-namespace \
  --set settings.clusterName=my-cluster \
  --set settings.interruptionQueue=my-cluster-sqs-queue \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --wait
```

#### Шаг 3: Конфигурация EC2NodeClass (AWS)

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  amiFamily: AL2023
  amiSelectorTerms:
    - alias: al2023@latest
  role: KarpenterNodeRole
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: my-cluster
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true
        deleteOnTermination: true
  metadataOptions:
    httpEndpoint: enabled
    httpTokens: required
```

#### Шаг 4: Валидация

```bash
# Проверка, что контроллер запущен
kubectl get pods -n karpenter -l app.kubernetes.io/name=karpenter

# Проверка наличия CRD
kubectl get crd nodeclaims.karpenter.sh nodeclasses.karpenter.k8s.aws nodepools.karpenter.sh
```

### Сценарий 2: Установка в Azure AKS

Karpenter для Azure достиг статуса GA в 2026 году. Установка производится из официального OCI-репозитория Microsoft.

#### Шаг 1: Установка контроллера через Helm (Azure OCI)

```bash
export KARPENTER_VERSION="1.14.0"
export CLUSTER_NAME="my-aks-cluster"
export CLUSTER_ENDPOINT=$(az aks show -n $CLUSTER_NAME -g $RG --query fqdn -o tsv)
export IDENTITY_CLIENT_ID=$(az identity show -n karpenter-identity -g $RG --query clientId -o tsv)

helm upgrade --install karpenter oci://mcr.microsoft.com/aks/karpenter/karpenter \
  --version "${KARPENTER_VERSION}" \
  --namespace kube-system \
  --create-namespace \
  --set settings.clusterName="${CLUSTER_NAME}" \
  --set settings.clusterEndpoint="${CLUSTER_ENDPOINT}" \
  --set serviceAccount.annotations."azure\.workload\.identity/client-id"="${IDENTITY_CLIENT_ID}" \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --wait
```

#### Шаг 2: Конфигурация AKSNodeClass (Azure)

```yaml
apiVersion: karpenter.azure.com/v1beta1
kind: AKSNodeClass
metadata:
  name: default
spec:
  imageFamily: Ubuntu
  vnetSubnetID: "/subscriptions/.../resourceGroups/.../providers/Microsoft.Network/virtualNetworks/.../subnets/aks-subnet"
  osDiskSizeGB: 128
  tags:
    ManagedBy: Karpenter
```

#### Шаг 3: Валидация

```bash
# Проверка контроллера
kubectl get pods -n kube-system -l app.kubernetes.io/name=karpenter

# Проверка CRD
kubectl get crd nodeclaims.karpenter.sh nodeclasses.karpenter.azure.com nodepools.karpenter.sh
```

### Сценарий 3: Конфигурация универсального NodePool

Этот NodePool может ссылаться как на `EC2NodeClass`, так и на `AKSNodeClass`.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  limits:
    cpu: 1000
    memory: 1000Gi
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws # Для Azure замените на karpenter.azure.com
        kind: EC2NodeClass       # Для Azure замените на AKSNodeClass
        name: default
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot", "on-demand"]
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64", "arm64"]
      expireAfter: 720h # Ротация узлов каждые 30 дней
      terminationGracePeriod: 48h
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "15%"
      - nodes: "0"
        schedule: "@daily"
        duration: 15m
```

### Сценарий 4: GPU-вычислительные нагрузки

Karpenter позволяет динамически подготавливать узлы с графическими ускорителями для задач рендеринга, научных расчётов, обработки видео и других вычислений, где стоимость простоя оборудования значительна.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-pool
spec:
  template:
    spec:
      requirements:
        - key: "karpenter.k8s.aws/instance-gpu-manufacturer"
          operator: In
          values: ["nvidia"]
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand"]
      taints:
        - key: "nvidia.com/gpu"
          value: "true"
          effect: "NoSchedule"
  disruption:
    consolidationPolicy: WhenEmpty
```

**Особенности:**
- Указание типов инстансов, поддерживающих несколько GPU-устройств на одном хосте.
- Использование `WhenEmpty` для консолидации, чтобы не прерывать длительные вычислительные задачи при недогрузе CPU.

### Сценарий 5: Air-gapped развёртывание

В закрытых контурах без доступа в интернет используется зеркалирование OCI-репозиториев или загрузка чартов в локальный registry.

#### Шаг 1: Экспорт чарта на машине с доступом в интернет

```bash
helm pull oci://public.ecr.aws/karpenter/karpenter --version 1.14.0
# Получен архив karpenter-1.14.0.tgz
```

#### Шаг 2: Импорт в локальный registry

```bash
# Загрузка в локальный registry (например, Harbor или Nexus)
helm push karpenter-1.14.0.tgz oci://registry.internal/helm-charts
```

#### Шаг 3: Установка из локального registry

```bash
helm upgrade --install karpenter oci://registry.internal/helm-charts/karpenter \
  --version 1.14.0 \
  --namespace karpenter --create-namespace \
  --set settings.clusterName=my-cluster \
  --wait
```

Для Azure аналогичный процесс через `mcr.microsoft.com/aks/karpenter/karpenter`.

### Сценарий 6: Обновление и откат версии

#### Обновление

```bash
export NEW_VERSION="1.15.0"

helm upgrade karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "${NEW_VERSION}" \
  --namespace karpenter \
  --set settings.clusterName=my-cluster \
  --wait
```

#### Откат

```bash
export PREVIOUS_VERSION="1.14.0"

helm rollback karpenter ${PREVIOUS_VERSION} -n karpenter --wait
```

Перед обновлением проверяйте [Release Notes](https://karpenter.sh/docs/upgrading/) на предмет breaking changes в CRD API.

### Сценарий 7: GitOps-развёртывание (ArgoCD / Flux)

Karpenter поддерживает установку через стандартные Helm-чарты, что делает его совместимым с любым GitOps-инструментом.

**ArgoCD Application (фрагмент):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: karpenter
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/org/infra-charts.git'
    targetRevision: HEAD
    path: charts/karpenter
    helm:
      releaseName: karpenter
      values: |
        settings:
          clusterName: my-cluster
          interruptionQueue: my-cluster-sqs-queue
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: karpenter
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Для Flux используйте `HelmRepository` и `HelmRelease` из источника `oci://`.

## Валидация установки

После установки проверьте работоспособность Karpenter:

```bash
# 1. Контроллер готов
kubectl get pods -n karpenter -l app.kubernetes.io/name=karpenter
# → Ожидаемый результат: STATUS Running, READY 1/1

# 2. CRD зарегистрированы
kubectl get crd nodeclaims.karpenter.sh nodeclasses.karpenter.k8s.aws nodepools.karpenter.sh
# → Ожидаемый результат: Established True

# 3. Логи контроллера без ошибок
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=50
# → Ожидаемый результат: нет ERROR/WARN за последние 10 строк

# 4. Потенциальный прогон provisioning
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: karpenter-test
spec:
  containers:
  - name: pause
    image: public.ecr.aws/eks-distro/kubernetes/pause:3.7
    resources:
      requests:
        cpu: 1
        memory: 1Gi
  nodeSelector:
    karpenter.sh/nodepool: default
EOF

# 5. Убедитесь, что NodeClaim создан и узел зарегистрировался
kubectl get nodeclaims
kubectl get nodes -l karpenter.sh/nodepool=default
# → Ожидаемый результат: узел в статусе Ready

# 6. Очистка тестового пода
kubectl delete pod karpenter-test
```

## Диагностика и устранение неисправностей

**Проверка логики планирования:**
Если поды висят в `Pending`, проверьте логи контроллера (причина отказа подбора, например "no instance types found").
```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100 -f
```

**Работа с NodeClaims:**
Если инстанс не создается в облаке, `NodeClaim` покажет ошибку API (например, квоты или IAM).
```bash
kubectl get nodeclaims
kubectl describe nodeclaim <name>
```

**Защита от прерываний (Disruption):**
Для временного запрета удаления узла (например, при миграции БД):
```bash
kubectl annotate node <node-name> karpenter.sh/do-not-disrupt=true
```

**Типичные проблемы установки:**

| Симптом | Возможная причина | Решение |
|---------|-----------------|---------|
| Контроллер не стартует (ImagePullBackOff) | Ошибка OCI-репозитория или авторизации | Проверьте `helm registry login`, доступность репозитория |
| Pod Identity ассоциация не применяется | Несовпадение namespace/serviceAccount | Убедитесь, что SA `karpenter` существует в namespace `karpenter` |
| NodePool не создается | CRD не установлены | Проверьте `kubectl get crd` |
| EC2NodeClass отклонен вебхуком | Отсутствуют обязательные поля | Проверьте `role`, `subnetSelectorTerms` |
| Узлы создаются, но не Ready | Проблемы с AMI, kubelet, сетью | Проверьте `kubectl describe node`, логи kubelet |

Общую диагностику работы кластера см. в **[Обзор и основные концепции](./overview.md#диагностика-и-устранение-неисправностей)**.

## Лучшие практики эксплуатации (установка)

1. **Controller Placement**: Запускайте контроллер Karpenter на системных узлах, которые он не управляет (не на Karpenter-пуле). Это предотвращает bootstrap-зависимость при пересоздании узлов.
2. **Helm Values as Code**: Храните `values.yaml` в Git. Используйте差异化 параметров для окружений (dev/staging/prod).
3. **OCIRegistry Auth**: Для продакшена автоматизируйте аутентификацию в ECR/MCR через IRSA или Workload Identity, а не через статические ключи.
4. **Resource Limits**: Устанавливайте `requests` и `limits` на pod контроллера Karpenter для предотвращения прерывания самого автоскейлера.
5. **Namespace Isolation**: Устанавливайте Karpenter в отдельный namespace (`karpenter`), не используйте `default`.

## Откат и очистка

#### Полное удаление Karpenter

```bash
# Удаление Helm-релиза
helm uninstall karpenter -n karpenter

# Удаление CRD (при полном удалении Karpenter из кластера)
kubectl delete crd nodeclaims.karpenter.sh nodeclasses.karpenter.k8s.aws nodepools.karpenter.sh

# Удаление namespace (опционально)
kubectl delete namespace karpenter
```

#### AWS: удаление Pod Identity ассоциации

```bash
aws eks delete-pod-identity-association \
  --cluster-name my-cluster \
  --association-id <association-id>
```

#### Azure: удаление Managed Identity

```bash
az identity delete -n karpenter-identity -g $RG
```

## Ссылки

- **[Обзор и основные концепции Karpenter](./overview.md)** — теоретическая база, архитектура, сравнение с CA.
- **[Официальная документация (v1.x)](https://karpenter.sh/)** — справочник API и инструкции.
- **[AWS Best Practices](https://aws.github.io/aws-eks-best-practices/karpenter/)** — рекомендации по настройке для production-сред.
- **[Karpenter Blueprints](https://github.com/aws-samples/karpenter-blueprints)** — готовые шаблоны от AWS.
