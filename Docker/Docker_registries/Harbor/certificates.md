# Harbor: Создание ЦА и подписание сертификатов

## Определения

* **Центр сертификации (CA, Certificate Authority)**: Доверенный источник (якорь доверия), выпускающий цифровые сертификаты. Клиенты, доверяющие корневому CA, автоматически доверяют всем им подписанным сертификатам.
* **Сертификат сервера (CRT)**: Публичный документ, удостоверяющий подлинность сервера Harbor и обеспечивающий шифрование трафика по протоколу HTTPS/TLS.
* **Приватный ключ (Key)**: Секретный файл, используемый сервером для расшифровки трафика и установки защищенного соединения. Требует максимальной защиты.
* **Запрос на подпись (CSR, Certificate Signing Request)**: Файл-заявка, содержащий открытый ключ и данные организации, передаваемый в CA для выпуска итогового сертификата.
* **SAN (Subject Alternative Name)**: Расширение сертификата X.509, позволяющее защитить несколько доменных имен или IP-адресов одним сертификатом. Современные браузеры и Docker требуют наличия SAN.

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
3. **Цепочка доверия**: Для корректной работы `docker push/pull` корневой сертификат CA (`root-ca.crt`) должен быть установлен в системное хранилище всех клиентских хостов.

## Практические сценарии

Ниже приведен «Быстрый метод» создания сертификатов, адаптированный для Harbor.

### 1. Подготовка и создание корневого CA

Создайте рабочую директорию и сгенерируйте корневой ключ и сертификат, которыми будут подписываться все остальные сертификаты.

```bash
mkdir -p ~/harbor/certs && cd ~/harbor/certs

# Генерируем ключ корневого CA (4096 бит)
openssl genrsa -out root-ca.key 4096

# Генерируем самоподписанный сертификат CA (срок 10 лет)
openssl req -x509 -new -nodes -sha256 -days 3650 \
  -key root-ca.key -out root-ca.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/CN=My-Internal-Root-CA"

# → root-ca.crt, root-ca.key
```

### 2. Генерация серверного сертификата для Harbor

Задайте переменные окружения для автоматизации процесса (замените значения на актуальные для вашей сети).

```bash
export HARBOR_HOST=harbor.example.local
export HARBOR_IP=192.168.1.50
```

Создайте конфигурационный файл для CSR, включающий расширения SAN:

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

# Подпись серверного сертификата вашим CA (срок 2 года)
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial \
  -out ${HARBOR_HOST}.crt -days 730 -sha256 \
  -extensions v3_req -extfile ${HARBOR_HOST}.cnf

# → harbor.example.local.crt, harbor.example.local.key
```

Подробнее о параметрах подписи см. в **[Быстром методе выпуска](../../../Security/Tools/openssl_ca/single_tier/quick_method.md)**.

### 3. Установка доверия на клиентских хостах

Чтобы Docker-демон доверял вашему Harbor, скопируйте `root-ca.crt` на все узлы и обновите системное хранилище.

**Ubuntu / Debian:**

```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
sudo update-ca-certificates
# → Updating certificates in /etc/ssl/certs... 1 added, 0 removed; done.
```

**RHEL / CentOS / Fedora:**

```bash
sudo cp root-ca.crt /etc/pki/ca-trust/source/anchors/harbor-ca.crt
sudo update-ca-trust extract
```

**ВАЖНО:** После обновления хранилища необходимо перезапустить Docker:

```bash
sudo systemctl restart docker
```

## Дополнительная информация

### Использование в Harbor

При установке укажите пути к сгенерированным файлам в `harbor.yml`:

```yaml
https:
  port: 443
  certificate: /opt/harbor/certs/harbor.example.local.crt
  private_key: /opt/harbor/certs/harbor.example.local.key
```

Инструкции по редактированию конфигурации см. в **[Установке Harbor](./installation.md)**.

### Безопасность

* **Защита ключей**: Приватный ключ сервера должен иметь права доступа `600` (`chmod 600 *.key`).
* **Хранение Root CA**: Никогда не передавайте `root-ca.key` по сети и не храните его на сервере Harbor без крайней необходимости. Он нужен только в момент подписи.

### Связанные документы

* **[Установка Harbor](./installation.md)** — применение сертификатов в конфигурации.
* **[Работа с Harbor](./usage.md)** — аутентификация и работа с образами.
* **[Настройка одноуровневого CA](../../../Security/Tools/openssl_ca/single_tier/ca_setup.md)** — формальный метод с базой данных.
* **[Диагностика SSL](../../../Security/Tools/ssl_certificate_diagnostics.md)** — проверка цепочек и поиск ошибок TLS.
