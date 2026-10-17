# Хранение Secret в etcd

**Актуально для:** Kubernetes 1.30+ / etcd 3.5+ (KMS v2 GA, автоматическая перезагрузка EncryptionConfiguration)

## Определения

**etcd** — распределенное отказоустойчивое хранилище данных типа «ключ-значение», реализующее алгоритм консенсуса Raft и встраиваемую B-tree базу данных bbolt. В архитектуре Kubernetes etcd является единственным источником правды (Single Source of Truth, SSoT), в котором фиксируется текущее и желаемое состояние всех объектов кластера.

**Хранение Secret в etcd** — процедура сериализации API-ресурсов типа `Secret` в бинарный wire-формат Protobuf (с магическим префиксом `k8s\x00`) и записи в пространство ключей `/registry/secrets/<namespace>/<name>`. По умолчанию данные записываются в etcd в открытом виде; поле `data` содержит строки, закодированные в Base64.

**Base64 vs Encryption** — кодирование Base64 не является криптографическим преобразованием и предназначено исключительно для передачи бинарных данных через текстовые протоколы. Любой субъект, получивший доступ к файлу базы данных `member/snap/db`, резервному снапшоту etcd или незащищенному API etcd, мгновенно получает доступ к незашифрованному содержимому всех секретов кластера.

**Encryption at Rest (EaR)** — механизм шифрования конфиденциальных данных на стороне `kube-apiserver` непосредственно перед передачей в etcd и обратной прозрачной расшифровки при операциях чтения. Параметры шифрования определяются спецификацией `EncryptionConfiguration`.

**Envelope Encryption (Конвертное шифрование)** — двухуровневая схема защиты данных: полезная нагрузка объекта шифруется локальным одноразовым или кэшируемым ключом шифрования данных (DEK), а сам DEK шифруется мастер-ключом шифрования ключей (KEK).

**KEK (Key Encryption Key)** — мастер-ключ, управляемый внешней системой управления ключами (KMS, например HashiCorp Vault Transit Engine или аппаратный HSM). KEK не покидает пределы KMS и используется исключительно для операций оборачивания (wrapping/encrypt) и разворачивания (unwrapping/decrypt) семян и ключей DEK.

**DEK (Data Encryption Key)** — симметричный ключ (по умолчанию AES-GCM 256-bit), генерируемый и используемый API-сервером для шифрования и дешифрования конкретного объекта `Secret`.

**Compaction (Компакция)** — внутренняя процедура etcd, удаляющая исторические ревизии данных из механизма MVCC (Multi-Version Concurrency Control) до заданной целевой ревизии, предотвращая бесконечный рост базы данных.

**Defragmentation (Дефрагментация)** — операция перестройки bbolt-файла базы данных etcd на диске, возвращающая неиспользуемые страницы (freelist) операционной системе и уменьшающая физический размер файла `db`.

---

## Архитектура и механизм работы

### Структура ключей и формат хранения в etcd

Все объекты Kubernetes сохраняются в иерархическом дереве ключей etcd со стандартизированным префиксом:

```text
/registry/secrets/<namespace>/<secret-name>
```

Начиная с Kubernetes 1.6, стандартным форматом сериализации является бинарный **Protocol Buffers (Protobuf)**. Запись в etcd предваряется магическим байтовым маркером `k8s\x00`, за которым следуют сериализованные метаданные и поля объекта.

```bash
# Чтение сырого бинарного значения ключа из etcd
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/secrets/default/app-db-pass --print-value-only | head -c 16 | xxd -p
# → 6b387300... (маркер Protobuf k8s\x00)
```

### Лимиты размера и последствия для etcd

1. **Лимит Kubernetes:** размер отдельного объекта `Secret` жестко ограничен величиной **1 МиБ** (1 048 576 байт). Данный лимит включает имя, аннотации, метки и все ключи словаря `data`. При попытке создания ресурса большего размера API-сервер возвращает ошибку `RequestEntityTooLarge`.
2. **Лимит etcd (`--max-request-bytes`):** по умолчанию размер одного запроса (транзакции) в etcd ограничен **1.5 МиБ**.
3. **SRE-архитектура и риски:**
   - Хранение крупных бинарных файлов (SSL-сертификаты с объемными цепочками, java keystore, конфигурации баз данных) в секретах вызывает резкое распухание базы данных etcd.
   - Из-за механизма MVCC каждая модификация секрета создает новую полную копию объекта в etcd. Если приложение часто обновляет секрет (например, динамические токены каждые 5 минут), etcd генерирует сотни мегабайт ревизий, что приводит к блокировкам дискового ввода-вывода (fsync latency), росту WAL и падению пропускной способности кластера Raft.

```
+-----------------------------------------------------------------------------------+
|                                  kube-apiserver                                   |
|                                                                                   |
|  [Запрос клиента]                                                                 |
|         │                                                                         |
|         ▼                                                                         |
|  [REST Handler] ──> [Envelope/KMS Transformer] ──> [bbolt Client / gRPC etcd]    |
|                               │                                     │             |
+───────────────────────────────┼─────────────────────────────────────┼─────────────+
                                │                                     │
           gRPC (UNIX socket)   │                                     │ mTLS (2379)
                                ▼                                     ▼
                     +─────────────────────+               +─────────────────────+
                     |    KMS v2 Plugin    |               |        etcd         |
                     |  (HashiCorp Vault)  |               |  /registry/secrets/ |
                     +─────────────────────+               +─────────────────────+
```

