# vCluster — безопасность и синхронизация

## Определения

**ResourceQuota (Ресурсные квоты)** — объект Kubernetes в хост-кластере, ограничивающий суммарное потребление ресурсов (процессорное время, память) и общее количество объектов (Pods, Services, Secrets) внутри пространства имен, выделенного под виртуальный кластер.

**LimitRange (Диапазоны ограничений)** — ресурс внутри виртуального кластера, устанавливающий значения по умолчанию (requests/limits) и допустимые пороги для контейнеров. Позволяет контролировать "раздувание" ресурсов внутри vCluster.

**Rootless Mode (Безрутовый режим)** — конфигурация эксплуатации, при которой процессы API-сервера и синхронизатора запускаются с UID/GID не-привилегированного пользователя. Это предотвращает возможность атаки типа Container Escape с получением прав root на узле хоста.

**Generic Sync (Универсальная синхронизация)** — механизм v0.20+, позволяющий синхронизировать Custom Resource Definitions (CRD) и их объекты между виртуальным и хостовым кластерами без написания кастомного кода.

## Основные концепции

### Направления синхронизации

Синхронизатор (Syncer) работает по двум основным векторам:

1. **toHost (vCluster → Host):** репликация рабочих нагрузок. Syncer создает "теневые" поды в хост-кластере, которые фактически выполняются на узлах.
2. **fromHost (Host → vCluster):** импорт ресурсов окружения. Позволяет виртуальному кластеру видеть системные объекты хоста (StorageClasses, Nodes).

### Изоляция Control Plane

В версии v0.20+ усилена сетевая изоляция. Параметр `isolatedControlPlane` блокирует прямой доступ подов виртуального кластера к API-серверу хост-кластера, заставляя их взаимодействовать только с локальным API-сервером vCluster.

### Механизм патчей ресурсов (Resource Patching)

vCluster позволяет модифицировать объекты "на лету" при синхронизации. Это используется для добавления специфических аннотаций, меток (labels) или изменения конфигурации ресурсов (например, добавление Sidecar-контейнеров) при их переносе в хост-кластер.

## Практические сценарии

### Настройка политик и квот в vcluster.yaml

В новом формате конфигурации управление ресурсами централизовано:

```yaml
# vcluster.yaml
policies:
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "8"
      requests.memory: 16Gi
      pods: "100"
  limitRange:
    enabled: true
    default:
      cpu: 1000m
      memory: 1Gi
    defaultRequest:
      cpu: 200m
      memory: 256Mi
```

### Реализация сетевой изоляции и Rootless Mode

Настройка максимального уровня безопасности для Control Plane:

```yaml
# vcluster.yaml
controlPlane:
  statefulSet:
    securityContext:
      runAsUser: 10000
      runAsNonRoot: true
  
networking:
  # Полная изоляция от API хост-кластера
  isolatedControlPlane:
    enabled: true
```

### Синхронизация Custom Resources (Generic Sync)

Пример синхронизации объектов Cert-Manager из виртуального кластера в хостовый:

```yaml
# vcluster.yaml
sync:
  generic:
    config: |-
      - apiVersion: cert-manager.io/v1
        kind: Certificate
        # Синхронизировать объекты этого типа в хост-кластер
```

### Использование патчей ресурсов

Пример автоматического добавления метки ко всем подам, синхронизируемым в хост-кластер:

```yaml
# vcluster.yaml
sync:
  toHost:
    pods:
      enabled: true
      patches:
        - op: add
          path: metadata.labels.vcluster-instance
          value: "team-alpha-prod"
```

## Лучшие практики безопасности

- **Минимизация Syncer прав:** по умолчанию vCluster требует широких прав в своем namespace. Используйте `controlPlane.serviceAccount.name` для подключения SA с минимально необходимым набором RBAC-ролей.
- **Поддержка Pod Security Standards:** используйте `podSecurityStandard: baseline` или `restricted` в конфигурации vCluster для автоматического применения политик безопасности Kubernetes к виртуальным нагрузкам.
- **Изоляция хранилищ:** при импорте `PersistentVolumes` через `fromHost` убедитесь, что политики доступа запрещают одному vCluster монтировать тома, принадлежащие другому виртуальному кластеру.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)

### Внешние ссылки

- [vCluster Security Official Docs](https://www.vcluster.com/docs/architecture/security)
- [Generic Resource Sync Guide](https://www.vcluster.com/docs/config/sync/generic-resources)
- [Network Isolation Features](https://www.vcluster.com/docs/features/network-isolation)
