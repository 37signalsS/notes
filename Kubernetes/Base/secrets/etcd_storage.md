# Хранение Secret в etcd

## Определения

**etcd** — это высоконадежное распределенное хранилище данных типа «ключ-значение», использующее алгоритм консенсуса Raft. В Kubernetes etcd служит централизованным хранилищем (Single Source of Truth) для всех объектов кластера, включая секреты, конфигурации и состояние узлов.

**Хранение секретов в etcd** — процесс сериализации объектов `Secret` (преимущественно в формате Protobuf) и их записи в базу данных bbolt, используемую etcd. По умолчанию данные в etcd записываются в незашифрованном виде, где конфиденциальные значения в поле `data` лишь закодированы в Base64.

> **Критическая уязвимость:** Кодирование Base64 не является шифрованием. Любое лицо с доступом к файлам базы данных etcd (например, через бэкапы, снапшоты виртуальных машин или прямой доступ к API etcd) может мгновенно получить доступ ко всем паролям и токенам кластера. Для защиты данных на диске необходимо использовать механизм **Encryption at Rest**.

**Encryption at Rest** (шифрование при хранении) — механизм Kubernetes, реализуемый на уровне `kube-apiserver`, который шифрует данные перед записью в etcd и расшифровывает их при чтении. Конфигурация шифрования задается объектом `EncryptionConfiguration`.

## Основные концепции

### Структура данных в etcd

Секреты хранятся в иерархии ключей etcd по пути:
`/registry/secrets/<namespace>/<name>`

**Формат хранения Protobuf:** Начиная с Kubernetes 1.6+, используется Protobuf как более компактный и быстрый формат по сравнению с JSON. При чтении напрямую через `etcdctl` данные будут выглядеть как бинарный поток. Для чтения в человекочитаемом формате используйте флаг `--decode-value` (доступен в etcdctl v3.5+) или_DECODE_VALUE_ через jq:

```bash
ETCDCTL_API=3 etcdctl --endpoints=$ENDPOINT \
  --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret --print-value-only | python3 -c "import sys,base64; print(base64.b64decode(sys.stdin.read()).decode())"
```

**Лимиты размера:** Kubernetes ограничивает отдельный Secret **1 MiB**. Серверный лимит etcd на запрос по умолчанию — **1.5 MiB** (`--max-request-bytes`), и в запрос входят метаданные и Base64-представление данных. Попытка создания секрета большего размера приведет к ошибке `RequestEntityTooLarge`.

**Ревизии и компакция:** Каждое изменение секрета создает новую ревизию в etcd. Для предотвращения бесконечного роста БД используется процесс **Compaction** (удаление старых ревизий) и **Defragmentation** (освобождение места на диске).

**События (Events):** Kubernetes события хранятся в etcd с TTL (Time To Live) по умолчанию 1 час (`--event-ttl` kube-apiserver). Это ключевое ограничение: события требуют отдельного механизма экспорта (например, через Event Exporter) для долгосрочного аудита.

### Шифрование при хранении (Encryption at Rest)

Шифрование выполняется на стороне `kube-apiserver` ПЕРЕД отправкой данных в etcd. При чтении API-сервер прозрачно расшифровывает данные, используя список провайдеров в `EncryptionConfiguration` (оценка идет сверху вниз).

**Провайдеры шифрования:**

| Провайдер | Алгоритм | Оценка безопасности | Особенности |
| :--- | :--- | :--- | :--- |
| **identity** | Нет | 0 | Значение по умолчанию. Данные хранятся как есть. Используется как fallback. |
| **aescbc** | AES-CBC (256-bit) | 8 | Рекомендуется для большинства сред. Использует PKCS7 padding. |
| **aesgcm** | AES-GCM (256-bit) | 9 | Быстрее на современных CPU (AES-NI). Обеспечивает проверку целостности данных (authenticated encryption). |
| **secretbox** | XSalsa20 + Poly1305 | 9 | Альтернатива AES, устойчивая к атакам по сторонним каналам. Использует NaCl-библиотеку. |
| **kms (v1)** | Внешний KMS | 10 | API-сервер делает gRPC-запрос на каждый объект. Высокая задержка (latency) на чтение/запись. Deprecated с Kubernetes 1.29. |
| **kms (v2)** | Внешний KMS | 10+ | **Стандарт 2026**. Кэширует ключи, поддерживает автоматическую ротацию без перезапуска API-сервера. GA с Kubernetes 1.29. |

