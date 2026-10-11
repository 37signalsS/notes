# Harbor: Управление сертификатами и TLS

**Актуально для:** Harbor 2.15.x

## Определения

* **Центр сертификации (CA, Certificate Authority)**: Доверенный источник (якорь доверия), выпускающий цифровые сертификаты. Клиенты, доверяющие корневому CA, автоматически доверяют всем им подписанным сертификатам.
* **Сертификат сервера (CRT)**: Публичный документ, удостоверяющий подлинность сервера Harbor и обеспечивающий шифрование трафика по протоколу HTTPS/TLS.
* **Запрос на подпись (CSR, Certificate Signing Request)**: Файл-заявка, содержащий открытый ключ и данные организации, передаваемый в CA для выпуска итогового сертификата.
* **SAN (Subject Alternative Name)**: Расширение сертификата X.509, позволяющее защитить несколько доменных имен или IP-адресов одним сертификатом. Современные клиенты (Docker, Containerd, Go) требуют обязательного наличия SAN.
* **Internal TLS**: Шифрование трафика между внутренними компонентами Harbor (core, jobservice, proxy, portal, registry, registryctl, trivy-adapter). По умолчанию межкомпонентное взаимодействие идёт по HTTP; TLS поддерживается с Harbor v2.0.
* **Cert-manager**: Kubernetes-оператор для автоматизации управления жизненным циклом сертификатов (выпуск, обновление, ротация). Подробности — в разделе cert-manager базы знаний.

## Основные концепции

Harbor не поставляется с сертификатами. Развёртывание по HTTP допустим **только** в изолированных (air-gapped) тестовых и dev-контурах без доступа во внешний интернет — в остальных средах HTTP подвергает трафик атакам man-in-the-middle. В production всегда HTTPS.

