# Управление сертификатами Kubernetes через kubeadm

## Определения

**kubeadm** — стандартная утилита управления жизненным циклом кластера, предоставляющая инструменты для выпуска, проверки и продления сертификатов Control Plane.

**CA (Certificate Authority)** — доверенный центр сертификации. Kubernetes использует несколько независимых CA (для API-сервера, etcd и front-proxy) для реализации принципа наименьших привилегий. Подробнее: [Обзор PKI](../../Security/Concepts/pki_overview.md).

**Leaf Certificates (Листовые сертификаты)** — сертификаты конечных компонентов (например, `apiserver`), подписанные соответствующим CA.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата. Используется компонентами (особенно Kubelet) для получения или обновления своих сертификатов через API-сервер.

**Admin kubeconfig** — файл `/etc/kubernetes/admin.conf`, содержащий клиентский сертификат пользователя `kubernetes-admin`. По умолчанию срок его действия также составляет 1 год.

**SSoT (Single Source of Truth) для сертификатов** — в кластере kubeadm это директория `/etc/kubernetes/pki` на каждом Control Plane узле. Все ротации должны инициироваться отсюда и синхронизироваться на другие мастера.

### Ключевые сертификаты Control Plane

Все сертификаты и ключи по умолчанию хранятся в директории `/etc/kubernetes/pki`.

| Файл сертификата | Назначение | Кем подписан |
| :--- | :--- | :--- |
| **ca.crt** | Основной корневой CA кластера | Self-signed |
| **apiserver.crt** | Сертификат сервера API (порт 6443) | ca.crt |
| **apiserver-kubelet-client.crt** | Клиентский сертификат API → Kubelet | ca.crt |
| **front-proxy-ca.crt** | CA для агрегированного API-слоя | Self-signed |
| **front-proxy-client.crt** | Клиент для агрегированного API | front-proxy-ca.crt |
| **etcd/ca.crt** | Корневой CA для кластера etcd | Self-signed |
| **etcd/server.crt** | Сертификат узла etcd | etcd/ca.crt |
| **etcd/peer.crt** | Для взаимодействия узлов etcd между собой | etcd/ca.crt |
| **etcd/healthcheck-client.crt** | Клиентский сертификат для проверки здоровья etcd | etcd/ca.crt |
| **apiserver-etcd-client.crt** | Клиентский сертификат API → etcd | etcd/ca.crt |
| **sa.key / sa.pub** | Ключи подписи ServiceAccount токенов (не сертификаты) | — |

## Основные концепции

### Сроки действия и ротация

| Тип сертификата | Срок действия | Способ обновления |
| :--- | :--- | :--- |
| **Корневые CA** | 10 лет | Ручная ротация (сложный процесс) |
| **Сертификаты компонентов** | 1 год | Автоматически (при `upgrade`) или `renew` |
| **Admin kubeconfig** | 1 год | Автоматически (при `upgrade`) или `renew` |
| **Kubelet client** | 1 год | Автоматическая ротация (при включенном `rotateCertificates`) |
| **Kubelet serving** | 1 год | Автоматическая ротация (при `serverTLSBootstrap: true` + CSR Approver) |

> **Важно:** Обновление версии Kubernetes через `kubeadm upgrade` автоматически продлевает все сертификаты, управляемые kubeadm. Если вы не планируете обновлять версию кластера до истечения года, необходимо выполнить ручное продление.

### Ротация Root CA (Корневых сертификатов)

В отличие от листовых сертификатов, ротация корневых CA (`ca.crt`, `etcd/ca.crt`, `front-proxy-ca.crt`) — это сложная и потенциально опасная процедура, требующая простоя (downtime) или использования смешанного (dual-stacked) CA на период переходного процесса.

