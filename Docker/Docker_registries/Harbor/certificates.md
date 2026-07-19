# Harbor: Создание ЦА и подписание сертификатов

## Определения

* **Центр сертификации (CA, Certificate Authority)**: Доверенный источник (якорь доверия), выпускающий цифровые сертификаты. Клиенты, доверяющие корневому CA, автоматически доверяют всем им подписанным сертификатам.
* **Сертификат сервера (CRT)**: Публичный документ, удостоверяющий подлинность сервера Harbor и обеспечивающий шифрование трафика по протоколу HTTPS/TLS.
* **Приватный ключ (Key)**: Секретный файл, используемый сервером для расшифровки трафика и установки защищенного соединения. Требует максимальной защиты (права 600).
* **Запрос на подпись (CSR, Certificate Signing Request)**: Файл-заявка, содержащий открытый ключ и данные организации, передаваемый в CA для выпуска итогового сертификата.
* **SAN (Subject Alternative Name)**: Расширение сертификата X.509, позволяющее защитить несколько доменных имен или IP-адресов одним сертификатом. Современные браузеры и Docker требуют обязательного наличия SAN.

## Основные концепции

Для работы Harbor по HTTPS в закрытых контурах (без доступа к публичным центрам сертификации вроде Let's Encrypt) необходимо создать собственный частный CA.

### Методы выпуска

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| **Быстрый** | Прямая подпись через `openssl x509`. Не требует базы данных. | Тестовые среды, быстрая настройка. |
| **Формальный** | Использование структуры директорий, базы `index.txt` и серийных номеров. | Production, необходимость отзыва (CRL). |

Подробное сравнение методов и теорию PKI см. в **[Обзоре одноуровневого CA](../../../Security/Tools/openssl_ca/single_tier/overview.md)**.

### Требования к сертификату Harbor

1. **Соответствие Hostname**: Поле `CN` (Common Name) или `DNS` в SAN должно в точности совпадать с параметром `hostname` из `harbor.yml`.
2. **Наличие SAN**: Обязательно укажите как доменное имя, так и IP-адрес сервера в расширении SAN, иначе Docker может выдать ошибку `x509: certificate relies on legacy Common Name field`.
3. **Цепочка доверия**: Для корректной работы `docker push/pull` корневой сертификат CA (`root-ca.crt`) должен быть установлен в доверенные хранилища клиентов.

## Практические сценарии

Ниже приведен быстрый метод создания сертификатов, адаптированный для Harbor.

### 1. Создание корневого CA

Создайте рабочую директорию и сгенерируйте корневой ключ и сертификат.

```bash
mkdir -p ~/harbor/certs && cd ~/harbor/certs

# Генерируем ключ корневого CA (4096 бит)
openssl genrsa -out root-ca.key 4096

# Генерируем самоподписанный сертификат CA (срок 10 лет)
openssl req -x509 -new -nodes -sha256 -days 3650 \
  -key root-ca.key -out root-ca.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/CN=Internal-Harbor-CA"

# → root-ca.crt, root-ca.key
```

### 2. Генерация серверного сертификата

Задайте переменные окружения для вашего сервера:

```bash
export HARBOR_HOST=harbor.example.local
export HARBOR_IP=192.168.1.50
```

Создайте конфигурационный файл для CSR с расширениями SAN:

```bash
# Генерация серверного ключа
openssl genrsa -out ${HARBOR_HOST}.key 4096

# Создание конфигурации SAN
cat > ${HARBOR_HOST}.cnf <<EOF
[req]
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
C = RU
ST = Moscow
L = Moscow
O = HomeLab
CN = ${HARBOR_HOST}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${HARBOR_HOST}
IP.1  = ${HARBOR_IP}
EOF

# Создание запроса (CSR)
openssl req -new -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr -config ${HARBOR_HOST}.cnf

# Подпись серверного сертификата (срок 2 года)
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial \
  -out ${HARBOR_HOST}.crt -days 730 -sha256 \
  -extensions v3_req -extfile ${HARBOR_HOST}.cnf
```

### 3. Установка доверия на клиентах

Чтобы Docker доверял Harbor, корневой сертификат должен быть известен системе или самому Docker-демону.

#### Вариант А: Системное хранилище (рекомендуется)

**Ubuntu / Debian:**
```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
sudo update-ca-certificates
```

**RHEL / CentOS:**
```bash
sudo cp root-ca.crt /etc/pki/ca-trust/source/anchors/harbor-ca.crt
sudo update-ca-trust extract
```

#### Вариант Б: Только для Docker (без изменения системы)

Docker поддерживает установку сертификатов в свою директорию конфигурации. Файл должен обязательно называться `ca.crt`.

```bash
sudo mkdir -p /etc/docker/certs.d/harbor.example.local/
sudo cp root-ca.crt /etc/docker/certs.d/harbor.example.local/ca.crt
```

**Важно:** После установки доверия любым способом необходимо перезапустить Docker (`systemctl restart docker`).

## Дополнительная информация

### Использование в Harbor

При установке укажите пути к файлам в `harbor.yml`. Обратите внимание, что Harbor ожидает полный путь внутри контейнеров или на хосте, где запущен `install.sh`.

```yaml
https:
  port: 443
  certificate: /data/cert/harbor.example.local.crt
  private_key: /data/cert/harbor.example.local.key
```

### Безопасность

* **Права доступа**: Файлы ключей (`.key`) должны иметь права `600` (`chmod 600 *.key`).
* **Разделение**: Никогда не храните `root-ca.key` на сервере Harbor в рабочем режиме. Используйте его только на изолированной машине для подписи новых сертификатов.
* **Срок действия**: Не выпускайте серверные сертификаты на срок более 2 лет. Многие современные клиенты (включая Go-приложения) могут отклонять сертификаты с чрезмерно долгим сроком жизни.

### Связанные документы

* **[Установка Harbor](./installation.md)** — применение сертификатов при развертывании.
* **[Диагностика SSL](../../../Security/Tools/ssl_certificate_diagnostics.md)** — поиск и устранение ошибок TLS.
* **[Настройка одноуровневого CA](../../../Security/Tools/openssl_ca/single_tier/ca_setup.md)** — формальный метод выпуска с базой данных.