### Методы выпуска сертификатов

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| **Ручной (OpenSSL)** | Прямая генерация CA и серверного сертификата через CLI. Высокий риск человеческой ошибки при ротации. | Тестовые стенды, оффлайн-установка (Docker Compose). |
| **Автоматический (Cert-manager)** | Декларативное описание в K8s. Автоматическое продление и интеграция с Ingress/Gateway. | Продакшен-кластеры Kubernetes. |
| **Публичный (Let's Encrypt и др.)** | Сертификаты от доверенных мировых центров через протокол ACME. Рекомендуемый подход для production. | Публичные инстансы Harbor с доступом в интернет. |

### Технические требования

1. **Hostname Matching**: Поле `CN` или `DNS` в SAN должно в точности совпадать с параметром `hostname` в `harbor.yml` или внешним DNS-именем. Параметр `hostname` не должен быть `localhost`, `127.0.0.1` или `0.0.0.0` — реестр должен быть доступен внешним клиентам.
2. **SAN (Subject Alternative Name)**: Обязательно укажите все IP-адреса и DNS-имена сервера. Отсутствие SAN приведёт к ошибке `x509: certificate relies on legacy Common Name field` (Go 1.15+ игнорирует CN).
3. **Цепочка доверия**: Корневой сертификат (Root CA) должен быть распределён на все узлы, которые будут выполнять операции `push` или `pull`.
4. **Пути в harbor.yml**: Пути к сертификатам должны быть абсолютными и указывать на файлы, доступные контейнеру Nginx. Директория по умолчанию — `/data/cert/` (не существует «из коробки», её нужно создать).

## Практические сценарии

### Сценарий 1: Ручная генерация (OpenSSL) для Docker Compose

Официальная процедура Harbor: создание собственного CA, подпись серверного сертификата с расширениями x509 v3 и предоставление сертификатов Harbor и Docker.

```bash
# 1. Создание корневого CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -sha512 -days 3650 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/OU=Infrastructure/CN=Internal-Harbor-CA" \
  -key ca.key -out ca.crt

# 2. Генерация серверного ключа и CSR
export HARBOR_HOST=harbor.example.local
openssl genrsa -out ${HARBOR_HOST}.key 4096
openssl req -sha512 -new \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/OU=Infrastructure/CN=${HARBOR_HOST}" \
  -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr

# 3. Расширения x509 v3 (SAN обязателен)
cat > v3.ext <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1=${HARBOR_HOST}
DNS.2=harbor
IP.1=192.168.1.50
EOF

# 4. Подпись сертификата
openssl x509 -req -sha512 -days 3650 \
  -extfile v3.ext \
  -CA ca.crt -CAkey ca.key -CAcreateserial \
  -in ${HARBOR_HOST}.csr -out ${HARBOR_HOST}.crt
```

Предоставление сертификатов Harbor и Docker:

```bash
# 5. Директория Harbor по умолчанию
sudo mkdir -p /data/cert/
sudo cp ${HARBOR_HOST}.crt ${HARBOR_HOST}.key /data/cert/

# 6. Доверие Docker daemon: конвертация .crt -> .cert и копирование всех трёх файлов
openssl x509 -inform PEM -in ${HARBOR_HOST}.crt -out ${HARBOR_HOST}.cert
sudo mkdir -p /etc/docker/certs.d/${HARBOR_HOST}/
sudo cp ${HARBOR_HOST}.cert ${HARBOR_HOST}.key ca.crt /etc/docker/certs.d/${HARBOR_HOST}/
sudo systemctl restart docker
```

Итоговая структура для Docker:

```text
/etc/docker/certs.d/
    └── harbor.example.local
       ├── harbor.example.local.cert
       ├── harbor.example.local.key
       └── ca.crt
```

Если Harbor уже развёрнут по HTTP, реконфигурация на HTTPS выполняется через скрипт `prepare` (он перегенерирует конфигурацию Nginx), затем перезапуск:

```bash
./prepare
docker compose down -v   # данные реестра в /data на хосте, не в volumes — потерь нет
docker compose up -d
```

### Сценарий 2: Автоматизация через Cert-manager в Kubernetes

Минимальная связка для внутреннего CA. Полное покрытие cert-manager (ACME/DNS01, Private CA, Vault, ротация) — в разделе [cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/definitions.md).

1. **Создание Issuer** (источника сертификатов):

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: harbor-ca-issuer
spec:
  ca:
    secretName: harbor-root-ca-secret # Секрет с root-ca.crt и root-ca.key
```

2. **Запрос сертификата**:

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

Для публичных инстансов используйте ACME-issuer (Let's Encrypt) — сценарии в [LetsEncrypt](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/index.md); для корпоративного PKI — [Private CA](../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/index.md).

### Сценарий 3: Установка доверия на клиентах (Docker и Containerd)

Без установки корневого сертификата клиенты выдают ошибку `x509: certificate signed by unknown authority`.

#### Настройка ОС

```bash
# Ubuntu/Debian
sudo cp ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
sudo update-ca-certificates

# Red Hat (CentOS и др.)
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/harbor-ca.crt
sudo update-ca-trust
```

#### Настройка Docker

Создайте директорию по имени хоста и положите туда сертификат под именем `ca.crt` (для полного доверия daemon'а — все три файла, как в Сценарии 1):

```bash
sudo mkdir -p /etc/docker/certs.d/harbor.example.local/
sudo cp ca.crt /etc/docker/certs.d/harbor.example.local/ca.crt
```

#### Настройка Containerd (K8s Nodes)

Рекомендуется использовать механизм `hosts.toml` (современный способ):

```toml
# /etc/containerd/certs.d/harbor.example.local/hosts.toml
server = "https://harbor.example.local"

[host."https://harbor.example.local"]
  ca = "/etc/containerd/certs.d/harbor.example.local/ca.crt"
```

### Сценарий 4: Internal TLS между компонентами Harbor

Шифрование межкомпонентного трафика (harbor-core, harbor-jobservice, proxy, harbor-portal, registry, registryctl, trivy-adapter). Включается параметром `internal_tls` в `harbor.yml`:

```yaml
internal_tls:
  enabled: true
  dir: /path/to/internal/tls/cert
```

Сертификаты генерируются автоматически утилитой `prepare`:

```bash
docker run -v /:/hostfs goharbor/prepare:<current_harbor_version> gencert -p /path/to/internal/tls/cert
```

Можно использовать собственный CA: положите его ключ и сертификат в директорию internal TLS с именами `harbor_internal_ca.key` и `harbor_internal_ca.crt`, либо предоставьте сертификаты для всех компонентов вручную. Ограничения:

1. Все сертификаты должны быть подписаны единым CA.
2. Имя файла и поле `CN` должны соответствовать соглашению:

| Файл | Назначение | CN |
| :--- | :--- | :--- |
| `harbor_internal_ca.key` / `harbor_internal_ca.crt` | Ключ и сертификат CA | N/A |
| `core.key` / `core.crt` | core | `core` |
| `job_service.key` / `job_service.crt` | job service | `jobservice` |
| `proxy.key` / `proxy.crt` | proxy | `proxy` |
| `portal.key` / `portal.crt` | portal | `portal` |
| `registry.key` / `registry.crt` | registry | `registry` |
| `registryctl.key` / `registryctl.crt` | registryctl | `registryctl` |
| `trivy_adapter.key` / `trivy_adapter.crt` | trivy adapter | `trivy-adapter` |

3. SAN обязателен (Go 1.15+ не принимает сертификаты без SAN) — DNS-имя в SAN должно совпадать с CN из таблицы, иначе Harbor не запустится.

### Сценарий 5: Ротация сертификатов

1. **Ручной метод (Docker Compose)**: повторите Сценарий 1, замените файлы в `/data/cert/` и `/etc/docker/certs.d/`, затем обязательно выполните `./prepare` (перегенерация конфигурации Nginx) и перезапуск:

    ```bash
    ./prepare
    docker compose down -v
    docker compose up -d
    ```

2. **Cert-manager (Kubernetes)**: ротация автоматическая по сроку действия. Принудительное обновление — через утилиту `cmctl` (legacy kubectl-плагин `kubectl cert-manager` больше не рекомендуется):

    ```bash
    cmctl renew harbor-tls -n harbor
    ```

## Валидация

1. **Браузер**: откройте `https://harbor.example.local` — должен отобразиться интерфейс Harbor. Предупреждение о неизвестном CA нормально для самоподписанного CA до его импорта в браузер.
2. **Docker login** (проверка доверия daemon'а):

    ```bash
    docker login harbor.example.local
    # если порт 443 проброшен на другой порт:
    docker login harbor.example.local:port
    ```

3. **Проверка daemon.json**: убедитесь, что для хоста Harbor не установлен флаг `insecure-registries`.
4. **Цепочка сертификатов**:

    ```bash
    openssl s_client -connect harbor.example.local:443 -servername harbor.example.local -CAfile ca.crt
    # → Verify return code: 0 (ok)
    ```

    Подробная диагностика TLS — в [Диагностике SSL](../../../Security/Tools/ssl_certificate_diagnostics.md).
5. **Контейнеры**: `docker compose ps` — все контейнеры в состоянии `Up`; логи контейнеров — в `/var/log/harbor/` (например, `core.log`).

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | Root CA не распространён на клиенте | Сценарий 3 (ОС, Docker, Containerd) |
| `x509: certificate relies on legacy Common Name field` | В сертификате нет SAN | Перевыпустите сертификат с расширением SAN (Сценарий 1, шаг 3) |
| Клиент не доверяет сертификату, хотя CA установлен | Промежуточный сертификат не включён в цепочку | Объедините цепочку: `cat intermediate-certificate.pem >> yourdomain.com.crt` |
| Harbor не запускается после смены HTTP→HTTPS | Не выполнен `./prepare` | Выполните `./prepare`, затем `docker compose down -v && docker compose up -d` |
| Циклические редиректы за nginx/LB | Дублирование заголовка `proxy_set_header X-Forwarded-Proto $scheme;` | Удалите его из секций `location /`, `location /v2/`, `location /service/` в `common/config/nginx/nginx.conf` и передеплойте Harbor |
| Сканер Trivy не может скачать БД | Сертификат реестра не доверен scanner'у | Для dev/test: `trivy: insecure: true` в `harbor.yml` (пропуск проверки сертификата реестра) |

## Best Practices

### Мониторинг истечения сертификатов

* Настройте проверку срока действия сертификатов (минимум за 14 дней до истечения) через cron-задачу или мониторинговую систему. Проверка: `openssl x509 -enddate -noout -in /path/to/certificate.crt`.
* Для внешнего HTTPS (NLB/ALB/Ingress) мониторьте срок действия сертификата на прокси, а не только на самом Harbor.
* В Kubernetes отслеживайте секреты `kubernetes.io/tls`; cert-manager экспортирует метрики истечения — интегрируйте их в систему мониторинга.

### Ротация и откат

* Ротация должна быть запланированной операцией, а не реакцией на истечение. Для публичных CA используйте срок не более 398 дней; для внутреннего PKI — по организационной политике (1–2 года для Root CA).
* Перед сменой создавайте backup: для Docker Compose — `cp /data/cert/*.crt /data/cert/*.key /backup/harbor-certs-$(date +%F)/`; в Kubernetes — `kubectl get secret harbor-tls -n harbor -o yaml > harbor-tls-backup.yaml`.
* При неудачной ротации восстановите backup и перезапустите `./prepare && docker compose down -v && docker compose up -d` (Compose) или повторно примените backup-секрет (Helm).

## Дополнительная информация

### Использование в конфигурации harbor.yml

```yaml
hostname: harbor.example.local   # IP или FQDN; не localhost/127.0.0.1/0.0.0.0
http:
  port: 80                      # только для air-gapped test/dev
https:
  port: 443
  certificate: /data/cert/harbor.example.local.crt
  private_key: /data/cert/harbor.example.local.key
internal_tls:
  enabled: true
  dir: /data/internal_tls
```

Смежные параметры:

* **`external_url`**: включается, когда Harbor находится за внешним прокси — при этом `hostname` больше не используется.
* **`storage_service.ca_bundle`**: путь к корневому CA, который инжектируется в trust store контейнеров registry и chart repository — нужен, если внешнее хранилище использует самоподписанный сертификат.
* **`trivy.insecure`**: пропуск проверки сертификата реестра (только dev/test).

### Безопасность и хранение ключей

* **Приватные ключи**: всегда устанавливайте права `600` на `.key` файлы.
* **Дистрибуция Root CA**: в крупных кластерах используйте **trust-manager** из экосистемы cert-manager для автоматического распространения CA-бандла во все Namespace.
* **Срок действия**: ограничение в 398 дней — требование к публично доверенным сертификатам (baseline requirements CA/Browser Forum, применяется браузерами и публичными CA). Для внутреннего PKI срок — организационная политика; примеры в документации Harbor для тестовых контуров используют 3650 дней. Корневой CA может иметь срок 5–10 лет.

### Граничные случаи

* **Harbor не поставляется с сертификатами** — их нужно создать или предоставить до первого развёртывания по HTTPS.
* **Смена HTTP→HTTPS** требует `./prepare`; простой `docker compose restart` не перегенерирует конфигурацию Nginx.
* **Порты**: если порт 443 на хосте занят или проброшен на другой порт, укажите его в `https.port` и используйте `docker login <host>:<port>`.
* **SAN для IP**: если клиенты обращаются по IP, IP должен быть в SAN (`IP.1=...`), одного DNS-имени недостаточно.
* **Внешний прокси/LB**: при использовании `external_url` TLS может терминироваться на прокси — тогда сертификат нужен прокси, а Harbor может работать по HTTP внутри контура (только если контур изолирован).
* **Принудительное удаление секрета `harbor-tls` в Kubernetes**: Harbor перестаёт обслуживать HTTPS. Восстановление — повторное создание секрета из backup или откат на HTTP (только в изолированном контуре).
* **Go 1.15+ и SAN**: клиенты на Go (Docker, Containerd, Harbor-компоненты) отклоняют сертификаты без SAN. При генерации всегда добавляйте расширение x509 v3 с `subjectAltName`.

### Связанные документы

* **[Установка Harbor](./installation.md)** — применение сертификатов при развертывании.
* **[Работа с Harbor](./usage.md)** — аутентификация и использование реестра.
* **[Диагностика SSL](../../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка ошибок TLS.
* **[Обзор PKI](../../../Security/Concepts/pki_overview.md)** — теория инфраструктуры открытых ключей.
* **[cert-manager: определения](../../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)** — автоматизация TLS-сертификатов в K8s.
* **[cert-manager: Private CA](../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/index.md)** — корпоративный внутренний CA.
* **[cert-manager: Let's Encrypt](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/index.md)** — публичные сертификаты через ACME.
* **[Harbor HA via Helm](https://goharbor.io/docs/2.15.0/install-config/harbor-ha-helm/)** — высокодоступное развёртывание (внешняя документация).