**Сравнение KMS v1 и KMS v2:**

| Характеристика | KMS v1 | KMS v2 |
| :--- | :--- | :--- |
| Статус | Deprecated | GA (Kubernetes 1.29+) |
| Задержка (latency) | Каждый запрос → KMS | Локальный кэш ключей |
| Ротация ключей | Требует перезапуска API-сервера | Автоматическая без перезапуска |
| Кэширование | Нет | Встроенное (`cachesize`) |
| Протокол | gRPC через unix socket | gRPC через unix socket |
| Monitoring | Ограниченный | Расширенный (`apiserver_storage_envelope_*`) |

### Иерархия ключей в KMS v2

KMS v2 (Key Management Service) реализует сложную иерархию для обеспечения баланса безопасности и производительности:

1.  **KEK (Key Encryption Key):** Главный ключ, управляемый внешним KMS (Vault Transit, HashiCorp Vault, или другой совместимый KMS). Никогда не покидает KMS и не передается в API-сервер.
2.  **Seed (Семя):** Плагин KMS генерирует случайное семя (seed), шифрует его с помощью KEK и передает в API-сервер в виде encrypted seed (EncryptedDataKey).
3.  **DEK (Data Encryption Key):** API-сервер использует зашифрованное семя для локальной деривации DEK (используя HKDF — HMAC-based Extract-and-Expand Key Derivation Function). DEK используется для шифрования конкретного объекта Secret.

**Влияние на производительность:** Благодаря локальной деривации ключей из семени, API-серверу больше не нужно обращаться к внешнему KMS при каждом чтении или записи объекта, что радикально снижает latency по сравнению с KMS v1. Время жизни DEK определяется параметром `cachesize` и автоматически обновляется.

**Процесс шифрования:**
1. KMS плагин генерирует DEK
2. DEK шифрует объект Secret (AES-GCM)
3. DEK оборачивается KEK (wrapping)
4. Зашифрованный объект + encrypted DEK записываются в etcd

**Процесс расшифрования:**
1. API-сервер читает encrypted DEK из etcd
2. DEK расшифровывается через KMS (KEK)
3. Объект Secret расшифровывается DEK
4. DEK кэшируется локально для повторного использования

### Использование EncryptedDataKey в KMS v2

При шифровании KMS v2 создает `EncryptedDataKey` — зашифрованную копию DEK, которая записывается в etcd вместе с зашифрованным объектом. Это позволяет расшифровывать данные даже при недоступности KMS (если DEK кэширован) и обеспечивает автоматическую ротацию ключей.

### On-the-fly шифрование vs静止ное шифрование

Encryption at Rest в Kubernetes шифрует данные **на диске** (at rest), но не шифрует данные **при передаче** (in transit) между компонентами Control Plane. Для шифрования трафика используйте mTLS (mutual TLS) между компонентами. Комбинация обоих механизмов обеспечивает полную защиту: mTLS защищает данные в сети, Encryption at Rest — на диске.

## Практические сценарии

### Настройка EncryptionConfiguration

Для включения шифрования необходимо создать файл конфигурации и передать его через флаг `--encryption-provider-config` в манифест `kube-apiserver`.

**Базовая конфигурация с KMS v2 (рекомендуется для production):**

