# Работа с большими конфигурациями (>1 MiB)

## Определения

**Лимит размера ConfigMap** — максимальный размер объекта ConfigMap ограничен **1 MiB** (1 048 576 байт). Это ограничение связано с рекомендациями по размеру объектов etcd для обеспечения производительности кластера. При превышении API-сервер отклоняет запрос с ошибкой `RequestEntityTooLarge`.

**Альтернативы ConfigMap для больших данных** — совокупность подходов, позволяющих хранить и доставлять конфигурации, превышающие 1 MiB, включая PersistentVolume, внешние хранилища, разбиение на части и внешние конфиг-сервисы.

## Основные концепции

### Почему 1 MiB — это проблема

ConfigMap хранится в etcd как единый JSON-объект. etcd рекомендует размер объекта не более 1–1.5 MiB для обеспечения:

*   **Производительности синхронизации:** большие объекты дольше реплицируются между узлами etcd.
*   **Стабильности кластера:** большие объекты увеличивают вероятность таймаутов при записи.
*   **Пропускной способности API-сервера:** каждый запрос на чтение/запуск передаёт полный объект.

При превышении лимита API-сервер возвращает HTTP 413:

```
Error from server (RequestEntityTooLarge): the server responded with the status code 413
```

### Стратегии обхода лимита

| Стратегия | Размер данных | Сложность | Hot Reload | Когда использовать |
|---|---|---|---|---|
| **Разбиение на несколько ConfigMap** | <5 MiB суммарно | Низкая | Да (тома) | Конфиг логически разделяется на части |
| **PersistentVolume (PVC)** | Не ограничён | Средняя | Да | Файлы >1 MiB, часто обновляемые |
| **ConfigMap + Git-sync** | Не ограничён | Средняя | Да | GitOps-подход, конфиги из Git |
| **Внешний конфиг-сервис** | Не ограничён | Высокая | Да | Динамические настройки, <1с задержка |
| **Docker-образ** | Не ограничён | Низкая | Нет | Статичные конфиги, которые меняются при деплое |
| **Object Storage (S3/MinIO)** | Не ограничён | Высокая | Да (sidecar) | Бинарные данные, большие JSON-конфиги |

## Практические сценарии

### Сценарий 1: Разбиение на несколько ConfigMap

Если конфигурация логически состоит из нескольких частей, разбейте её на отдельные объекты:

```yaml
# app-nginx.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-nginx-upstream
immutable: true
data:
  upstream.conf: |
    upstream backend {
        server app1:8080;
        server app2:8080;
    }
---
# app-nginx-server.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-nginx-server
immutable: true
data:
  server.conf: |
    server {
        listen 80;
        location / {
            proxy_pass http://backend;
        }
    }
```

**Deployment с двумя ConfigMap:**

```yaml
spec:
  containers:
  - name: nginx
    volumeMounts:
    - name: upstream-config
      mountPath: /etc/nginx/conf.d/upstream.conf
      subPath: upstream.conf
      readOnly: true
    - name: server-config
      mountPath: /etc/nginx/conf.d/server.conf
      subPath: server.conf
      readOnly: true
  volumes:
  - name: upstream-config
    configMap:
      name: app-nginx-upstream
  - name: server-config
    configMap:
      name: app-nginx-server
```

**Преимущества:**
*   Каждый ConfigMap в пределах 1 MiB.
*   Изменение одной части не затрагивает другую.
*   Можно монтировать разные части в разные поды.

**Недостатки:**
*   Сложнее управлять согласованностью версий.
*   Нужно следить за тем, чтобы все части были совместимы.

---

### Сценарий 2: PersistentVolume (PVC) для больших конфигов

Для файлов >1 MiB используйте PersistentVolume:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-bootstrap
  namespace: production
data:
  # Bootstrap-конфиг: только путь к PV
  config.json: |
    {
      "configPath": "/etc/app/config",
      "reloadEnabled": true
    }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-config-pvc
  namespace: production
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Mi
  storageClassName: local-path
```

**Deployment:**

```yaml
spec:
  containers:
  - name: app
    volumeMounts:
    - name: bootstrap
      mountPath: /etc/app/bootstrap
      readOnly: true
    - name: config-pv
      mountPath: /etc/app/config
      readOnly: true
  volumes:
  - name: bootstrap
    configMap:
      name: config-bootstrap
  - name: config-pv
    persistentVolumeClaim:
      claimName: app-config-pvc
