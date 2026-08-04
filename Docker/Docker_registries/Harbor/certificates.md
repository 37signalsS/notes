# Harbor: Управление сертификатами и TLS

## Определения

* **Центр сертификации (CA, Certificate Authority)**: Доверенный источник (якорь доверия), выпускающий цифровые сертификаты. Клиенты, доверяющие корневому CA, автоматически доверяют всем им подписанным сертификатам.
* **Сертификат сервера (CRT)**: Публичный документ, удостоверяющий подлинность сервера Harbor и обеспечивающий шифрование трафика по протоколу HTTPS/TLS.
* **Запрос на подпись (CSR, Certificate Signing Request)**: Файл-заявка, содержащий открытый ключ и данные организации, передаваемый в CA для выпуска итогового сертификата.
* **SAN (Subject Alternative Name)**: Расширение сертификата X.509, позволяющее защитить несколько доменных имен или IP-адресов одним сертификатом. Современные клиенты (Docker, Containerd, Go) требуют обязательного наличия SAN.
* **Cert-manager**: Kubernetes-оператор для автоматизации управления жизненным циклом сертификатов (выпуск, обновление, ротация).

## Основные концепции

Для обеспечения безопасности и доверия в корпоративной среде Harbor должен работать исключительно по протоколу HTTPS. В изолированных контурах (Air-gapped) это требует создания внутренней инфраструктуры PKI.

### Методы выпуска сертификатов

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| **Ручной (OpenSSL)** | Прямая генерация через CLI. Высокий риск человеческой ошибки при ротации. | Тестовые стенды, оффлайн-установка (Docker Compose). |
| **Автоматический (Cert-manager)** | Декларативное описание в K8s. Автоматическое продление и интеграция с Ingress. | Продакшен-кластеры Kubernetes. |
| **Публичный (Let's Encrypt)** | Использование доверенных мировых центров через протокол ACME. | Публичные инстансы Harbor с доступом в интернет. |

### Технические требования

1.  **Hostname Matching**: Поле `CN` или `DNS` в SAN должно в точности совпадать с параметром `hostname` в `harbor.yml` или внешним DNS-именем.
2.  **SAN (Subject Alternative Name)**: Обязательно укажите все IP-адреса и DNS-имена сервера. Отсутствие SAN приведет к ошибке `x509: certificate relies on legacy Common Name field`.
3.  **Цепочка доверия**: Корневой сертификат (Root CA) должен быть распределен на все узлы, которые будут выполнять операции `push` или `pull`.

## Практические сценарии

### Сценарий 1: Ручная генерация (OpenSSL) для Docker Compose

Подходит для быстрой настройки на выделенном сервере.

```bash
mkdir -p ~/harbor/certs && cd ~/harbor/certs

# 1. Создание корневого CA
openssl genrsa -out root-ca.key 4096
openssl req -x509 -new -nodes -sha256 -days 3650 \
  -key root-ca.key -out root-ca.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/CN=Internal-Harbor-CA"

# 2. Генерация серверного ключа и CSR
export HARBOR_HOST=harbor.example.local
openssl genrsa -out ${HARBOR_HOST}.key 4096

cat > ${HARBOR_HOST}.cnf <<EOF
[req]
prompt = no
distinguished_name = dn
req_extensions = v3_req
[dn]
CN = ${HARBOR_HOST}
[v3_req]
subjectAltName = DNS:${HARBOR_HOST},IP:192.168.1.50
EOF

openssl req -new -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr -config ${HARBOR_HOST}.cnf

# 3. Подпись сертификата
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial \
  -out ${HARBOR_HOST}.crt -days 730 -sha256 -extensions v3_req -extfile ${HARBOR_HOST}.cnf
```

### Сценарий 2: Автоматизация через Cert-manager в Kubernetes

Современный стандарт для управления TLS в K8s.

1.  **Создание Issuer** (источника сертификатов):

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: harbor-ca-issuer
spec:
  ca:
    secretName: harbor-root-ca-secret # Секрет с root-ca.crt и root-ca.key
```

2.  **Запрос сертификата**:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: harbor-tls
  namespace: harbor
spec:
  secretName: harbor-tls-secret
  issuerRef:
    name: harbor-ca-issuer
    kind: ClusterIssuer
  dnsNames:
  - harbor.example.local
  - registry.example.local
```

### Сценарий 3: Установка доверия на клиентах (Docker и Containerd)

Без установки корневого сертификата клиенты будут выдавать ошибку `x509: certificate signed by unknown authority`.

#### Настройка ОС (Ubuntu/Debian)
```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
sudo update-ca-certificates
```

#### Настройка Docker
Создайте директорию по имени хоста и положите туда сертификат под именем `ca.crt`:
```bash
sudo mkdir -p /etc/docker/certs.d/harbor.example.local/
sudo cp root-ca.crt /etc/docker/certs.d/harbor.example.local/ca.crt
```

#### Настройка Containerd (K8s Nodes)
Рекомендуется использовать механизм `hosts.toml` (современный способ):
```bash
# /etc/containerd/certs.d/harbor.example.local/hosts.toml
server = "https://harbor.example.local"

[host."https://harbor.example.local"]
  ca = "/etc/containerd/certs.d/harbor.example.local/ca.crt"
```

### Сценарий 4: Ротация сертификатов

1.  **Ручной метод**: Повторите шаги из Сценария 1, обновите файлы в директории Harbor и выполните `docker-compose down && docker-compose up -d`.
2.  **Cert-manager**: Ротация происходит автоматически. Для принудительного обновления используйте команду:
    ```bash
    kubectl cert-manager renew harbor-tls -n harbor
    ```

## Дополнительная информация

### Использование в конфигурации harbor.yml

Пути к сертификатам в `harbor.yml` должны быть абсолютными и указывать на файлы внутри томов, доступных контейнеру Nginx.

```yaml
https:
  port: 443
  certificate: /data/cert/harbor.example.local.crt
  private_key: /data/cert/harbor.example.local.key
```

### Безопасность и хранение ключей

* **Приватные ключи**: Всегда устанавливайте права `600` на `.key` файлы.
* **Дистрибуция Root CA**: В крупных кластерах используйте **trust-manager** для автоматического распространения CA-бандла во все Namespace.
* **Срок действия**: Не выпускайте серверные сертификаты более чем на 398 дней (стандарт безопасности современных браузеров). Корневой CA может иметь срок 5-10 лет.

### Связанные документы

* **[Установка Harbor](./installation.md)** — применение сертификатов при развертывании.
* **[Работа с Harbor](./usage.md)** — аутентификация и использование реестра.
* **[Диагностика SSL](../../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка ошибок TLS.