### Жизненный цикл ревизий в etcd (MVCC, Raft, bbolt)

1. **Raft Propose:** любая операция записи секрета отправляется через консенсус-лидеру etcd и фиксируется в Write-Ahead Log (WAL) на диске всех кворумных узлов.
2. **MVCC Revision:** каждой транзакции присваивается монотонно возрастающий номер ревизии (`revision`). Старая версия объекта не перезаписывается, а помечается как историческая.
3. **bbolt freelist:** при выполнении компакции старые ревизии освобождаются внутри B-дерева, но размер файла `db` на файловой системе хоста не уменьшается — страницы попадают в список свободных страниц (freelist) для повторного использования. Реальное сжатие файла происходит только при ручной или регламентной процедуре **defrag**.

### Механизм Encryption at Rest в kube-apiserver

Шифрование выполняется компонентом `kube-apiserver` с помощью цепочки криптографических трансформаторов (**Transformer Chain**), инициализируемых из файла `EncryptionConfiguration`:

- **Путь записи (Write Path):** новый или обновляемый объект `Secret` передается первому провайдеру, указанному в списке `providers`. Первый провайдер шифрует данные и добавляет в начало зашифрованного блока уникальный префикс.
- **Путь чтения (Read Path):** при получении данных из etcd API-сервер последовательно опрашивает провайдеры сверху вниз, сопоставляя сигнатуру (префикс). Первый подошедший провайдер выполняет расшифровку. Если ни один провайдер не подошел, возвращается ошибка дешифрования.
- **Роль провайдера `identity`:** провайдер `identity` не выполняет шифрования. Если поместить его в конец списка, API-сервер сможет читать ранее записанные незашифрованные секреты. Если `identity` отсутствует в конфигурации, все незашифрованные секреты станут недоступны для чтения.

### Провайдеры шифрования

| Провайдер | Криптографический алгоритм | Оценка стойкости | Особенности и статус |
| :--- | :--- | :--- | :--- |
| **identity** | Отсутствует | 0 / 10 | Данные сохраняются открытым текстом. Обязателен в конце списка при миграции. |
| **aescbc** | AES-CBC (256-bit) с PKCS#7 padding | 7 / 10 | Симметричный локальный ключ. Уязвим к padding oracle при утечке каналов ошибок. |
| **aesgcm** | AES-GCM (256-bit) с аутентификацией (AEAD) | 9 / 10 | Аппаратное ускорение через AES-NI. Аутентифицированное шифрование. Требует регулярной ротации ключей для исключения коллизии nonce. |
| **secretbox** | XSalsa20 + Poly1305 (NaCl) | 9 / 10 | Высокопроизводительная альтернатива AES без риска атак по сторонним каналам (cache-timing). |
| **kms (v1)** | Внешний KMS через gRPC | 6 / 10 | **Удален в Kubernetes 1.32**. Блокирующий gRPC-запрос на каждый объект; высокое время отклика, отсутствие иерархии ключей. |
| **kms (v2)** | Внешний KMS (Envelope) + HKDF | 10 / 10 | **Стандарт индустрии (GA с K8s 1.29+)**. Кэширование ключей, локальная деривация через HKDF, авторотация без перезапуска API-сервера. |

### Иерархия ключей и устройство KMS v2

KMS v2 полностью устраняет узкие места производительности v1 за счет трехуровневой схемы:

1. **KEK (Key Encryption Key):** хранится на защищенном локальном/on-premise сервере управления секретами (например, HashiCorp Vault с движком Transit).
2. **Encrypted Seed:** KMS-плагин генерирует криптографически стойкое случайное семя (seed), шифрует его с помощью KEK и возвращает в `kube-apiserver` вместе с уникальным `key_id`.
3. **DEK Derivation (HKDF):** `kube-apiserver` локально использует расшифрованное семя для деривации индивидуальных ключей DEK с применением алгоритма HKDF (HMAC-based Extract-and-Expand Key Derivation Function, RFC 5869) и алгоритма AES-GCM.
4. **Кэширование:** DEK кэшируются в памяти API-сервера (размер настраивается параметром `cachesize`, по умолчанию 1000). При операциях чтения и записи секретов сетевых вызовов к KMS не происходит, пока ключ присутствует в кэше.

### Формат префиксов шифрования в etcd

Каждый зашифрованный блок в etcd начинается со специфического префикса, позволяющего API-серверу идентифицировать ключ и алгоритм:

| Префикс | Провайдер | Пример структуры в базе etcd |
| :--- | :--- | :--- |
| `k8s:enc:kms:v2:<name>:` | KMS v2 | `k8s:enc:kms:v2:vault-kms:<encrypted-seed>:<encrypted-payload>` |
| `k8s:enc:aesgcm:v1:<key-name>:` | AES-GCM | `k8s:enc:aesgcm:v1:key1:<nonce><ciphertext><tag>` |
| `k8s:enc:aescbc:v1:<key-name>:` | AES-CBC | `k8s:enc:aescbc:v1:key1:<iv><ciphertext>` |
| `k8s:enc:secretbox:v1:<key-name>:` | Secretbox | `k8s:enc:secretbox:v1:key1:<nonce><ciphertext>` |

