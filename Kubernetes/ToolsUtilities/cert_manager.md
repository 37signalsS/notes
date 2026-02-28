# Cert-manager

## Определения

Cert-manager — это нативный для Kubernetes инструмент для управления TLS-сертификатами. Он автоматизирует получение, обновление и использование сертификатов, избавляя от необходимости ручного вмешательства. Cert-manager гарантирует, что сертификаты действительны и обновлены, и пытается обновить их в подходящее время до истечения срока действия.

## Ключевые возможности

* **Автоматизация получения сертификатов:** Интегрируется с различными центрами сертификации (CA), такими как Let's Encrypt, HashiCorp Vault, Venafi, а также поддерживает самоподписанные сертификаты и приватные CA.
* **Автоматическое продление:** Следит за сроком действия сертификатов и автоматически продлевает их.
* **Интеграция с Ingress:** Автоматически создает сертификаты для Ingress-ресурсов.
* **Расширяемость:** Помимо стандартных CA, может работать с HashiCorp Vault и интегрироваться в платформы вроде OpenShift.
* **Управление жизненным циклом:** Управляет полным жизненным циклом сертификатов, включая их создание, продление и отзыв.

## Основные концепции (CRD)

Cert-manager добавляет в Kubernetes API следующие Custom Resource Definitions (CRD) для управления сертификатами:

* `Issuer` и `ClusterIssuer`: "Издатели" сертификатов. Это ресурсы, которые представляют центр сертификации и определяют, как будут выдаваться сертификаты.
  * `Issuer`: Работает в рамках одного namespace.
  * `ClusterIssuer`: Является общекластерным ресурсом и может использоваться в любом namespace.
* `Certificate`: Ресурс, который запрашивает сертификат у `Issuer` или `ClusterIssuer`. Cert-manager обеспечит получение и обновление этого сертификата.
* `CertificateRequest`: Ресурс для внутреннего использования, который представляет запрос на подпись сертификата (CSR) к `Issuer`.
* `Order` и `Challenge`: Ресурсы, используемые для выполнения ACME-проверок (например, HTTP-01 или DNS-01) при получении сертификатов от Let's Encrypt. Обычно с ними не работают напрямую.

## Практические сценарии

### Установка

Существует два основных способа установки `cert-manager`: через Helm (рекомендуемый) и напрямую через манифесты.

#### 1. Установка через Helm (рекомендуемый способ)

Helm упрощает управление версиями и конфигурацией `cert-manager`.

**Шаг 1: Добавление репозитория Jetstack**
```bash
helm repo add jetstack https://charts.jetstack.io
```

**Шаг 2: Обновление локального кэша Helm**
```bash
helm repo update
```

