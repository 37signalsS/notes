# Лучшие практики Pod IAM

## 1. Использовать IRSA в EKS

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

## 2. Минимальные права (Least Privilege)

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

## 3. Namespace isolation

```yaml
# Отдельный SA для каждого namespace
apiVersion: v1
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

## 4. Мониторинг

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