### Шифрование данных в покое (at rest) vs в передаче (in transit)

- **Encryption at Rest:** защищает исключительно блоки данных на накопителе etcd от чтения через файловые бэкапы, кражу дисков или прямой несанкционированный доступ к процессу `etcd`.
- **Encryption in Transit:** весь сетевой обмен между компонентами Control Plane обязан защищаться взаимным TLS (mTLS):
  - Клиентский порт etcd (`2379/TCP`): проверка сертификата клиента API-сервером (`--client-cert-auth=true`).
  - Peer-порт etcd (`2380/TCP`): шифрование межузлового консенсуса Raft (`--peer-client-cert-auth=true`).
  - Порт `kube-apiserver` (`6443/TCP`): обязательный TLS для всех администраторов и рабочих узлов (Kubelet).

---

## Практические сценарии и конфигурация

### Базовый синтаксис EncryptionConfiguration (v1)

Начиная с Kubernetes 1.29+, спецификация `apiserver.config.k8s.io/v1` является стандартом GA.

```yaml
# /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
      - configmaps
    providers:
      - kms:
          apiVersion: v2
          name: vault-kms-provider
          endpoint: unix:///var/run/kms-plugin/vault-plugin.sock
          timeout: 3s
          cachesize: 2000
      - aesgcm:
          keys:
            - name: key2026
              secret: 9qN0k8lD9c2vF4gH6jK8lD9c2vF4gH6jK8lD9c2vF4g=
      - identity: {}
```

> [!IMPORTANT]
> Начиная с Kubernetes 1.27+, поддерживается группировка ресурсов масками (wildcards): `resources: ["*.*"]` позволяет зашифровать все ресурсы ядра и пользовательские CRD. Для изоляции накладных расходов в production рекомендуется явно перечислять `secrets` и `configmaps`.

---

### Сценарий 1: Production On-Premise с KMS v2 и HashiCorp Vault

В изолированной инфраструктуре без внешних облачных зависимостей KMS-плагин запускается в виде локального демона (Static Pod) на каждом Control Plane узле и взаимодействует с `kube-apiserver` через локальный UNIX domain socket.

#### 1. Подготовка Transit Secrets Engine в HashiCorp Vault

```bash
# Включение движка транзитного шифрования на сервере Vault
vault secrets enable transit
# → Success! Enabled the transit secrets engine at: transit/

# Создание ключа KEK с поддержкой ротации (aes256-gcm96)
vault write -f transit/keys/k8s-cluster-kek type=aes256-gcm96
# → Success! Data written to: transit/keys/k8s-cluster-kek

# Создание политики доступа для узлов Control Plane Kubernetes
vault policy write k8s-kms - <<EOF
path "transit/encrypt/k8s-cluster-kek" {
  capabilities = ["update"]
}
path "transit/decrypt/k8s-cluster-kek" {
  capabilities = ["update"]
}
EOF
# → Success! Uploaded policy: k8s-kms
```

#### 2. Развертывание локального плагина HashiCorp Vault KMS v2

Плагин запускается как Static Pod на каждом мастере, используя AppRole или локальный токен Vault для аутентификации.

```yaml
# /etc/kubernetes/manifests/vault-kms-plugin.yaml
apiVersion: v1
kind: Pod
metadata:
  name: vault-kms-plugin
  namespace: kube-system
  labels:
    tier: control-plane
    component: vault-kms-plugin
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
    - name: vault-kms-plugin
      image: hashicorp/vault-k8s-kms-provider:v0.4.0
      imagePullPolicy: IfNotPresent
      args:
        - --listen-addr=unix:///var/run/kms-plugin/vault-plugin.sock
        - --vault-addr=https://vault.internal.infra:8200
        - --vault-transit-key=k8s-cluster-kek
        - --vault-tls-ca-cert=/etc/vault-pki/vault-ca.crt
        - --vault-auth-method=approle
        - --vault-role-id-file=/etc/vault-auth/role-id
        - --vault-secret-id-file=/etc/vault-auth/secret-id
      volumeMounts:
        - name: kms-socket-dir
          mountPath: /var/run/kms-plugin
        - name: vault-pki
          mountPath: /etc/vault-pki
          readOnly: true
        - name: vault-auth
          mountPath: /etc/vault-auth
          readOnly: true
      resources:
        requests:
          cpu: 100m
          memory: 128Mi
        limits:
          cpu: 500m
          memory: 256Mi
  volumes:
    - name: kms-socket-dir
      hostPath:
        path: /var/run/kms-plugin
        type: DirectoryOrCreate
    - name: vault-pki
      hostPath:
        path: /etc/vault-pki
        type: Directory
    - name: vault-auth
      hostPath:
        path: /etc/vault-auth
        type: Directory
```

#### 3. Настройка прав доступа к сокету на хосте

