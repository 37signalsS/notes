# Безопасность Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes для хранения конфиденциальных данных (пароли, токены, ключи API).

> О шифровании в etcd см. [Хранение в etcd](etcd_storage.md). О создании Secret см. [Создание Secret](creating_secrets.md).

## Основные концепции

### Неизменяемые Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-immutable-secret
immutable: true
data:
  API_KEY: dmFsdWU=
```

**Преимущества:**

- Защита от случайных/вредоносных правок
- Снижение нагрузки на kube-apiserver и kubelet
- Предсказуемость: обновление требует создания нового объекта

> Аналогично для ConfigMap. Подробнее в [ConfigMap](../configmap.md).

## Практические сценарии

### RBAC

Ограничивайте доступ к Secret:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: default
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
```

### Монтирование vs Переменные окружения

**Предпочитайте монтирование как volume:**

- Секреты в tmpfs (RAM), не на диске
- Переменные окружения видны в `/proc/<pid>/environ` и логах
- Ограничение доступа к конкретным ключам

```yaml
spec:
  containers:
  - name: app
    volumeMounts:
    - name: secret-volume
      mountPath: "/etc/secrets"
      readOnly: true
  volumes:
  - name: secret-volume
    secret:
      secretName: my-secret
```

### Защита etcd

Подробнее о защите Secret в etcd см. [Хранение в etcd](etcd_storage.md#шифрование-at-rest-encryption-at-rest).

### CI/CD

- **Никогда не храните манифесты Secret с открытыми данными в Git**
- Используйте внешние хранилища (Vault, Sealed Secrets, External Secrets Operator)
- Применяйте [SOPS (Security)](../../../Security/Tools/sops_overview.md) или git-crypt для шифрования в репозитории

## Дополнительная информация

### Лучшие практики

- Используйте неизменяемые Secrets
- Применяйте принцип минимальных привилегий в RBAC
- Регулярно ротируйте секреты
- Мониторьте доступ (аудит-логи)
- Используйте внешние менеджеры для production

### Связанные темы

[Основы Secret](secrets_basics.md), [Создание Secret](creating_secrets.md), [Использование Secret](using_secrets.md), [Хранение в etcd](etcd_storage.md), [Внешние менеджеры](external_managers.md), [Sealed Secrets](../../Security/sealed_secrets_overview.md), [SOPS](../../../Security/Tools/sops_overview.md), [ConfigMap](../configmap.md), [RBAC](../../Security/rbac/rbac_overview.md).