```yaml
# /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
      - configmaps # Рекомендуется шифровать, если там есть токены
    providers:
      - kms: # Рекомендуемый метод (v2)
          apiVersion: v2
          name: vault-kms-provider
          endpoint: unix:///var/run/kms-plugin/vault-plugin.sock
          timeout: 3s
          cachesize: 1000 # Кэш DEK (по умолчанию 1000)
      - aescbc: # Локальный ключ как fallback для чтения старых данных
          keys:
            - name: key1
              secret: <base64-encoded-32-byte-key> # generate with: head -c 32 /dev/urandom | base64
      - identity: {} # Обязательный fallback для чтения незашифрованных данных
```

**Конфигурация для kubeadm (Static Pod):**

При использовании kubeadm файл конфигурации размещается в `/etc/kubernetes/encryption-config.yaml` и подключается через манифест kube-apiserver:

```yaml
# /etc/kubernetes/manifests/kube-apiserver.yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-apiserver
  namespace: kube-system
spec:
  containers:
  - command:
    - kube-apiserver
    - --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
    # ... другие флаги
    volumeMounts:
    - name: encryption-config
      mountPath: /etc/kubernetes/encryption-config.yaml
      readOnly: true
  volumes:
  - name: encryption-config
    hostPath:
      path: /etc/kubernetes/encryption-config.yaml
      type: FileOrCreate
```

**Важно:** При использовании kubeadm файл конфигурации может управляться через kubeadm config map. При обновлении кластера kubeadm автоматически обновляет манифест kube-apiserver.

### Процедура включения шифрования на работающем кластере

**Предусловия:**
- Доступ к мастер-узлам с правами root
- Резервная копия etcd (обязательно!)
- Тестовый кластер для проверки конфигурации

**Пошаговая инструкция:**

1. **Создайте резервную копию etcd:**
   ```bash
   ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-before-encryption-$(date +%Y%m%d).db \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt \
     --key=/etc/kubernetes/pki/etcd/server.key
   ```

2. **Сгенерируйте ключ шифрования:**
   ```bash
   # Для aescbc (32 байта = 256 бит)
   ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)
   echo "Сгенерированный ключ: $ENCRYPTION_KEY"
   ```

3. **Создайте файл конфигурации:**
   ```bash
   cat <<EOF > /etc/kubernetes/encryption-config.yaml
   apiVersion: apiserver.config.k8s.io/v1
   kind: EncryptionConfiguration
   resources:
     - resources:
         - secrets
         - configmaps
       providers:
         - aescbc:
             keys:
               - name: key1
                 secret: ${ENCRYPTION_KEY}
         - identity: {}
   EOF
   ```

4. **Установите правильные права доступа:**
   ```bash
   chmod 600 /etc/kubernetes/encryption-config.yaml
   chown root:root /etc/kubernetes/encryption-config.yaml
   ```

5. **Скопируйте файл на все мастер-узлы:**
   ```bash
   for node in master-{1,2,3}; do
     scp /etc/kubernetes/encryption-config.yaml ${node}:/etc/kubernetes/
   done
   ```

6. **Обновите манифест kube-apiserver** (добавьте флаг `--encryption-provider-config`):
   ```bash
   # На каждом мастер-узле
   sed -i 's|--encryption-provider-config=.*|--encryption-provider-config=/etc/kubernetes/encryption-config.yaml|' /etc/kubernetes/manifests/kube-apiserver.yaml
   ```

7. **Дождитесь перезапуска kube-apiserver:**
   ```bash
   watch kubectl get pods -n kube-system -l component=kube-apiserver
   ```

8. **Инициируйте перешифрование существующих секретов:**
   ```bash
   # Все секреты будут прочитаны старым методом и записаны новым
   kubectl get secrets --all-namespaces -o json | kubectl replace -f -
   # → result: данные будут прочитаны старым ключом и записаны новым
   ```

9. **Проверьте шифрование:**
   ```bash
   # Проверьте наличие префикса шифрования
   ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt \
     --key=/etc/kubernetes/pki/etcd/server.key \
     get /registry/secrets/default/test-secret | strings | head -1
   # → Должен показать k8s:enc:aesgcm:v1:key1: или k8s:enc:kms:v2:name:
   ```

