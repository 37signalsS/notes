# Pod IAM: IRSA, Kube2iam и Kiam

## Определения

**Pod IAM (Identity and Access Management)** — это практика предоставления Kubernetes Pods минимально необходимых IAM-прав для доступа к облачным ресурсам (S3, DynamoDB, RDS и т.д.) без использования долгоживущих credentials.

**IRSA (IAM Roles for Service Accounts)** — нативное решение AWS EKS для предоставления IAM-ролей Kubernetes Service Accounts через OIDC (OpenID Connect) federation.

**Kube2iam** — старое решение для назначения IAM-ролей Pods через annotations (deprecated).

**Kiam** — улучшенная версия kube2iam с серверной архитектурой и кэшированием (deprecated).

## Проблема: Доступ к AWS ресурсам из Kubernetes

### Антипаттерн: Hardcoded credentials

```yaml
# ❌ ПЛОХО: Статические ключи в secrets
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials
type: Opaque
data:
  AWS_ACCESS_KEY_ID: QUtJQVNERVZHVFlPVVJLRVk=  # base64
  AWS_SECRET_ACCESS_KEY: c2VjcmV0LWFjY2Vzcy1rZXk=  # base64
```

**Проблемы:**
- Ключи никогда не истекают
- Сложно ротировать
- Утечка = компрометация аккаунта
- Не масштабируется

### Антипаттерн: Node IAM Role

```yaml
# ❌ ПЛОХО: Использование Node IAM Role всеми Pods
# Все Pods получают права ноды (слишком широкие)
```

**Проблемы:**
- Нарушение least privilege
- Нет изоляции между workloads
- Сложно аудитировать

## IRSA (IAM Roles for Service Accounts)

### Архитектура IRSA

```
┌─────────────────────────────────────────────────────────────┐
│                    AWS CLOUD                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   IAM Role   │  │   OIDC IdP   │  │   S3, RDS    │      │
│  │  (pod-role)  │  │  (EKS OIDC)  │  │   etc.       │      │
│  └──────┬───────┘  └──────┬───────┘  └──────▲───────┘      │
│         │                 │                  │              │
│         │ Trust Policy    │ Issuer URL       │ AWS API      │
│         │ (oidc:sub)      │ JWKS endpoint    │ calls        │
└─────────┼─────────────────┼──────────────────┼──────────────┘
          │                 │                  │
          │                 │                  │
┌─────────┼─────────────────┼──────────────────┼──────────────┐
│         │                 │                  │              │
│  ┌──────▼───────┐  ┌─────▼──────┐  ┌────────┴────────┐     │
│  │   AWS STS    │  │  EKS API   │  │   Pod with SDK  │     │
│  │  AssumeRole  │◄─┤  Server    │  │   (AWS SDK)     │     │
│  │  with WebId  │  │            │  │                 │     │
│  └──────┬───────┘  └────────────┘  └─────────────────┘     │
│         │                              │                   │
│         │ AssumeRoleWithWebIdentity    │ Service Account   │
│         │                            JWT Token           │
│         │                                  │              │
│         └──────────────────────────────────┘              │
│                        Temporary Credentials              │
│                        (AccessKey, SecretKey, Token)      │
└─────────────────────────────────────────────────────────────┘
```

### Настройка IRSA

#### Шаг 1: Включить OIDC для EKS кластера

```bash
# Проверить OIDC provider
aws eks describe-cluster --name my-cluster --query "cluster.identity.oidc.issuer"

# Ассоциировать OIDC provider
eksctl utils associate-iam-oidc-provider \
  --cluster my-cluster \
  --approve

# Или через AWS CLI
aws iam create-open-id-connect-provider \
  --url https://oidc.eks.region.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E \
  --thumbprint-list 9e99a48a9960b14926bb7f3b02e22da2b0ab7280 \
  --client-id-list sts.amazonaws.com
```

#### Шаг 2: Создать IAM Role для Service Account

```bash
# Trust policy для IAM Role
cat > trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/oidc.eks.region.amazonaws.com/id/EXAMPLE"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.region.amazonaws.com/id/EXAMPLE:sub": "system:serviceaccount:default:my-service-account",
          "oidc.eks.region.amazonaws.com/id/EXAMPLE:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
EOF

# Создать IAM Role
aws iam create-role \
  --role-name my-pod-role \
  --assume-role-policy-document file://trust-policy.json

# Добавить политики
aws iam attach-role-policy \
  --role-name my-pod-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
```

#### Шаг 3: Создать Service Account

```bash
# С помощью eksctl (рекомендуется)
eksctl create iamserviceaccount \
  --name my-service-account \
  --namespace default \
  --cluster my-cluster \
  --attach-role-arn arn:aws:iam::123456789012:role/my-pod-role \
  --approve

# Или вручную
kubectl apply -f - << EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-service-account
  namespace: default
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/my-pod-role
EOF
```

#### Шаг 4: Использовать Service Account в Pod

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      serviceAccountName: my-service-account  # <-- IRSA здесь!
      containers:
      - name: app
        image: my-app:latest
        env:
        - name: AWS_REGION
          value: "us-west-2"