```

**Как заполнять PV:**

```bash
# Один из способов: использовать init-контейнер или Job
kubectl cp large-config.json app-pod:/etc/app/config/config.json

# Или использовать ConfigMap + конвертацию (для данных <50 MiB)
kubectl create configmap large-config --from-file=config.json=large-config.json
kubectl get configmap large-config -o jsonpath='{.data.config\.json}' | base64 -d > /mnt/pv/config.json
```

**Преимущества:**
*   Неограниченный размер.
*   Hot Reload через sidecar (envoy, consul-template).
*   Данные доступны между рестартами подов.

**Недостатки:**
*   Сложнее управлять жизненным циклом.
*   PV не версионируется автоматически.
*   Требуется дополнительная логика обновления.

---

### Сценарий 3: ConfigMap + Git-sync sidecar

Используйте sidecar-контейнер, который синхронизирует конфигурацию из Git:

```yaml
spec:
  containers:
  - name: app
    image: my-app:2.0
    volumeMounts:
    - name: config
      mountPath: /etc/app/config
      readOnly: true
  - name: git-sync
    image: registry.k8s.io/git-sync:v4.1.0
    args:
      - --repo=https://github.com/myorg/configs.git
      - --branch=main
      - --root=/config
      - --one-time=false
      - --wait=30
    env:
    - name: GIT_SYNC_USERNAME
      valueFrom:
        secretKeyRef:
          name: git-credentials
          key: username
    - name: GIT_SYNC_PASSWORD
      valueFrom:
        secretKeyRef:
          name: git-credentials
          key: password
    volumeMounts:
    - name: config
      mountPath: /config
  volumes:
  - name: config
    emptyDir: {}
```

**Преимущества:**
*   Полноценный GitOps: версионирование, аудит, Code Review.
*   Конфигурация неограниченного размера.
*   Автоматическая синхронизация каждые N секунд.

**Недостатки:**
*   Задержка синхронизации (30–60 секунд).
*   Дополнительный контейнер в поде.
*   Нужны права доступа к Git-репозиторию.

---

### Сценарий 4: Внешний конфиг-сервис (Consul KV)

Для динамических конфигураций, которые меняются чаще, чем раз в час, используйте Consul KV:

```yaml
# Bootstrap-конфиг для приложения
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-bootstrap
immutable: true
data:
  consul-config.json: |
    {
      "consulAddress": "consul.service.consul:8500",
      "configPath": "config/myapp/",
      "watchEnabled": true,
      "retryInterval": "10s"
    }
```

Приложение обращается к Consul KV и получает актуальную конфигурацию:

```bash
# Пример чтения из Consul KV
curl -s http://consul.service.consul:8500/v1/kv/config/myapp/database?raw | jq .
# → {"host": "db.example.com", "port": 5432}
```

> Подробнее: [Consul KV Store](../../../../Consul/consul_kv_store.md), [Consul Overview](../../../../Consul/consul_overview.md)

**Преимущества:**
*   Мгновенное обновление (<1с через watch).
*   Неограниченный размер.
*   Версионирование через ModifyIndex.
*   Централизованное управление.

**Недостатки:**
*   Дополнительная инфраструктура (Consul-кластер).
*   Сложность отказоустойчивости.
*   Нет нативного версионирования в Git.

---

### Сценарий 5: Vault Agent для секретных больших конфигов

Для секретных данных >1 MiB используйте HashiCorp Vault:

```yaml
# Vault Agent sidecar генерирует конфигурационные файлы
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      initContainers:
      - name: vault-agent-init
        image: hashicorp/vault:1.15
        command: ["vault", "agent", "-config=/vault/config/agent.hcl"]
        volumeMounts:
        - name: vault-token
          mountPath: /vault/token
        - name: vault-config
          mountPath: /vault/config
      containers:
      - name: app
        image: my-app:2.0
        volumeMounts:
        - name: vault-config-volume
          mountPath: /etc/app/config
      volumes:
      - name: vault-config-volume
        emptyDir: {}