10. **Убедитесь, что KMS плагин доступен** (для KMS v2):
    ```bash
    # Проверьте логи KMS плагина
    kubectl logs -n kube-system -l app=kms-plugin
    # Проверьте сокет
    ls -la /var/run/kms-plugin/
    ```

### Ротация ключей и перешифрование

**Ротация локальных ключей (aesgcm/aescbc):**

1.  Добавьте новый ключ первым в список провайдеров.
2.  Обновите `EncryptionConfiguration` на всех мастер-узлах и перезапустите `kube-apiserver`.
3.  Инициируйте перешифрование всех существующих секретов:
    ```bash
    kubectl get secrets --all-namespaces -o json | kubectl replace -f -
    # → result: данные будут прочитаны старым ключом и записаны новым
    ```
4.  Убедитесь через `etcdctl`, что префикс ключа изменился.
5.  Удалите старый ключ из конфигурации.

**В KMS v2** ротация KEK происходит во внешнем хранилище автоматически. API-сервер обнаруживает обновление `key_id` и начинает использовать новое семя без перезагрузки. Полная ротация DEK происходит в течение времени, определенного параметром `cachesize`.

### Проверка шифрования через etcdctl

Чтобы убедиться, что данные зашифрованы, проверьте сырое значение ключа. Зашифрованные данные начинаются с магического префикса провайдера:

| Префикс | Провайдер | Пример |
| :--- | :--- | :--- |
| `k8s:enc:aesgcm:v1:key1:` | AES-GCM | `k8s:enc:aesgcm:v1:key1:base64data...` |
| `k8s:enc:aescbc:v1:key1:` | AES-CBC | `k8s:enc:aescbc:v1:key1:base64data...` |
| `k8s:enc:secretbox:v1:` | Secretbox | `k8s:enc:secretbox:v1:base64data...` |
| `k8s:enc:kms:v2:name:` | KMS v2 | `k8s:enc:kms:v2:name:vault-kms:base64data...` |

```bash
# Пример команды для чтения секрета напрямую из etcd
ETCDCTL_API=3 etcdctl --endpoints=$ENDPOINT \
  --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-app-secret

# Проверка наличия шифрования (поиск префикса)
ETCDCTL_API=3 etcdctl --endpoints=$ENDPOINT \
  --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-app-secret --print-value-only | strings | grep -o "k8s:enc:[a-z]*"
# → k8s:enc:aesgcm:v1
```

### Шпаргалка etcdctl для работы с секретами

**Базовые операции CRUD:**

```bash
# Конфигурация (переменные для удобства)
export ETCDCTL_API=3
export ENDPOINTS="https://127.0.0.1:2379"
export CA="/etc/kubernetes/pki/etcd/ca.crt"
export CERT="/etc/kubernetes/pki/etcd/server.crt"
export KEY="/etc/kubernetes/pki/etcd/server.key"

# Просмотр всех секретов в неймспейсе
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/ --prefix --keys-only

# Чтение конкретного секрета (сырой формат Protobuf)
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret

# Удаление секрета
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  del /registry/secrets/default/my-secret

# Проверка версии (ревизии) ключа
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret -w json | jq '.header.revision'

# Проверка размера всех секретов
etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/ --prefix | awk '{print $1, length($0)}' | sort -k2 -nr | head -20
```

**Операции с снапшотами и восстановление:**

```bash
# Создание снапшота
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY

# Проверка целостности снапшота
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-$(date +%Y%m%d).db --write-out=table

# Восстановление из снапшота (на новом кластере)
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --data-dir=/var/lib/etcd-restored \
  --name=master-1 \
  --initial-cluster=master-1=https://master-1:2380,master-2=https://master-2:2380,master-3=https://master-3:2380 \
  --initial-advertise-peer-urls=https://master-1:2380
```

