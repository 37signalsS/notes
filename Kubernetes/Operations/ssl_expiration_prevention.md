# Предотвращение истечения SSL-сертификатов в Kubernetes

## Определения

**SSL/TLS Rotation (Ротация сертификатов)** — процесс планового обновления цифровых сертификатов до истечения их срока действия. В Kubernetes ротация должна быть автоматизирована для обеспечения непрерывности работы (High Availability) и исключения человеческого фактора.

**Kubelet Serving Certificate** — сертификат, используемый агентом `kubelet` для идентификации себя при входящих запросах от API-сервера (например, при командах `kubectl logs`, `exec`, `metrics-server`). По умолчанию часто не ротируется автоматически без специальной настройки.

**CSR (Certificate Signing Request) Approver** — контроллер или процесс, ответственный за автоматическую проверку и одобрение запросов на подпись сертификатов. Без него автоматизация ротации на уровне узлов (особенно серверных сертификатов Kubelet) невозможна.

**ARI (ACME Renewal Information)** — расширение протокола ACME, позволяющее центру сертификации (например, Let's Encrypt) рекомендовать клиенту (cert-manager) оптимальное время для продления сертификата, основываясь на нагрузке или технических работах на стороне CA.

**Certificate Validity Period (v1.31+)** — настраиваемый параметр в конфигурации `kubeadm` (v1beta4), позволяющий определить срок действия выпускаемых сертификатов (ранее был жестко ограничен 1 годом).

**OCSP Stapling** — механизм, позволяющий серверу (например, Ingress-контроллеру) периодически запрашивать у CA статус отзыва сертификата и "прикреплять" (staple) подписанный ответ к TLS-рукопожатию. Это исключает необходимость для клиента самостоятельно проверять OCSP и снижает задержки.

**CT Log (Certificate Transparency Log)** — криптографически проверяемый журнал, в который CA публикуют все выданные сертификаты. Позволяет обнаружить несанкционированную выдачу сертификатов для ваших доменов.

## Предварительные требования

### Средства и доступ

- **kubectl**: версия, совместимая с кластером (разница не более чем на одну минорную версию). Проверка: `kubectl version --client`.
- **Доступ к Control Plane**: SSH-доступ к узлам Control Plane с правами `root` (или через `sudo`) для выполнения `kubeadm certs`.
- **Сетевой доступ**: из машины, с которой запускаются команды, должен быть доступ к API-серверу (порт `6443`) и, при необходимости, к Ingress-контроллеру (порты `80`/`443`) для ACME-проверок.
- **Синхронизация времени**: на всех узлах кластера и на рабочей станции оператора должен быть настроен NTP (`chrony` или `ntpd`). Расхождение более 5 секунд приводит к некорректной валидации сертификатов.
- **Права на файлы**: учетная запись, под которой выполняется `kubeadm`, должна иметь права на чтение/запись в `/etc/kubernetes/pki` и `/etc/kubernetes/*.conf`.
- **Браузер или curl** (для OIDC/ACME проверок): при работе с внешними CA требуется возможность прохождения HTTP-01 или DNS-01 проверок.

### Знания

- Понимание иерархии PKI в Kubernetes (Root CA → Intermediate → Leaf Certificates). Детали: [Обзор PKI](../../Security/Concepts/pki_overview.md).
- Знание структуры директории `/etc/kubernetes/pki` и назначения каждого файла. Детали: [Управление сертификатами через kubeadm](./certificate_management.md).
- Умение работать с `openssl` для проверки срока действия и целостности сертификатов.

## Основные концепции

Стратегия защиты от истечения сертификатов в Kubernetes строится на трех независимых эшелонах:

### 1. Эшелон инфраструктуры (Control Plane и etcd)

Самый критический уровень. Истечение сертификата API-сервера или etcd приводит к потере управления кластером ("cluster bricking").

- **Метод:** Плановые обновления версии кластера (автоматический `renew`) или принудительное продление через `kubeadm`. Детали: [Управление сертификатами через kubeadm](./certificate_management.md).
- **etcd:** Особое внимание требует встроенный etcd. Если etcd вынесен за пределы управления `kubeadm`, его сертификаты должны управляться внешними средствами (Ansible, Terraform, Vault).
- **Доверие:** Корневые сертификаты (CA) имеют срок действия 10 лет, листовые — по умолчанию 1 год (настраивается в v1.31+).
- **Валидация:** После ротации обязательно проверяйте целостность цепочки доверия (`openssl verify`) и работоспособность кворума etcd.

### 2. Эшелон узлов (Kubelet)

Обеспечивает связь между API и агентами на узлах.

- **Client Certs:** Используются для авторизации узла в API. Обновляются автоматически при включенном параметре `rotateCertificates: true` (стандарт для современных дистрибутивов).
- **Server Certs:** Требуются для безопасного сбора метрик и логов. Требуют настройки `serverTLSBootstrap: true` и наличия аппрувера в кластере.
- **Хранение:** Начиная с K8s 1.24, клиентские сертификаты kubelet хранятся в `/var/lib/kubelet/pki/` (а не в `/etc/kubernetes/pki/`). Ротация происходит автоматически.

### 3. Эшелон приложений

Сертификаты для Ingress, Gateway API и внутренних mTLS-соединений (Service Mesh).

- **Метод:** Полная автоматизация через ACME/Vault с использованием `cert-manager`.
- **Стандарты 2026:** переход на `ECDSA`/`Ed25519`, короткие сроки (45–90 дней), обязательная интеграция с ARI для публичных CA.
- **Изоляция:** Не используйте Cluster CA для прикладных сертификатов. Это позволяет ротировать прикладные сертификаты без риска для инфраструктуры.

## Практические сценарии

### 1. Управление сроками действия в современных кластерах (v1.31+)

Начиная с версии 1.31 (API `kubeadm.k8s.io/v1beta4`), можно превентивно увеличить срок действия сертификатов, чтобы снизить частоту регламентных работ.

**Настройка через ClusterConfiguration:**

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
certificateValidityPeriod: 43800h    # Листовые сертификаты на 5 лет
caCertificateValidityPeriod: 87600h   # CA на 10 лет
encryptionAlgorithm: ECDSA-P256       # Использование современных алгоритмов (опционально)
```

*Примечание: Использование ECDSA повышает производительность TLS-хендшейков и безопасность по сравнению с RSA. Переход с RSA на ECDSA должен осуществляться при инициализации нового кластера; `kubeadm` не поддерживает изменение алгоритма "на лету" во время обновления или ротации.*

Детали операций: **[Управление сертификатами через kubeadm](./certificate_management.md)**.

### 2. Автоматизация ротации Control Plane (kubeadm)

В кластерах под управлением `kubeadm` основным методом продления является регулярное обновление минорной версии (Upgrade).

- **Проверка (Check-point):**
    ```bash
    sudo kubeadm certs check-expiration
    ```
- **Принудительное продление:**
    Если обновление кластера невозможно, сертификаты продлеваются командой:
    ```bash
    sudo kubeadm certs renew all
    ```
    *Важно: После продления необходим перезапуск компонентов. Kubelet перезапустит поды API-сервера автоматически при изменении манифестов в `/etc/kubernetes/manifests`.*

**Валидация после ротации:**

```bash
# 1. Проверка срока действия
sudo kubeadm certs check-expiration

# 2. Проверка статуса статических подов Control Plane
kubectl get pods -n kube-system -l component=kube-apiserver

# 3. Проверка целостности цепочки доверия
openssl verify -CAfile /etc/kubernetes/pki/ca.crt /etc/kubernetes/pki/apiserver.crt
# → apiserver.crt: OK

# 4. Проверка кворума etcd
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key endpoint health
```

### 3. Настройка автоматической ротации для Kubelet

Для исключения ручного вмешательства необходимо убедиться, что Kubelet настроен на самообслуживание.

**Шаг 1: Настройка конфигурации (`kubelet-config.yaml`)**

```yaml
apiVersion: kubelet.config.k8s.io/v1
kind: KubeletConfiguration
serverTLSBootstrap: true
rotateCertificates: true
```

**Шаг 2: Автоматизация одобрения (CSR Approver)**

Для автоматического одобрения серверных сертификатов (Serving Certs) используйте один из методов:

1.  **kubelet-serving-cert-approver:** Контроллер, проверяющий SAN (DNS/IP) в запросе на соответствие реальному статусу узла.
2.  **cert-manager (CSI Driver):** Позволяет Kubelet получать сертификаты напрямую из внешней PKI (например, Vault).

**Верификация ротации:**

```bash
# Проверка наличия активных CSR
kubectl get csr

# Проверка срока действия сертификата на узле
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep "Not After"

# Проверка серверного сертификата (порт 10250)
echo | openssl s_client -connect <node-ip>:10250 -showcerts 2>/dev/null \
  | openssl x509 -noout -issuer -subject
```

### 4. Настройка cert-manager для приложений

Для предотвращения истечения сертификатов (например, Let's Encrypt) используйте связку `duration`, `renewBefore` и механизмы ARI.

**Стандартный ресурс Certificate (2026):**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  duration: 2160h # 90 дней
  renewBefore: 360h # Начать продление за 15 дней до конца срока
  dnsNames:
  - api.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
```

**Использование ARI (ACME Renewal Information, v1.15+):**

`cert-manager` автоматически интегрируется с ARI. Если CA сигнализирует о необходимости перевыпуска (например, из-за массового отзыва), `cert-manager` проигнорирует `renewBefore` и обновит сертификат в рекомендованное CA окно. Это критично для предотвращения простоев при инцидентах безопасности на стороне CA.

**Проверка статуса сертификата:**

```bash
# Полный статус цепочки выпуска
cmctl status certificate api-tls-secret -n <namespace>

# Проверка событий
kubectl describe certificate api-tls-secret -n <namespace>
kubectl get events --field-selector reason=FailedSynchronization
```

Детали конфигурации Ingress-интеграции: **[Cert-manager: Интеграция с Ingress](../ToolsUtilities/cert_manager/ingress/overview.md)**.

### 5. Ротация сертификатов внешнего etcd

Если etcd развернут на отдельных ВМ вне управления `kubeadm`, его сертификаты необходимо ротировать отдельно.

**Диагностика:**

```bash
# Проверка срока действия сертификата etcd
openssl x509 -in /etc/etcd/pki/server.crt -noout -dates

# Проверка цепочки доверия
openssl verify -CAfile /etc/etcd/pki/ca.crt /etc/etcd/pki/server.crt
# → server.crt: OK
```

**Ротация без даунтайма (etcd v3.5+):**

```bash
# 1. Сгенерируйте новые сертификаты с тем же CN/SAN
openssl x509 -req -in etcd-server.csr -CA /etc/etcd/pki/ca.crt -CAkey /etc/etcd/pki/ca.key \
  -CAcreateserial -out /etc/etcd/pki/server.crt -days 365 -sha256

# 2. Перезапустите etcd (по одному узлу для сохранения кворума)
systemctl restart etcd

# 3. Проверьте кворум после возврата каждого члена
etcdctl endpoint health
```

### 6. Верификация OCSP Stapling

OCSP Stapling позволяет Ingress-контроллеру (Nginx, HAProxy, Angie) предоставлять клиентам подписанный ответ о статусе сертификата, исключая внешний запрос к CA.

**Проверка через openssl:**

```bash
# Проверка, что сервер прикрепляет OCSP-ответ
openssl s_client -connect api.example.com:443 -status </dev/null 2>/dev/null \
  | grep -A 5 "OCSP response"
# → OCSP Response Status: successful
```

**Проверка через curl:**

```bash
curl -I --cert-status https://api.example.com 2>&1 | grep -i "ocsp"
# → OCSP Response Status: successful
```

### 7. Мониторинг Certificate Transparency (CT) логов

Для публичных CA (Let's Encrypt) рекомендуется периодически проверять, что выданные сертификаты присутствуют в CT-логах и не являются несанкционированными.

```bash
# Проверка наличия SCT (Signed Certificate Timestamp) в сертификате
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -text -noout \
  | grep -A 5 "CT Precertificate SCTs"
```

Для прикладных сертификатов (cert-manager) проверка CT выполняется автоматически CA.

### 8. Программный доступ через client-go

Для интеграции с системами автоматизации можно проверять срок действия сертификатов программно:

```go
package main

import (
    "crypto/x509"
    "encoding/pem"
    "fmt"
    "os"
    "time"
)

func main() {
    certPath := "/etc/kubernetes/pki/apiserver.crt"
    data, err := os.ReadFile(certPath)
    if err != nil {
        panic(err)
    }
    block, _ := pem.Decode(data)
    cert, err := x509.ParseCertificate(block.Bytes)
    if err != nil {
        panic(err)
    }
    expiry := cert.NotAfter
    daysLeft := time.Until(expiry).Hours() / 24
    fmt.Printf("Сертификат %s истекает через %.1f дней (%s)\n", certPath, daysLeft, expiry)
}
```

### 9. Автоматизация через CronJob (SRE подход)

Для кластеров без внешнего мониторинга Prometheus можно развернуть CronJob, периодически проверяющий сертификаты и отправляющий уведомления:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cert-expiry-check
  namespace: monitoring
spec:
  schedule: "0 6 * * *" # Ежедневно в 06:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: checker
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              #!/bin/sh
              WARN_DAYS=30
              CRITICAL_DAYS=7
              find /etc/kubernetes/pki -name "*.crt" | while read cert; do
                expiry=$(openssl x509 -in "$cert" -noout -enddate 2>/dev/null | cut -d= -f2)
                if [ -z "$expiry" ]; then continue; fi
                days_left=$(( ($(date -d "$expiry" +%s) - $(date +%s)) / 86400 ))
                if [ "$days_left" -le "$CRITICAL_DAYS" ]; then
                  echo "CRITICAL: $cert истекает через $days_left дней ($expiry)"
                  # Отправка уведомления (webhook, email, slack)
                elif [ "$days_left" -le "$WARN_DAYS" ]; then
                  echo "WARNING: $cert истекает через $days_left дней ($expiry)"
                fi
              done
          restartPolicy: OnFailure
```

### 10. Sidecar-паттерн для ротации TLS в подах

Для приложений, не интегрированных с cert-manager, можно использовать sidecar, который обновляет TLS-сертификаты из внешнего источника (Vault, cert-manager) и записывает их в shared volume:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-cert-rotation
spec:
  volumes:
  - name: cert-volume
    emptyDir: {}
  initContainers:
  - name: cert-fetcher
    image: vault:latest
    command:
    - /bin/sh
    - -c
    - |
      vault kv get -field=tls.crt pki/issue/example.com > /certs/tls.crt
      vault kv get -field=tls.key pki/issue/example.com > /certs/tls.key
    volumeMounts:
    - name: cert-volume
      mountPath: /certs
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: cert-volume
      mountPath: /etc/tls
```

## Мониторинг и оповещения

Мониторинг — это последняя линия обороны. Не полагайтесь только на автоматику.

### Метрики инфраструктуры (Prometheus)

Для мониторинга файлов в `/etc/kubernetes/pki` используйте специализированные экспортеры:

1.  **x509-certificate-exporter:** Сканирует директории с сертификатами и отдает метрики `x509_cert_not_after`.
2.  **Kube-state-metrics:** Для мониторинга объектов `Certificate` (cert-manager).

### Алертинг (Prometheus Rules)

```yaml
# Алерт для сертификатов в файловой системе (через x509-exporter)
- alert: KubernetesControlPlaneCertExpiring
  expr: x509_cert_not_after{filepath=~"/etc/kubernetes/pki/.*"} - time() < 30 * 86400
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Сертификат Control Plane {{ $labels.filepath }} истекает менее чем через 30 дней"

# Алерт для cert-manager
- alert: cert-managerCertExpiringSoon
  expr: certmanager_certificate_expiration_timestamp_seconds - time() < (21 * 24 * 3600)
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "Сертификат {{ $labels.name }} в namespace {{ $labels.namespace }} истекает через 21 день"
```

### Внешний мониторинг (Blackbox Exporter)

Проверка SSL "снаружи" через Ingress/LoadBalancer.

```yaml
- alert: SSLCertificateExpiring
  expr: probe_ssl_earliest_cert_expiry - time() < 86400 * 14
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: "SSL-сертификат для {{ $labels.instance }} истекает через 14 дней"
```

Подробности: **[Blackbox Exporter: Метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md)**.

## Диагностика и устранение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`x509: certificate has expired`** | Срок действия сертификата истек | Выполнить `kubeadm certs renew all` и перезапустить компоненты. Для kubelet: проверьте `rotateCertificates`. |
| **`Unable to connect to the server: x509...`** | Истек клиентский сертификат в kubeconfig | Обновить `admin.conf` и скопировать в `~/.kube/config`. |
| **`x509: certificate signed by unknown authority`** | Поле `certificate-authority-data` отсутствует или не соответствует сертификату сервера | Обновите CA-данные в конфиге или временно используйте `insecure-skip-tls-verify: true` (только для тестирования). |
| **`Unable to read CA certificate`** | Файл CA поврежден или отсутствует | Проверьте права на файл CA или обновите `certificate-authority-data`. |
| **`etcdserver: no leader`** | Потеря кворума etcd из-за истечения сертификатов | Восстановите кворум или снапшот; проверьте сертификаты etcd. |
| **`serverTLSBootstrap не работает`** | Отсутствует CSR Approver в кластере | Установите `kubelet-serving-cert-approver` или одобряйте CSR вручную. |
| **`kubeadm certs renew не обновляет ca.crt`** | Ожидаемое поведение | Root CA ротируются только вручную. Используйте `kubeadm init phase certs` для отдельного компонента. |
| **Challenge висит в `Pending`** | Порт 80 закрыт или DNS не указывает на кластер | Проверьте внешнюю доступность для HTTP-01. |
| **`Certificate` не создается** | Отсутствует аннотация или опечатка в имени Issuer | Проверьте `metadata.annotations` в Ingress. |
| **Расхождение времени на узлах** | Сертификат "еще не валиден" или "уже истек" | Настройте синхронизацию времени через `chrony` или `ntpd`. |

## Рекомендации и очистка

### Лучшие практики безопасности

| Рекомендация | Техническое обоснование |
| :--- | :--- |
| **Короткие сроки (Short-lived)** | Используйте сертификаты на 24–48 часов (через Vault), чтобы сделать процесс ротации регулярным и проверяемым ("rotation as a normal state"). |
| **Изоляция CA** | Не используйте Cluster CA для приложений. Это позволяет ротировать прикладные сертификаты без риска для инфраструктуры. |
| **Автоматические апгрейды** | Используйте инструменты типа **Kured** или операторы обслуживания для регулярного обновления кластера, что автоматически решает проблему ротации. |
| **Централизация в Vault** | Для on-prem сред используйте HashiCorp Vault как бэкенд для cert-manager, чтобы иметь единую точку аудита всех выпущенных сертификатов. |
| **Бэкап PKI** | Регулярно резервное копируйте `/etc/kubernetes/pki` (особенно `ca.key`, `sa.key`, `etcd/ca.key`). Храните бэкап в защищенном месте (offline/HSM). |
| **ECDSA/Ed25519** | Используйте современные алгоритмы вместо RSA-2048. Они обеспечивают выше производительность TLS-хендшейков и лучшее соответствие современным стандартам безопасности. |

### Очистка среды

```bash
# Удалить неиспользуемые контексты из kubeconfig
kubectl config delete-context <context-name>

# Удалить неиспользуемых пользователей
kubectl config delete-user <user-name>

# Удалить неиспользуемые записи кластеров
kubectl config delete-cluster <cluster-name>

# Очистка кэша OIDC-плагина (kubelogin)
rm -rf ~/.config/kubelogin

# Убрать неиспользуемые файлы kubeconfig
rm -f ~/.kube/old-config-backup-*.yaml

# Очистка старых CSR (Pending/Denied старше 24 часов)
kubectl get csr --field-selector status!=Approved,status!=Denied | tail -n +2 \
  | awk '{print $1}' | xargs -r kubectl delete csr

# Очистка старых CertificateRequest и Order (cert-manager)
kubectl delete certificaterequest,certificate,order,challenge \
  -n <namespace> --field-selector status.conditions.reason=Expired
```

## Крайние случаи

### Смешанный режим kubeadm + External CA

Если часть узлов использует `kubeadm`, а часть — внешний CA, `kubeadm certs check-expiration` покажет не все сертификаты. Внешние сертификаты нужно мониторить отдельно.

### Многокластерная среда с общим CA

При использовании одного CA для нескольких кластеров, ротация должна синхронизироваться между кластерами, чтобы избежать несовместимости доверия.

### Ротация во время нагрузочного пика

Выполняйте `kubeadm certs renew` и перезапуск компонентов в периоды минимальной нагрузки. `kubeadm` идемпотентен — команду можно безопасно прервать и повторно запустить.

### Ограничение Let's Encrypt Rate Limits

При массовой выдаче сертификатов соблюдайте лимиты Let's Encrypt (50 сертификатов на Registered Domain в неделю для production). Для тестов используйте Staging окружение:

```bash
# ClusterIssuer для тестирования
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: security-alerts@example.com
    privateKeySecretRef:
      name: letsencrypt-staging
    solvers:
    - http01:
        ingress:
          class: nginx
```

### Сети с ограниченным исходящим трафиком

В air-gapped средах cert-manager не может достучаться до ACME-серверов. Используйте:
- Внутренний ACME-сервер (например, Pebble для тестов или Step CA для production).
- Vault PKI как внутренний CA.
- Self-signed CA с корпоративным trust bundle.

### Специальные символы в DNS-именах

При использовании доменов с подчеркиваниями (`_`) или другими специальными символами, убедитесь, что:
- Ingress-контроллер корректно их обрабатывает.
- ACME-провайдер поддерживает такие домены (Let's Encrypt требует валидные DNS-имена по RFC 1123).

### Версионный сдвиг (Version Skew)

Утилита `kubeadm` должна соответствовать версии API-сервера (разница не более чем на одну минорную версию). Использование `kubeadm` более новой версии для управления сертификатами старого кластера может привести к несовместимости форматов.

## Дополнительная информация

### Белые пятна и нюансы

- **Внешний etcd:** Если ваш etcd запущен вне Kubernetes (например, на отдельных ВМ), `kubeadm certs renew` **не затронет** его. Вам нужно настроить отдельный пайплайн ротации для etcd.
- **ServiceAccount Tokens:** Хотя это не SSL-сертификаты, токены (Bound ServiceAccount Tokens, v1.24+) имеют срок действия (по умолчанию 1 час). Следите за тем, чтобы projected volumes с токенами не имели слишком короткого `expirationSeconds`, что может вызвать перебои при сетевых проблемах.
- **Admin Kubeconfig:** Сертификат в `admin.conf` (используемый `kubectl`) также истекает через год. Его нужно обновлять вручную после ротации через `kubeadm`.
- **cert-manager CSI Driver:** При использовании CSI-драйвера cert-manager приватные ключи не попадают в etcd, что повышает безопасность, но требует наличия CSI-провайдера на всех узлах.

### Связанные темы

* [Управление сертификатами через kubeadm](./certificate_management.md) — детальные команды, таблицы файлов и процедуры восстановления.
* [Обновление кластера](./upgrading_clusters.md) — процедура `kubeadm upgrade` с автоматической ротацией.
* [Cert-manager: Определения](../ToolsUtilities/cert_manager/definitions.md) — архитектура контроллера и CRD.
* [Cert-manager: Интеграция с Ingress](../ToolsUtilities/cert_manager/ingress/overview.md) — аннотации и практические сценарии.
* [TLS и mTLS в Kubernetes](../Security/tls_and_mtls_in_kubernetes.md) — концепции безопасности соединений.
* [Kubeconfig: Подключение к кластеру](../Operations/kubeconfig_and_connection.md) — структура конфигурационных файлов.
* [Высокая доступность (High Availability)](../Base/high_availability.md) — наблюдение за здоровьем Control Plane, включая проверку сертификатов.
* [Kubelet — агент Kubernetes на узле](../Concepts/kubelet.md) — конфигурация TLS Bootstrapping и параметры KubeletConfiguration.
* [Blackbox Exporter: Метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md) — внешний мониторинг SSL.
