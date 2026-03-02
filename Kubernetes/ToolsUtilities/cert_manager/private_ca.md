# Приватный CA для внутренних сервисов

В закрытых контурах или для локальной разработки необходимо использовать собственный центр сертификации (CA). Cert-manager позволяет автоматизировать этот процесс.

## Шаг 1: Создание самоподписанного CA

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

## Шаг 2: Создание CA Issuer'а для подписи сертификатов

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

## Шаг 3: Выпуск сертификатов для нод и администратора

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

---

*Основа: [](../cert_manager.md)*