```bash
mkdir -p /var/run/kms-plugin
chmod 700 /var/run/kms-plugin
chown root:root /var/run/kms-plugin
```

---

### Сценарий 2: Автономный кластер с локальным симметричным ключом (AES-GCM)

Для небольших или автономных инсталляций без развернутого кластера Vault допустимо использование встроенного провайдера `aesgcm`.

```bash
# Генерация 32-байтного (256-бит) случайного ключа в Base64
NEW_KEY=$(head -c 32 /dev/urandom | base64)
echo "Сгенерированный ключ: $NEW_KEY"
# → Сгенерированный ключ: 4uH8o1Lz5qRw... (32 байта)

# Создание конфигурационного файла
cat <<EOF > /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
    providers:
      - aesgcm:
          keys:
            - name: local-key-01
              secret: ${NEW_KEY}
      - identity: {}
EOF

chmod 600 /etc/kubernetes/encryption-config.yaml
chown root:root /etc/kubernetes/encryption-config.yaml
```

---

### Сценарий 3: Подключение к kube-apiserver и автоматическая перезагрузка

Начиная с Kubernetes 1.30, флаг `--encryption-provider-config-automatic-reload=true` включен по умолчанию (GA). При изменении содержимого файла `/etc/kubernetes/encryption-config.yaml` встроенный контроллер `kube-apiserver` перечитывает конфигурацию по событию inotify без перезапуска процесса.

```yaml
# Фрагмент /etc/kubernetes/manifests/kube-apiserver.yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-apiserver
  namespace: kube-system
spec:
  containers:
  - name: kube-apiserver
    command:
    - kube-apiserver
    - --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
    - --encryption-provider-config-automatic-reload=true
    # ... остальные параметры
    volumeMounts:
    - name: encryption-config
      mountPath: /etc/kubernetes/encryption-config.yaml
      readOnly: true
    - name: kms-socket
      mountPath: /var/run/kms-plugin
  volumes:
  - name: encryption-config
    hostPath:
      path: /etc/kubernetes/encryption-config.yaml
      type: File
  - name: kms-socket
    hostPath:
      path: /var/run/kms-plugin
      type: DirectoryOrCreate
```

---

### Сценарий 4: Безопасное включение шифрования на HA-кластере (Zero Downtime)

В High Availability кластере с несколькими мастер-узлами прямое включение шифрования на первом узле приведет к ошибкам: мастер №1 запишет зашифрованный секрет, а мастера №2 и №3 не смогут его прочитать. Процедура выполняется строго в 4 фазы.

```
[Фаза 1: Подготовка к чтению]
Мастер 1: [identity, new-key]  Мастер 2: [identity, new-key]  Мастер 3: [identity, new-key]
Все пишут открыто, но все узлы уже способны читать зашифрованное.

[Фаза 2: Переключение записи]
Мастер 1: [new-key, identity]  Мастер 2: [new-key, identity]  Мастер 3: [new-key, identity]
Все пишут зашифровано, старые секреты открыто читаются через fallback.

[Фаза 3: Миграция данных]
Запуск batch-перешифрования всех секретов в etcd.

[Фаза 4: Удаление identity]
Мастер 1: [new-key]            Мастер 2: [new-key]            Мастер 3: [new-key]
Незашифрованное чтение заблокировано.
```

#### Пошаговый протокол:

1. **Создание снапшота etcd:**
   ```bash
   ETCDCTL_API=3 etcdctl snapshot save /var/backups/etcd-pre-encrypt-$(date +%F).db \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt \
     --key=/etc/kubernetes/pki/etcd/server.key
   # → Snapshot saved at /var/backups/etcd-pre-encrypt-2026-10-17.db
   ```

2. **Фаза 1 (добавление ключа в хвост списка):**
   Разместить файл на всех мастерах:
   ```yaml
   apiVersion: apiserver.config.k8s.io/v1
   kind: EncryptionConfiguration
   resources:
     - resources:
         - secrets
       providers:
         - identity: {}
         - aesgcm:
             keys:
               - name: key-v1
                 secret: <base64-key>
   ```
   Дождаться применения конфигурации (контроллер перезагружает конфиг автоматически либо перезапустить `kube-apiserver`).

3. **Фаза 2 (сделать ключ активным для записи):**
   Поочередно обновить файл конфигурации на каждом мастере:
   ```yaml
   apiVersion: apiserver.config.k8s.io/v1
   kind: EncryptionConfiguration
   resources:
     - resources:
         - secrets
       providers:
         - aesgcm:
             keys:
               - name: key-v1
                 secret: <base64-key>
         - identity: {}
   ```

4. **Фаза 3 (Storage Migration):**
   Выполнить перезапись существующих объектов для перешифрования на диске (см. Сценарий 5).

5. **Фаза 4 (фиксация):**
   Удалить `- identity: {}` из файлов конфигурации на всех мастерах для предотвращения сохранения данных в открытом виде.

---

### Сценарий 5: Перешифрование существующих данных (Storage Migration)

