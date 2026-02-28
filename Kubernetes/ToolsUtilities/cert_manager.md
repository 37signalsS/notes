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

* `--namespace cert-manager`: Устанавливает `cert-manager` в отдельный namespace.
* `--create-namespace`: Создает namespace, если он не существует.
* `--set installCRDs=true`: Эта опция указывает Helm-чарту установить и управлять CRD.

### Приватный Certificate Authority (CA) для локальной разработки

В ситуациях, когда использование публичных CA вроде Let's Encrypt невозможно (например, в закрытой инфраструктуре или для доменов `.local` без внешнего доступа), необходимо развернуть собственный приватный Certificate Authority. Cert-manager значительно упрощает этот процесс.

#### Шаг 1: Создание самоподписанного CA

Сначала создается временный `Issuer`, который нужен только для одной цели — выпустить корневой сертификат для нашего будущего CA.

Затем создается ресурс `Certificate`, который использует этот временный `Issuer` для генерации самого себя. Это и будет наш корневой сертификат CA.

```yaml
# issuer-ca-selfsigned.yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca-issuer
  namespace: cert-manager
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: home-ca-certificate
  namespace: cert-manager
spec:
  isCA: true
  duration: 87600h # 10 лет
  secretName: home-ca-secret # Секрет, в котором будет храниться ключ и сертификат CA
  commonName: "My Home Certificate Authority" # Имя вашего CA
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
```

После применения этого манифеста `cert-manager` создаст секрет `home-ca-secret`, содержащий `tls.crt` (сертификат) и `tls.key` (приватный ключ) нашего CA.

#### Шаг 2: Создание ClusterIssuer для подписи сертификатов

Теперь, когда у нас есть секрет с CA, мы можем создать `ClusterIssuer`. Этот "издатель" будет использовать наш CA для подписи сертификатов для приложений уже во всех неймспейсах кластера.

```yaml
# clusterissuer-ca.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: home-ca-cluster-issuer
spec:
  ca:
    secretName: home-ca-secret # Ссылка на секрет с нашим CA из Шага 1
```

> **`Issuer` vs `ClusterIssuer`**: `Issuer` работает в рамках одного namespace. `ClusterIssuer` является общекластерным ресурсом и может использоваться для выпуска сертификатов в любом namespace, что делает его более удобным для общих CA.

#### Шаг 3: Добавление CA в доверенные на клиентских машинах

Чтобы браузеры и утилиты командной строки (curl, git и т.д.) доверяли сертификатам, подписанным нашим новым CA, его корневой сертификат нужно добавить в хранилище доверенных сертификатов на всех машинах, с которых будет осуществляться доступ.

1.  **Экспорт сертификата CA из кластера:**

    ```bash
    kubectl get secret home-ca-secret -n cert-manager -o jsonpath='{.data.tls\.crt}' | base64 -d > ca.crt
    ```

2.  **Добавление сертификата в ОС:**

    *   **Debian / Ubuntu / и другие производные:**
        ```bash
        sudo cp ca.crt /usr/local/share/ca-certificates/home-ca.crt
        sudo update-ca-certificates
        ```

    *   **Red Hat / CentOS / Rocky Linux:**
        ```bash
        sudo cp ca.crt /etc/pki/ca-trust/source/anchors/home-ca.crt
        sudo update-ca-trust extract
        ```

    *   **Windows:**
        1.  Дважды щелкните по файлу `ca.crt`.
        2.  Нажмите "Установить сертификат...".
        3.  Выберите "Текущий пользователь" и нажмите "Далее".
        4.  Выберите опцию "Поместить все сертификаты в следующее хранилище".
        5.  Нажмите "Обзор..." и выберите "Доверенные корневые центры сертификации".
        6.  Нажмите "ОК", "Далее" и "Готово". Согласитесь на импорт.

    *   **macOS:**
        Откройте приложение "Связка ключей" (Keychain Access), перейдите в раздел "Система" (System) и просто перетащите файл `ca.crt` в окно приложения. Дважды щелкните по импортированному сертификату и в разделе "Доверие" (Trust) установите "При использовании этого сертификата" (When using this certificate) в "Всегда доверять" (Always Trust).

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