**Шаг 3: Установка cert-manager**
> **Важно:** Перед установкой всегда рекомендуется проверять [официальную документацию](https://cert-manager.io/docs/installation/) на предмет последней актуальной версии Helm-чарта.

```bash
helm install \
  cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.13.2 \
  --set installCRDs=true
```
* `--namespace cert-manager`: Устанавливает `cert-manager` в отдельный namespace.
* `--create-namespace`: Создает namespace, если он не существует.
* `--set installCRDs=true`: Эта опция указывает Helm-чарту установить и управлять CRD.

#### 2. Установка через манифесты (`kubectl apply`)

Этот способ не требует наличия Helm и заключается в прямом применении YAML-манифеста, который содержит все необходимые ресурсы (CRD, Deployment, RBAC и т.д.).

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.5.0/cert-manager.yaml
```
> **Внимание:** Замените `v1.5.0` на актуальную версию из [официального репозитория](https://github.com/cert-manager/cert-manager/releases).

**Плюсы:**
*   Простота и отсутствие зависимости от Helm.

**Минусы:**
*   Обновление и откат версий выполняются вручную.
*   Управление конфигурацией менее гибкое по сравнению с Helm values.

### Сценарий: Создание приватного CA для внутренних сервисов (например, OpenSearch)

В закрытых контурах или для локальной разработки необходимо использовать собственный центр сертификации (CA). Cert-manager позволяет автоматизировать этот процесс.

#### Шаг 1: Создание самоподписанного CA

Сначала создается `Issuer` типа `selfSigned` и `Certificate`, который будет являться корневым сертификатом нашего CA.

```yaml
# ca-setup.yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca-issuer
  namespace: opensearch # Работаем в целевом namespace
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: opensearch-ca
  namespace: opensearch
spec:
  isCA: true
  commonName: "opensearch-ca"
  secretName: ca-secret # Секрет, где будет храниться ключ и сертификат CA
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8 # Критически важный параметр
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
    group: cert-manager.io
```

> **Важно: Кодировка ключа PKCS8**
> Для Java-приложений, таких как OpenSearch, требуется, чтобы приватные ключи были в формате **PKCS#8**. По умолчанию `cert-manager` может использовать `PKCS#1`. Неправильная кодировка приведет к ошибкам подключения, которые сложно диагностировать. Всегда указывайте `encoding: PKCS8` при выпуске сертификатов для Java-стека.

#### Шаг 2: Создание CA Issuer'а для подписи сертификатов

Теперь, когда у нас есть секрет с CA (`ca-secret`), мы создаем `Issuer` типа `ca`, который будет подписывать сертификаты для компонентов нашего кластера.

```yaml
# ca-issuer.yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: opensearch-ca-issuer
  namespace: opensearch
spec:
  ca:
    secretName: ca-secret # Ссылка на секрет с нашим CA из Шага 1
```

> **`Issuer` vs `ClusterIssuer`**: `Issuer` работает в рамках одного namespace. `ClusterIssuer` является общекластерным. Для сервисов, работающих в одном namespace (как OpenSearch), использование `Issuer` является более предпочтительным с точки зрения изоляции.

#### Шаг 3: Выпуск сертификатов для нод и администратора

С помощью созданного `opensearch-ca-issuer` выпускаем сертификаты для компонентов OpenSearch.

```yaml
# node-certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: opensearch-nodes-cert
  namespace: opensearch
spec:
  secretName: nodes-cert-secret
  duration: 8760h # 1 год
  issuerRef:
    name: opensearch-ca-issuer
    kind: Issuer
  commonName: "nodes"
  dnsNames:
  - "opensearch-cluster-master"
  - "*.opensearch-cluster-master"
  # ... другие необходимые DNS имена
  privateKey:
    encoding: PKCS8 # Также используем PKCS8
```
`commonName` и `subject` этого сертификата в дальнейшем используются в конфигурации безопасности OpenSearch (`nodes_dn`) для авторизации нод в кластере. Аналогичным образом создается отдельный сертификат для администратора (`admin_dn`).

### Сценарий: Использование CA кластера для выпуска внутренних сертификатов

Для внутренних сервисов, которые не доступны извне, нет необходимости получать публично доверенные сертификаты (например, от Let's Encrypt). Вместо этого можно использовать корневой CA самого кластера Kubernetes для подписи сертификатов. Это обеспечивает шифрование трафика внутри кластера, которому доверяют все его компоненты.

**Задача:** Выпустить TLS-сертификат для внутреннего Ingress-ресурса (например, `netdata.k8s.local`), подписанный корневым CA кластера.

#### Шаг 1: Создание `Secret` с корневым CA кластера

Сначала необходимо сделать сертификат и ключ корневого CA Kubernetes доступными для `cert-manager`. Для этого создается `Secret` типа `tls` в том же `namespace`, где будет работать `cert-manager`.

> **Внимание:** Эта операция требует доступа к master-узлу и файлам в `/etc/kubernetes/pki/`.

```bash
kubectl create secret tls kubernetes-ca-secret \
  --cert=/etc/kubernetes/pki/ca.crt \
  --key=/etc/kubernetes/pki/ca.key \
  -n cert-manager # или другой namespace, где работает cert-manager
```

#### Шаг 2: Создание `Issuer` на основе секрета

Теперь создаем `Issuer` (или `ClusterIssuer`), который будет использовать этот секрет для подписи сертификатов.

```yaml
# cluster-ca-issuer.yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: kubernetes-ca-issuer
  namespace: cert-manager
spec:
  ca:
    secretName: kubernetes-ca-secret # Ссылка на секрет с CA кластера
```
*   `kind: Issuer`: Если `Issuer` и `Secret` находятся в одном namespace.
*   `kind: ClusterIssuer`: Если вы хотите, чтобы `Issuer` был доступен из любого namespace (в этом случае `Secret` все равно должен быть в `cert-manager` namespace).

#### Шаг 3: Запрос сертификата через ресурс `Certificate`

Создаем ресурс `Certificate`, который запрашивает у нашего `Issuer`'а сертификат для нужных доменных имен.

```yaml
# internal-certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-services-tls
  namespace: monitoring # Namespace, где будет использоваться сертификат
spec:
  secretName: internal-services-secret # Имя секрета, куда будет сохранен сертификат
  duration: 2160h # 90d
  renewBefore: 360h # 15d
  issuerRef:
    name: kubernetes-ca-issuer
    kind: Issuer
    group: cert-manager.io
  dnsNames:
    - netdata.k8s.local
    - grafana.k8s.local
    - prometheus.k8s.local
```

После применения этого манифеста `cert-manager` создаст в `namespace: monitoring` секрет `internal-services-secret` с TLS-сертификатом, подписанным CA кластера.

#### Шаг 4: Использование сертификата в `Ingress`

Наконец, используем созданный секрет в `Ingress`-ресурсе.

```yaml
# netdata-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    # Аннотация, чтобы cert-manager управлял этим Ingress
    cert-manager.io/issuer: "kubernetes-ca-issuer" 
spec:
  ingressClassName: system-ingress # Указываем наш внутренний Ingress-контроллер
  tls:
  - hosts:
    - netdata.k8s.local
    secretName: internal-services-secret # Ссылка на наш секрет
  rules:
  - host: netdata.k8s.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: netdata
            port:
              name: http
```
Этот подход позволяет централизованно управлять TLS-сертификатами для всех внутренних сервисов, обеспечивая безопасное взаимодействие внутри кластера.

### Конфигурация для публичных CA (Let's Encrypt)

Для получения публично доверенных сертификатов настраивается `ClusterIssuer` для Let's Encrypt.

```yaml
# clusterissuer-letsencrypt.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: your-email@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-private-key
    solvers:
    - http01:
        ingress:
          class: nginx # Укажите ваш Ingress-класс
```

## Использование с Ingress

Самый распространенный способ использования `cert-manager` — это автоматическое получение сертификатов для Ingress-ресурсов с помощью аннотаций.

Просто добавьте аннотацию в ваш Ingress-манифест, и `cert-manager` сделает все остальное.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    # Указываем, какой ClusterIssuer использовать
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - my-domain.com
    secretName: my-domain-tls # cert-manager создаст и заполнит этот секрет
  rules:
  - host: my-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

## Прямое создание ресурса Certificate

Второй способ — создать ресурс `Certificate` напрямую. Этот подход обеспечивает больший контроль и полезен, когда сертификат не привязан к Ingress (например, для mTLS между сервисами).

В этом ресурсе вы описываете желаемый сертификат, указываете доменные имена и ссылаетесь на `Issuer` или `ClusterIssuer`.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-domain-com
  namespace: default
spec:
  # Имя секрета, в который будет сохранен сертификат
  secretName: my-domain-tls
  # Длительность и период обновления
  duration: 2160h # 90d
  renewBefore: 360h # 15d
  # Доменные имена
  dnsNames:
  - my-domain.com
  - www.my-domain.com
  # Ссылка на Issuer или ClusterIssuer
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

Cert-manager отследит этот ресурс и автоматически создаст/обновит секрет `my-domain-tls` с валидным сертификатом.

## Дополнительная информация

* **Примечание об устаревшей аннотации:** Ранее использовалась аннотация `kubernetes.io/tls-acme: "true"`. Она считается устаревшей и ее следует избегать. Вместо нее всегда используйте `cert-manager.io/cluster-issuer` или `cert-manager.io/issuer`.

## Администрирование и особенности

### Управление секретами при удалении сертификатов

По умолчанию `cert-manager` **не удаляет** Kubernetes `Secret`, когда удаляется соответствующий ему ресурс `Certificate`. Это сделано для безопасности, чтобы случайное удаление `Certificate` не привело к немедленной потере рабочего TLS-сертификата и простою сервиса.

Однако, когда вы пересоздаете `Certificate` с тем же `secretName`, `cert-manager` не будет изменять существующий `Secret`, что может привести к неожиданному поведению (например, использованию старого сертификата).

#### Включение автоматического удаления (Garbage Collection)

Для изменения этого поведения `cert-manager` можно запустить с флагом `--enable-certificate-owner-ref=true`.

При установке через Helm это делается так:
```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set extraArgs='{--enable-certificate-owner-ref=true}'
```
Когда этот флаг включен, `cert-manager` добавляет `ownerReference` к `Secret`'у, указывая на `Certificate`. Это позволяет сборщику мусора Kubernetes автоматически удалять `Secret` при удалении `Certificate`.

**Плюсы:**
- Упрощает управление жизненным циклом и очистку.

**Минусы:**
- **Риск:** Случайное удаление ресурса `Certificate` немедленно приведет к удалению секрета и, возможно, к сбою в работе приложения. Используйте с осторожностью.
