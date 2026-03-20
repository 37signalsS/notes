# Projected Volumes в Kubernetes

## Определения

**Projected Volume** — это тип тома, который позволяет объединить несколько источников (`secret`, `configMap`, `downwardAPI`, `serviceAccountToken`) в один том, который монтируется как единая директория.

**Основное преимущество:** **одна точка монтирования** вместо нескольких отдельных томов.

## Источники данных

Projected volume поддерживает следующие источники:

- `secret` — секреты из того же namespace
- `configMap` — ConfigMap из того же namespace
- `downwardAPI` — метаданные пода через Downward API
- `serviceAccountToken` — кастомизированный токен service account
- `clusterTrustBundle` — объекты ClusterTrustBundle (сертификаты), **beta v1.33** (требуется feature gate)
- `podCertificate` — X.509 сертификаты для Pod, **beta v1.35** (требуется feature gate)

**Важно:** При конфликте имен файлов приоритет имеет последний источник в списке `sources`.

**Ограничение:** Контейнеры, использующие projected volume source как `subPath` volume mount, **не будут получать обновления** для этих источников.

---

## Практический пример: Projected Volume

Этот пример показывает, как объединить данные из `Secret`, `ConfigMap` и `DownwardAPI` в одну директорию `/projected-volume`.

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
          name: user-password-secret # Предполагается, что этот Secret существует
          items:
            - key: username
              path: app-credentials/user.txt
      - configMap:
          name: app-config # Предполагается, что этот ConfigMap существует
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

**Результат:** Все данные будут доступны в одной директории `/projected-volume`:
- `app-credentials/user.txt` — данные из Secret
- `app-config/settings.yaml` — данные из ConfigMap
- `pod-labels` — метаданные пода из DownwardAPI
- `container-cpu-limit` — лимиты ресурсов из DownwardAPI

---

## Практический пример: Projected Volume с serviceAccountToken

По умолчанию токен service account монтируется автоматически по пути `/var/run/secrets/kubernetes.io/serviceaccount/token`. Projected volume позволяет создать кастомизированный токен с измененными параметрами и смонтировать его в нестандартный путь.

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
          audience: api-gateway # Аудитория токена (опционально)
          expirationSeconds: 3600 # Срок действия: 1 час (минимум 600, максимум зависит от флага API server)
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "cat /etc/custom-token/token && sleep infinity"]
    volumeMounts:
    - name: custom-token
      mountPath: /etc/custom-token
      readOnly: true
  # Отключаем автоматическое монтирование стандартного токена
  automountServiceAccountToken: false
```

### Параметры serviceAccountToken

| Поле | Описание | Значение по умолчанию | Ограничения |
| :--- | :--- | :--- | :--- |
| `path` | Относительный путь к точке монтирования | — | **Обязательно** |
| `audience` | Аудитория токена. Получатель должен идентифицировать себя этим идентификатором | Идентификатор API server | Опционально |
| `expirationSeconds` | Продолжительность действия токена | 1 час (3600 секунд) | Минимум: 600 секунд, Максимум: ограничивается флагом `--service-account-max-token-expiration` |

**Use case:** Ситуации, когда требуется токен с нестандартным сроком действия или специфической аудиторией (например, для доступа к внешнему API Gateway).

---

## Практический пример: ClusterTrustBundle и PodCertificate (beta)

> **Внимание:** Эти функции находятся в статусе **beta** (v1.33 и v1.35 соответственно) и требуют включения feature gates на API server.

Для использования `clusterTrustBundle` и `podCertificate` необходимо включить feature gates:

```bash
# Для clusterTrustBundle (beta v1.33)
--feature-gates=ClusterTrustBundle=true,ClusterTrustBundleProjection=true
--runtime-config=certificates.k8s.io/v1beta1/clustertrustbundles=true

# Для podCertificate (beta v1.35)
--feature-gates=PodCertificateRequest=true
--runtime-config=certificates.k8s.io/v1beta1/podcertificaterequests=true
```

### Пример использования clusterTrustBundle:

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
          name: ca-bundle # Имя ClusterTrustBundle объекта
          path: ca-certificates.crt
  containers:
  - name: app
    image: my-app
    volumeMounts:
    - name: trust-bundle
      mountPath: /etc/ssl/certs
      readOnly: true
```

## Дополнительные ссылки

- [Базовые концепции Volume](./volumes_basics.md)
- [Downward API](../downward_api/)
