# TLS и mTLS в Kubernetes

## Определения

* **CA (Certificate Authority / Центр сертификации):** Доверенный "удостоверяющий центр", который выпускает и подписывает цифровые сертификаты. В кластере Kubernetes существует корневой CA (Root CA), который является корнем доверия для всего кластера. Технически, это такой же сертификат x.509, но с правом подписывать другие сертификаты (`CA:TRUE`).
* **Приватный ключ (Private Key):** Секретная часть криптографической пары, используемая для создания цифровых подписей и расшифровки данных. Должна храниться в строжайшем секрете.
* **Публичный ключ (Public Key):** Открытая часть криптографической пары. Используется для проверки цифровой подписи и шифрования данных. Распространяется внутри сертификата.
* **Сертификат (x.509 Certificate):** Цифровой документ, связывающий публичный ключ с идентификационными данными (например, `system:node:node01`). Подлинность заверяется подписью CA.
* **CSR (Certificate Signing Request):** Формальный запрос в CA на получение подписанного сертификата. Содержит публичный ключ и идентификационные данные.
* **TLS (Transport Layer Security):** Протокол, обеспечивающий шифрование и целостность данных.
* **mTLS (Mutual TLS):** Взаимная аутентификация, при которой и клиент, и сервер проверяют сертификаты друг друга. Стандарт для компонентов Control Plane.
* **Certificates API:** Ресурс Kubernetes (`CertificateSigningRequest`), позволяющий запрашивать и получать сертификаты через API-сервер.
* **Signer (Подписчик):** Контроллер, ответственный за подпись одобренных CSR (например, `kubernetes.io/kube-apiserver-client`).
* **Kubelet TLS Bootstrapping:** Механизм автоматической генерации ключей и запроса сертификатов для новых узлов кластера.
* **etcd TLS:** Конфигурация шифрования для хранилища etcd, включающая как клиент-серверное взаимодействие, так и общение между узлами (peer-to-peer).
* **Kubeconfig:** Файл конфигурации для доступа к кластеру, содержащий адреса, сертификаты CA и данные аутентификации пользователей/компонентов.

## Основные концепции

### Модель взаимодействия компонентов

* **`kube-apiserver`**: Центральный узел, принимает API-запросы, валидирует их и сохраняет состояние в `etcd`.
* **`kubelet`**: Агент на каждом узле. Получает инструкции от API-сервера и управляет контейнерами.
* **`etcd`**: Распределенное хранилище "ключ-значение", являющееся "мозгом" кластера.

Все коммуникации между компонентами Control Plane и узлами происходят по HTTPS с использованием **mTLS**.

### Процесс mTLS-аутентификации

1. Устанавливается TCP-соединение между сторонами.
2. TLS-рукопожатие:
    * Клиент и сервер обмениваются сертификатами.
    * Каждая сторона проверяет подпись сертификата через доверенный CA кластера.
    * Проверяется владение приватным ключом.
    * Анализируется расширение `extendedKeyUsage`: `serverAuth` для серверов, `clientAuth` для клиентов.
3. После проверки устанавливается зашифрованный канал.

Это гарантирует, что API-сервер доверяет только легитимным агентам `kubelet`, а узлы получают команды только от авторизованного Control Plane.

### Kubernetes Certificates API (CSR Workflow)

Рабочий процесс управления сертификатами внутри кластера:
1. **Создание запроса**: Компонент генерирует ключ и CSR, затем создает объект `CertificateSigningRequest` в API.
2. **Одобрение**: Администратор или контроллер одобряет запрос (`kubectl certificate approve`).
3. **Выпуск**: Signer подписывает запрос и помещает сертификат в поле `status.certificate` объекта CSR.
4. **Использование**: Компонент скачивает сертификат и использует его для TLS-соединений.

### TLS Bootstrapping и ротация

* **Bootstrap Token**: Временный токен, используемый новым `kubelet` для первичной аутентификации в API-сервере и создания CSR.
* **Client Rotation**: Автоматическое обновление клиентского сертификата `kubelet` до истечения его срока действия.
* **Server TLS Bootstrap**: Механизм, позволяющий `kubelet` запрашивать подписанный сертификат для своего HTTPS-сервера (порт 10250), что устраняет необходимость использования самоподписанных сертификатов на узлах.

## Практические сценарии

### Настройка Kubelet Server TLS Bootstrap

Для включения автоматической ротации серверных сертификатов узлов:

1. **Настройка Kubelet**: В файле `kubelet-config.yaml` или через флаги запуска установите:
   ```yaml
   serverTLSBootstrap: true
   ```
2. **Перезапуск Kubelet**: `systemctl restart kubelet`.
3. **Одобрение запроса**:
   ```bash
   # Поиск новых запросов
   kubectl get csr
   # Одобрение серверного сертификата узла
   kubectl certificate approve <node-csr-name>
   ```

### Конфигурация TLS для etcd

Если `etcd` развернут вне `kubeadm` или требует ручной настройки, используются следующие флаги:

```bash
# Флаги сервера для клиентских соединений (от API-сервера)
--cert-file=/etc/etcd/pki/server.crt
--key-file=/etc/etcd/pki/server.key
--trusted-ca-file=/etc/etcd/pki/ca.crt
--client-cert-auth=true

# Флаги для взаимодействия между узлами etcd (peer-to-peer)
--peer-cert-file=/etc/etcd/pki/peer.crt
--peer-key-file=/etc/etcd/pki/peer.key
--peer-trusted-ca-file=/etc/etcd/pki/ca.crt
--peer-client-cert-auth=true
```