*   **Ограничение `kubeadm`:** Команда `kubeadm certs renew` **не обновляет** корневые CA.
*   **Дистрибуция доверия:** При замене Root CA новые корневые сертификаты должны быть доставлены на все узлы кластера (включая worker nodes) и в поды, использующие ServiceAccount токены. Для автоматизации доставки `ca.crt` в распределенных системах часто используются инструменты вроде **trust-manager** (аддон для cert-manager).
*   **Процедура двойного CA (Dual-stack):** Для ротации без downtime используется параллельная работа двух CA (старого и нового). Новые сертификаты выпускаются новым CA, после чего старый CA деактивируется. Это требует точного планирования и синхронизации на всех узлах.

### ServiceAccount Keys (Ключи подписи токенов)

В директории `/etc/kubernetes/pki/` находятся файлы `sa.key` (приватный ключ) и `sa.pub` (публичный ключ).

*   **Назначение:** Эти ключи используются `kube-controller-manager` для криптографической подписи JWT-токенов ServiceAccounts, и `kube-apiserver` для их верификации.
*   **Технический нюанс:** Это ключи асимметричного шифрования (RSA), а не сертификаты X.509. Они **не имеют встроенного срока действия (expiration date)**.
*   **Ротация:** Команда `kubeadm certs check-expiration` их игнорирует. Их ротация требуется только в случае компрометации (утечки `sa.key`). Процесс ротации требует временного использования флагов `--service-account-key-file` с обоими ключами (старым и новым) для обеспечения плавного перехода без инвалидации всех существующих токенов в кластере.
*   **Bound ServiceAccount Tokens (v1.24+):** Начиная с K8s 1.24, используются только краткосрочные привязанные токены (bound SA tokens). Они имеют TTL (по умолчанию 1 час) и подписываются текущим `sa.key`. При компрометации ключа все токены автоматически становятся невалидными.

### ServiceAccount Token Projection и поды

В каждом поде маунтится том `kube-api-access-<name>` с автоматически сгенерированным kubeconfig. Этот kubeconfig содержит встроенный CA `kube-root-ca.crt`, который автоматически обновляется при ротации Root CA и не требует ручного вмешательства. Срок его действия составляет 30 дней (по умолчанию), что перекрывает максимальный TTL bound SA токена.

### Ротация сертификатов etcd

Сертификаты etcd (`etcd/ca.crt`, `etcd/server.crt`, `etcd/peer.crt`, `etcd/healthcheck-client.crt`, `apiserver-etcd-client.crt`) хранятся в `/etc/kubernetes/pki/etcd/` и ротируются вместе с остальными через `kubeadm certs renew all`. Однако:

*   **Внешний etcd:** Если etcd развернут на отдельных ВМ вне управления kubeadm, его сертификаты необходимо ротировать отдельно (вручную или через Ansible/Terraform).
*   **etcd healthcheck-client:** Используется для проверки здоровья etcd через `etcdctl`. При его истечении команды администрирования etcd перестают работать, хотя сам кластер может функционировать.
*   **Ротация во время работы:** `kubeadm certs renew` перезаписывает файлы на диске, но работающие статические поды API-сервера и etcd продолжают использовать старые сертификаты до перезапуска.

### Версионный сдвиг (Version Skew)

Утилита `kubeadm` должна соответствовать версии API-сервера (разница не более чем на одну минорную версию). Использование `kubeadm` более новой версии, чем текущий Control Plane, для управления его сертификатами не рекомендуется и может привести к несовместимости форматов сертификатов.

### Настройка сроков и алгоритмов (v1.31+, v1beta4 API)

