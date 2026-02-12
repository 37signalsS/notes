# Pod IAM: IRSA, Kube2iam и Kiam - Обзор

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