```

> Подробнее: [Vault Agent Sidecar Pattern](../../../../Vault/guides/vault_agent/sidecar_pattern.md)

---

### Сценарий 6: Object Storage (S3/MinIO) + init-контейнер

Для очень больших конфигураций (>50 MiB) или бинарных данных:

```yaml
spec:
  initContainers:
  - name: fetch-config
    image: amazon/aws-cli:latest
    command: ["aws", "s3", "cp", "s3://my-bucket/config/config.tar.gz", "/config/"]
    env:
    - name: AWS_ACCESS_KEY_ID
      valueFrom:
        secretKeyRef:
          name: aws-credentials
          key: access-key
    - name: AWS_SECRET_ACCESS_KEY
      valueFrom:
        secretKeyRef:
          name: aws-credentials
          key: secret-key
    volumeMounts:
    - name: config
      mountPath: /config
  containers:
  - name: app
    image: my-app:2.0
    volumeMounts:
    - name: config
      mountPath: /etc/app/config
  volumes:
  - name: config
    emptyDir: {}
```

**Преимущества:**
*   Неограниченный размер.
*   Не занимает место в etcd.
*   Может использоваться для бинарных данных.

**Недостатки:**
*   Задержка при старте пода (загрузка с S3).
*   Нужны права доступа к Object Storage.
*   Нет нативного Hot Reload.

---

## Дополнительная информация

### Диагностика превышения лимита

```bash
# Проверка размера ConfigMap перед применением
kubectl get configmap my-config -o yaml | wc -c
# → 1048577  (если >1048576, будет отклонено)

# Проверка размера локального YAML перед apply
wc -c my-configmap.yaml

# Поиск самых больших ConfigMap в кластере
kubectl get configmap -A -o json | jq -r '
  .items[] |
  "\(.metadata.namespace)/\(.metadata.name) \(.data | to_entries | map(.value | length) | add // 0) bytes"
' | sort -t' ' -k2 -rn | head -10
```

### Лимиты etcd

| Параметр | Значение | Описание |
|---|---|---|
| `--max-request-bytes` | 1.5 MiB (по умолчанию) | Максимальный размер запроса к etcd |
| Рекомендация по размеру объекта | 1 MiB | Для обеспечения производительности |
| `quota-backend-bytes` | 2 GiB (по умолчанию), 8 GiB — рекомендуемый максимум | Общий размер хранилища etcd |

> Подробнее: [etcd Storage](../../Base/secrets/etcd_storage.md), [etcd Overview](../../Concepts/etcd_overview.md)

### Сравнение стратегий

| Критерий | Разбиение | PV | Git-sync | Consul | Vault | S3 |
|---|---|---|---|---|---|---|
| **Размер** | <5 MiB | ∞ | ∞ | ∞ | ∞ | ∞ |
| **Hot Reload** | Да | Да | Да | Да (<1с) | Да | Нет |
| **Версионирование** | Git | Ручное | Git | ModifyIndex | Vault | Versioning |
| **Простота** | Высокая | Средняя | Средняя | Низкая | Низкая | Низкая |
| **Доп. инфраструктура** | Нет | Нет | Нет | Consul | Vault | S3/MinIO |
| **Секреты** | Нет | Нет | Нет | Да (с шифрованием) | Да | Да |

### Рекомендации

1. **Начните с разбиения.** Если конфигурация логически состоит из нескольких файлов — разбейте на отдельные ConfigMap. Это самый простой подход.
2. **Для файлов >1 MiB используйте PV.** PersistentVolume неограничен по размеру и поддерживает Hot Reload.
3. **Для динамических настроек используйте Consul/Vault.** Если конфигурация меняется несколько раз в час — ConfigMap не подходит.
4. **Для статичных данных используйте Docker-образ.** Если конфигурация меняется только при деплое — включите её в образ.
5. **Не храните бинарные данные в ConfigMap.** Используйте Object Storage или PV.

### См. также

* [Создание ConfigMap](./creation.md) — декларативные и императивные подходы.
* [Рекомендации и лучшие практики](./best_practices.md) — границы применимости ConfigMap.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — шаблоны для Nginx, Prometheus, Postgres.
* [Consul KV Store](../../../../Consul/consul_kv_store.md) — динамическая конфигурация через Consul.
* [Vault Agent Sidecar](../../../../Vault/guides/vault_agent/sidecar_pattern.md) — динамическое обновление конфигурации.
