# Projected Volumes в Kubernetes

## Определения

**Projected Volume (проектируемый том)** — специализированный тип тома в Kubernetes, предназначенный для агрегации нескольких существующих источников данных в одну общую директорию внутри контейнера. В отличие от стандартных томов, которые обычно представляют одну сущность (например, только один `Secret`), проектируемый том выступает в роли "проекции" нескольких ресурсов разного типа.

**Ключевые преимущества:**
- **Агрегация данных:** объединение конфигураций, секретов и метаданных в единую структуру (например, `/etc/app/config`).
- **Упрощение манифестов:** сокращение количества секций `volumeMounts` в описании контейнера.
- **Безопасность (Zero Trust):** использование Bound Service Account Tokens с ограниченным временем жизни и привязкой к конкретному сервису (Audience).
- **Динамическое распространение доверия:** автоматическое монтирование актуальных сертификатов кластера через `ClusterTrustBundle`.

---

## Базовые концепции

### Поддерживаемые источники данных

В 2026 году (Kubernetes v1.35+) проектируемые тома поддерживают следующие источники:

| Источник | Описание | Статус |
| :--- | :--- | :--- |
| `secret` | Данные из объектов Secret в том же Namespace. | Stable |
| `configMap` | Данные из объектов ConfigMap в том же Namespace. | Stable |
| `downwardAPI` | Метаданные Pod и контейнера (имя, IP, лимиты). | Stable |
| `serviceAccountToken` | Токен ServiceAccount с заданным Audience и TTL. | Stable |
| `clusterTrustBundle` | Глобальные наборы доверенных сертификатов (trust anchors). | Stable |
| `podCertificate` | Автоматически выпускаемые X.509 сертификаты для идентификации Pod. | Beta |

### Механизм агрегации и обновления

1.  **Разрешение конфликтов:** Если разные источники содержат файлы с одинаковыми именами, приоритет имеет тот источник, который указан **ниже** (последним) в списке `sources`.
2.  **Атомарность:** Kubelet обновляет данные в проектируемом томе атомарно. При изменении исходного `Secret` или `ConfigMap` создается новая временная директория, заполняется данными и затем символическая ссылка переключается на нее.
3.  **Ограничение subPath:** Если проектируемый том монтируется через `subPath`, файлы внутри него **не будут обновляться** автоматически при изменении исходных объектов. Для работы механизма обновления необходимо монтировать весь том целиком.

---

## Параметры настройки

- **`defaultMode`**: устанавливает права доступа (Permissions) для всех файлов в томе (например, `0644`).
- **`sources`**: список объектов-источников.
- **`items`**: позволяет выбрать конкретные ключи из источника и сопоставить их с определенными путями (именами файлов) внутри тома.

---

## Практические сценарии

### Сценарий 1: Агрегация конфигураций и паролей

Объединение настроек приложения, паролей БД и метаданных в единую структуру `/etc/app`.

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

### Сценарий 2: Безопасные токены (Bound Service Account Token)

Использование кратковременных токенов (обычно 1 час) с привязкой к конкретной системе (Audience). Это стандарт для интеграции с Vault, AWS IAM, GCP Workload Identity.

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
          expirationSeconds: 3600
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: sa-token
      mountPath: /var/run/secrets/vault
      readOnly: true
```

### Сценарий 3: Доверительные сертификаты через ClusterTrustBundle

Позволяет приложению автоматически получать актуальный набор корневых сертификатов (CA) компании без их вшивания в образ.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-client
spec:
  volumes:
  - name: trusted-ca
    projected:
      sources:
      - clusterTrustBundle:
          name: "corp-root-ca"
          path: "ca-certificates.crt"
  containers:
  - name: curl
    image: curlimages/curl
    volumeMounts:
    - name: trusted-ca
      mountPath: /etc/ssl/certs/corp
      readOnly: true
```

---

## Дополнительная информация

**Технические нюансы:**
- **Размер тома:** Проектируемые тома используют память (`tmpfs`), если это разрешено в кластере, или локальный диск узла.
- **Задержка обновления:** Обновление данных в томе может занимать до 1 минуты (зависит от настроек `syncFrequency` в Kubelet).
- **Service Account Identity:** С 2024 года `serviceAccountToken` в проецируемых томах является рекомендуемым способом аутентификации вместо старых токенов-секретов (Secret-based tokens).

**Связанные темы:**
- [Тома в Kubernetes — общие сведения](./volume_types.md)
- [Downward API — доступ к метаданным Pod](../downward_api.md)
- [Безопасность Secret в Kubernetes](../../secrets/security.md)
- [Использование ConfigMap в Pod](../../ConfigMap/pod_usage.md)

**Официальная документация:** [Projected Volumes](https://kubernetes.io/docs/concepts/storage/projected-volumes/)
