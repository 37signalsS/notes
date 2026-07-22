# Projected Volumes в Kubernetes

## Определения

**Projected Volume (проектируемый том)** — специализированный тип тома в Kubernetes, который позволяет агрегировать несколько существующих источников данных в одну общую директорию внутри контейнера. В отличие от стандартных томов, которые обычно представляют одну сущность (один `Secret` или один `ConfigMap`), проектируемый том выступает в роли "проекции" нескольких ресурсов.

**Основные преимущества:**
- **Упрощение манифестов:** сокращение количества секций `volumeMounts` в описании контейнера.
- **Логическая группировка:** возможность объединить конфигурации, секреты и метаданные в единую структуру (например, `/etc/app/config`).
- **Безопасность:** поддержка Bound Service Account Tokens с ограниченным временем жизни.

---

## Базовые концепции

### Поддерживаемые источники данных

Проектируемые тома могут агрегировать информацию из следующих источников:

| Источник | Описание | Статус (v1.35+) |
| :--- | :--- | :--- |
| `secret` | Данные из объектов Secret в том же Namespace. | Stable |
| `configMap` | Данные из объектов ConfigMap в том же Namespace. | Stable |
| `downwardAPI` | Метаданные Pod и контейнера (имя, IP, лимиты). | Stable |
| `serviceAccountToken` | Токен ServiceAccount с заданным Audience и временем жизни. | Stable |
| `clusterTrustBundle` | Наборы доверенных сертификатов кластера (trust anchors). | Stable |
| `podCertificate` | Автоматически выпускаемые X.509 сертификаты для идентификации Pod. | Beta |

### Параметры настройки

1. **`defaultMode`**: Устанавливает права доступа (Permissions) для всех файлов в томе (например, `0644`). По умолчанию — `0644`.
2. **`sources`**: Список источников, данные из которых будут "спроецированы" в том.
3. **`items`**: Позволяет выбрать конкретные ключи из источника и сопоставить их с определенными путями (файлами) внутри тома.

### Особенности реализации

**Разрешение конфликтов:** Если несколько источников содержат файлы с идентичными путями, приоритет имеет тот источник, который указан **последним** в списке `sources`.

**Атомарные обновления:** Kubernetes обновляет данные в проектируемом томе атомарно. При изменении `ConfigMap` или `Secret` Kubelet создает новую директорию, записывает туда обновленные данные и затем обновляет символическую ссылку, чтобы минимизировать время несоответствия.

**Ограничение subPath:** Если проектируемый том монтируется через `subPath`, файлы внутри него **не будут обновляться** автоматически при изменении исходных объектов. Для работы механизма обновления необходимо монтировать весь том целиком.

---

## Практические сценарии

### Сценарий 1: Агрегация конфигураций и метаданных

Пример объединения паролей базы данных, настроек приложения и имени Pod в одну директорию.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-bundle-pod
spec:
  volumes:
  - name: all-configs
    projected:
      defaultMode: 0400 # Только чтение для владельца
      sources:
      - secret:
          name: db-auth
          items:
            - key: password
              path: db/pass.txt
      - configMap:
          name: runtime-settings
          items:
            - key: log-level
              path: settings/logging.conf
      - downwardAPI:
          items:
            - path: "meta/pod-name"
              fieldRef:
                fieldPath: metadata.name
  containers:
  - name: main-app
    image: nginx:1.27
    volumeMounts:
    - name: all-configs
      mountPath: "/etc/app"
      readOnly: true
```

### Сценарий 2: Bound Service Account Token (Безопасность)

Использование токенов с коротким временем жизни и привязкой к конкретному сервису (Audience). Это стандарт де-факто для интеграции с внешними системами (Vault, AWS IAM).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: vault-auth-pod
spec:
  volumes:
  - name: sa-token
    projected:
      sources:
      - serviceAccountToken:
          path: vault-token
          audience: https://vault.example.com
          expirationSeconds: 3600 # Токен действителен 1 час
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: sa-token
      mountPath: /var/run/secrets/vault
      readOnly: true
```

### Сценарий 3: Автоматическая идентификация через PodCertificate

Монтирование сертификата для mTLS, который Kubelet выпускает и ротирует автоматически.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mtls-enabled-pod
spec:
  volumes:
  - name: identity
    projected:
      sources:
      - podCertificate:
          path: tls.crt
          # Kubelet автоматически создаст tls.key в той же директории
  containers:
  - name: server
    image: envoyproxy/envoy:v1.30
    volumeMounts:
    - name: identity
      mountPath: /etc/tls/identity
      readOnly: true
```

---

## Дополнительная информация

**Технические нюансы:**
- **Размер тома:** Проектируемые тома используют память (`tmpfs`), если это настроено в кластере, или локальный диск узла.
- **Версионность:** При использовании `ConfigMap` и `Secret` обновление данных в томе может занимать до 1 минуты (зависит от настроек `syncFrequency` и `configMapAndSecretChangeDetectionStrategy` в Kubelet).

**Связанные темы:**
- [Тома в Kubernetes — общие сведения](./volume_types.md)
- [Использование ConfigMap в Pod](../../ConfigMap/pod_usage.md)
- [Механизмы работы с Secret](../../secrets/using_secrets.md)
- [Downward API в Kubernetes](../downward_api.md)

**Официальная документация:** [Projected Volumes](https://kubernetes.io/docs/concepts/storage/projected-volumes/)