Команда `kubectl get secrets --all-namespaces -o json | kubectl replace -f -` часто рекомендуется в документации, однако на production-кластерах с тысячами секретов она несет критические риски:
- Загрузка сотен мегабайт JSON в память клиента приводит к падению `kubectl` по OOM.
- При активных мутациях объектов возникают ошибки конфликта ревизий `409 Conflict (the object has been modified)`.
- Массивная лавина параллельных записей перегружает журнал WAL etcd.

#### Надежный Bash-скрипт пакетной постраничной миграции

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Запуск регламентной пакетной перешифровки секретов ==="

NAMESPACES=$(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}')

for ns in ${NAMESPACES}; do
  echo "--- Обработка пространства имен: ${ns} ---"
  
  # Получение списка имен секретов, исключая сервисные токены helm и дефолтные служебные токены
  SECRETS=$(kubectl get secrets -n "${ns}" -o jsonpath='{.items[*].metadata.name}')
  
  for secret in ${SECRETS}; do
    # Попытка безопасного обновления с контролем ошибок
    if kubectl get secret "${secret}" -n "${ns}" -o json | kubectl replace -f - >/dev/null 2>&1; then
      echo "Секрет [${ns}/${secret}] успешно перешифрован."
    else
      echo "ВНИМАНИЕ: Секрет [${ns}/${secret}] изменен во время миграции, повторная попытка..."
      sleep 0.5
      kubectl get secret "${secret}" -n "${ns}" -o json | kubectl replace -f - || echo "ОШИБКА: Пропуск [${ns}/${secret}]"
    fi
    # Задержка 50мс для предотвращения всплесков записи в etcd
    sleep 0.05
  done
done

echo "=== Перешифровка всех секретов завершена ==="
```

#### Использование Kubernetes StorageVersionMigration (K8s 1.30+)

В современных версиях Kubernetes доступен нативный контроллер миграции версий хранения:

```yaml
# migration.yaml
apiVersion: storagemigration.k8s.io/v1alpha1
kind: StorageVersionMigration
metadata:
  name: secrets-encryption-migration
spec:
  resource:
    group: ""
    version: v1
    resource: secrets
```

```bash
kubectl apply -f migration.yaml
# → storageversionmigration.storagemigration.k8s.io/secrets-encryption-migration created

# Мониторинг прогресса миграции
kubectl get storageversionmigration secrets-encryption-migration -o wide
# → NAME                          RUNNING   COMPLETE   AGE
# → secrets-encryption-migration  False     True       42s
```

---

### Сценарий 6: Ротация ключей шифрования

#### 1. Ротация в KMS v2 (HashiCorp Vault)
1. Выполнить ротацию ключа в Vault:
   ```bash
   vault write -f transit/keys/k8s-cluster-kek/rotate
   # → Success! Key k8s-cluster-kek rotated to version 2
   ```
2. API-сервер автоматически обнаруживает изменение версии ключа во время очередного вызова gRPC `Status` или деривации DEK.
3. Перезапуск `kube-apiserver` **не требуется**.
4. Запустить процедуру Storage Migration для перешифрования старых секретов новым KEK v2.

#### 2. Ротация локальных ключей (AES-GCM / AES-CBC)
1. Сгенерировать новый ключ `key-v2`.
2. Поместить `key-v2` **первым** в список ключей провайдера, а старый `key-v1` оставить вторым:
   ```yaml
   providers:
     - aesgcm:
         keys:
           - name: key-v2
             secret: <new-base64-key>
           - name: key-v1
             secret: <old-base64-key>
   ```
3. Благодаря автоматической перезагрузке конфига `kube-apiserver` сразу начнет шифровать новые объекты ключом `key-v2`, сохраняя возможность чтения объектов с ключом `key-v1`.
4. Запустить Storage Migration.
5. Удалить `key-v1` из файла конфигурации.

---

## Операции и команды etcdctl

### Подключение к etcd с mTLS

Для выполнения административных команд требуется аутентификация через клиентские TLS-сертификаты etcd:

```bash
export ETCDCTL_API=3
export ENDPOINTS="https://127.0.0.1:2379"
export CA="/etc/kubernetes/pki/etcd/ca.crt"
export CERT="/etc/kubernetes/pki/etcd/server.crt"
export KEY="/etc/kubernetes/pki/etcd/server.key"

# Алиас для удобства администрирования
alias k8s-etcdctl="ETCDCTL_API=3 etcdctl --endpoints=${ENDPOINTS} --cacert=${CA} --cert=${CERT} --key=${KEY}"
```

### Проверка состояния кластера etcd

```bash
# Проверка доступности и задержки участников кворума
k8s-etcdctl endpoint health --write-out=table
# → +------------------------+--------+-------------+-------+
# → |        ENDPOINT        | HEALTH |    TOOK     | ERROR |
# → +------------------------+--------+-------------+-------+
# → | https://127.0.0.1:2379 |   true | 10.456123ms |       |
# → +------------------------+--------+-------------+-------+

