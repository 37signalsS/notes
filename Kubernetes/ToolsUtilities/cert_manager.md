# Cert-manager

**Definitions:**

Cert-manager — это нативный для Kubernetes инструмент для управления TLS-сертификатами. Он автоматизирует получение, обновление и использование сертификатов, избавляя от необходимости ручного вмешательства. Cert-manager гарантирует, что сертификаты действительны и обновлены, и пытается обновить их в подходящее время до истечения срока действия.

**Basic Concepts:**

## Ключевые возможности

*   **Автоматизация получения сертификатов:** Интегрируется с различными центрами сертификации (CA), такими как Let's Encrypt, HashiCorp Vault, Venafi, а также поддерживает самоподписанные сертификаты и приватные CA.
*   **Автоматическое продление:** Следит за сроком действия сертификатов и автоматически продлевает их.
*   **Интеграция с Ingress:** Автоматически создает сертификаты для Ingress-ресурсов.
*   **Расширяемость:** Помимо стандартных CA, может работать с HashiCorp Vault и интегрироваться в платформы вроде OpenShift.
*   **Управление жизненным циклом:** Управляет полным жизненным циклом сертификатов, включая их создание, продление и отзыв.

## Основные концепции (CRD)

Cert-manager добавляет в Kubernetes API следующие Custom Resource Definitions (CRD) для управления сертификатами:

*   `Issuer` и `ClusterIssuer`: "Издатели" сертификатов. Это ресурсы, которые представляют центр сертификации и определяют, как будут выдаваться сертификаты.
    *   `Issuer`: Работает в рамках одного namespace.
    *   `ClusterIssuer`: Является общекластерным ресурсом и может использоваться в любом namespace.
*   `Certificate`: Ресурс, который запрашивает сертификат у `Issuer` или `ClusterIssuer`. Cert-manager обеспечит получение и обновление этого сертификата.
*   `CertificateRequest`: Ресурс для внутреннего использования, который представляет запрос на подпись сертификата (CSR) к `Issuer`.
*   `Order` и `Challenge`: Ресурсы, используемые для выполнения ACME-проверок (например, HTTP-01 или DNS-01) при получении сертификатов от Let's Encrypt. Обычно с ними не работают напрямую.

**Practical Scenarios:**

## Установка

Рекомендуемый способ установки — через Helm.

**1. Добавление репозитория Jetstack:**

```bash
helm repo add jetstack https://charts.jetstack.io
```

**2. Обновление локального кэша Helm:**

```bash
helm repo update
```

**3. Установка cert-manager:**

> **Важно:** Перед установкой всегда рекомендуется проверять [официальную документацию](https://cert-manager.io/docs/installation/) на предмет последней актуальной версии Helm-чарта.

```bash
helm install \
  cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.19.2 \
  --set installCRDs=true
```

*   `--namespace cert-manager`: Устанавливает `cert-manager` в отдельный namespace.
*   `--create-namespace`: Создает namespace, если он не существует.
*   `--set installCRDs=true`: Эта опция указывает Helm-чарту установить и управлять CRD.

## Конфигурация: Создание ClusterIssuer

После установки необходимо настроить `Issuer` или `ClusterIssuer`, который будет отвечать за выдачу сертификатов. Ниже приведен пример `ClusterIssuer` для Let's Encrypt с использованием HTTP-01 проверки.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    # Email address used for ACME registration
    email: your-email@example.com
    # ACME server URL
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      # Secret resource that will be used to store the ACME account's private key.
      name: letsencrypt-prod-private-key
    # Enable the HTTP-01 challenge provider
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

**Additional information:**

*   **Примечание об устаревшей аннотации:** Ранее использовалась аннотация `kubernetes.io/tls-acme: "true"`. Она считается устаревшей и ее следует избегать. Вместо нее всегда используйте `cert-manager.io/cluster-issuer` или `cert-manager.io/issuer`.