В современных версиях `kubeadm` (начиная с API `v1beta4`) появилась возможность не только гибко переопределять сроки действия сертификатов, но и явно задавать алгоритм шифрования, отказавшись от устаревшего Feature Gate.

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
# Явное указание алгоритма шифрования (вместо RSA-2048 по умолчанию).
# Использование ECDSA повышает производительность TLS-хендшейков.
encryptionAlgorithm: "ECDSA-P256"
# Гранулярный контроль над сроком жизни листовых сертификатов
certificateValidityPeriod: 8760h      # Листовые сертификаты (1 год)
# Контроль над сроком жизни корневых CA
caCertificateValidityPeriod: 87600h   # CA сертификаты (10 лет)
```

*Внимание:* Переход с RSA на ECDSA должен осуществляться при инициализации нового кластера; `kubeadm` не поддерживает изменение алгоритма "на лету" во время обновления или ротации сертификатов.

### Внешний CA (External CA)

Если кластер был инициализирован с флагом `--external-ca`, `kubeadm` не генерирует корневые CA и не управляет листовыми сертификатами. В этом случае:
*   `kubeadm certs check-expiration` покажет только `admin.conf` и `kubelet.conf` (если они были созданы kubeadm).
*   Ротацию всех сертификатов необходимо выполнять вручную или через внешнюю автоматизацию (Ansible, Vault, cert-manager).
*   При использовании External CA убедитесь, что все узлы доверяют внешнему Root CA (файл должен быть в `/etc/kubernetes/pki/ca.crt`).

## Практические сценарии

Все команды должны выполняться под учетной записью `root` на узлах Control Plane.

### Проверка срока действия

```bash
sudo kubeadm certs check-expiration
```
Команда анализирует файлы в `/etc/kubernetes/pki` и конфигурационные файлы в `/etc/kubernetes/*.conf`.

Для проверки конкретного сертификата (например, etcd CA):
```bash
openssl x509 -in /etc/kubernetes/pki/etcd/ca.crt -noout -dates
# → notBefore=Mar 15 12:00:00 2025 GMT
# → notAfter=Mar 15 12:00:00 2035 GMT
```

### Ручное продление всех сертификатов

Если до истечения срока осталось мало времени:

```bash
sudo kubeadm certs renew all
```

После выполнения этой команды сертификаты обновляются на диске, но **работающие компоненты (API-сервер, etcd) продолжают использовать старые сертификаты в памяти**.

### Применение обновленных сертификатов

Чтобы изменения вступили в силу, необходимо перезапустить статические поды Control Plane:

1. **Автоматический способ:** Kubelet обычно замечает изменение файлов в `/etc/kubernetes/manifests` и перезапускает поды.
2. **Гарантированный способ:**
    ```bash
    sudo systemctl restart kubelet
    ```
3. **Принудительный способ (через временное перемещение):**
    ```bash
    sudo mv /etc/kubernetes/manifests/*.yaml /tmp/
    sleep 20
    sudo mv /tmp/*.yaml /etc/kubernetes/manifests/
    ```

### Выборочное продление сертификатов

Вместо `renew all` можно продлить конкретные сертификаты (полезно для диагностики или точечного исправления):

```bash
# Продление только сертификата API-сервера
sudo kubeadm certs renew apiserver

# Продление сертификатов etcd
sudo kubeadm certs renew etcd-server etcd-peer etcd-healthcheck-client apiserver-etcd-client

# Продление admin.conf
sudo kubeadm certs renew admin.conf
```

### Ротация сертификатов в HA-кластерах

В кластерах с несколькими мастерами (High Availability):
1. Продление сертификатов должно быть выполнено **на каждом узле Control Plane** независимо.
2. Сертификаты `ca.crt`, `etcd/ca.crt` и `front-proxy-ca.crt` должны быть **идентичны** на всех узлах. Если вы решите сменить CA, его нужно скопировать на все узлы вручную.
3. **Рекомендуемый порядок:**
   - Сначала выполните `renew all` на одном мастере.
   - Перезапустите kubelet на этом мастере и убедитесь, что все статические поды запустились.
   - Затем выполните ту же процедуру на остальных мастерах по очереди.
   - Проверьте кворум etcd после каждого мастера: `ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt --key=/etc/kubernetes/pki/etcd/healthcheck-client.key endpoint health`.

### Обновление Admin Kubeconfig

После `kubeadm certs renew all` сертификат внутри `/etc/kubernetes/admin.conf` обновляется. Если вы используете копию этого файла в `~/.kube/config`, её нужно обновить:

```bash
sudo cp /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

Для проверки срока действия сертификата в kubeconfig:
```bash
grep 'client-certificate-data' ~/.kube/config | awk '{print $2}' | base64 -d | openssl x509 -noout -dates
```

### Добавление новых Subject Alternative Names (SANs)

Если вам нужно добавить новый IP или DNS-имя (например, адрес внешнего балансировщика) в сертификат API-сервера:

1. Отредактируйте `kubeadm-config` ConfigMap:
    ```bash
    kubectl edit cm kubeadm-config -n kube-system
    ```
    Добавьте в `ClusterConfiguration`:
    ```yaml
    apiServer:
      certSANs:
      - "1.2.3.4"
      - "api.example.com"
    ```
2. Удалите текущий сертификат:
    ```bash
    sudo rm /etc/kubernetes/pki/apiserver.{crt,key}
    ```
3. Сгенерируйте его заново:
    ```bash
    sudo kubeadm init phase certs apiserver --config /path/to/local/config.yaml
    ```
4. Перезапустите статический под API-сервера:
    ```bash
    sudo systemctl restart kubelet
    ```

### Ротация сертификатов Kubelet (Server TLS Bootstrap)

По умолчанию Kubelet использует сертификаты, выписанные при инициализации. Клиентские сертификаты (для связи с API) ротируются автоматически, однако **серверные сертификаты** (порт 10250 для `kubectl exec`, `logs`, `metrics-server`) требуют дополнительной настройки. Без этого API-сервер часто работает в режиме `insecure-skip-tls-verify` при обращении к узлам.

1. **Включение Bootstrap**:
    - **Kubeadm / Generic**: В `KubeletConfiguration` установите:
      ```yaml
      serverTLSBootstrap: true
      rotateCertificates: true
      ```
    - **Talos Linux**: В конфигурации узла (`machine.kubelet.extraConfig`):
      ```yaml
      machine:
        kubelet:
          extraConfig:
            serverTLSBootstrap: true
      ```
2. **Процесс**:
    После перезапуска Kubelet создаст CSR для signer `kubernetes.io/kubelet-serving`.
    ```bash
    kubectl get csr
    # → Состояние: Pending
    ```
3. **Одобрение запроса (вручную)**:
    ```bash
    kubectl certificate approve <csr-name>
    ```

**Автоматизация одобрения (CSR Approver)**:
Встроенный контроллер `kubernetes.io/kubelet-serving` **не одобряет** такие CSR автоматически из соображений безопасности.

*   **Рекомендуемое решение (2026):** Контроллер `kubelet-serving-cert-approver`. Он сверяет SAN из запроса с реальными адресами объекта `Node` и одобряет CSR только при полном совпадении.
*   **Установка (Standalone):**
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/alex1989hu/kubelet-serving-cert-approver/main/deploy/standalone-install.yaml
    ```
*   **Безопасность (RBAC):** Контроллер должен иметь права только на конкретный signer для минимизации ущерба:
    ```yaml
    - apiGroups: ["certificates.k8s.io"]
      resourceNames: ["kubernetes.io/kubelet-serving"]
      resources: ["signers"]
      verbs: ["approve"]
    ```

> **Внимание (Security Warning):** При использовании любого кастомного CSR-аппрувера (например, `kubelet-csr-approver`) убедитесь, что он строго верифицирует не только `CommonName`, но и запрошенные IP-адреса и DNS-имена (SANs) в CSR. Это предотвращает атаки, при которых скомпрометированный узел может запросить сертификат для чужого IP или домена.

**Верификация**:
После одобрения проверьте эндпоинт узла:
```bash
echo | openssl s_client -connect <node-ip>:10250 -showcerts 2>/dev/null \
  | openssl x509 -noout -issuer -subject
# → issuer: CN = kubernetes (или CA кластера)
# → subject: CN = system:node:<node-name>
```

### Восстановление после потери CA (Disaster Recovery)

Потеря файлов `ca.key` (приватного ключа корневого CA) — критический инцидент. Восстановление возможно только из резервной копии.

**Сценарий: потеря `/etc/kubernetes/pki/ca.key`**

1. **Остановка Control Plane:** Переместите все манифесты из `/etc/kubernetes/manifests/` во временную директорию, чтобы остановить статические поды.
2. **Восстановление из бэкапа:** Восстановите пару `ca.key` + `ca.crt` из резервной копии.
3. **Проверка цепочки:** Убедитесь, что все листовые сертификаты (`apiserver.crt`, `etcd/server.crt` и др.) были подписаны восстановленным CA:
    ```bash
    openssl verify -CAfile /etc/kubernetes/pki/ca.crt /etc/kubernetes/pki/apiserver.crt
    # → apiserver.crt: OK
    ```
4. **Перезапуск:** Верните манифесты на место и перезапустите kubelet.
5. **Распространение на worker nodes:** Если worker nodes кэшировали `ca.crt` (например, в kubelet.conf), обновите их:
    ```bash
    # На каждом worker node
    sudo cp /etc/kubernetes/pki/ca.crt /var/lib/kubelet/ca.crt
    sudo systemctl restart kubelet
    ```

> **Предупреждение:** Если бэкапа `ca.key` нет, единственный вариант — полная реинициализация кластера с новым CA. Это приведет к потере всех объектов Kubernetes, так как старые сертификаты перестанут валидироваться новым CA. В крайнем случае можно использовать флаг `--config` с новым CA и перевыпустить все сертификаты, но это потребует перезапуска всех компонентов и может вызвать downtime.

### Восстановление сертификата API-сервера после сбоя

Если `apiserver.crt` или `apiserver.key` повреждены или утеряны, но Root CA (`ca.crt` + `ca.key`) целы:

```bash
# 1. Удалите поврежденные файлы
sudo rm /etc/kubernetes/pki/apiserver.{crt,key}

# 2. Перегенерируйте сертификат через kubeadm
sudo kubeadm init phase certs apiserver --config /etc/kubernetes/admin.conf

# 3. Перезапустите kubelet
sudo systemctl restart kubelet
```

Для изменения SAN без полного перевыпуска используйте редактирование ConfigMap (см. раздел "Добавление новых SANs").

### Полный сценарий ротации в HA-кластере (пошаговый)

```bash
# === МАСТЕР 1 ===
# 1. Проверка текущего состояния
sudo kubeadm certs check-expiration
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key endpoint health

# 2. Бэкап PKI (обязательно!)
sudo tar -czf /var/lib/kube-backups/pki-pre-renew-$(date +%F).tar.gz /etc/kubernetes/pki

# 3. Продление
sudo kubeadm certs renew all

# 4. Перезапуск компонентов
sudo systemctl restart kubelet

# 5. Валидация (подождите 30-60 секунд)
sudo kubeadm certs check-expiration
kubectl get nodes
kubectl get pods -n kube-system -l component=kube-apiserver
ETCDCTL_API=3 etcdctl endpoint health

# === МАСТЕР 2 (после успешного прохождения МАСТЕРА 1) ===
# Повторите шаги 1-5 на втором мастере

# === МАСТЕР 3 (после успешного прохождения МАСТЕРА 2) ===
# Повторите шаги 1-5 на третьем мастере
```

### Автоматизация через Ansible (Kubespray)

В инфраструктуре под управлением Kubespray ротация сертификатов выполняется через playbook:

```bash
# Плановая ротация через теги
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml \
  --tags=certificates,kubeadm

# Ротация только сертификатов etcd
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml \
  --tags=etcd
```

## Диагностика и устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **x509: certificate has expired** | Срок действия истек | Выполнить `renew all` и перезапустить компоненты. |
| **Unable to connect to the server: x509...** | Истек клиентский сертификат в kubeconfig | Обновить `admin.conf` и скопировать его в `~/.kube/config`. |
| **etcd connection refused (TLS error)** | Несовпадение CA или истечение `apiserver-etcd-client` | Проверить целостность `/etc/kubernetes/pki/etcd/ca.crt` на всех узлах. |
| **Расхождение времени на узлах** | Сертификат "еще не валиден" или "уже истек" | Настройте синхронизацию времени через `ntp` или `chrony`. |
| **serverTLSBootstrap не работает** | Отсутствует CSR Approver в кластере | Установите `kubelet-serving-cert-approver` или одобряйте CSR вручную. |
| **kubeadm certs renew не обновляет ca.crt** | Ожидаемое поведение | Root CA ротируются только вручную. Используйте `kubeadm init phase certs` для отдельного компонента при необходимости. |
| **Потеря ca.key** | Удаление или повреждение файла | Восстановите из бэкапа. Без бэкапа требуется полная реинициализация кластера. |
| **Сертификаты не совпадают между мастерами** | Ротация выполнена не на всех узлах | Скопируйте `/etc/kubernetes/pki` с обновленного мастера на остальные. |

## Дополнительная информация

### Лучшие практики

* **Бэкап PKI:** Регулярно резервное копируйте `/etc/kubernetes/pki` (особенно `ca.key`, `sa.key`, `etcd/ca.key`). Храните бэкап в защищенном месте (offline/HSM). Автоматизируйте бэкап через cron на каждом Control Plane узле.
* **Мониторинг:** Используйте Prometheus Blackbox Exporter или специализированные скрипты для проверки срока действия сертификата на порту 6443. Автоматизируйте алертинг за 30 дней до истечения.
* **Синхронизация времени:** Убедитесь, что все узлы кластера используют NTP (chrony/ntpd). Расхождение времени более 5 секунд приводит к некорректной валидации сертификатов.
* **Kubelet cert dir:** Начиная с K8s 1.24, kubelet хранит свои клиентские сертификаты в `/var/lib/kubelet/pki/` (а не в `/etc/kubernetes/pki/`). Ротация этих сертификатов происходит автоматически при `rotateCertificates: true`.
* **Идемпотентность:** Команда `kubeadm certs renew` идемпотентна — её можно безопасно выполнять несколько раз подряд.

### Проверка целостности PKI

Перед ротацией и после неё рекомендуется выполнять проверку целостности сертификатов:

```bash
# Проверка соответствия ключа и сертификата (RSA)
openssl rsa -noout -modulus -in /etc/kubernetes/pki/apiserver.key | openssl md5
openssl x509 -noout -modulus -in /etc/kubernetes/pki/apiserver.crt | openssl md5
# Хеши должны совпадать

# Проверка цепочки доверия для apiserver.crt
openssl verify -CAfile /etc/kubernetes/pki/ca.crt /etc/kubernetes/pki/apiserver.crt
# → apiserver.crt: OK

# Проверка цепочки для etcd/server.crt
openssl verify -CAfile /etc/kubernetes/pki/etcd/ca.crt /etc/kubernetes/pki/etcd/server.crt
# → etcd/server.crt: OK
```

### Ограничения

* `kubeadm` не управляет сертификатами, если кластер был развернут с использованием внешнего CA (External CA).
* Автоматическое продление через `kubeadm upgrade` работает только для сертификатов, расположенных в стандартных путях.
* Корневые CA не ротируются автоматически — требуется ручная процедура.
* В кластерах с внешним etcd его сертификаты нужно ротировать отдельно.

### Связанные темы

* [Предотвращение истечения SSL](./ssl_expiration_prevention.md) — общая стратегия мониторинга и алертинга.
* [Обновление кластера](./upgrading_clusters.md) — автоматическая ротация в процессе апгрейда.
* [Обзор PKI в Kubernetes](../../Security/Concepts/pki_overview.md) — глубокое понимание иерархии доверия.
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — концепции безопасности соединений.
* [Kubeconfig: Подключение к кластеру](../Operations/kubeconfig_and_connection.md) — структура конфигурационных файлов и управление учетными данными.
* [etcd: практические сценарии](../Concepts/etcd_operations.md) — администрирование хранилища, включая управление сертификатами.
* [Бэкап и DR для Kubernetes](../Operations/backup-strategies.md) — стратегии резервного копирования etcd и PKI.
