# Projected Volumes в Kubernetes

## Определения

**Projected Volume** — тип тома Kubernetes, позволяющий объединить несколько источников (`secret`, `configMap`, `downwardAPI`, `serviceAccountToken`) в один том, монтируемый как единая директория.

**Основное преимущество:** Одна точка монтирования вместо нескольких отдельных томов.

---

## Базовые концепции

### Источники данных

Projected volume поддерживает следующие источники:

| Источник | Описание | Статус |
| :--- | :--- | :--- |
| `secret` | Секреты из того же namespace | Stable |
| `configMap` | ConfigMap из того же namespace | Stable |
| `downwardAPI` | Метаданные пода через Downward API | Stable |
| `serviceAccountToken` | Кастомизированный токен service account | Stable |
| `clusterTrustBundle` | Объекты ClusterTrustBundle (сертификаты) | Beta v1.33 (требуется feature gate) |
| `podCertificate` | X.509 сертификаты для Pod | Beta v1.35 (требуется feature gate) |

### Механизм работы

**Конфликты имён:** При конфликте имён файлов приоритет имеет последний источник в списке `sources`.

**Обновления:** Файлы в projected volume обновляются автоматически при изменении исходных объектов (Secret, ConfigMap).

**Ограничение subPath:** Контейнеры, использующие projected volume source как `subPath` volume mount, **не будут получать обновления** для этих источников.

### Сравнение с отдельными томами

| Характеристика | Отдельные тома | Projected Volume |
| :--- | :--- | :--- |
| Точки монтирования | Несколько (по одной на источник) | Одна |
| Сложность манифеста | Выше (много `volumeMounts`) | Ниже (один `volumeMount`) |
| Изоляция данных | Полная | Общая директория |
| Конфликты имён | Невозможны | Возможны (последний источник выигрывает) |

---

## Практические сценарии

### Пример 1: Базовый Projected Volume

Объединение данных из `Secret`, `ConfigMap` и `DownwardAPI` в одну директорию `/projected-volume`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: projected-volume-pod
spec:
  volumes:
  - name: all-in-one
    projected:
      sources:
      - secret:
          name: user-password-secret
          items:
            - key: username
              path: app-credentials/user.txt
      - configMap:
          name: app-config
          items:
            - key: config.yaml
              path: app-config/settings.yaml
      - downwardAPI:
          items:
            - path: "pod-labels"
              fieldRef:
                fieldPath: metadata.labels
            - path: "container-cpu-limit"
              resourceFieldRef:
                containerName: test-container
                resource: limits.cpu
  containers:
  - name: test-container
    image: busybox
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: all-in-one
      mountPath: "/projected-volume"
      readOnly: true
```

**Результат в файловой системе:**

- `/projected-volume/app-credentials/user.txt` — данные из Secret
- `/projected-volume/app-config/settings.yaml` — данные из ConfigMap
- `/projected-volume/pod-labels` — метаданные пода из DownwardAPI
- `/projected-volume/container-cpu-limit` — лимиты ресурсов из DownwardAPI

### Пример 2: Projected Volume с serviceAccountToken

По умолчанию токен service account монтируется автоматически по пути `/var/run/secrets/kubernetes.io/serviceaccount/token`. Projected volume позволяет создать кастомизированный токен с изменёнными параметрами.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: projected-sa-token-pod
spec:
  volumes:
  - name: custom-token
    projected:
      sources:
      - serviceAccountToken:
          path: token
          audience: api-gateway
          expirationSeconds: 3600
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "cat /etc/custom-token/token && sleep infinity"]
    volumeMounts:
    - name: custom-token
      mountPath: /etc/custom-token
      readOnly: true
  automountServiceAccountToken: false
```

**Параметры serviceAccountToken:**

| Поле | Описание | Значение по умолчанию | Ограничения |
| :--- | :--- | :--- | :--- |
| `path` | Относительный путь к точке монтирования | — | **Обязательно** |
| `audience` | Аудитория токена | Идентификатор API server | Опционально |
| `expirationSeconds` | Продолжительность действия токена | 1 час (3600 секунд) | Минимум: 600 секунд, Максимум: зависит от `--service-account-max-token-expiration` |

**Use case:** Токен с нестандартным сроком действия или специфической аудиторией (например, для доступа к внешнему API Gateway).

### Пример 3: ClusterTrustBundle и PodCertificate (beta)

> **Внимание:** Функции в статусе **beta** (v1.33 и v1.35) и требуют включения feature gates на API server.

**Необходимые feature gates:**

```bash
# Для clusterTrustBundle (beta v1.33)
--feature-gates=ClusterTrustBundle=true,ClusterTrustBundleProjection=true
--runtime-config=certificates.k8s.io/v1beta1/clustertrustbundles=true

# Для podCertificate (beta v1.35)
--feature-gates=PodCertificateRequest=true
--runtime-config=certificates.k8s.io/v1beta1/podcertificaterequests=true
```

**Пример использования clusterTrustBundle:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pod-with-trust-bundle
spec:
  volumes:
  - name: trust-bundle
    projected:
      sources:
      - clusterTrustBundle:
          name: ca-bundle
          path: ca-certificates.crt
  containers:
  - name: app
    image: my-app
    volumeMounts:
    - name: trust-bundle
      mountPath: /etc/ssl/certs
      readOnly: true
```

---

## Дополнительная информация

**Связанные темы:** [Базовые концепции Volume](./volumes_basics.md), [Downward API](../downward_api.md), [ConfigMap в подах](../../ConfigMap/pod_usage.md), [Использование Secret](../../secrets/using_secrets.md).
