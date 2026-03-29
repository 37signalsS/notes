# Harbor: Создание ЦА и подписание сертификатов

## Определения

* **Центр сертификации (CA, Certificate Authority)**: Доверенный источник, который выпускает и подписывает цифровые сертификаты. Все клиенты, доверяющие CA, автоматически доверяют его подписанным сертификатам.
* **Сертификат сервера**: Цифровой сертификат, который удостоверяет подлинность сервера Harbor и обеспечивает шифрование трафика по HTTPS/TLS.
* **CSR (Certificate Signing Request)**: Запрос на подпись сертификата, содержащий информацию о сервере и его публичный ключ.
* **SAN (Subject Alternative Name)**: Расширение сертификата, позволяющее указать несколько доменных имён и IP-адресов, для которых действителен сертификат.

## Основные концепции

Для обеспечения доверия хостов к репозиторию Harbor необходимо создать собственный центр сертификации (CA) и выпустить подписанные им серверные сертификаты. Этот подход применяется в закрытых контурах (без доступа к публичным CA) или для внутренних сервисов компании.

**Процесс включает:**

1. Создание корневого CA (ключ и сертификат).
2. Генерация серверного ключа и CSR для Harbor.
3. Подпись серверного сертификата корневым CA.
4. Распространение корневого CA на все клиентские хосты.

**Требования к сертификату Harbor:**

* **CN (Common Name)**: Должен совпадать с доменным именем Harbor (`hostname` из `harbor.yml`).
* **SAN**: Должен включать как доменное имя (DNS), так и IP-адрес сервера.
* **Срок действия**: Рекомендуется 2–3 года (730–1095 дней) для серверного сертификата, 5–10 лет для корневого CA.

## Практические сценарии

### 1. Создание корневого CA

Создаём директорию для хранения сертификатов:

```bash
sudo mkdir -p ~/harbor/certs
cd ~/harbor/certs
```

Генерируем ключ и сертификат корневого CA:

```bash
# Root CA key (4096 бит)
openssl genrsa -out root-ca.key 4096

# Root CA cert (срок 10 лет)
openssl req -x509 -new -nodes -sha256 -days 3650 \
  -key root-ca.key -out root-ca.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/OU=ITZM/CN=My-Root-CA"
```

### 2. Создание серверного сертификата Harbor

Задаём переменные (измените под вашу инфраструктуру):

```bash
export HARBOR_HOST=harbor.example.local
export MyIP=2.2.2.2
```

Генерируем серверный ключ и CSR с SAN:

```bash
# Server key
openssl genrsa -out ${HARBOR_HOST}.key 4096

# CSR config с SAN
cat > ${HARBOR_HOST}.csr.cnf <<EOF
[req]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[dn]
C=RU
ST=Moscow
L=Moscow
O=HomeLab
OU=ITZM
CN=${HARBOR_HOST}

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${HARBOR_HOST}
IP.1  = ${MyIP}
EOF

# Create CSR
openssl req -new -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr -config ${HARBOR_HOST}.csr.cnf

# Sign server cert by our CA (срок 2.25 года / 825 дней)
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial \
  -out ${HARBOR_HOST}.crt -days 825 -sha256 \
  -extensions req_ext -extfile ${HARBOR_HOST}.csr.cnf
```

**Результат:**

* `root-ca.crt` — корневой сертификат для распространения на клиентские хосты.
* `${HARBOR_HOST}.crt` и `${HARBOR_HOST}.key` — серверные сертификаты для Harbor.

### 3. Распространение корневого CA на клиентские хосты

Скопируйте `root-ca.crt` на все хосты, которые будут взаимодействовать с Harbor.

**Ubuntu/Debian:**

```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

**CentOS/RHEL:**

```bash
sudo cp root-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust extract
```

**После установки:** Перезапустите Docker на хостах:

```bash
systemctl restart docker.service
```

## Дополнительная информация

### Размещение сертификатов

Для установки Harbor скопируйте серверные сертификаты в директорию, указанную в `harbor.yml`:

```yaml
https:
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key
```

Подробности настройки Harbor см. в [установке Harbor](./installation.md).

### Безопасность ключей

* **Ключ корневого CA (`root-ca.key`)**: Храните в безопасном месте, используйте только для подписи новых сертификатов.
* **Серверный ключ**: Защищайте правами доступа `chmod 600`.

### Альтернативные подходы

* **cert-manager в Kubernetes**: Для кластеров Kubernetes рекомендуется использовать [cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) для автоматического выпуска TLS-сертификатов.
* **Публичные CA**: Для публично доступных сервисов используйте доверенные публичные CA (Let's Encrypt, DigiCert).
