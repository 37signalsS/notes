# Projected Volumes в Kubernetes

## Определения

**Projected Volume (проектируемый том)** — специализированный тип Volume (тома) в Kubernetes, который позволяет объединить несколько существующих источников данных (`Secret`, `ConfigMap`, `Downward API`, `ServiceAccountToken`) в один том, монтируемый как единая директория в файловую систему container (контейнера).

**Основное преимущество:** упрощение манифеста Pod (пода) за счёт использования одной точки монтирования вместо создания нескольких отдельных томов для разных источников.

---

## Базовые концепции

### Поддерживаемые источники данных

Проектируемые тома могут агрегировать информацию из следующих источников:

| Источник | Описание | Статус |
| :--- | :--- | :--- |
| `secret` | Данные из объектов Secret в том же Namespace (пространстве имён). | Stable |
| `configMap` | Данные из объектов ConfigMap в том же Namespace. | Stable |
| `downwardAPI` | Метаданные Pod через механизм Downward API. | Stable |
| `serviceAccountToken` | Кастомизированный токен ServiceAccount для аутентификации в API. | Stable |
| `clusterTrustBundle` | Глобальные наборы доверенных сертификатов (trust anchors). | Beta (v1.33+) |
| `podCertificate` | Автоматически выпускаемые X.509 сертификаты для Pod. | Beta (v1.35+) |

### Особенности реализации

**Разрешение конфликтов:** Если несколько источников содержат файлы с одинаковыми именами, приоритет имеет тот источник, который указан последним в списке `sources`.

**Автоматические обновления:** Файлы в проектируемом томе обновляются автоматически при изменении исходных объектов (Secret или ConfigMap) в кластере.

**Ограничение subPath:** Если источник данных в проектируемом томе монтируется через `subPath`, автоматическое обновление данных для такого монтирования **не происходит**.

### Сравнение подходов

| Характеристика | Отдельные тома | Projected Volume |
| :--- | :--- | :--- |
| **Точки монтирования** | Несколько (по одной на каждый ресурс) | Одна (общая директория) |
| **Сложность манифеста** | Высокая (множество `volumeMounts`) | Низкая (один `volumeMount`) |
| **Изоляция данных** | Изолированы на уровне томов | Находятся в одной общей структуре |
| **Контроль имен** | Имена файлов не пересекаются | Последний источник в списке выигрывает |

---

## Практические сценарии

### Сценарий 1: Агрегация конфигурации и секретов

Объединение настроек приложения, паролей и метаданных в одну рабочую директорию `/app/config`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: all-in-one-pod
spec:
  volumes:
  - name: config-all-in-one
    projected:
      sources:
      - secret:
          name: db-credentials
          items:
            - key: password
              path: secrets/db-pass.txt
      - configMap:
          name: app-settings
          items:
            - key: ui-config.yaml
              path: settings/ui.yaml
      - downwardAPI:
          items:
            - path: "info/pod-name"
              fieldRef:
                fieldPath: metadata.name
  containers:
  - name: app-container
    image: busybox:1.36
    command: ["sh", "-c", "ls -R /app/config && sleep infinity"]
    volumeMounts:
    - name: config-all-in-one
      mountPath: "/app/config"
      readOnly: true
```

### Сценарий 2: Кастомизация ServiceAccountToken

Создание токена с ограниченным сроком действия и специфической аудиторией (Audience) для взаимодействия с внешним API Gateway.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-token-pod
spec:
  volumes:
  - name: vault-token
    projected:
      sources:
      - serviceAccountToken:
          path: token
          audience: vault-service
          expirationSeconds: 7200 # 2 часа
  containers:
  - name: worker
    image: busybox
    volumeMounts:
    - name: vault-token
      mountPath: /var/run/secrets/tokens
      readOnly: true
  automountServiceAccountToken: false
```

### Сценарий 3: Использование ClusterTrustBundle (Beta)

Монтирование общекластерных доверенных сертификатов для проверки соединений (требует активации Feature Gate `ClusterTrustBundleProjection`).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: trusted-app
spec:
  volumes:
  - name: trusted-certs
    projected:
      sources:
      - clusterTrustBundle:
          name: company-ca
          path: cluster-ca.crt
  containers:
  - name: main
    image: alpine:latest
    volumeMounts:
    - name: trusted-certs
      mountPath: /etc/ssl/certs/cluster-ca.crt
      subPath: cluster-ca.crt
      readOnly: true
```

---

## Дополнительная информация

**Связанные темы:**

- [Базовые концепции Volume](./volumes_basics.md)
- [Использование Downward API в Kubernetes](../downward_api.md)
- [Использование ConfigMap в Pod](../../ConfigMap/pod_usage.md)
- [Механизмы работы с Secret](../../secrets/using_secrets.md)

**Официальная документация:** [Projected Volumes](https://kubernetes.io/docs/concepts/storage/projected-volumes/)
