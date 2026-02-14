# Sealed Secrets

## Определения

**Sealed Secrets** — инструмент от Bitnami для безопасного хранения Kubernetes Secrets в публичных Git-репозиториях через асимметричное шифрование.

**SealedSecret** — кастомный ресурс Kubernetes (CRD), содержащий зашифрованные данные секрета.

**Controller** — компонент Sealed Secrets в кластере, управляющий ключами и расшифровкой.

**kubeseal** — CLI-утилита для шифрования Secrets публичным ключом контроллера.

## Основные концепции

### Архитектура и криптографическая схема

Компоненты системы:

| Компонент | Расположение | Функция |
|-----------|--------------|---------|
| Controller | В кластере | Генерация ключей, расшифровка |
| kubeseal | Локально/CI | Шифрование с публичным ключом |
| SealedSecret | Git-репозиторий | Безопасное хранение |
| Secret | В кластере | Расшифрованный секрет для Pod'ов |

### Гибридная схема шифрования

Для каждого значения секрета:
1. Генерация случайного симметричного ключа
2. Шифрование данных AES-GCM симметричным ключом
3. Шифрование симметричного ключа RSA-OAEP публичным ключом контроллера
4. Привязка к имени и namespace секрета (контекст)

### Области шифрования (Scope)

| Режим | Привязка | Переносимость | Назначение |
|-------|----------|---------------|------------|
| `strict` (по умолчанию) | Имя + namespace | Нет | Максимальная безопасность |
| `namespace-wide` | Только namespace | Ограниченная | Переименование секрета |
| `cluster-wide` | Нет | Высокая | Редко используется |

### Жизненный цикл

1. **Создание**: Разработчик создаёт обычный Secret
2. **Шифрование**: `kubeseal` шифрует с публичным ключом
3. **Хранение**: SealedSecret коммитится в Git
4. **Деплой**: Применяется в кластер (kubectl/GitOps)
5. **Расшифровка**: Controller создаёт Secret
6. **Использование**: Pod'ы получают доступ к Secret

## Практические сценарии

### Сценарий 1: Установка контроллера

```bash
# Установка с помощью Helm 3
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm repo update
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets
```

### Сценарий 2: Шифрование секрета

```bash
# Получение публичного ключа контроллера
kubeseal --controller-name=sealed-secrets \
  --controller-namespace=kube-system \
  --fetch-cert > pub-cert.pem

# Создание и шифрование секрета
kubectl create secret generic my-secret \
  --from-literal=password='supersecret' \
  --dry-run=client -o yaml | \
  kubeseal --cert pub-cert.pem --format yaml > my-sealed-secret.yaml

# Результат безопасен для Git
kubectl apply -f my-sealed-secret.yaml
```

Полученный манифест:
```yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: my-secret
  namespace: default
spec:
  encryptedData:
    password: AgByM4hO...
  template:
    metadata:
      name: my-secret
      namespace: default
```

### Сценарий 3: RBAC для CI/CD

Ограничение прав CI-системы только созданием SealedSecret:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-sealed-writer
  namespace: app
rules:
- apiGroups: ["bitnami.com"]
  resources: ["sealedsecrets"]
  verbs: ["create", "get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-sealed-writer
  namespace: app
subjects:
- kind: ServiceAccount
  name: ci-runner
  namespace: app
roleRef:
  kind: Role
  name: ci-sealed-writer
  apiGroup: rbac.authorization.k8s.io
```

Подробнее о RBAC: [RBAC Overview](../rbac/rbac_overview.md), [Role и ClusterRole](../rbac/roles.md), [Привязки](../rbac/bindings.md)

### Сценарий 4: GitOps-интеграция

```yaml
# ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: main
    path: overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

В репозитории:
```
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── sealed-secret.yaml  # Безопасно хранить в Git
└── overlays/
    └── production/
        └── kustomization.yaml
```

### Сценарий 5: Ротация ключей

```bash
# Проверка текущего сертификата
kubeseal --fetch-cert --controller-namespace=kube-system

# Перешифрование на новый ключ
kubeseal --re-encrypt < old.sealed.yaml > new.sealed.yaml

# Обновление в Git и применение
kubectl apply -f new.sealed.yaml
```

## Дополнительная информация

### Преимущества

- **Безопасность**: Секреты в открытом виде никогда не попадают в Git
- **Декларативность**: Часть GitOps-процесса
- **Аудит**: История изменений через Git
- **Изоляция**: Каждый кластер имеет уникальную ключевую пару

### Модель угроз

| Угроза | Уровень | Митигация |
|--------|---------|-----------|
| Компрометация приватного ключа | Критический | Защита [RBAC](../rbac/rbac_overview.md), etcd encryption |
| Перенос между кластерами | Низкий | Кластеры изолированы по дизайну |
| Утечка в Git | Низкий | Данные зашифрованы |
| Физический доступ к etcd | Средний | Encryption at rest |

### Ограничения

- Нет фильтрации по FQDN/доменам (L3/L4 только)
- Требует поддержки со стороны CNI
- Не работает с Flannel

### Альтернативы

- **External Secrets Operator** — интеграция с внешними KMS
- **SOPS** — шифрование с ключами AWS/GCP/Azure
- **Vault** — полноценное secrets management

### Связанные темы

- Сетевая изоляция: [NetworkPolicy](../network_policies.md)
- Управление доступом: [RBAC Overview](../rbac/rbac_overview.md)
- Ограничения RBAC: [Недостатки RBAC и OPA](../rbac/limitations_opa.md)
- [Sealed Secrets GitHub](https://github.com/bitnami-labs/sealed-secrets)
