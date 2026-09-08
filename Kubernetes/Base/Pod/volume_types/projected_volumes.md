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

### Параметры каждого источника

**secret / configMap:**
| Параметр | Описание |
| :--- | :--- |
| `name` | Имя Secret/ConfigMap (обязательный). |
| `items[]` | Список ключей для монтирования (если не указан — монтируются все ключи). |
| `items[].key` | Ключ в Secret/ConfigMap. |
| `items[].path` | Путь файла внутри тома. |

**downwardAPI:**
| Параметр | Описание |
| :--- | :--- |
| `items[].path` | Путь файла внутри тома. |
| `items[].fieldRef.fieldPath` | Метрика Pod (например, `metadata.name`, `metadata.labels`). |
| `items[].resourceFieldRef` | Лимиты/запросы контейнера (например, `limits.cpu`). |

**serviceAccountToken:**
| Параметр | Описание |
| :--- | :--- |
| `path` | Путь к файлу токена внутри тома (обязательный). |
| `audience` | Идентифицируемый сервис (аудитория токена). Обязателен в стабильных версиях. |
| `expirationSeconds` | Время жизни токена в секундах (по умолчанию 1 час, максимум 24 часа). |

**clusterTrustBundle:**
| Параметр | Описание |
| :--- | :--- |
| `name` | Имя объекта `clusterTrustBundle` или `configMap` с CA-сертификатом. |
| `signerName` | Фильтрация по имени подписчика (опционально). |
| `path` | Путь к файлу сертификата внутри тома. |

**podCertificate:**
| Параметр | Описание |
| :--- | :--- |
| `kubeletClientConfig` | Конфигурация для запроса сертификата через kubelet API. |

---

## Безопасность

### Рекомендуемые практики

- **Всегда указывайте `readOnly: true`** при монтировании projected volumes. Это предотвращает случайную или злонамеренную модификацию файлов.
- **Используйте минимальные `defaultMode`** (например, `0400` или `0600`). Не давайте права на запись группе или всем (`0644`, `0777`).
- **Ограничивайте `items`** только необходимыми ключами. Не монтируйте целый Secret/ConfigMap, если нужны 1-2 значения.
- **Не храните credential-файлы на постоянной ФС.** Projected volumes размещаются на tmpfs (если разрешено в кластере) или на локальном диске. Для долгосрочных секретов используйте CSI Secret Store.

### Bound Service Account Token — рекомендуемый способ аутентификации

С 2024 года `serviceAccountToken` в projected volumes является рекомендуемым способом аутентификации вместо статических секретов ServiceAccount. Преимущества:

- **Ограниченный TTL** (по умолчанию 1 час) — токен автоматически истекает.
- **Привязка к аудитории** (audience) — токен валиден только для конкретного сервиса.
- **Не сохраняется в etcd** — токен генерируется на лету и монтируется через TokenRequest API.

```yaml
# Статический токен (устаревший способ) — НЕ рекомендуется
volumes:
- name: sa-secret
  secret:
    secretName: my-sa-token    # ← Сохраняется в etcd, не истекает

# Projected token (рекомендуемый способ)
volumes:
- name: sa-token
  projected:
    sources:
    - serviceAccountToken:
        path: token
        audience: https://my-api.example.com
        expirationSeconds: 3600
```

### Сравнение: projected volume vs отдельные тома

| Критерий | Projected Volume | Отдельные тома (secret, configMap и т.д.) |
| :--- | :--- | :--- |
| **Количество volumeMounts** | Один на все источники | Отдельный на каждый источник |
| **Конфликт имён файлов** | Приоритет у последнего в `sources` | Нет конфликтов (разные монтирования) |
| **Гибкость (`items`)** | Да — можно переименовывать файлы | Да — через `items` в каждом томе |
| **Обновление файлов** | Атомарное через symlinks | Аналогично для каждого тома |
| **Безопасность** | Единая точка контроля `readOnly` | Контроль для каждого тома отдельно |
| **Сложность манифеста** | Проще (одна секция volumes) | Сложнее (много секций) |
| **ServiceAccountToken** | Только через projected | Невозможно монтировать отдельно |

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

Использование кратковременных токенов (обычно 1 час) с привязкой к конкретной системе (Audience). Это стандарт для интеграции с внешними системами аутентификации.

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

### Сценарий 4: Инъекция метаданных для логирования и метрик

