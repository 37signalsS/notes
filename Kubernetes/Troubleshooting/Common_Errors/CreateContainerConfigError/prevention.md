# CreateContainerConfigError: Профилактика

## Prevention (Профилактика)

### 1. Валидация манифестов

```bash
# Проверка манифеста перед применением
kubectl apply -f deployment.yaml --dry-run=client

# Проверка с помощью kubeval
kubeval deployment.yaml

# Проверка с помощью kubeconform
kubeconform deployment.yaml
```

### 2. Использование Kustomize

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml

configMapGenerator:
- name: app-config
  literals:
  - DATABASE_URL=postgres://db:5432/mydb

secretGenerator:
- name: db-credentials
  literals:
  - username=admin
  - password=SuperSecret
```

**Применение:**

```bash
kubectl apply -k .
```

### 3. Helm values validation

```yaml
# values.yaml
configMap:
  enabled: true
  data:
    LOG_LEVEL: info

secret:
  enabled: true
  data:
    password: changeme
```

## Best Practices

| Практика | Описание |
|----------|----------|
| **Используйте один namespace** | ConfigMap/Secret должны быть в том же namespace |
| **Валидируйте манифесты** | `kubectl apply --dry-run=client` |
| **Используйте Kustomize/Helm** | Управление зависимостями |
| **Настройте RBAC** | Права для ServiceAccount |
| **Мониторьте события** | Алерты на CreateContainerConfigError |

## Ссылки

- [ConfigMap](https://kubernetes.io/docs/concepts/configuration/configmap/)
- [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [Volumes](https://kubernetes.io/docs/concepts/storage/volumes/)