### Шифрование Pod-to-Pod
Защита трафика между прикладными подами:
- **Инфраструктурный слой (CNI):** Сетевые плагины, такие как **Calico** (с WireGuard) или **Flannel** (с IPSec), обеспечивают прозрачное шифрование на уровне L3.
- **Сервисный слой (Service Mesh):**
  - **Istio**: Внедряет Envoy-sidecar, который автоматически управляет mTLS на основе SPIFFE-идентификаторов. Обеспечивает политики `Strict` (только mTLS) или `Permissive`.
  - **Linkerd**: Обеспечивает автоматический mTLS для всего TCP-трафика внутри меша без сложной конфигурации.

### Ручная генерация сертификатов с помощью OpenSSL

#### 1. Создание самоподписанного корневого CA

**Конфигурационный файл `ca.cnf`:**

```ini
[ req ]
distinguished_name = req_distinguished_name
x509_extensions    = v3_ca
prompt             = no

[ req_distinguished_name ]
C = RU
ST = Moscow
L = Moscow
O = Kubernetes
CN = kubernetes-ca

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
```

**Генерация:**

```bash
# 1. Сгенерировать приватный ключ
openssl genrsa -out ca.key 2048

# 2. Сгенерировать самоподписанный сертификат CA
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -config ca.cnf
```

#### 2. Создание сертификата для Kubelet

**Конфигурационный файл `kubelet.cnf`:**

```ini
[ req ]
distinguished_name = req_distinguished_name
req_extensions     = v3_req
prompt             = no

[ req_distinguished_name ]
O = system:nodes
CN = system:node:node01.example.com

[ v3_req ]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth, serverAuth
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = node01.example.com
IP.1 = 192.168.1.10
```

**Генерация и подпись:**

```bash
# 1. Сгенерировать ключ
openssl genrsa -out kubelet.key 2048

# 2. Создать CSR
openssl req -new -key kubelet.key -out kubelet.csr -config kubelet.cnf

# 3. Подписать сертификат
openssl x509 -req -in kubelet.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out kubelet.crt -days 365 -sha256 -extensions v3_req -extfile kubelet.cnf
```

### Работа с Certificates API через kubectl

Если необходимо выпустить сертификат через кластерный CA:

1. **Создание CSR манифеста**:
   ```yaml
   apiVersion: certificates.k8s.io/v1
   kind: CertificateSigningRequest
   metadata:
     name: my-user-csr
   spec:
     request: <BASE64_ENCODED_CSR>
     signerName: kubernetes.io/kube-apiserver-client
     usages:
     - client auth
   ```
2. **Одобрение и извлечение**:
   ```bash
   kubectl certificate approve my-user-csr
   # Получение сертификата
   kubectl get csr my-user-csr -o jsonpath='{.status.certificate}' | base64 --decode > user.crt
   ```

### Проверка состояния сертификатов

```bash
# Проверка срока действия (notAfter)
openssl x509 -in kubelet.crt -noout -enddate

# Проверка цепочки доверия
openssl verify -CAfile ca.crt kubelet.crt
# → kubelet.crt: OK

# Просмотр всех деталей сертификата
openssl x509 -in kubelet.crt -text -noout
```

### Шифрование внешнего трафика (Ingress TLS)

- **TLS Termination**: Ingress-контроллеры (Nginx, Traefik) расшифровывают трафик на входе и передают его сервисам (обычно по HTTP, если не настроен сквозной TLS).
- **Конфигурация**:
  1. Создайте секрет:
     ```bash
     kubectl create secret tls ingress-cert --cert=tls.crt --key=tls.key
     ```
  2. Укажите его в манифесте Ingress:
     ```yaml
     spec:
       tls:
       - hosts:
         - api.example.com
         secretName: ingress-cert
     ```

### Совет по собеседованию: TLS vs mTLS
> **Вопрос:** В чем разница между TLS и mTLS?
> **Ответ:** TLS обеспечивает одностороннюю аутентификацию (клиент доверяет серверу) и шифрование. **mTLS (Mutual TLS)** требует взаимной проверки сертификатов, что гарантирует подлинность обеих сторон. В Kubernetes mTLS используется для защиты связи между всеми компонентами Control Plane.

### Совет по собеседованию: Шифрование API
> **Вопрос:** Как шифрование TLS защищает связь API Kubernetes?
> **Ответ:** TLS защищает все каналы связи (kubelet -> API, API -> etcd) от перехвата и атак Man-in-the-Middle. Без TLS токены аутентификации и конфигурации кластера передавались бы в открытом виде.

## Дополнительная информация

* **[Управление сертификатами через kubeadm](../Operations/certificate_management.md)** — команды ротации и продления.
* **[cert-manager](../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md)** — автоматизация выпуска сертификатов через Let's Encrypt и другие CA.
* **[Kubelet — агент Kubernetes](../Concepts/kubelet.md)** — детальное описание работы агента.
* **[Безопасность Kubelet](./kubelet_security.md)** — полный гайд по аутентификации, авторизации, TLS и CIS Benchmark для kubelet.
* **[Etcd: практические сценарии](../Concepts/etcd_operations.md)** — управление и обслуживание хранилища.
* **[Обзор PKI в Kubernetes](../../Security/Concepts/pki_overview.md)** — иерархия центров сертификации.
* Подробное описание структуры `kubeconfig` см. в **[Kubeconfig: Подключение к кластеру Kubernetes](../Operations/kubeconfig_and_connection.md)**.