**Мониторинг и аудит:**

```bash
# Проверка health кластера
ETCDCTL_API=3 etcdctl endpoint health --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY

# Проверка размера БД
ETCDCTL_API=3 etcdctl endpoint status --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY --write-out=table

# Проверка leader-а кластера
ETCDCTL_API=3 etcdctl endpoint status --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY --write-out=table | grep -o "is leader: [a-z]*"

# Компакция (осторожно! فقط на конкретной ревизии)
ETCDCTL_API=3 etcdctl compact $(ETCDCTL_API=3 etcdctl endpoint status --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY -w json | jq -r '.[].header.revision') \
  --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY

# Дефрагментация (освобождение диска после компакции)
ETCDCTL_API=3 etcdctl defrag --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY
```

## Риски и нюансы

*   **Потеря ключей:** Если файл `EncryptionConfiguration` или доступ к KMS будут утеряны, данные в etcd расшифровать невозможно. Бэкап etcd бесполезен без сохранения соответствующих ключей шифрования. **Правило:** Храните ключи шифрования отдельно от etcd-бэкапов (в KMS, HSM или защищенном хранилище).
*   **Консистентность при раскатке:** При обновлении конфигурации шифрования на нескольких мастерах (High Availability) важно обеспечить консистентность. Рекомендуется сначала добавить новый ключ как второстепенный (для чтения) на все узлы, и только потом сделать его основным (для записи).
*   **Безопасность мастера:** Файл `EncryptionConfiguration` (если используются локальные ключи) должен иметь права доступа только для `root` и процесса `kube-apiserver` (0600). Компрометация этого файла эквивалентна компрометации всех секретов кластера.
*   **Зависимость от KMS:** При использовании KMS v2 доступность KMS критична для записи новых секретов. Однако расшифровка существующих данных может выполняться из кэша DEK, что снижает зависимость от KMS при чтении.
*   **Производительность:** Шифрование добавляет незначительную задержку (1-5ms на операцию) при использовании локальных ключей и большую задержку (10-100ms) при использовании внешнего KMS (зависит от сети).
*   **Миграция между провайдерами:** Переход с локального шифрования (aescbc) на KMS v2 требует поэтапной процедуры: сначала добавить KMS как fallback, затем перешифровать все данные, затем сделать KMS основным провайдером.

## Резервное копирование и восстановление (Backup/Restore)

При восстановлении кластера из снапшота etcd необходимо восстановить и тот же файл `EncryptionConfiguration`, который использовался в момент создания бэкапа. Если восстановить более новый конфиг, API-сервер может не найти старые ключи для расшифровки данных из бэкапа.

**Процедура безопасного бэкапа:**

```bash
# 1. Бэкап etcd
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 2. Сохранить EncryptionConfiguration
cp /etc/kubernetes/encryption-config.yaml /backup/encryption-config-$(date +%Y%m%d).yaml

# 3. Проверить целостность снапшота
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-$(date +%Y%m%d).db --write-out=table
```

**Процедура восстановления:**

```bash
# 1. Восстановить EncryptionConfiguration (тот же файл, что использовался при бэкапе)
cp /backup/encryption-config-20240101.yaml /etc/kubernetes/encryption-config.yaml

# 2. Восстановить etcd из снапшота
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-20240101.db \
  --data-dir=/var/lib/etcd-restored \
  --name=master \
  --initial-cluster=master=https://127.0.0.1:2380 \
  --initial-advertise-peer-urls=https://127.0.0.1:2380

# 3. Обновить конфигурацию etcd для использования восстановленных данных
# 4. Перезапустить etcd и kube-apiserver
```

> **Критически важно:** Если файл `EncryptionConfiguration` был изменен после создания снапшота, восстановление будет невозможно без старого файла конфигурации или доступа к тем же ключам KMS.

## Наблюдаемость (Observability)

Мониторинг шифрования критичен для стабильности Control Plane:

### Ключевые метрики

