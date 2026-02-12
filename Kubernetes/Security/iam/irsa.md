# IRSA (IAM Roles for Service Accounts)

## Архитектура IRSA

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

## Настройка IRSA

### Шаг 1: Включить OIDC для EKS кластера

```bash
# Проверить OIDC provider
aws eks describe-cluster --name my-cluster --query "cluster.identity.oidc.issuer"

# Ассоциировать OIDC provider
eksctl utils associate-iam-oidc-provider \
  --cluster my-cluster \
  --approve
```

### Шаг 2: Создать IAM Role для Service Account

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

### Шаг 3: Создать Service Account

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

### Шаг 4: Использовать Service Account в Pod

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

## Как это работает

1. **Pod запускается** с Service Account, имеющей annotation `eks.amazonaws.com/role-arn`

2. **EKS Pod Identity Webhook** автоматически:
   - Монтирует projected volume с Service Account token
   - Устанавливает переменные окружения

3. **AWS SDK в приложении**:
   - Читает токен из файла
   - Вызывает `sts:AssumeRoleWithWebIdentity`
   - Получает временные credentials (15 минут - 1 час)

4. **AWS STS** валидирует JWT token

## Преимущества IRSA

| Преимущество | Описание |
|--------------|----------|
| **Fine-grained access** | Каждый Pod получает только нужные права |
| **Credential isolation** | Нет shared credentials на ноде |
| **Auditability** | CloudTrail показывает, какой SA делал вызов |
| **No secrets** | Нет статических ключей в Kubernetes |
| **Automatic rotation** | Credentials автоматически обновляются |
