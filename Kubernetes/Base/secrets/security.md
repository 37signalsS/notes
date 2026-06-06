# Безопасность Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes, предназначенный для хранения конфиденциальной информации, такой как пароли, OAuth-токены, SSH-ключи и API-ключи.

**Безопасность секретов** — комплекс мер по защите данных от несанкционированного доступа, компрометации etcd и случайного раскрытия в логах или системах контроля версий.

> О создании секретов см. [Создание Secret](creating_secrets.md). О принципах хранения см. [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Неизменяемые секреты (Immutable Secrets)

Начиная с Kubernetes 1.21, секреты можно помечать как неизменяемые.

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
- **Защита от изменений:** предотвращает случайное или злонамеренное обновление данных.
- **Производительность:** `kubelet` перестает опрашивать `kube-apiserver` на предмет обновлений для этих секретов, что снижает нагрузку на Control Plane.

### Шифрование при хранении (Encryption at Rest)

По умолчанию секреты хранятся в etcd в формате base64 (незашифрованном). Для защиты данных необходимо включить шифрование на уровне `kube-apiserver` с помощью `EncryptionConfiguration`.

Подробнее: [Хранение в etcd (Шифрование)](etcd_storage.md#шифрование-at-rest-encryption-at-rest).

### Принцип минимальных привилегий

Доступ к секретам должен быть ограничен только теми Pod и пользователями, которым это необходимо для работы. Это достигается через тонкую настройку RBAC и использование сервисных аккаунтов.

## Практические сценарии

### Ограничение доступа через RBAC

Используйте Roles и ClusterRoles для ограничения `verbs` (get, list, watch) на ресурс `secrets`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: prod
  name: app-secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"] # Только чтение конкретного секрета, а не список всех
```

### Монтирование в Volume против переменных окружения

**Рекомендуемый метод:** монтирование секретов как Volume.

- **Безопасность:** секреты монтируются в `tmpfs` (оперативную память) и не записываются на диск узла.
- **Скрытость:** переменные окружения часто попадают в логи приложений, дампы памяти и видны через `/proc/1/environ`.
- **Обновление:** при изменении секрета файл в Volume обновляется автоматически (для неизменяемых — нет), в то время как переменные окружения требуют перезапуска контейнера.

```yaml
spec:
  containers:
  - name: my-app
    volumeMounts:
    - name: secret-vol
      mountPath: "/etc/secrets"
      readOnly: true
  volumes:
  - name: secret-vol
    secret:
      secretName: my-db-secret
```

### Использование внешних менеджеров (External Secrets)

Для Production рекомендуется хранить секреты во внешних защищенных хранилищах (HashiCorp Vault, AWS Secrets Manager, Google Secret Manager).

**Инструменты интеграции:**
- **External Secrets Operator (ESO):** синхронизирует секреты из внешних систем в нативные `Secret` Kubernetes.
- **Secrets Store CSI Driver:** монтирует секреты напрямую в Pod из внешнего хранилища без создания объекта `Secret`.

Подробнее: [Внешние менеджеры](external_managers.md).

### Безопасность в CI/CD и GitOps

Никогда не храните секреты в Git в открытом виде.

1. **[Sealed Secrets](../../Security/sealed_secrets_overview.md):** шифрование секрета с использованием публичного ключа контроллера. Расшифровать может только контроллер внутри кластера.
2. **[SOPS (Secrets Operations)](../../../Security/Tools/sops_overview.md):** шифрование файлов с использованием KMS, PGP или age.
3. **Vault Agent / Injector:** автоматическая вставка секретов в Pod на этапе деплоя.

## Дополнительная информация

### Лучшие практики

- **Регулярная ротация:** автоматизируйте смену паролей и ключей.
- **Аудит доступа:** включите K8s Audit Logs для отслеживания того, кто и когда обращался к секретам.
- **Очистка истории:** если секрет попал в Git, считайте его скомпрометированным и немедленно смените его.
- **Использование сервисных аккаунтов:** привязывайте права доступа к конкретным SA приложений.

### Связанные темы

[Основы Secret](secrets_basics.md), [Создание Secret](creating_secrets.md), [Использование Secret](using_secrets.md), [Хранение в etcd](etcd_storage.md), [Внешние менеджеры](external_managers.md), [Sealed Secrets](../../Security/sealed_secrets_overview.md), [SOPS](../../../Security/Tools/sops_overview.md), [ConfigMap](../configmap.md), [RBAC](../../Security/rbac/rbac_overview.md).