*   `kms_operation_duration_seconds` (Histogram): Метрика для отслеживания задержек внешнего KMS. Ключевые percentile: p50, p95, p99. Алерт при p99 > 1s.
*   `apiserver_storage_transformation_operations_total` (Counter): Позволяет видеть объем операций шифрования/дешифрования. Разбивка по `transformation_type` (encrypt/decrypt) и `resource` (secrets/configmaps).
*   `apiserver_storage_transformation_failures_total` (Counter): Счетчик ошибок трансформации (критический алерт). Любое увеличение этого счетчика требует немедленного расследования.
*   `apiserver_storage_envelope_transformation_successes_total` (Counter): Количество успешных операций envelope encryption (KMS v2).
*   `apiserver_storage_envelope_transformation_failures_total` (Counter): Количество неуспешных операций envelope encryption.
*   `etcd_disk_wal_fsync_duration_seconds` (Histogram): Задержка fsync для WAL (Write-Ahead Log) etcd. Важно для мониторинга производительности диска.
*   `etcd_disk_backend_commit_duration_seconds` (Histogram): Задержка коммита в backend (bbolt).

### Примеры алертов (Prometheus)

```yaml
groups:
- name: etcd-encryption-security
  rules:
  - alert: SecretDecryptionFailure
    expr: apiserver_storage_transformation_failures_total > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Ошибка дешифрования секрета в etcd"
      description: "Обнаружена ошибка дешифрования. Возможные причины: утерян ключ KMS, поврежден EncryptionConfiguration."
      
  - alert: KMSHighLatency
    expr: histogram_quantile(0.99, rate(kms_operation_duration_seconds_bucket[5m])) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокая задержка KMS (>1s p99)"
      description: "Задержка KMS превышает 1 секунду на 99-м перцентиле. Это может замедлить чтение/запись секретов."
      
  - alert: KMSUnavailable
    expr: absent(up{job="kms-plugin"})
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "KMS плагин недоступен"
      description: "KMS плагин не отвечает более 2 минут. Запись новых секретов невозможна."
      
  - alert: HighEncryptionOperationsRate
    expr: rate(apiserver_storage_transformation_operations_total[5m]) > 100
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Высокий уровень операций шифрования"
      description: "Более 100 операций шифрования в секунду. Это может указывать на массовое чтение секретов."
```

### Мониторинг через Prometheus ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kube-apiserver-metrics
  namespace: monitoring
spec:
  selector:
    matchLabels:
      component: kube-apiserver
  endpoints:
  - port: https-metrics
    scheme: https
    tlsConfig:
      caFile: /etc/kubernetes/pki/ca.crt
      certFile: /etc/kubernetes/pki/apiserver.crt
      keyFile: /etc/kubernetes/pki/apiserver.key
  namespaceSelector:
    matchNames:
    - kube-system
```

## Диагностика и устранение неполадок

### Типичные ошибки

**1. Ошибка "secret not found" (после включения шифрования):**

```bash
# Симптом
Error: secrets "my-secret" not found

# Диагностика: проверьте, существует ли секрет в etcd
ETCDCTL_API=3 etcdctl --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY \
  get /registry/secrets/default/my-secret

# Решение: возможно, секрет не был перешифрован после включения EncryptionConfiguration
# Перешифруйте все секреты:
kubectl get secrets --all-namespaces -o json | kubectl replace -f -
```

**2. Ошибка "failed to decode secret" (потеря ключей):**

```bash
# Симптом
Error from server: Internal error: failed to decode secret

# Диагностика: проверьте EncryptionConfiguration
cat /etc/kubernetes/encryption-config.yaml

# Проверьте доступность KMS
kubectl logs -n kube-system kube-apiserver-master | grep -i kms

# Решение: восстановите EncryptionConfiguration из резервной копии
cp /backup/encryption-config.yaml /etc/kubernetes/encryption-config.yaml
```

**3. Высокая задержка чтения секретов:**

```bash
# Диагностика: проверьте метрики KMS
kubectl port-forward -n kube-system svc/kube-apiserver 6443:443
curl -k https://localhost:6443/metrics | grep kms_operation_duration_seconds