```

### Как это работает

1. **Pod запускается** с Service Account, имеющей annotation `eks.amazonaws.com/role-arn`

2. **EKS Pod Identity Webhook** автоматически:
   - Монтирует projected volume с Service Account token
   - Устанавливает переменные окружения:
     ```
     AWS_ROLE_ARN=arn:aws:iam::123456789012:role/my-pod-role
     AWS_WEB_IDENTITY_TOKEN_FILE=/var/run/secrets/eks.amazonaws.com/serviceaccount/token
     ```

3. **AWS SDK в приложении**:
   - Читает токен из файла
   - Вызывает `sts:AssumeRoleWithWebIdentity`
   - Получает временные credentials (15 минут - 1 час)

4. **AWS STS** валидирует:
   - JWT token подписан OIDC provider
   - `sub` claim совпадает с `system:serviceaccount:<ns>:<sa>`
   - `aud` claim = `sts.amazonaws.com`

### Преимущества IRSA

| Преимущество | Описание |
|--------------|----------|
| **Fine-grained access** | Каждый Pod получает только нужные права |
| **Credential isolation** | Нет shared credentials на ноде |
| **Auditability** | CloudTrail показывает, какой SA делал вызов |
| **No secrets** | Нет статических ключей в Kubernetes |
| **Automatic rotation** | Credentials автоматически обновляются |
| **Standard AWS SDK** | Работает с любым AWS SDK без изменений |

## Kube2iam (Deprecated)

```
Архитектура Kube2iam:

┌─────────────────────────────────────────────────────────────┐
│                    KUBERNETES NODE                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Pod A     │  │   Pod B     │  │   Pod C     │         │
│  │ (iam-role-a)│  │ (iam-role-b)│  │ (iam-role-c)│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                │
│         │                │                │                │
│         └────────────────┼────────────────┘                │
│                          │ IPtables/NFTABLES               │
│                          │ (redirect 169.254.169.254)       │
│                          ▼                                │
│                   ┌──────────────┐                        │
│                   │  Kube2iam    │                        │
│                   │   Daemon     │                        │
│                   │ (hostNetwork)│                        │
│                   └──────┬───────┘                        │
│                          │                                │
└──────────────────────────┼────────────────────────────────┘
                           │ STS AssumeRole
                           ▼
                    ┌──────────────┐
                    │   AWS IAM    │
                    └──────────────┘
```

### Проблемы Kube2iam

1. **Security**: Pod может получить credentials другого Pod
2. **Reliability**: Kube2iam pod failure = нет доступа
3. **Complexity**: iptables rules, host networking
4. **Deprecated**: AWS не рекомендует использовать

```yaml
# Пример использования kube2iam (устаревший)
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
  annotations:
    iam.amazonaws.com/role: my-role  # <-- Kube2iam annotation
spec:
  containers:
  - name: app
    image: my-app
```

## Kiam (Deprecated)

### Архитектура Kiam (Server-Agent)

```
┌─────────────────────────────────────────────────────────────┐
│                    KUBERNETES CLUSTER                       │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Pod A     │    │   Pod B     │    │   Pod C     │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │            │
│         │ gRPC             │ gRPC             │ gRPC       │
│         └──────────────────┼──────────────────┘            │
│                            │                              │
│                   ┌────────▼────────┐                     │
│                   │   Kiam Agent    │  (DaemonSet)        │
│                   │   (gRPC proxy)  │                     │
│                   └────────┬────────┘                     │
│                            │                              │
│         ┌──────────────────┼──────────────────┐           │
│         │                  │                  │           │
│  ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐    │
│  │Kiam Server 1│    │Kiam Server 2│    │Kiam Server 3│    │
│  │  (cache)    │    │  (cache)    │    │  (cache)    │    │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    │
│         │                  │                  │           │
└─────────┼──────────────────┼──────────────────┼───────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │ STS AssumeRole
                             ▼
                      ┌──────────────┐
                      │   AWS IAM    │
                      └──────────────┘
```

### Преимущества Kiam над Kube2iam

- **Server-Agent архитектура**: Better reliability
- **Credential caching**: Reduced STS calls
- **Granular policies**: Server-side enforcement
- **Audit logging**: Centralized logging

**Но все равно deprecated в пользу IRSA**

## Сравнение решений

| Критерий | IRSA | Kube2iam | Kiam |
|----------|------|----------|------|
| **AWS Native** | ✅ Да | ❌ Нет | ❌ Нет |
| **Fine-grained** | ✅ Pod level | ✅ Pod level | ✅ Pod level |
| **Security** | ✅ OIDC-based | ⚠️ IP-based | ⚠️ gRPC proxy |
| **Reliability** | ✅ No single point | ❌ Daemon failure | ⚠️ Server failure |
| **Complexity** | ✅ Low | ⚠️ Medium | ⚠️ High |
| **Multi-cloud** | ❌ AWS only | ✅ Any cloud | ✅ Any cloud |
| **Status** | ✅ Рекомендуется | ❌ Deprecated | ❌ Deprecated |

## Лучшие практики

### 1. Использовать IRSA в EKS

```bash
# Проверить, что IRSA работает
kubectl exec -it my-pod -- aws sts get-caller-identity

# Должно показать:
# {
#   "UserId": "AROA1234567890:my-service-account",
#   "Account": "123456789012",
#   "Arn": "arn:aws:sts::123456789012:assumed-role/my-pod-role/my-service-account"
# }
```

### 2. Минимальные права (Least Privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::my-bucket/data/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control"
        }
      }
    }
  ]
}
```

### 3. Namespace isolation

```yaml
# Отдельный SA для каждого namespace/apiVersion: v1
kind: ServiceAccount
metadata:
  name: backend-sa
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/prod-backend-role
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: backend-sa
  namespace: staging
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/staging-backend-role
```

### 4. Мониторинг

```yaml
# CloudWatch Alarm на STS calls
Resources:
  STSAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      MetricName: AssumeRoleWithWebIdentity
      Namespace: AWS/STS
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 1000
      ComparisonOperator: GreaterThanThreshold
```

## Дополнительная информация

- [EKS IRSA Documentation](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [AWS OIDC Provider](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [IRSA Deep Dive](https://aws.amazon.com/blogs/opensource/introducing-fine-grained-iam-roles-service-accounts/)
