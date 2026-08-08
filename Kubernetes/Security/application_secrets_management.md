# Управление секретами и конфигурациями приложений

## Определения

- **Secret**: Объект Kubernetes для хранения конфиденциальных данных (пароли, токены). Данные кодируются в base64, но по умолчанию не шифруются в etcd.
- **ConfigMap**: Ресурс для хранения несекретных конфигураций. Позволяет отделить параметры запуска от кода и образа контейнера.
- **initContainer**: Вспомогательный контейнер, завершающий работу до старта основного приложения. Идеален для подготовки конфигов.
- **Sidecar Container (Native)**: Начиная с Kubernetes 1.28, sidecar-контейнеры имеют собственный жизненный цикл (`restartPolicy: Always` внутри `initContainers`) и могут работать на протяжении всей жизни пода, обеспечивая, например, динамическое обновление секретов.
- **Secrets Store CSI Driver**: Механизм монтирования секретов из внешних хранилищ (Vault, AWS KMS) напрямую в файловую систему пода как том (tmpfs).
- **Vault Secrets Operator (VSO)**: Современный оператор для синхронизации секретов из HashiCorp Vault в нативные объекты `Secret` Kubernetes с поддержкой автоматической ротации.
- **Immutable Secrets/ConfigMaps**: Ресурсы, помеченные как `immutable: true`. Они запрещают изменение данных, что снижает нагрузку на `kube-apiserver` (kubelet не опрашивает их на предмет изменений) и предотвращает случайные ошибки при обновлении.

**Важно:** Этот документ описывает паттерны *доставки* и *потребления* секретов приложениями. Для стратегий хранения в Git см. [Sealed Secrets](./sealed_secrets_overview.md) или [SOPS](../../Security/Tools/sops_overview.md).

## Основные концепции

Проблема "секретов в коде" решается разделением ответственности между инфраструктурой и приложением. Существует два основных подхода к доставке секретов:

### 1. Модель синхронизации (Push/Pull)
Внешний оператор (ESO, VSO) считывает данные из внешнего хранилища и создает нативный `Secret` в Kubernetes.
- **Плюсы**: Приложению не нужны специальные библиотеки; стандартная работа через `env` или `volume`.
- **Минусы**: Секреты хранятся в etcd (нужно шифрование etcd); администраторы кластера могут их прочитать.

### 2. Модель прямого монтирования (CSI)
Секреты монтируются напрямую из внешнего хранилища в память пода.
- **Плюсы**: Секреты никогда не попадают в etcd и API Kubernetes; максимальная безопасность.
- **Минусы**: Сложнее в настройке; требует установки CSI-драйверов на узлы.

### Паттерн динамической генерации
Если приложение ожидает специфический формат файла (например, `.ini` или `.properties`) с подставленными секретами, используется `initContainer` для генерации финального конфига из шаблона.

## Практические сценарии

### Сценарий 1: Генерация конфига через `envsubst` (Рекомендуемый для шаблонов)

Использование `envsubst` (пакет `gettext`) позволяет элегантно подставлять переменные окружения в шаблон.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  initContainers:
  - name: config-builder
    image: alpine:3.18
    command: ['sh', '-c']
    args:
      - apk add --no-cache gettext && envsubst < /tmpl/config.yaml.tmpl > /config/config.yaml
    envFrom:
    - secretRef:
        name: my-db-secrets
    volumeMounts:
    - name: template-vol
      mountPath: /tmpl
    - name: config-vol
      mountPath: /config
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: config-vol
      mountPath: /app/config
  volumes:
  - name: template-vol
    configMap:
      name: app-config-template
  - name: config-vol
    emptyDir:
      medium: Memory # Важно: храним секрет только в RAM
```

### Сценарий 2: Использование Native Sidecar (K8s 1.28+)

Для приложений, требующих динамического обновления секретов без перезагрузки, можно использовать нативные sidecar-контейнеры.

```yaml
initContainers:
- name: vault-agent
  image: hashicorp/vault-agent:latest
  restartPolicy: Always # Делает контейнер sidecar-ом
  args: ["agent", "-config=/etc/vault/config.hcl"]
  volumeMounts:
  - name: config-vol
    mountPath: /app/config
```

### Сценарий 3: Secrets Store CSI Driver (Максимальная безопасность)

Этот метод исключает создание `Secret` в Kubernetes. Приложение видит секреты как файлы в `/mnt/secrets-store`.

1. **SecretProviderClass**: Описывает, что и откуда брать (например, из Vault).
2. **Монтирование в Pod**:
```yaml
spec:
  containers:
  - name: app
    volumeMounts:
    - name: secrets-store-inline
      mountPath: "/mnt/secrets-store"
      readOnly: true
  volumes:
    - name: secrets-store-inline
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "vault-db-creds"
```
Подробнее см. в [Внешние менеджеры секретов](../Base/secrets/external_managers.md).

## Дополнительная информация

### Безопасность и оптимизация
- **RBAC**: Ограничивайте доступ к объектам `Secret`. Только ServiceAccount, от имени которого работает под, должен иметь права `get` на нужные секреты. См. [RBAC](./rbac/rbac_overview.md).
- **Memory-backed emptyDir**: Всегда используйте `medium: Memory` для томов, содержащих временные файлы с секретами. Это предотвращает утечку данных на диск (особенно на HDD/SSD без шифрования).
- **Immutable ресурсы**: Если конфигурация или секрет не должны меняться в течение жизненного цикла пода, установите `immutable: true`. Это защищает от случайных изменений и снижает нагрузку на API.
- **Security Context**:
  - `runAsNonRoot: true`: Запускайте контейнеры от не-привилегированных пользователей.
  - `fsGroup`: Используйте для предоставления прав на чтение томов с секретами определенной группе пользователей.
  - `readOnlyRootFilesystem: true`: Рекомендуется для минимизации поверхности атаки.

### Проверка и отладка
- **Отсутствие секрета**: Если под висит в `CreateContainerConfigError`, проверьте наличие Secret/ConfigMap через `kubectl get secret`.
- **Ошибки монтирования**: При использовании CSI драйверов ошибки логируются в событиях пода (`kubectl describe pod`) или в логах драйвера (DaemonSet в namespace `kube-system`).

### См. также
- **[Основы Kubernetes Secret](../Base/secrets/secrets_basics.md)** — типы и базовое использование.
- **[Безопасность Secret в Kubernetes](../Base/secrets/security.md)** — шифрование etcd и RBAC.
- **[Внешние менеджеры секретов](../Base/secrets/external_managers.md)** — детали работы ESO и CSI Driver.
- **[Sealed Secrets](./sealed_secrets_overview.md)** — хранение зашифрованных секретов в Git.
- **[Интеграция Vault и Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)** — глубокое погружение в Vault.