# Решение: увеличьте кэш DEK в KMS v2 (cachesize)
# Или проверьте сетевую задержку до KMS
```

**4. KMS плагин не отвечает:**

```bash
# Диагностика
kubectl get pods -n kube-system | grep kms
kubectl logs -n kube-system -l app=kms-plugin

# Решение: перезапустите KMS плагин
kubectl delete pod -n kube-system -l app=kms-plugin
# KMS плагин должен быть запущен как DaemonSet или static pod
```

**5. etcd заполнен (достигнут лимит 8 ГБ):**

```bash
# Диагностика
ETCDCTL_API=3 etcdctl endpoint status --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY --write-out=table
# → Проверьте размер DB

# Решение: компакция + дефрагментация
ETCDCTL_API=3 etcdctl compact $(etcdctl endpoint status -w json | jq -r '.[].header.revision') \
  --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY
ETCDCTL_API=3 etcdctl defrag --endpoints=$ENDPOINTS --cacert=$CA --cert=$CERT --key=$KEY
```

### Команды для отладки

```bash
# Просмотр всех секретов в неймспейсе
kubectl get secrets -n prod

# Просмотр деталей секрета (без расшифровки данных)
kubectl describe secret my-secret -n prod

# Проверка использований секрета
kubectl get pods -n prod -o json | jq '.items[] | select(.spec.volumes[]?.secret.secretName == "my-secret") | .metadata.name'

# Проверка Pod, использующих секрет через env
kubectl get pods -n prod -o json | jq '.items[] | select(.spec.containers[].envFrom[]?.secretRef.name == "my-secret") | .metadata.name'

# Просмотр audit logs для секретов
kubectl logs -n kube-system kube-apiserver-master -f | jq 'select(.objectRef.resource == "secrets")'

# Проверка версии etcd и шифрования
ETCDCTL_API=3 etcdctl endpoint health --write-out=table

# Проверка размера секретов
kubectl get secrets -A -o json | jq '.items[] | {namespace: .metadata.namespace, name: .metadata.name, size: (.data | to_entries | map(.value | length) | add)}' | sort-by(.size) | reverse

# Проверка EncryptionConfiguration
cat /etc/kubernetes/encryption-config.yaml | grep -A 10 "providers:"
```

## Лучшие практики

1.  **Используйте KMS v2** для production-сред. Локальные ключи (aescbc/aesgcm) подходят для development/testing.
2.  **Регулярно бэкапируйте** etcd и `EncryptionConfiguration` вместе. Храните их в разных местах.
3.  **Не храните ключи** в том же хранилище, что и etcd-бэкапы.
4.  **Включите mTLS** для всех соединений с etcd (peer и client).
5.  **Настройте мониторинг** KMS и ошибок шифрования (см. раздел "Наблюдаемость").
6.  **Тестируйте восстановление** из бэкапа на изолированном кластере не реже 1 раза в квартал.
7.  **Ротируйте ключи** регулярно (для KMS v2 — автоматически, для локальных — вручную).
8.  **Шифруйте и ConfigMap**, если они содержат чувствительные данные (токены, пароли).
9.  **Избегайте `list`/`watch` на секреты** через API — это может раскрыть данные в логах audit.
10. **Документируйте процедуру** восстановления ключей шифрования для команды SRE.

## Смотрите также

*   **[Безопасность Secret](security.md)** — общие принципы защиты и RBAC.
*   **[Внешние менеджеры](external_managers.md)** — интеграция с Vault и облачными KMS.
*   **[Архитектура etcd](../../etcd/architecture-and-concepts.md)** — детальный разбор работы Raft и bbolt.
*   **[Безопасность etcd](../../etcd/security.md)** — TLS и RBAC на уровне etcd.
