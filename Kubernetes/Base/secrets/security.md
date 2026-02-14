# Безопасность Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes для хранения конфиденциальных данных (пароли, токены, ключи API).

> О шифровании в etcd см. [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Шифрование в etcd (Encryption at Rest)

Базовый уровень защиты: API-сервер шифрует Secret перед сохранением в etcd и расшифровывает при чтении.

Настраивается через `--encryption-provider-config`.

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

- **Всегда включайте Encryption at Rest**
- Ограничьте доступ к etcd только API-серверу
- Регулярно ротируйте ключи шифрования
- Используйте отдельные диски с шифрованием

### CI/CD

- **Никогда не храните манифесты Secret с открытыми данными в Git**
- Используйте внешние хранилища (Vault, Sealed Secrets, External Secrets Operator)
- Применяйте git-crypt или sops для шифрования в репозитории

## Дополнительная информация

### Ограничение размера

Размер Secret: **до 1 MiB**. Для больших данных:
- ConfigMap с `binaryData` для неконфиденциальных бинарных данных
- Внешние хранилища через CSI-драйверы

### Лучшие практики

- Используйте неизменяемые Secrets
- Применяйте принцип минимальных привилегий в RBAC
- Регулярно ротируйте секреты
- Мониторьте доступ (аудит-логи)
- Используйте внешние менеджеры для production

### Связанные темы

- [Основы Secret](secrets_basics.md)
- [Создание Secret](creating_secrets.md)
- [Использование Secret](using_secrets.md)
- [Хранение в etcd](etcd_storage.md)
- [Внешние менеджеры](external_managers.md)
- [ConfigMap](../configmap.md)
