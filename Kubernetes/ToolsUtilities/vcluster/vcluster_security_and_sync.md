# vCluster — безопасность и синхронизация

## Определения

**Pod Security Admission (PSA)** — встроенный механизм Kubernetes (v0.35+ полностью интегрирован в vCluster), позволяющий применять стандарты безопасности (Privileged, Baseline, Restricted) на уровне виртуального кластера. Автоматически блокирует запуск небезопасных подов внутри vCluster.

**ResourceQuota (Ресурсные квоты)** — объект в хост-кластере, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество объектов) пространством имен, в котором работает vCluster.

**LimitRange (Диапазоны ограничений)** — политика внутри vCluster, устанавливающая значения по умолчанию и границы для ресурсов подов тенанта.

**Generic Sync (Нативная синхронизация CRD)** — механизм (v0.35+), позволяющий декларативно синхронизировать произвольные Custom Resource Definitions (например, Cert-Manager, Istio) между виртуальным и хостовым окружениями без внешних плагинов.

**Sync Patches (CEL-патчи)** — инструмент модификации ресурсов "на лету" при синхронизации, использующий Common Expression Language (CEL). Позволяет динамически изменять поля объектов (например, добавлять префиксы к именам секретов) при их переносе на хост.

**Namespace 1:1 Syncing** — режим работы, при котором пространства имен внутри vCluster отображаются в хост-кластер без изменения имен (no rewriting), что упрощает работу инструментов безопасности и мониторинга.

**Rootless Mode (Безрутовый режим)** — запуск компонентов vCluster с минимальными привилегиями (non-root UID/GID) для минимизации рисков при потенциальном взломе контейнера.

## Основные концепции

### Векторы синхронизации

Синхронизатор (Syncer) управляет потоками данных между плоскостями:

1.  **toHost (vCluster → Host):** Репликация подов, сервисов и маршрутов. Syncer создает "теневые" объекты на хосте для фактического исполнения нагрузки.
2.  **fromHost (Host → vCluster):** Импорт инфраструктурных ресурсов (StorageClasses, Nodes, ClusterIssuers). Позволяет тенантам использовать ресурсы физического кластера.

### Изоляция и стандарты безопасности (PSS)

vCluster v0.35+ поддерживает автоматическое применение **Pod Security Standards**. При установке уровня `restricted` в конфигурации, виртуальный API-сервер будет отклонять любые запросы на создание подов, не соответствующих жестким требованиям безопасности (запрет root, hostPath, привилегий).

### Динамическая модификация (Resource Patching)

Патчи позволяют адаптировать ресурсы виртуального кластера под требования хоста.
- **Маскировка имен:** Добавление уникальных суффиксов к именам ресурсов для предотвращения коллизий.
- **Изменение типов:** Например, принудительное преобразование `LoadBalancer` в `ClusterIP` при синхронизации на хост для экономии публичных IP.
- **Инъекция Sidecar:** Добавление агентов мониторинга или безопасности во все синхронизируемые поды.

### Сетевая изоляция и NetworkPolicies

vCluster может автоматически генерировать `NetworkPolicies` на хосте, которые:
- Разрешают трафик только между компонентами одного vCluster.
- Изолируют Control Plane от подов тенанта.
- Блокируют доступ подов vCluster к API-серверу хост-кластера (`isolatedControlPlane`).

## Практические сценарии

### Настройка безопасности и квот в vcluster.yaml (v0.35+)

Централизованное управление стандартами безопасности и ресурсными ограничениями.

```yaml
# vcluster.yaml
policies:
  # Применение Pod Security Standards (Restricted по умолчанию)
  podSecurityStandard: restricted
  
  # Автоматическая генерация NetworkPolicies для изоляции
  networkPolicy:
    enabled: true
    
  # Ресурсные квоты на уровне неймспейса хоста
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "50"
      
  # Лимиты по умолчанию внутри vCluster
  limitRange:
    enabled: true
    default:
      cpu: 500m
      memory: 512Mi
```

### Настройка нативной синхронизации CRD (Generic Sync)

Синхронизация объектов `cert-manager` с использованием CEL-патчей для предотвращения конфликтов.

```yaml
# vcluster.yaml
sync:
  toHost:
    customResources:
      certificates.cert-manager.io:
        enabled: true
        patches:
          - path: spec.secretName
            # Добавление префикса к имени секрета на хосте
            expression: '"v-secret-" + value'
      issuers.cert-manager.io:
        enabled: true
  fromHost:
    customResources:
      clusterissuers.cert-manager.io:
        enabled: true
```

### Использование CEL-патчей для модификации ресурсов

Пример изменения типа сервиса и добавления метаданных при синхронизации.

```yaml
# vcluster.yaml
sync:
  toHost:
    services:
      enabled: true
      patches:
        - path: metadata.annotations["managed-by"]
          value: "vcluster-prod"
        - path: spec.type
          # Преобразование LoadBalancer в ClusterIP для экономии ресурсов хоста
          expression: 'value == "LoadBalancer" ? "ClusterIP" : value'
```

### Сетевая изоляция и Rootless Mode

Максимальное ужесточение безопасности для Control Plane.

```yaml
# vcluster.yaml
controlPlane:
  backingStore:
    etcd:
      embedded: true
  statefulSet:
    securityContext:
      runAsUser: 10000
      runAsNonRoot: true
      
networking:
  # Блокировка доступа к API хост-кластера для подов vCluster
  isolatedControlPlane:
    enabled: true
```

## Лучшие практики безопасности

- **Принудительное использование PSA:** Всегда устанавливайте `podSecurityStandard: restricted` для недоверенных тенантов. Это предотвращает запуск контейнеров с привилегиями root и доступ к хостовой ФС.
- **Минимизация RBAC для Syncer:** Избегайте использования `ClusterRole` для vCluster. Ограничивайте права синхронизатора только необходимым набором в целевом неймспейсе. Используйте `controlPlane.serviceAccount.name` для подключения SA с минимальными правами.
- **Включение сетевой изоляции:** Используйте `policies.networkPolicy.enabled` для автоматического создания политик, блокирующих межкластерный трафик и доступ к метаданным облачного провайдера.
- **Namespace 1:1 Syncing:** Используйте этот режим, если ваши инструменты безопасности (например, Falco или Sysdig) требуют соответствия имен неймспейсов между виртуальным и хостовым слоями.
- **Изоляция хранилищ:** При импорте `PersistentVolumes` через `fromHost` убедитесь, что политики доступа запрещают одному vCluster монтировать тома, принадлежащие другому виртуальному кластеру.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)

### См. также

- [Security Context в Kubernetes](../Security/pod_security_context.md) — детали PSA и PSS.
- [Мульти-тенантность в Kubernetes](../Concepts/multi-tenancy.md) — общие подходы к изоляции.

### Внешние ссылки

- [vCluster Security Documentation](https://www.vcluster.com/docs/architecture/security)
- [Resource Syncing and Patches](https://www.vcluster.com/docs/config/sync/overview)
- [Common Expression Language (CEL) in Kubernetes](https://kubernetes.io/docs/reference/using-api/cel/)