# Проверка физического размера БД и ревизии
k8s-etcdctl endpoint status --write-out=table
# → +------------------------+------------------+---------+---------+-----------+------------+
# → |        ENDPOINT        |        ID        | VERSION | DB SIZE | IS LEADER | REVISION   |
# → +------------------------+------------------+---------+---------+-----------+------------+
# → | https://127.0.0.1:2379 | 8e9e05c52164694d |  3.5.15 |   48 MB |      true |    1845920 |
# → +------------------------+------------------+---------+---------+-----------+------------+
```

### Проверка статуса шифрования секретов в etcd

```bash
# Чтение сырого значения секрета для проверки наличия префикса шифрования
k8s-etcdctl get /registry/secrets/default/app-secret --print-value-only | head -c 40
# → k8s:enc:kms:v2:vault-kms-provider:...

# Проверка конкретного алгоритма шифрования через регулярное выражение
k8s-etcdctl get /registry/secrets/default/app-secret --print-value-only | strings | grep -E '^k8s:enc:(kms|aesgcm|aescbc|secretbox)'
# → k8s:enc:kms:v2:vault-kms-provider:AQICAHg...
```

### Поиск незашифрованных секретов (Аудит безопасности)

Команда обходит все секреты в etcd и выводит список тех, у которых отсутствует маркер `k8s:enc:`:

```bash
k8s-etcdctl get /registry/secrets/ --prefix --keys-only | while read -r key; do
  if [ -n "$key" ]; then
    VAL_PREFIX=$(k8s-etcdctl get "$key" --print-value-only | head -c 8 | tr -d '\0')
    if [[ "$VAL_PREFIX" != "k8s:enc:"* ]]; then
      echo "ТРЕВОГА: Секрет не зашифрован -> $key"
    fi
  fi
done
# → (если пусто — все секреты в etcd успешно зашифрованы)
```

### Обслуживание дискового пространства etcd

```bash
# 1. Получение текущей ревизии
CURRENT_REV=$(k8s-etcdctl endpoint status --write-out=json | jq -r '.[0].Status.header.revision')
echo "Текущая ревизия etcd: ${CURRENT_REV}"
# → Текущая ревизия etcd: 1845920

# 2. Компакция базы (удаление истории изменений строго до указанной ревизии)
k8s-etcdctl compact "${CURRENT_REV}"
# → compacted revision 1845920

# 3. Дефрагментация (освобождение дискового пространства bbolt на локальном узле)
k8s-etcdctl defrag --endpoints=https://127.0.0.1:2379
# → Finished defragmenting etcd member[https://127.0.0.1:2379]

# 4. Проверка и снятие тревог переполнения квоты (alarm NOSPACE)
k8s-etcdctl alarm list
# → (если список пуст, тревог нет)

# В случае срабатывания тревоги переполнения после defrag:
k8s-etcdctl alarm disarm
# → alarm:NOSPACE disarmed
```

---

## Резервное копирование и аварийное восстановление

> [!CRITICAL]
> Снапшот базы данных etcd, созданный при включенном `EncryptionConfiguration`, абсолютно бесполезен без точной копии конфигурационного файла `encryption-config.yaml` и доступа к соответствующим ключам KEK/KMS. Восстановление зашифрованного etcd без ключей приводит к полной потере кластера.

### Регламент создания атомарного бэкапа

Резервная копия должна объединять состояние базы и ключи в единый защищенный архив.

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/k8s-controlplane/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

echo "1. Сохранение снапшота etcd..."
ETCDCTL_API=3 etcdctl snapshot save "${BACKUP_DIR}/etcd.db" \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → Snapshot saved at /var/backups/k8s-controlplane/.../etcd.db

echo "2. Проверка валидности снапшота..."
ETCDCTL_API=3 etcdctl snapshot status "${BACKUP_DIR}/etcd.db" --write-out=table
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | d41d8cd9 |  1845920 |       4210 |      48 MB |
# → +----------+----------+------------+------------+

echo "3. Архивация конфигурации шифрования и сопутствующих сертификатов..."
cp -p /etc/kubernetes/encryption-config.yaml "${BACKUP_DIR}/encryption-config.yaml"
tar -czf "${BACKUP_DIR}/pki-certs.tar.gz" -C /etc/kubernetes/pki etcd ca.crt ca.key

echo "4. Создание контрольных сумм SHA-256..."
sha256sum "${BACKUP_DIR}"/* > "${BACKUP_DIR}/checksums.sha256"

echo "Бэкап успешно сформирован в каталоге: ${BACKUP_DIR}"
```

### Процедура аварийного восстановления из бэкапа

1. **Остановка компонентов Control Plane на всех мастерах:**
   ```bash
   mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
   mv /etc/kubernetes/manifests/etcd.yaml /tmp/
   ```

2. **Восстановление EncryptionConfiguration:**
   ```bash
   cp /var/backups/k8s-controlplane/<DATE>/encryption-config.yaml /etc/kubernetes/encryption-config.yaml
   chmod 600 /etc/kubernetes/encryption-config.yaml
   ```

3. **Восстановление базы etcd в новый каталог данных:**
   ```bash
   ETCDCTL_API=3 etcdctl snapshot restore /var/backups/k8s-controlplane/<DATE>/etcd.db \
     --data-dir=/var/lib/etcd-restored \
     --name=master-1 \
     --initial-cluster=master-1=https://192.168.10.11:2380 \
     --initial-cluster-token=etcd-cluster-restore \
     --initial-advertise-peer-urls=https://192.168.10.11:2380
   # → Restoring snapshot to /var/lib/etcd-restored ...
   # → Added member master-1 to cluster
   ```