Сбор метаданных Pod для structured logging и метрик без обращения к Kubernetes API. Подходит для sidecar-контейнеров, собирающих логи.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-metadata
  labels:
    app: web
    env: production
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: pod-metadata
      mountPath: /etc/podinfo
      readOnly: true
  - name: log-collector
    image: fluentd:latest
    volumeMounts:
    - name: pod-metadata
      mountPath: /etc/podinfo
      readOnly: true
  volumes:
  - name: pod-metadata
    projected:
      defaultMode: 0444
      sources:
      - downwardAPI:
          items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "annotations"
            fieldRef:
              fieldPath: metadata.annotations
          - path: "pod-name"
            fieldRef:
              fieldPath: metadata.name
          - path: "namespace"
            fieldRef:
              fieldPath: metadata.namespace
          - path: "node-name"
            fieldRef:
              fieldPath: spec.nodeName
```

**Проверка:**
```bash
kubectl exec app-with-metadata -c log-agent -- cat /etc/podinfo/labels
# → app="web"
# → env="production"
```

### Сценарий 5: Общая конфигурация для нескольких контейнеров в Pod

Один источник конфигурации для init-контейнера и основного контейнера. Init-контейнер подготавливает данные, основной — использует.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-stage-app
spec:
  initContainers:
  - name: init-config
    image: busybox
    command: ['sh', '-c', 'cat /etc/app/config.ini > /shared/config-ready && echo OK']
    volumeMounts:
    - name: shared-config
      mountPath: /etc/app
    - name: shared-data
      mountPath: /shared
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: shared-config
      mountPath: /etc/app
      readOnly: true
    - name: shared-data
      mountPath: /data
  volumes:
  - name: shared-config
    projected:
      defaultMode: 0400
      sources:
      - configMap:
          name: app-config
          items:
          - key: config.ini
            path: config.ini
      - secret:
          name: db-credentials
          items:
          - key: password
            path: db-password
  - name: shared-data
    emptyDir: {}
```

### Сценарий 6: TTL токена для долгоживущих задач

Настройка времени жизни ServiceAccount токена для задач, которые выполняются дольше стандартного часа.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: long-task
spec:
  containers:
  - name: worker
    image: my-worker:latest
    command: ["python", "long_task.py"]
    volumeMounts:
    - name: api-token
      mountPath: /var/run/secrets/api
      readOnly: true
  volumes:
  - name: api-token
    projected:
      sources:
      - serviceAccountToken:
          path: token
          audience: https://internal-api.corp
          expirationSeconds: 86400  # 24 часа
```

---

## Типичные ошибки и диагностика

### Ошибка 1: `projected volume error: configmap "x" not found`

Если один из источников в `sources` не найден — Pod не запустится с ошибкой `CreateContainerConfigError`.

**Диагностика:**
```bash
# Проверка всех источников, указанных в манифесте
kubectl get cm,secret -n <namespace>

# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 5 "Events:"
```

### Ошибка 2: Файлы Secret/ConfigMap не обновляются

**Причина:** Монтирование через `subPath` блокирует механизм обновления через symlinks.

**Проверка:**
```bash
# Проверьте, не используется ли subPath
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[?(@.projected)].projected.sources}'

# Проверьте, не помечен ли Secret/ConfigMap как immutable
kubectl get cm <name> -o jsonpath='{.spec.immutable}'
kubectl get secret <name> -o jsonpath='{.spec.immutable}'
```

**Решение:** Не используйте `subPath` с projected volumes для обновляемых данных. Монтируйте весь том целиком и переименовывайте файлы через `items[].path`.

### Ошибка 3: Токен ServiceAccount не валиден

**Диагностика:**
```bash
# Проверьте содержимое токена (payload между точками)
kubectl exec <pod> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | cut -d '.' -f2 | base64 -d
# → {"aud":["https://my-api.example.com"],"exp":...}

# Проверьте, что audience совпадает с тем, что ожидает сервер
```

**Решение:** Убедитесь, что `audience` в манифесте совпадает с тем, что ожидает сервер.

### Ошибка 4: Под не запускается из-за отсутствия одного из источников

**Причина:** Projected volume требует **все** источники одновременно. Если хотя бы один Secret/ConfigMap не найден — Pod не запустится.

**Диагностика:**
```bash
# Проверьте статус пода
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="ContainersReady")].message}'

# Проверьте, что все указанные в манифесте ресурсы существуют
kubectl get cm,secret -n <namespace>
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
- [Troubleshooting: проблемы с томами](../../../Troubleshooting/Common_Errors/CreateContainerConfigError/volume_issues.md)

**Официальная документация:** [Projected Volumes](https://kubernetes.io/docs/concepts/storage/projected-volumes/)