4. **Переключение etcd на новые данные:**
   ```bash
   rm -rf /var/lib/etcd
   mv /var/lib/etcd-restored /var/lib/etcd
   chown -R root:root /var/lib/etcd
   ```

5. **Возврат манифестов static pods и проверка работоспособности:**
   ```bash
   mv /tmp/etcd.yaml /etc/kubernetes/manifests/
   mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
   
   # Проверка доступности секретов
   kubectl get secrets -A
   # → NAMESPACE     NAME                  TYPE     DATA   AGE
   # → default       app-db-pass           Opaque   1      12d
   ```

---

## Наблюдаемость и мониторинг

### Ключевые метрики Prometheus

#### Метрики kube-apiserver (Encryption / Envelope)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `apiserver_storage_transformation_operations_total` | Counter | Общее число операций трансформации с лейблами `resource` (`secrets`), `transformation_type` (`encrypt`/`decrypt`). |
| `apiserver_storage_transformation_failures_total` | Counter | Количество сбоев шифрования или дешифрования. Любой рост означает инцидент. |
| `apiserver_storage_envelope_transformation_latency_seconds_bucket` | Histogram | Задержка операций шифрования/дешифрования с использованием KMS v2. |
| `apiserver_encryption_config_controller_automatic_reloads_total` | Counter | Количество успешных горячих перезагрузок файла `EncryptionConfiguration`. |
| `apiserver_encryption_config_controller_automatic_reload_failures_total` | Counter | Ошибки парсинга или валидации нового файла `EncryptionConfiguration`. |
| `kms_operation_duration_seconds_bucket` | Histogram | Время gRPC-запросов (`encrypt`, `decrypt`, `status`) от плагина к внешнему KMS. |

#### Метрики etcd

| Метрика | Тип | Пороговое значение SRE | Описание |
| :--- | :--- | :--- | :--- |
| `etcd_server_has_leader` | Gauge | `!= 1` | Отсутствие лидера в кластере etcd. |
| `etcd_disk_wal_fsync_duration_seconds` | Histogram | p99 > 10ms | Задержка синхронизации WAL на диске. |
| `etcd_mvcc_db_total_size_in_bytes` | Gauge | > 2.147.483.648 (2 ГиБ) | Физический объем базы данных etcd. |
| `etcd_server_leader_changes_seen_total` | Counter | Рост > 3 за 15 мин | Нестабильность кворума / частая смена лидеров. |

---

### Примеры правил алертинга (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: k8s-etcd-encryption-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
    - name: etcd-encryption.rules
      rules:
        - alert: KubeSecretDecryptionFailure
          expr: increase(apiserver_storage_transformation_failures_total[2m]) > 0
          for: 0m
          labels:
            severity: critical
            tier: control-plane
          annotations:
            summary: "Критический сбой дешифрования секретов в etcd"
            description: "kube-apiserver зафиксировал {{ $value }} ошибок дешифрования за последние 2 минуты. Возможные причины: повреждение ключа KEK, сбой KMS-плагина или рассинхронизация EncryptionConfiguration."

        - alert: KMSPluginHighLatency
          expr: histogram_quantile(0.99, rate(kms_operation_duration_seconds_bucket[5m])) > 0.5
          for: 3m
          labels:
            severity: warning
            tier: control-plane
          annotations:
            summary: "Высокая задержка вызовов KMS (> 500мс p99)"
            description: "Задержка операций gRPC KMS плагина составляет {{ $value }}s на 99 перцентиле. Это замедляет создание и чтение Secret/ConfigMap."

        - alert: EncryptionConfigReloadFailed
          expr: increase(apiserver_encryption_config_controller_automatic_reload_failures_total[5m]) > 0
          for: 0m
          labels:
            severity: high
            tier: control-plane
          annotations:
            summary: "Ошибка перезагрузки файла EncryptionConfiguration"
            description: "kube-apiserver не смог применить обновленный конфигурационный файл шифрования из-за синтаксической ошибки или недоступности сокета."

        - alert: EtcdDatabaseApproachingQuota
          expr: etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.8
          for: 5m
          labels:
            severity: warning
            tier: storage
          annotations:
            summary: "База данных etcd заполнена более чем на 80%"
            description: "Размер bbolt базы etcd превысил 80% от лимита квоты. Требуется провести compaction и defragmentation."
```

---

## Диагностика и устранение неполадок

### Матрица типовых инцидентов

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Internal error: failed to decode secret` | Утерян ключ шифрования или удален провайдер `identity` до окончания миграции | `kubectl logs -n kube-system kube-apiserver-<node> \| grep "transformation"` | Восстановить старый ключ в `EncryptionConfiguration` вторым в списке провайдеров. |
| `kube-apiserver` уходит в CrashLoopBackOff | Ошибка в YAML `EncryptionConfiguration`, недопустимый алгоритм, неверная длина ключа | `crictl logs $(crictl ps -a --name kube-apiserver -q)` | Проверить длину ключа (32 байта для AES-256) и корректность синтаксиса `apiserver.config.k8s.io/v1`. |
| `stat /var/run/kms-plugin/vault-plugin.sock: no such file or directory` | Падение Static Pod плагина KMS или некорректный `hostPath` | `ls -la /var/run/kms-plugin/` и `crictl ps -a \| grep kms` | Перезапустить pod KMS-плагина, проверить права на директорию (`root:root`, 700). |
| `etcdserver: mvcc: database space exceeded` | Достигнут лимит размера базы (по умолчанию 2–8 ГиБ), включился `alarm NOSPACE` | `k8s-etcdctl alarm list` | Запустить `compact`, затем поузловой `defrag`, после чего выполнить `alarm disarm`. |
| Разные мастера отдают разные ошибки при чтении секрета | Рассинхронизация файлов `encryption-config.yaml` между узлами HA | Сравнить `sha256sum /etc/kubernetes/encryption-config.yaml` на всех узлах | Синхронизировать конфигурацию на всех мастерах. |

---

### Команды глубокой диагностики SRE

```bash
# 1. Проверка логов контроллера шифрования kube-apiserver
kubectl logs -n kube-system kube-apiserver-master-1 --tail=100 | grep -E "encryption|kms|transformer"
# → I1017 14:20:10.123456 encryption_config_controller.go:128] "Encryption config reloaded successfully"

# 2. Проверка статуса сокета KMS через curl/grpcurl
curl --unix-socket /var/run/kms-plugin/vault-plugin.sock http://localhost/healthz
# → ok

# 3. Диагностика соединения API-сервера с etcd
kubectl logs -n kube-system kube-apiserver-master-1 | grep "etcdserver" | tail -n 20

# 4. Проверка прав и контекста безопасности на сокет
ls -laZ /var/run/kms-plugin/vault-plugin.sock
# → srw-------. 1 root root system_u:object_r:container_file_t:s0 0 Oct 17 14:00 /var/run/kms-plugin/vault-plugin.sock

# 5. Анализ распределения размера секретов в кластере
kubectl get secrets -A -o json | jq -r '
  .items[] | 
  {
    ns: .metadata.namespace, 
    name: .metadata.name, 
    bytes: (.data // {} | to_entries | map(.value | length) | add // 0)
  } | select(.bytes > 50000) | "\(.bytes) байт: \(.ns)/\(.name)"' | sort -nr
# → 524288 байт: production/large-bundle-certs
```

---

## Риски и лучшие практики

### Практики для системных инженеров и SRE

1. **Приоритет KMS v2:** для production-инфраструктуры используйте KMS v2 в связке с изолированным кластером HashiCorp Vault. Локальные ключи (`aesgcm`) применяйте только для тестовых контуров или автономных edge-узлов.
2. **Неразрывность бэкапов:** бэкап etcd без сохранения `encryption-config.yaml` и ключей KMS бесполезен. Автоматизируйте резервное копирование связки базы и конфигурации в изолированное защищенное хранилище (S3/MinIO с WORM-политикой).
3. **Безопасность файловой системы хоста:**
   - Права на `/etc/kubernetes/encryption-config.yaml` должны быть строго `0600`, владелец `root:root`.
   - Доступ к сокету `/var/run/kms-plugin/vault-plugin.sock` должен быть ограничен только пользователем `root`.
4. **Запрет массовых запросов (`list`/`watch`):**
   - Предоставление права `list` на секреты на уровне всего кластера (`ClusterRole`) позволяет злоумышленнику выгрузить все секреты в открытом виде через API-сервер в обход шифрования etcd.
   - Используйте строгий RBAC с ограничением доступа по конкретным именам ресурсов (`resourceNames`).
5. **Контроль размера etcd:**
   - Не храните в `Secret` файлы размером более 256 КиБ. Для передачи крупных конфигурационных файлов используйте специализированные хранилища артефактов.
   - Настройте периодическую компакцию и еженедельную дефрагментацию etcd в часы минимальной нагрузки.
6. **Тестирование восстановления (Disaster Recovery Drill):** не реже одного раза в квартал проводите учебное восстановление снапшота etcd на тестовом стенде со сквозной проверкой расшифровки секретов через API.
7. **Включение шифрования для ConfigMap:** если в кластере исторически сложилась практика хранения токенов или паролей в `ConfigMap`, включите шифрование для ресурса `configmaps` в том же файле `EncryptionConfiguration`.

---

## Смотрите также

*   **[Безопасность Secret](security.md)** — RBAC, аудит доступа и жизненный цикл секретов.
*   **[Создание Secret](creating_secrets.md)** — типы данных, кодирование и способы определения секретов.
*   **[Внешние менеджеры секретов](external_managers.md)** — интеграция с Vault и External Secrets Operator.
*   **[Архитектура etcd](../../../etcd/architecture-and-concepts.md)** — внутреннее устройство Raft, MVCC и движка bbolt.
*   **[Безопасность etcd](../../../etcd/security.md)** — взаимная TLS-аутентификация, права доступа и защита сетевого контура etcd.
*   **[Резервное копирование etcd](../../../etcd/backup_strategies.md)** — регламенты создания и валидации снапшотов etcd.
